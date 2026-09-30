import asyncio
import json
import time
import websockets
import datetime
from typing import Dict, Any, Optional, List, Set

from kalshi_api import load_api_key, sign_pss_text, _PRIVATE_KEY


API_KEY = load_api_key()

###############################################################
##################### WEBSOCKET FUNCTIONS #####################
###############################################################

class KalshiWebSocket:
    """
    WebSocket client for Kalshi real-time data feeds.
    """

    def __init__(self, api_key: Optional[str] = None, print_kalshi_websocket_messages: bool = False):
        self.api_key = api_key or API_KEY
        self.ws_url = 'wss://api.elections.kalshi.com/trade-api/ws/v2'
        self.websocket = None
        self.cmd_id = 1
        self.states = {}
        self.print_kalshi_websocket_messages = print_kalshi_websocket_messages
        self._draining_tickers: Set[str] = set()

        # SID tracking: map request_id -> subscription entry so we can
        # record the sids that Kalshi returns in 'subscribed' confirmations.
        self._pending_subs: Dict[int, Dict[str, Any]] = {}  # cmd_id -> entry
        # Reverse lookup: ticker -> list of sids for that ticker
        self._ticker_sids: Dict[str, List[int]] = {}
        # SIDs that have been explicitly unsubscribed — messages on these are stale
        self._retired_sids: Set[int] = set()
        # request_ids whose arriving SIDs must be retired immediately (deferred unsubscribe).
        # Used when unsubscribe_ticker is called before subscribed confirmations arrive.
        self._retire_pending: Set[int] = set()

    async def _generate_auth_headers(self) -> Dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        signature = sign_pss_text(_PRIVATE_KEY, timestamp + 'GET' + '/trade-api/ws/v2')
        return {
            'KALSHI-ACCESS-KEY': self.api_key,
            'KALSHI-ACCESS-SIGNATURE': signature,
            'KALSHI-ACCESS-TIMESTAMP': timestamp,
        }

    async def connect(self):
        headers = await self._generate_auth_headers()

        self.websocket = await websockets.connect(
            self.ws_url,
            additional_headers=headers,
            ping_interval=20,
            ping_timeout=30,
            close_timeout=10,
            max_size=2**23,
        )
        print(">> Connected to Kalshi WebSocket with ping_interval=20s, ping_timeout=30s")

    async def disconnect(self):
        if self.websocket:
            await self.websocket.close()
            print(">> Disconnected from Kalshi WebSocket")

    async def subscribe(
        self,
        channels: List[str],
        market_ticker: Optional[str] = None,
        market_tickers: Optional[List[str]] = None,
    ):
        if not self.websocket:
            raise RuntimeError("KalshiWebSocket (subscribe): Not connected to WebSocket")

        request_id = self.cmd_id
        subscription = {
            'id': request_id,
            'cmd': 'subscribe',
            'params': {
                'channels': channels
            }
        }

        if market_ticker and market_tickers:
            raise ValueError("Provide either market_ticker or market_tickers, not both.")
        if market_tickers:
            subscription['params']['market_tickers'] = list(market_tickers)
        elif market_ticker:
            subscription['params']['market_ticker'] = market_ticker

        self.cmd_id += 1
        await self.websocket.send(json.dumps(subscription))

        target_summary = market_tickers or market_ticker
        print(f">> Requested to subscribe to channels: {channels}, ticker: {target_summary}")

        tickers = list(market_tickers) if market_tickers else ([market_ticker] if market_ticker else [])
        entry = {
            'request_id': request_id,
            'channels': list(channels),
            'tickers': tickers,
            'sids': [],
            'expected_count': len(channels),
            'sent_at': time.monotonic(),
        }
        self._pending_subs[request_id] = entry

    async def unsubscribe_ticker(self, market_ticker: str) -> bool:
        """Unsubscribe from all channels for a specific ticker using collected SIDs.
        Returns True if an unsubscribe was actually sent, False if skipped (SIDs shared)."""
        if not self.websocket:
            print("KalshiWebSocket (unsubscribe_ticker): Not connected to WebSocket")
            return True  # not connected — caller can safely destroy state

        # Mark any in-flight pending subs for this ticker as "deferred retire":
        # their SIDs will arrive later and must be immediately retired + unsubscribed
        # rather than registered as active.  Do NOT delete them — we need the entries
        # to route the arriving SIDs into retirement.
        stale_cutoff = time.monotonic() - 60.0
        for k, e in list(self._pending_subs.items()):
            if market_ticker in e.get('tickers', []):
                if not e.get('sids') and e.get('sent_at', 0) < stale_cutoff:
                    # Ghost entry that has been waiting > 60 s with zero SIDs — Kalshi
                    # never confirmed this subscribe (market may not support these channels).
                    # Drop it outright; we can't defer-unsubscribe without SIDs anyway.
                    del self._pending_subs[k]
                    self._retire_pending.discard(k)
                    print(f"KalshiWebSocket (unsubscribe_ticker): Pruned stale ghost pending sub {k} for {market_ticker}")
                else:
                    self._retire_pending.add(k)

        all_sids = self._ticker_sids.get(market_ticker, [])
        # Kalshi reuses SIDs across markets in the same event. Only send an unsubscribe
        # for SIDs that are exclusively owned by this ticker; shared SIDs must stay alive
        # for the other markets that use them.
        shared_sids = set(s for other, sids in self._ticker_sids.items() if other != market_ticker for s in sids)
        exclusive_sids = [s for s in all_sids if s not in shared_sids]

        self._retired_sids.update(exclusive_sids)
        if not exclusive_sids:
            if all_sids:
                print(f"KalshiWebSocket (unsubscribe_ticker): {market_ticker} SIDs {all_sids} are shared — skipping unsubscribe to protect other markets")
            else:
                print(f"KalshiWebSocket (unsubscribe_ticker): No SIDs found for {market_ticker} — deferred unsubscribe queued if in-flight")
            # Keep _ticker_sids entry so subsequent unsubscribe_ticker calls for other
            # tickers sharing this SID still see it as shared and don't wrongly retire it.
            self._draining_tickers.add(market_ticker)
            return False  # unsubscribe skipped — caller should keep state warm

        self._ticker_sids.pop(market_ticker, None)
        request_id = self.cmd_id
        self.cmd_id += 1

        unsubscription = {
            'id': request_id,
            'cmd': 'unsubscribe',
            'params': {
                'sids': exclusive_sids
            }
        }
        await self.websocket.send(json.dumps(unsubscription))
        self._draining_tickers.add(market_ticker)
        # print(f">> Unsubscribing {market_ticker} with exclusive sids={exclusive_sids} (skipped shared={list(shared_sids & set(all_sids))})")
        return True  # unsubscribe was sent

    async def unsubscribe_all(self):
        """Unsubscribe from all tracked tickers."""
        if not self.websocket:
            print("KalshiWebSocket (unsubscribe_all): Not connected to WebSocket")
            return

        all_sids = list({s for sids in self._ticker_sids.values() for s in sids})
        for ticker in self._ticker_sids:
            self._draining_tickers.add(ticker)
        self._ticker_sids.clear()

        if not all_sids:
            return

        request_id = self.cmd_id
        self.cmd_id += 1

        unsubscription = {
            'id': request_id,
            'cmd': 'unsubscribe',
            'params': {
                'sids': all_sids
            }
        }
        try:
            await self.websocket.send(json.dumps(unsubscription))
        except Exception as exc:
            print(f"KalshiWebSocket (unsubscribe_all): Failed to send unsubscribe: {exc}")

    async def listen(self):
        if not self.websocket:
            raise RuntimeError("KalshiWebSocket (listen): Not connected to WebSocket")

        async for message in self.websocket:
            try:
                data = json.loads(message)
                task = asyncio.create_task(self._handle_message(data))
                task.add_done_callback(self._on_task_done)
            except json.JSONDecodeError as e:
                print(f"Failed to parse message: {e}")
            except Exception as e:
                print(f"Error handling message: {e}")
                raise RuntimeError("KalshiWebSocket (listen): Error handling message") from e

    @staticmethod
    def _on_task_done(task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception() is not None:
            print(f"KalshiWebSocket (task error): {task.exception()}")

    async def _handle_message(self, data: Dict[str, Any]):
        channel = data.get('type')

        if channel == 'subscribed':
            self._handle_subscribed(data)
        elif channel == 'orderbook_snapshot':
            await self.handle_orderbook_snapshot(data)
        elif channel == 'orderbook_delta':
            await self.handle_orderbook_delta(data)
        elif channel == 'fill':
            await self.handle_fill(data)
        elif channel == 'trade':
            await self.handle_public_trade(data)
        elif channel == 'ok':
            pass
        elif channel == 'error':
            # Try to link the error back to the subscribe that caused it.
            error_id = data.get('id')
            entry = self._pending_subs.pop(error_id, None) if error_id is not None else None
            if entry:
                tickers = entry.get('tickers', [])
                for t in tickers:
                    self._ticker_sids.pop(t, None)
                print(f"KalshiWebSocket: Kalshi rejected subscribe for {tickers}: {data}")
            else:
                print(f"KalshiWebSocket (handle_message): Error message: {data}")
        elif channel == 'unsubscribed':
            self._handle_unsubscribed(data)
        else:
            print(f"KalshiWebSocket (handle_message): Unknown message type {channel!r}: {data}")

    def _handle_subscribed(self, data: Dict[str, Any]):
        """Record the SID from a subscription confirmation and associate it with the ticker(s)."""
        print(f">> KALSHI {datetime.datetime.now().strftime('%H:%M:%S')}: Confirmed subscription: {data}")
        request_id = data.get('id')
        msg = data.get('msg', {})
        sid = msg.get('sid')
        market_ticker_in_msg = msg.get('market_ticker', '')

        if sid is None:
            return

        # Primary: match by request_id
        entry = None
        entry_key = None
        if request_id is not None:
            entry = self._pending_subs.get(request_id)
            entry_key = request_id

        # Fallback: Kalshi may not echo the id correctly — match by market_ticker in msg.
        # Prefer real (non-retire-pending) entries over ghost entries so that a ghost sub
        # sitting in _retire_pending doesn't steal SIDs meant for the live subscription.
        if entry is None and market_ticker_in_msg:
            ghost_fallback = (None, None)
            for key, pending in self._pending_subs.items():
                if market_ticker_in_msg in pending.get('tickers', []):
                    if key not in self._retire_pending:
                        entry = pending
                        entry_key = key
                        break  # real match wins immediately
                    elif ghost_fallback[0] is None:
                        ghost_fallback = (key, pending)
            if entry is None and ghost_fallback[0] is not None:
                entry_key, entry = ghost_fallback

        if entry is not None:
            entry['sids'].append(sid)

            if entry_key in self._retire_pending:
                # This subscribe was logically cancelled before its SIDs arrived.
                # Only retire the SID if it's not shared with another active ticker;
                # retiring a shared SID would drop messages for markets still using it.
                if not any(sid in active for active in self._ticker_sids.values()):
                    self._retired_sids.add(sid)
                if len(entry['sids']) >= entry['expected_count']:
                    del self._pending_subs[entry_key]
                    self._retire_pending.discard(entry_key)
                    # _deferred_unsubscribe filters out shared SIDs before sending.
                    asyncio.create_task(self._deferred_unsubscribe(list(entry['sids'])))
                return  # Do NOT add to _ticker_sids

            for ticker in entry['tickers']:
                if ticker not in self._ticker_sids:
                    self._ticker_sids[ticker] = []
                if sid not in self._ticker_sids[ticker]:  # guard against warm-state re-subscribe duplicates
                    self._ticker_sids[ticker].append(sid)
                self._draining_tickers.discard(ticker)
            if len(entry['sids']) >= entry['expected_count']:
                del self._pending_subs[entry_key]
        elif market_ticker_in_msg:
            # No pending sub matched, but we know the ticker — track SID directly
            if market_ticker_in_msg not in self._ticker_sids:
                self._ticker_sids[market_ticker_in_msg] = []
            self._ticker_sids[market_ticker_in_msg].append(sid)
            self._draining_tickers.discard(market_ticker_in_msg)


    def _handle_unsubscribed(self, data: Dict[str, Any]) -> None:
        ts = datetime.datetime.now().strftime('%H:%M:%S')
        msg = data.get('msg', {}) or {}
        # Kalshi puts 'sid' at the top level for unsubscribed messages, not inside 'msg'
        sid = data.get('sid')
        if sid is None:
            sid = msg.get('sid')

        if sid is None:
            print(f">> KALSHI {ts}: Unsubscribed (no sid): {data}")
            return

        if sid in self._retired_sids:
            # We asked for this — expected, clean up
            self._retired_sids.discard(sid)
            print(f">> KALSHI {ts}: Unsubscribed (requested) sid={sid}")
            return

        # Involuntary unsub — find ALL tickers sharing this SID and resubscribe each.
        # Kalshi reuses SIDs across markets in the same event, so one dropped SID can
        # affect multiple markets simultaneously.
        affected_tickers = [t for t, sids in list(self._ticker_sids.items()) if sid in sids]

        print(f">> KALSHI {ts}: Involuntary unsubscribe sid={sid} tickers={affected_tickers} — resubscribing")

        for affected_ticker in affected_tickers:
            if affected_ticker not in self.states:
                continue
            # Pop all SIDs so later messages for the same ticker's other SIDs don't
            # trigger duplicate resubscriptions.
            self._ticker_sids.pop(affected_ticker, None)
            asyncio.create_task(self.subscribe(
                ['orderbook_delta', 'fill', 'trade'],
                market_ticker=affected_ticker,
            ))

    async def _deferred_unsubscribe(self, sids: List[int]) -> None:
        """Send an unsubscribe for SIDs that were confirmed after their ticker was already removed."""
        if not self.websocket or not sids:
            return
        # Don't unsubscribe SIDs still tracked by active tickers (shared subscriptions).
        in_use = set(s for active in self._ticker_sids.values() for s in active)
        safe_sids = [s for s in sids if s not in in_use]
        if not safe_sids:
            return
        request_id = self.cmd_id
        self.cmd_id += 1
        try:
            await self.websocket.send(json.dumps({
                'id': request_id,
                'cmd': 'unsubscribe',
                'params': {'sids': safe_sids},
            }))
        except Exception as exc:
            print(f"KalshiWebSocket (_deferred_unsubscribe): Failed to send: {exc}")

    #############################################################
    ##################### HANDLER FUNCTIONS #####################
    #############################################################

    def _is_draining(self, ticker: str) -> bool:
        return ticker in self._draining_tickers

    def _register_sid_from_message(self, ticker: str, sid: int) -> None:
        """Register a SID learned from a snapshot, delta, fill, or trade message when
        'subscribed' confirmations never arrive — Kalshi shares one SID per channel across
        every market in an event (e.g. KXWCMENTION-* / KXWORLDNEWSMENTION-* style markets)
        but only confirms one of the concurrent subscribe requests; every other ticker
        sharing that SID must still get it registered here or it silently loses that
        channel forever the next time the SID drops. Skips if already tracked."""
        if sid is None:
            return
        if ticker not in self._ticker_sids:
            self._ticker_sids[ticker] = []
        if sid not in self._ticker_sids[ticker]:
            self._ticker_sids[ticker].append(sid)
            self._draining_tickers.discard(ticker)
            # Clean up any real (non-ghost) pending sub for this ticker — the snapshot
            # or delta arrival is confirmation enough that the subscription is live.
            for k in list(self._pending_subs.keys()):
                if (ticker in self._pending_subs[k].get('tickers', [])
                        and k not in self._retire_pending):
                    del self._pending_subs[k]
            print(f"KalshiWebSocket: Learned SID {sid} for {ticker} from message (no subscribed confirmation received)")

    async def handle_orderbook_snapshot(self, data: Dict[str, Any]):
        if self.print_kalshi_websocket_messages:
            print(f">> KALSHI {datetime.datetime.now().strftime('%H:%M:%S')}: Orderbook snapshot received:", data)
        ticker = data['msg']['market_ticker']
        sid = data.get('sid')
        if sid in self._retired_sids:
            return

        if ticker and ticker in self.states:
            # Register SID from snapshot if we don't already know it — handles markets
            # where Kalshi doesn't send 'subscribed' confirmations.
            if sid not in self._ticker_sids.get(ticker, []):
                self._register_sid_from_message(ticker, sid)
            await self.states[ticker].handle_orderbook_snapshot(data)
        elif not self._is_draining(ticker):
            print(f"KalshiWebSocket (handle_orderbook_snapshot): No state found for ticker {ticker}")

    async def handle_orderbook_delta(self, data: Dict[str, Any]):
        if self.print_kalshi_websocket_messages:
            print(f">> KALSHI {datetime.datetime.now().strftime('%H:%M:%S')}: Orderbook delta received:", data)
        ticker = data['msg']['market_ticker']
        sid = data.get('sid')
        if sid in self._retired_sids:
            return

        if ticker and ticker in self.states:
            # Register SID from delta as a fallback if snapshot never arrived.
            if sid not in self._ticker_sids.get(ticker, []):
                self._register_sid_from_message(ticker, sid)
            foreign_update = await self.states[ticker].handle_orderbook_delta(data)
            if self.print_kalshi_websocket_messages:
                if foreign_update:
                    print(f">> Updated orderbook delta for {ticker}")
                else:
                    print(f">> IGNORED")
        elif not self._is_draining(ticker):
            print(f"KalshiWebSocket (handle_orderbook_delta): No state found for ticker {ticker}")

    async def handle_fill(self, data: Dict[str, Any]):
        if self.print_kalshi_websocket_messages:
            print(f">> KALSHI {datetime.datetime.now().strftime('%H:%M:%S')}: Fill received:", data)
        ticker = data['msg']['market_ticker']
        sid = data.get('sid')

        # Register this (ticker, sid) pair so involuntary-unsubscribe handling knows this
        # ticker depends on this SID too — Kalshi shares one fill SID across every market in
        # the same event, but only sends a 'subscribed' confirmation to one of them; without
        # this, every other ticker sharing the SID silently stops receiving fills forever the
        # next time that SID drops. Guarded like the orderbook handlers: never resurrect a SID
        # we already retired via a stale/late message. This never gates fill *processing* —
        # fills aren't replayable by Kalshi, so they must always be applied regardless.
        if sid not in self._retired_sids and ticker and sid not in self._ticker_sids.get(ticker, []):
            self._register_sid_from_message(ticker, sid)

        if ticker and ticker in self.states:
            await self.states[ticker].handle_fill(data)
        elif not self._is_draining(ticker):
            print(f"KalshiWebSocket (handle_fill): No state found for ticker {ticker}")

    async def handle_public_trade(self, data: Dict[str, Any]):
        if self.print_kalshi_websocket_messages:
            print(f">> KALSHI {datetime.datetime.now().strftime('%H:%M:%S')}: Public trade received", data)
        ticker = data['msg']['market_ticker']
        sid = data.get('sid')

        if sid not in self._retired_sids and ticker and sid not in self._ticker_sids.get(ticker, []):
            self._register_sid_from_message(ticker, sid)

        if ticker and ticker in self.states:
            await self.states[ticker].handle_public_trade(data)
        elif not self._is_draining(ticker):
            print(f"KalshiWebSocket (handle_public_trade): No state found for ticker {ticker}")
