import asyncio
import datetime
import time
from typing import Dict
import websockets

from state import State
from ladder_server import LadderServer
from static_server import start_static_server
from kalshi_websocket import KalshiWebSocket
from kalshi_api import (
    get_positions, cancel_all_bids_api, cancel_all_asks_api, get_markets_by_event,
    get_balance, set_target_balance_allocation, close_session,
)

PRINT_KALSHI_WEBSOCKET_MESSAGES = False
PRINT_ORDERBOOK_STRINGS = False
PRINT_FILL_STRINGS = True
# Set True to print a per-market "seconds since last WS message" line every 5s.
# Useful for diagnosing why markets go stale; flip to False once root cause is found.
PRINT_ACTIVITY_SUMMARY = False

# Standing cross-shard bankroll split, {exchange_index: percent}, must sum to 100.
# Re-asserted on every startup (the write is idempotent); Kalshi then rebalances
# server-side ~every 10s to hold it. Set to None to leave the account's existing
# allocation untouched.
TARGET_BALANCE_ALLOCATION = {0: 50, 3: 50}
# How often to poll account balance for the UI shard strip (seconds). This runs on
# its own timer, entirely off the order-placement path.
BALANCE_POLL_INTERVAL = 10.0
# Port the ladder UI is served from. It must be a localhost origin: Kalshi's WAF 403s
# `Origin: null` (file://) but allow-lists http://localhost:*, which is what lets the
# market finder query Kalshi from the browser instead of from this process.
STATIC_UI_PORT = 8080

class Main:
    """
    Main application that manages states for multiple tickers and runs the WebSocket.
    """

    def __init__(self, ladder_server: LadderServer = None):
        """Initialize the main application."""
        self.states: Dict[str, State] = {}
        self.websocket = KalshiWebSocket(
            print_kalshi_websocket_messages=PRINT_KALSHI_WEBSOCKET_MESSAGES
        )
        self.ladder_server = ladder_server
        self.slot_tickers: Dict[int, str] = {}
        self.active_tickers: set[str] = set()
        self._warm_states: set[str] = set()
        self.connected = False
        self._last_resync: Dict[str, float] = {}

    def add_market(self, event: dict, market: dict) -> State:
        """Add a new market to track."""
        ticker = market['ticker']
        if ticker not in self.states:
            self.states[ticker] = State(
                event, market,
                print_orderbook_strings=PRINT_ORDERBOOK_STRINGS,
                print_fill_strings=PRINT_FILL_STRINGS,
                on_orderbook_update=self._broadcast_orderbook
            )
            if self.ladder_server:
                self.ladder_server.register_state(self.states[ticker])
        return self.states[ticker]

    async def _broadcast_orderbook(self, state: State) -> None:
        if not self.ladder_server:
            return
        if state.ticker not in self.active_tickers:
            return  # warm state — don't push to UI or fill empty panels
        await self.ladder_server.broadcast_orderbook(state)

    async def _add_ticker(self, market_ticker: str) -> None:
        if market_ticker in self.active_tickers:
            return

        # Reuse a warm state when one exists (kept alive because the shared event-level SID
        # was never actually unsubscribed). The orderbook has been current the whole time, so
        # we just promote it back to active — no re-subscription or snapshot needed.
        if market_ticker in self._warm_states:
            self._warm_states.discard(market_ticker)
            self.active_tickers.add(market_ticker)
            state = self.states[market_ticker]
            if self.ladder_server:
                self.ladder_server.register_state(state)
            # The event-level SID is still active and delivering deltas/fills/trades —
            # do NOT re-subscribe. Doing so would create new exclusive fill/trade SIDs
            # that make the next removal look exclusive, destroying the state instead of
            # keeping it warm and breaking the cycle on the second switch.
            self.websocket._draining_tickers.discard(market_ticker)
            state.last_ws_message_at = time.monotonic()
            self._last_resync.pop(market_ticker, None)
            await state.emit_orderbook_update()
            return

        # Validate format before touching any shared state.
        # Raise (don't catch) so set_ticker_for_slot can roll back the slot assignment.
        event_ticker = _get_event_ticker_from_market(market_ticker)

        self.active_tickers.add(market_ticker)

        market_info = None
        try:
            markets = await get_markets_by_event(event_ticker)
            if isinstance(markets, list):
                for entry in markets:
                    if isinstance(entry, dict) and entry.get('ticker') == market_ticker:
                        market_info = entry
                        break
            elif isinstance(markets, dict):
                candidates = markets.get('markets', []) or []
                for entry in candidates:
                    if isinstance(entry, dict) and entry.get('ticker') == market_ticker:
                        market_info = entry
                        break
        except Exception as exc:
            print(f"Main (add_ticker): Failed to fetch market info for {market_ticker}: {exc}")
        event = {"event_ticker": event_ticker}
        market = _build_manual_market(market_ticker)
        if market_info:
            market['title'] = market_info.get('title')
            # exchange_index rides along on the market info we already fetched — no
            # extra REST call on the ticker-add path.
            market['exchange_index'] = market_info.get('exchange_index', 0)
        state = self.add_market(event, market)

        # Cancel any resting orders for this ticker before subscribing.
        try:
            await cancel_all_bids_api(ticker=market_ticker, quiet_not_found=True)
            await cancel_all_asks_api(ticker=market_ticker, quiet_not_found=True)
        except Exception as exc:
            print(f"Main (add_ticker): Failed to cancel resting orders: {exc}")

        # Clear stale resync cooldown so the loop can react immediately if needed
        self._last_resync.pop(market_ticker, None)

        # Subscribe before seeding position: any fill that lands while we're fetching the
        # REST position snapshot is now captured live (and the subsequent seed overwrites
        # state.position with the authoritative value anyway), instead of being missed in
        # the gap and permanently desyncing state.position.
        if self.connected:
            try:
                await self.websocket.subscribe(
                    ['orderbook_delta', 'fill', 'trade'],
                    market_ticker=market_ticker
                )
            except Exception as exc:
                print(f"Main (add_ticker): Failed to subscribe to {market_ticker}: {exc}")

        # Seed position for new ticker
        try:
            positions = await get_positions(ticker=market_ticker)
            if positions and isinstance(positions, dict):
                market_positions = positions.get('market_positions', []) or []
                if market_positions:
                    state.position = float(market_positions[0].get('position_fp', '0.0'))
        except Exception as exc:
            print(f"Main (add_ticker): Failed to fetch positions: {exc}")

        # Always broadcast initial state so the panel isn't blank while waiting for snapshot
        await state.emit_orderbook_update()

    async def _remove_ticker(self, market_ticker: str) -> None:
        if market_ticker not in self.active_tickers:
            return

        actually_unsubscribed = True
        if self.connected:
            try:
                actually_unsubscribed = await self.websocket.unsubscribe_ticker(market_ticker)
            except Exception as exc:
                print(f"Main (remove_ticker): Failed to unsubscribe {market_ticker}: {exc}")

        self.active_tickers.discard(market_ticker)
        if self.ladder_server:
            self.ladder_server.unregister_state(market_ticker)

        if actually_unsubscribed:
            self.states.pop(market_ticker, None)
        else:
            # Kalshi's SID is shared with other active markets — we couldn't actually
            # unsubscribe, so the event channel keeps delivering deltas for this ticker.
            # Keep the state alive (warm) so the orderbook stays current. If the ticker
            # is re-added, we promote the warm state instead of creating a blank one that
            # would receive deltas without a snapshot (causing negative-quantity errors).
            self._warm_states.add(market_ticker)
            print(f"Main (remove_ticker): Keeping {market_ticker} warm (shared SID)")

        asyncio.create_task(self._cancel_resting_orders(market_ticker))

    async def _cancel_resting_orders(self, market_ticker: str) -> None:
        try:
            await cancel_all_bids_api(ticker=market_ticker, quiet_not_found=True)
            await cancel_all_asks_api(ticker=market_ticker, quiet_not_found=True)
        except Exception as exc:
            print(f"Main (_cancel_resting_orders): Failed for {market_ticker}: {exc}")
        finally:
            # These REST cancels bypass state.orderbook.live_orders bookkeeping (they don't
            # go through update_orders.cancel_order). Reconcile afterward so a ticker kept
            # warm on removal (shared SID) doesn't keep showing cancelled orders as resting
            # if/when it's promoted back into a panel.
            state = self.states.get(market_ticker)
            if state:
                state.request_reconcile()

    async def set_ticker_for_slot(self, slot: int, market_ticker: str, force: bool = False) -> None:
        previous_ticker = self.slot_tickers.get(slot)
        market_ticker = market_ticker.strip() if market_ticker else ""

        if previous_ticker == market_ticker and not force:
            return

        # ts = datetime.datetime.now().strftime('%H:%M:%S')
        # print(f">> SLOT_CHANGE {ts}: slot={slot} {previous_ticker!r} → {market_ticker!r} force={force}")

        if previous_ticker:
            self.slot_tickers.pop(slot, None)
            if previous_ticker not in self.slot_tickers.values():
                await self._remove_ticker(previous_ticker)

        if not market_ticker:
            return

        self.slot_tickers[slot] = market_ticker
        if market_ticker not in self.active_tickers:
            try:
                await self._add_ticker(market_ticker)
            except Exception as exc:
                print(f"Main (set_ticker_for_slot): Failed to add {market_ticker}: {exc}")
                # Roll back the slot assignment so the panel isn't stuck with a bad ticker
                self.slot_tickers.pop(slot, None)
                self.active_tickers.discard(market_ticker)
                return
        elif force and market_ticker in self.states:
            # Ticker is in another slot — can't fully reload, just re-broadcast current state
            await self.states[market_ticker].emit_orderbook_update()

    def get_state(self, ticker: str) -> State:
        """Get state for a ticker."""
        return self.states[ticker]

    def get_all_tickers(self) -> list:
        """Get list of all tracked tickers."""
        return list(self.states.keys())

    async def _resync_loop(self) -> None:
        """Periodically re-subscribes markets whose local orderbook went out of sync."""
        resync_cooldown = 30.0  # seconds between resyncs for the same ticker
        silent_threshold = 20.0  # seconds of no WS message before forcing a resync
        while True:
            await asyncio.sleep(5)
            if not self.connected:
                continue
            now = time.monotonic()

            if PRINT_ACTIVITY_SUMMARY and self.states:
                ts = datetime.datetime.now().strftime('%H:%M:%S')
                parts = "  ".join(
                    f"{t}:{now - s.last_ws_message_at:.0f}s"
                    for t, s in self.states.items()
                )
                print(f">> ACTIVITY {ts}: {parts}")
            for ticker, state in list(self.states.items()):
                if ticker not in self.active_tickers:
                    continue  # warm state — skip resync
                time_silent = now - state.last_ws_message_at
                needs_delta_resync = state.orderbook.had_negative_delta
                needs_silence_resync = time_silent > silent_threshold

                if not needs_delta_resync and not needs_silence_resync:
                    continue
                if now - self._last_resync.get(ticker, 0) < resync_cooldown:
                    continue

                # Skip if there is a real in-flight pending sub that was sent recently
                # (not a ghost in _retire_pending, and not a stale entry that never got
                # its expected confirmations — goals/closed markets may never get all 3).
                real_in_flight = any(
                    ticker in e.get('tickers', [])
                    and k not in self.websocket._retire_pending
                    and (now - e.get('sent_at', 0)) < 30.0
                    for k, e in self.websocket._pending_subs.items()
                )
                if real_in_flight:
                    print(f"Main (_resync_loop): Skipping resync for {ticker} — subscription in-flight, snapshot will clear the flag")
                    continue

                has_sids = bool(self.websocket._ticker_sids.get(ticker))

                # Delta-sync requires SIDs to safely unsubscribe and re-snapshot.
                # Silence-sync on a market with no SIDs (shared subscription) can
                # recover with a subscribe-only call — Kalshi will send a fresh snapshot
                # without us needing to unsubscribe first.
                if needs_delta_resync and not has_sids:
                    print(f"Main (_resync_loop): Skipping delta-resync for {ticker} — no SIDs yet")
                    continue

                reason = "out-of-sync orderbook" if needs_delta_resync else f"silent for {time_silent:.0f}s"
                state.orderbook.had_negative_delta = False
                self._last_resync[ticker] = now
                print(f"Main (_resync_loop): Re-syncing {ticker} due to {reason} (has_sids={has_sids})")
                try:
                    if has_sids:
                        actually_unsubscribed = await self.websocket.unsubscribe_ticker(ticker)
                        if not actually_unsubscribed:
                            # SID is shared with other markets — Kalshi won't send a fresh
                            # snapshot on re-subscribe, so skipping it avoids creating orphaned
                            # exclusive fill/trade SIDs that corrupt the next unsubscribe.
                            print(f"Main (_resync_loop): Skipping re-subscribe for {ticker} — shared SID, snapshot not available")
                            continue
                    await self.websocket.subscribe(
                        ['orderbook_delta', 'fill', 'trade'],
                        market_ticker=ticker
                    )
                except Exception as exc:
                    print(f"Main (_resync_loop): Failed to resync {ticker}: {exc}")

    async def _balance_loop(self) -> None:
        """Poll account balance and push the per-shard breakdown to the UI.

        Runs on its own timer, fully off the order-placement path. A slow or failed
        poll just skips a tick — it never blocks or delays trading.
        """
        while True:
            await asyncio.sleep(BALANCE_POLL_INTERVAL)
            if not self.ladder_server:
                continue
            try:
                data = await get_balance()
            except Exception as exc:
                print(f"Main (_balance_loop): balance fetch failed: {exc}")
                continue
            if not data:
                continue
            try:
                await self.ladder_server.broadcast_balance(data, TARGET_BALANCE_ALLOCATION)
            except Exception as exc:
                print(f"Main (_balance_loop): broadcast failed: {exc}")

    async def run(self):
        """Run the main application with WebSocket connection."""
        self.websocket.states = self.states

        try:
            await self.websocket.connect()
            self.connected = True

            for ticker in sorted(self.active_tickers):
                await self.websocket.subscribe(
                    ['orderbook_delta', 'fill', 'trade'],
                    market_ticker=ticker
                )

            asyncio.create_task(self._resync_loop())
            asyncio.create_task(self._balance_loop())

            # One-time config write: set the standing cross-shard bankroll split.
            # Kalshi maintains it server-side afterwards; nothing here touches the
            # order path.
            if TARGET_BALANCE_ALLOCATION:
                try:
                    result = await set_target_balance_allocation(TARGET_BALANCE_ALLOCATION)
                    if result is not None:
                        print(f">> Target balance allocation set to {TARGET_BALANCE_ALLOCATION}")
                except Exception as exc:
                    print(f"Main (run): Failed to set target balance allocation: {exc}")

            # Start listening for messages
            await self.websocket.listen()
        finally:
            self.connected = False
            # Warm states are only valid within a single WebSocket session. Clear them on
            # disconnect so reconnect always starts with fresh subscriptions and snapshots.
            for ticker in list(self._warm_states):
                self.states.pop(ticker, None)
            self._warm_states.clear()
            await self.websocket.unsubscribe_all()
            await self.websocket.disconnect()
            await close_session()


async def _handle_interrupting_shutdown(app: Main) -> None:
    print("Shutting down system...")
    shutdown_tasks = [state.shutdown() for state in app.states.values()]
    await asyncio.gather(*shutdown_tasks, return_exceptions=True)
    await asyncio.sleep(1)

    await app.websocket.unsubscribe_all()
    await app.websocket.disconnect()


def _get_event_ticker_from_market(market_ticker: str) -> str:
    parts = market_ticker.split('-')
    if len(parts) < 2:
        raise ValueError(f"Invalid market ticker: {market_ticker}")
    return "-".join(parts[:2])


def _build_manual_market(market_ticker: str) -> dict:
    return {
        "ticker": market_ticker,
    }


async def run_system():
    print("Starting Kalshi Trader System...")
    print("=========== Starting Kalshi Trader System ===========")

    app = Main()
    ladder_server = LadderServer(on_set_ticker=app.set_ticker_for_slot)
    app.ladder_server = ladder_server
    await ladder_server.start()
    # Daemon thread; dies with the process. Makes no Kalshi calls of its own.
    start_static_server(STATIC_UI_PORT)

    try:
        await app.run()
    except (KeyboardInterrupt, asyncio.CancelledError):
        msg = "Main (shutdown): Keyboard interrupt or cancelled error"
        print(msg)
        await _handle_interrupting_shutdown(app)
    except websockets.exceptions.ConnectionClosed as exc:
        msg = f"Main (shutdown): WebSocket connection closed: {exc}"
        print(msg)
        await _handle_interrupting_shutdown(app)
        raise
    finally:
        await ladder_server.stop()


if __name__ == "__main__":
    asyncio.run(run_system())
