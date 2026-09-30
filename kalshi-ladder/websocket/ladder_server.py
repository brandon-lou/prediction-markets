import asyncio
import json
from typing import Dict, List, Set, Optional, Any

import websockets

from update_orders import post_order, cancel_orders_at_price, cancel_all_bids, cancel_all_asks
from orderbook import CENTS_PER_INTERNAL


class LadderServer:
    """
    Local WebSocket server that broadcasts orderbook snapshots to UI clients.
    """

    def __init__(self, host: str = "localhost", port: int = 8765, on_set_ticker=None):
        self.host = host
        self.port = port
        self.server: Optional[Any] = None
        self.connections: Set[websockets.WebSocketServerProtocol] = set()
        self.latest_by_ticker: Dict[str, Dict] = {}
        self.latest_balance: Optional[Dict] = None
        self.states: Dict[str, Any] = {}
        self.on_set_ticker = on_set_ticker

    async def start(self) -> None:
        if self.server:
            return
        self.server = await websockets.serve(
            self._handler,
            self.host,
            self.port,
            ping_interval=20,
            ping_timeout=20,
        )
        print(f">> Ladder UI server running on ws://{self.host}:{self.port}")

    async def stop(self) -> None:
        if not self.server:
            return
        self.server.close()
        await self.server.wait_closed()
        self.server = None
        self.connections.clear()

    async def _handler(self, websocket) -> None:
        self.connections.add(websocket)
        try:
            # Send the latest snapshot(s) immediately on connect.
            for payload in self.latest_by_ticker.values():
                await websocket.send(json.dumps(payload))
            if self.latest_balance is not None:
                await websocket.send(json.dumps(self.latest_balance))
            async for message in websocket:
                await self._handle_message(message)
        finally:
            self.connections.discard(websocket)

    async def _handle_message(self, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return

        message_type = payload.get("type")
        if message_type == "set_ticker":
            slot = payload.get("slot")
            ticker = payload.get("ticker")
            force = bool(payload.get("force", False))
            if not isinstance(slot, int):
                return
            normalized = ticker.strip() if isinstance(ticker, str) else ""
            if self.on_set_ticker:
                try:
                    await self.on_set_ticker(slot, normalized, force)
                except Exception as exc:
                    print(f"LadderServer (set_ticker): Unhandled error for slot={slot} ticker={normalized!r}: {exc}")
            return

        if message_type == "cancel_all":
            scope = payload.get("scope")
            if scope not in {"bids", "asks", "both"}:
                return
            ticker = payload.get("ticker")
            if ticker is None:
                # Ticker deliberately omitted = the panic key: every registered market.
                targets = list(self.states.values())
            elif isinstance(ticker, str) and ticker.strip():
                state = self.states.get(ticker.strip())
                targets = [state] if state else []
            else:
                # A malformed ticker must never widen into a cancel-everything.
                return
            if not targets:
                return
            # Each cancel is one REST call per resting order, so a multi-market sweep run
            # inline would head-of-line-block every later order click on this sequential
            # read loop. main.py backgrounds its resting-order cancels for the same reason.
            asyncio.create_task(self._cancel_all(targets, scope))
            return

        if message_type not in {"post_order", "cancel_orders_at_price"}:
            return

        action = payload.get("side")  # UI sends "side" as buy/sell, internally we call it "action"
        price_cents = payload.get("price")
        count = payload.get("count", 1)
        ticker = payload.get("ticker")

        if action not in {"buy", "sell"}:
            return
        if not isinstance(price_cents, int):
            return
        if message_type == "post_order":
            if not isinstance(count, int) or count <= 0:
                return

        state = None
        if ticker and ticker in self.states:
            state = self.states[ticker]
        if not state:
            return

        internal_price = price_cents * CENTS_PER_INTERNAL

        try:
            if message_type == "post_order":
                await post_order(state, action, count, internal_price, should_abort=lambda: False)
            else:
                await cancel_orders_at_price(state, action, internal_price)
        except Exception as e:
            print(f"LadderServer (_handle_message): Error handling {message_type} ({type(e).__name__}): {e}")

    async def _cancel_all(self, states: List[Any], scope: str) -> None:
        """Pull resting orders in bulk. Never raises into the caller's task."""
        for state in states:
            try:
                if scope in ("bids", "both"):
                    await cancel_all_bids(state)
                if scope in ("asks", "both"):
                    await cancel_all_asks(state)
            except Exception as e:
                print(f"LadderServer (_cancel_all): Error cancelling {scope} for "
                      f"{getattr(state, 'ticker', '?')} ({type(e).__name__}): {e}")

    def register_state(self, state) -> None:
        self.states[state.ticker] = state

    def clear_states(self) -> None:
        self.states.clear()
        self.latest_by_ticker.clear()

    def unregister_state(self, ticker: str) -> None:
        self.states.pop(ticker, None)
        self.latest_by_ticker.pop(ticker, None)

    async def broadcast_orderbook(self, state) -> None:
        try:
            payload = state.orderbook.get_ladder_snapshot()
        except Exception as e:
            # Book-level computation (bids/asks/my orders) can fail independently of
            # state.position, which is always authoritative at this point (set from the
            # exchange's post_position_fp). Don't let a book-rendering error suppress the
            # position broadcast — fall back to an empty book instead of returning early.
            print(f"LadderServer (broadcast_orderbook): Error getting snapshot for {state.ticker}, broadcasting position only: {e}")
            payload = {
                "bids": [], "asks": [], "my_bids": [], "my_asks": [],
                "best_bid": 0, "best_ask": 100,
                "sequence_number": state.orderbook.sequence_number,
                "last_update_ts": None,
            }
        payload.update({
            "type": "orderbook",
            "ticker": state.ticker,
            "event_ticker": state.event_ticker,
            "position": state.position,
            "position_description": state.get_position_description(),
            "market_title": state.market_title,
            "exchange_index": getattr(state, "exchange_index", 0),
        })
        self.latest_by_ticker[state.ticker] = payload
        await self._broadcast(payload)

    async def broadcast_balance(self, data: Dict, targets: Optional[Dict[int, int]] = None) -> None:
        """Push the per-shard collateral breakdown to UI clients.

        `data` is the raw GetBalance response. Called from an independent poll loop,
        never from the order path.
        """
        breakdown = []
        for item in (data.get("balance_breakdown") or []):
            try:
                idx = int(item.get("exchange_index", 0))
                dollars = float(item.get("balance", 0) or 0)
            except (TypeError, ValueError):
                continue
            breakdown.append({"exchange_index": idx, "balance": dollars})

        total = None
        raw_total = data.get("balance")
        if raw_total is not None:
            try:
                total = int(raw_total) / 100.0
            except (TypeError, ValueError):
                total = None

        payload = {
            "type": "balance",
            "total": total,
            "breakdown": breakdown,
            "targets": {str(k): v for k, v in (targets or {}).items()},
            "updated_ts": data.get("updated_ts"),
        }
        self.latest_balance = payload
        await self._broadcast(payload)

    async def _broadcast(self, payload: Dict) -> None:
        if not self.connections:
            return
        message = json.dumps(payload)
        stale = []
        # Snapshot before iterating — a client connecting or disconnecting mid-broadcast
        # (each runs as its own concurrent task) would otherwise mutate self.connections
        # while this loop is still iterating over it, raising "Set changed size during
        # iteration" the next time await websocket.send() yields control.
        for websocket in list(self.connections):
            try:
                await websocket.send(message)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.connections.discard(websocket)
