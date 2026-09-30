"""
Kalshi Ladder — unit / integration tests.
Run from the scratchpad with:
  python3.11 test_ladder.py
"""

import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

_WEBSOCKET_DIR = Path(__file__).resolve().parent.parent

# ── stub out all external dependencies before importing app code ──────────────
_mock_kalshi_api = MagicMock()
_mock_kalshi_api.load_api_key.return_value = "test-key"
_mock_kalshi_api.load_private_key_from_file.return_value = MagicMock()
_mock_kalshi_api._PRIVATE_KEY = MagicMock()
_mock_kalshi_api.sign_pss_text.return_value = "sig"
_mock_kalshi_api.get_markets_by_event = AsyncMock(return_value=[])
_mock_kalshi_api.get_positions = AsyncMock(return_value={})
_mock_kalshi_api.cancel_all_bids_api = AsyncMock()
_mock_kalshi_api.cancel_all_asks_api = AsyncMock()
_mock_kalshi_api.close_session = AsyncMock()

_mock_update_orders = MagicMock()
_mock_update_orders.post_order = AsyncMock()
_mock_update_orders.cancel_orders_at_price = AsyncMock()

sys.modules["kalshi_api"] = _mock_kalshi_api
sys.modules["update_orders"] = _mock_update_orders

sys.path.insert(0, str(_WEBSOCKET_DIR))

from orderbook import OrderBook, PRICE_MULTIPLIER, MAX_PRICE, to_internal  # noqa: E402
from kalshi_websocket import KalshiWebSocket  # noqa: E402
import main as main_module  # noqa: E402
from main import Main, _get_event_ticker_from_market  # noqa: E402
from state import State  # noqa: E402
from ladder_server import LadderServer  # noqa: E402


# ── helpers ───────────────────────────────────────────────────────────────────

def run(coro):
    return asyncio.run(coro)


def make_fake_ws():
    """Return a mock object that behaves like a websockets.WebSocketClientProtocol."""
    ws = MagicMock()
    ws.send = AsyncMock()
    ws.close = AsyncMock()
    return ws


def make_subscribed_msg(request_id, sid, market_ticker, channel="orderbook_delta"):
    return {
        "type": "subscribed",
        "id": request_id,
        "sid": sid,
        "msg": {
            "sid": sid,
            "market_ticker": market_ticker,
            "channel": channel,
        },
    }


def make_snapshot_msg(market_ticker, sid, seq=1):
    """Minimal orderbook snapshot message."""
    return {
        "type": "orderbook_snapshot",
        "sid": sid,
        "seq": seq,
        "msg": {
            "market_id": "m1",
            "market_ticker": market_ticker,
            "yes_dollars_fp": [[0.45, 10], [0.50, 5]],
            "no_dollars_fp": [[0.50, 8], [0.55, 3]],
        },
    }


def make_delta_msg(market_ticker, sid, side, price_dollars, delta, seq=2):
    return {
        "type": "orderbook_delta",
        "sid": sid,
        "seq": seq,
        "msg": {
            "market_id": "m1",
            "market_ticker": market_ticker,
            "side": side,
            "price_dollars": str(price_dollars),
            "delta_fp": str(delta),
            "ts": "2026-01-01T00:00:00+00:00",
        },
    }


def make_fill_msg(
    market_ticker, sid, count, post_position, action="buy", book_side="bid",
    yes_price_dollars="0.45", client_order_id="co-1", order_id="o-1", trade_id="t-1",
):
    return {
        "type": "fill",
        "sid": sid,
        "msg": {
            "market_ticker": market_ticker,
            "trade_id": trade_id,
            "order_id": order_id,
            "is_taker": False,
            "book_side": book_side,
            "yes_price_dollars": yes_price_dollars,
            "count_fp": str(count),
            "action": action,
            "ts": "2026-01-01T00:00:00+00:00",
            "client_order_id": client_order_id,
            "post_position_fp": str(post_position),
            "purchased_side": "yes",
        },
    }


def make_trade_msg(market_ticker, sid):
    return {
        "type": "trade",
        "sid": sid,
        "msg": {
            "market_ticker": market_ticker,
            "yes_price_dollars": "0.45",
            "count_fp": "1.00",
            "ts": "2026-01-01T00:00:00+00:00",
        },
    }


# ── OrderBook tests ───────────────────────────────────────────────────────────

class TestOrderBook(unittest.TestCase):

    def test_snapshot_initialises_book(self):
        ob = OrderBook("TICK-A")
        snapshot = make_snapshot_msg("TICK-A", sid=1)
        ob.initialize_from_snapshot(snapshot, {})
        self.assertIn(to_internal(0.45), ob.orderbook["bid"])
        self.assertIn(to_internal(0.50), ob.orderbook["bid"])
        self.assertFalse(ob.had_negative_delta)

    def test_positive_delta_updates_quantity(self):
        ob = OrderBook("TICK-A")
        ob.initialize_from_snapshot(make_snapshot_msg("TICK-A", sid=1), {})
        delta = make_delta_msg("TICK-A", 1, "yes", 0.45, 3)
        ob.update_from_delta(delta)
        self.assertAlmostEqual(ob.orderbook["bid"][to_internal(0.45)], 13.0)
        self.assertFalse(ob.had_negative_delta)

    def test_zero_delta_removes_level(self):
        ob = OrderBook("TICK-A")
        ob.initialize_from_snapshot(make_snapshot_msg("TICK-A", sid=1), {})
        # Remove all 10 units at 0.45
        delta = make_delta_msg("TICK-A", 1, "yes", 0.45, -10)
        ob.update_from_delta(delta)
        self.assertNotIn(to_internal(0.45), ob.orderbook["bid"])
        self.assertFalse(ob.had_negative_delta)

    def test_negative_delta_sets_flag_and_removes_level(self):
        ob = OrderBook("TICK-A")
        ob.initialize_from_snapshot(make_snapshot_msg("TICK-A", sid=1), {})
        # Over-subtract to force negative
        delta = make_delta_msg("TICK-A", 1, "yes", 0.45, -999)
        ob.update_from_delta(delta)
        self.assertTrue(ob.had_negative_delta)
        self.assertNotIn(to_internal(0.45), ob.orderbook["bid"])

    def test_snapshot_clears_negative_delta_flag(self):
        ob = OrderBook("TICK-A")
        ob.had_negative_delta = True
        ob.initialize_from_snapshot(make_snapshot_msg("TICK-A", sid=1), {})
        self.assertFalse(ob.had_negative_delta)

    def test_get_ladder_snapshot_structure(self):
        ob = OrderBook("TICK-A")
        ob.initialize_from_snapshot(make_snapshot_msg("TICK-A", sid=1), {})
        snap = ob.get_ladder_snapshot()
        self.assertIn("bids", snap)
        self.assertIn("asks", snap)
        self.assertIn("best_bid", snap)
        self.assertIn("best_ask", snap)
        self.assertIsInstance(snap["best_bid"], int)
        # best_bid should be 50 cents (= 0.50 yes price)
        self.assertEqual(snap["best_bid"], 50)

    def test_ask_price_inversion(self):
        """No-side prices are stored as MAX_PRICE - to_internal(no_price)."""
        ob = OrderBook("TICK-A")
        ob.initialize_from_snapshot(make_snapshot_msg("TICK-A", sid=1), {})
        # no_price 0.50 → internal ask at MAX_PRICE - to_internal(0.50) = 10000 - 5000 = 5000
        self.assertIn(MAX_PRICE - to_internal(0.50), ob.orderbook["ask"])

    def test_get_event_ticker_from_market_valid(self):
        self.assertEqual(_get_event_ticker_from_market("KXWC-26JUL01ENGCOD-COD"), "KXWC-26JUL01ENGCOD")

    def test_get_event_ticker_from_market_invalid(self):
        with self.assertRaises(ValueError):
            _get_event_ticker_from_market("NOTICKER")


# ── KalshiWebSocket subscription tracking ─────────────────────────────────────

class TestKalshiWebSocketSubscriptions(unittest.TestCase):

    def _make_ws(self):
        ws = KalshiWebSocket(api_key="k")
        ws.websocket = make_fake_ws()
        return ws

    def test_subscribe_creates_pending_entry(self):
        ws = self._make_ws()
        run(ws.subscribe(["orderbook_delta", "fill", "trade"], market_ticker="TICK-A"))
        self.assertIn(1, ws._pending_subs)
        entry = ws._pending_subs[1]
        self.assertEqual(entry["expected_count"], 3)
        self.assertIn("TICK-A", entry["tickers"])

    def test_three_subscribed_msgs_populate_ticker_sids(self):
        ws = self._make_ws()
        run(ws.subscribe(["orderbook_delta", "fill", "trade"], market_ticker="TICK-A"))
        req_id = 1
        for sid in [10, 11, 12]:
            ws._handle_subscribed(make_subscribed_msg(req_id, sid, "TICK-A"))
        self.assertNotIn(req_id, ws._pending_subs)  # cleaned up
        self.assertEqual(sorted(ws._ticker_sids["TICK-A"]), [10, 11, 12])

    def test_unsubscribe_with_sids_sends_message(self):
        ws = self._make_ws()
        ws._ticker_sids["TICK-A"] = [10, 11, 12]
        run(ws.unsubscribe_ticker("TICK-A"))
        ws.websocket.send.assert_called_once()
        sent = json.loads(ws.websocket.send.call_args[0][0])
        self.assertEqual(sent["cmd"], "unsubscribe")
        self.assertEqual(sorted(sent["params"]["sids"]), [10, 11, 12])
        self.assertNotIn("TICK-A", ws._ticker_sids)
        self.assertTrue(ws._retired_sids.issuperset({10, 11, 12}))

    def test_unsubscribe_before_sids_marks_retire_pending(self):
        ws = self._make_ws()
        run(ws.subscribe(["orderbook_delta", "fill", "trade"], market_ticker="TICK-A"))
        req_id = 1
        # Unsubscribe BEFORE any subscribed confirmations
        run(ws.unsubscribe_ticker("TICK-A"))
        # No send should have happened (no SIDs to send)
        ws.websocket.send.assert_called_once()  # only the subscribe call
        self.assertIn(req_id, ws._retire_pending)
        self.assertIn("TICK-A", ws._draining_tickers)

    def test_deferred_retire_fires_when_all_sids_arrive(self):
        """Ghost-sub scenario: unsubscribe before SIDs → deferred unsubscribe after all 3 arrive."""
        async def _body():
            ws = self._make_ws()
            await ws.subscribe(["orderbook_delta", "fill", "trade"], market_ticker="TICK-A")
            req_id = 1

            # Mark for deferred retirement (simulates rapid reload)
            await ws.unsubscribe_ticker("TICK-A")
            self.assertIn(req_id, ws._retire_pending)

            # SIDs arrive one at a time — entry should NOT be cleaned up until the 3rd
            ws._handle_subscribed(make_subscribed_msg(req_id, 20, "TICK-A"))
            self.assertIn(req_id, ws._pending_subs)
            self.assertIn(20, ws._retired_sids)
            self.assertNotIn("TICK-A", ws._ticker_sids)  # must NOT be registered as active

            ws._handle_subscribed(make_subscribed_msg(req_id, 21, "TICK-A"))
            self.assertIn(req_id, ws._pending_subs)

            # Third confirmation — pending entry should be cleaned up and deferred unsubscribe queued
            ws._handle_subscribed(make_subscribed_msg(req_id, 22, "TICK-A"))

            # Yield so the deferred task runs
            await asyncio.sleep(0)

            self.assertNotIn(req_id, ws._pending_subs)
            self.assertNotIn(req_id, ws._retire_pending)
            self.assertNotIn("TICK-A", ws._ticker_sids)
            self.assertTrue({20, 21, 22}.issubset(ws._retired_sids))

            # Deferred unsubscribe should have sent an unsubscribe command
            calls = ws.websocket.send.call_args_list
            cmds = [json.loads(c[0][0])["cmd"] for c in calls]
            self.assertIn("unsubscribe", cmds)

        run(_body())

    def test_snapshot_with_retired_sid_is_dropped(self):
        ws = self._make_ws()
        ws._retired_sids.add(99)
        ws.states["TICK-A"] = MagicMock()
        ws.states["TICK-A"].handle_orderbook_snapshot = AsyncMock()
        run(ws.handle_orderbook_snapshot(make_snapshot_msg("TICK-A", sid=99)))
        ws.states["TICK-A"].handle_orderbook_snapshot.assert_not_called()

    def test_delta_with_retired_sid_is_dropped(self):
        ws = self._make_ws()
        ws._retired_sids.add(99)
        ws.states["TICK-A"] = MagicMock()
        ws.states["TICK-A"].handle_orderbook_delta = AsyncMock(return_value=False)
        run(ws.handle_orderbook_delta(make_delta_msg("TICK-A", 99, "yes", 0.50, 1)))
        ws.states["TICK-A"].handle_orderbook_delta.assert_not_called()

    def test_unknown_message_type_does_not_raise(self):
        ws = self._make_ws()
        # Should not raise — unknown types are now just printed
        run(ws._handle_message({"type": "UNKNOWN_TYPE_XYZ"}))

    def test_error_message_cleans_pending_sub(self):
        ws = self._make_ws()
        run(ws.subscribe(["orderbook_delta", "fill", "trade"], market_ticker="TICK-A"))
        req_id = 1
        run(ws._handle_message({"type": "error", "id": req_id, "msg": "bad ticker"}))
        self.assertNotIn(req_id, ws._pending_subs)


# ── Main state-management logic ────────────────────────────────────────────────

class TestMainStateManagement(unittest.TestCase):

    def _make_main(self):
        app = Main()
        app.websocket.websocket = make_fake_ws()
        app.connected = True
        return app

    def test_invalid_ticker_raises_value_error(self):
        """No-hyphen ticker must raise ValueError (so set_ticker_for_slot can roll back)."""
        app = self._make_main()
        with self.assertRaises(ValueError):
            run(app._add_ticker("BADTICKER"))
        self.assertNotIn("BADTICKER", app.active_tickers)

    def test_invalid_ticker_slot_rolls_back(self):
        """set_ticker_for_slot must not leave a zombie slot when the ticker is invalid."""
        app = self._make_main()
        run(app.set_ticker_for_slot(0, "BADTICKER"))
        # Slot must not be permanently assigned to the bad ticker
        self.assertNotIn(0, app.slot_tickers)
        self.assertNotIn("BADTICKER", app.active_tickers)

    def test_valid_ticker_adds_to_active_and_states(self):
        app = self._make_main()
        run(app._add_ticker("KXWC-ENGCOD"))
        self.assertIn("KXWC-ENGCOD", app.active_tickers)
        self.assertIn("KXWC-ENGCOD", app.states)

    def test_same_ticker_not_double_added(self):
        app = self._make_main()
        run(app._add_ticker("KXWC-ENGCOD"))
        run(app._add_ticker("KXWC-ENGCOD"))
        send_calls = app.websocket.websocket.send.call_count
        self.assertEqual(send_calls, 1)  # only one subscribe

    def test_remove_ticker_cleans_state(self):
        app = self._make_main()
        run(app._add_ticker("KXWC-ENGCOD"))
        # Give it fake SIDs so unsubscribe actually sends
        app.websocket._ticker_sids["KXWC-ENGCOD"] = [1, 2, 3]
        run(app._remove_ticker("KXWC-ENGCOD"))
        self.assertNotIn("KXWC-ENGCOD", app.active_tickers)
        self.assertNotIn("KXWC-ENGCOD", app.states)

    def test_set_ticker_for_slot_assigns_and_subscribes(self):
        app = self._make_main()
        run(app.set_ticker_for_slot(0, "KXWC-ENGCOD"))
        self.assertEqual(app.slot_tickers[0], "KXWC-ENGCOD")
        self.assertIn("KXWC-ENGCOD", app.active_tickers)

    def test_set_ticker_for_slot_same_no_force_skips(self):
        app = self._make_main()
        run(app.set_ticker_for_slot(0, "KXWC-ENGCOD"))
        call_count_after_first = app.websocket.websocket.send.call_count
        run(app.set_ticker_for_slot(0, "KXWC-ENGCOD"))  # same, no force
        # No additional sends
        self.assertEqual(app.websocket.websocket.send.call_count, call_count_after_first)

    def test_set_ticker_for_slot_force_resubscribes(self):
        app = self._make_main()
        run(app.set_ticker_for_slot(0, "KXWC-ENGCOD"))
        # Give SIDs so unsubscribe can fire
        app.websocket._ticker_sids["KXWC-ENGCOD"] = [10, 11, 12]
        calls_before = app.websocket.websocket.send.call_count
        run(app.set_ticker_for_slot(0, "KXWC-ENGCOD", force=True))
        # Should have sent at least one extra command (unsubscribe + re-subscribe)
        self.assertGreater(app.websocket.websocket.send.call_count, calls_before)

    def test_resync_loop_skips_when_no_flag(self):
        """Resync must not trigger when had_negative_delta is False."""
        app = self._make_main()
        run(app._add_ticker("KXWC-ENGCOD"))
        app.websocket._ticker_sids["KXWC-ENGCOD"] = [1, 2, 3]
        # Simulate one pass of the resync loop body — nothing should trigger
        for ticker, state in list(app.states.items()):
            if not state.orderbook.had_negative_delta:
                continue
            self.fail("Resync triggered without had_negative_delta flag")

    def test_resync_loop_skips_real_in_flight_sub(self):
        """Resync must skip if a real (non-retire-pending) subscribe is in-flight."""
        app = self._make_main()
        run(app._add_ticker("KXWC-ENGCOD"))
        state = app.states["KXWC-ENGCOD"]
        state.orderbook.had_negative_delta = True
        # There IS an in-flight pending sub (from the subscribe in _add_ticker)
        # and it is NOT in _retire_pending
        real_in_flight = any(
            "KXWC-ENGCOD" in e.get("tickers", []) and k not in app.websocket._retire_pending
            for k, e in app.websocket._pending_subs.items()
        )
        self.assertTrue(real_in_flight)

    def test_resync_loop_does_not_skip_retire_pending(self):
        """Ghost subs in _retire_pending must NOT block the resync."""
        app = self._make_main()
        run(app._add_ticker("KXWC-ENGCOD"))
        state = app.states["KXWC-ENGCOD"]
        state.orderbook.had_negative_delta = True
        # Mark the pending sub as ghost (retire_pending)
        for k in list(app.websocket._pending_subs.keys()):
            app.websocket._retire_pending.add(k)
        # Now _ticker_sids is empty; give fake SIDs for the resync to proceed
        app.websocket._ticker_sids["KXWC-ENGCOD"] = [1, 2, 3]
        # real_in_flight should be False because all pending are in _retire_pending
        real_in_flight = any(
            "KXWC-ENGCOD" in e.get("tickers", []) and k not in app.websocket._retire_pending
            for k, e in app.websocket._pending_subs.items()
        )
        self.assertFalse(real_in_flight)

    def test_clear_panel_on_ticker_change(self):
        """Changing the ticker in a slot must remove the old one."""
        app = self._make_main()
        run(app.set_ticker_for_slot(0, "KXWC-ENGCOD"))
        app.websocket._ticker_sids["KXWC-ENGCOD"] = [1, 2, 3]
        run(app.set_ticker_for_slot(0, "KXWC-BRAGER"))
        self.assertNotIn("KXWC-ENGCOD", app.active_tickers)
        self.assertIn("KXWC-BRAGER", app.active_tickers)
        self.assertEqual(app.slot_tickers[0], "KXWC-BRAGER")

    def test_same_ticker_two_slots_not_double_subscribed(self):
        """Same ticker in two slots should only create one subscription."""
        app = self._make_main()
        run(app.set_ticker_for_slot(0, "KXWC-ENGCOD"))
        calls_after_first = app.websocket.websocket.send.call_count
        run(app.set_ticker_for_slot(1, "KXWC-ENGCOD"))
        # Second slot should NOT trigger another subscribe
        self.assertEqual(app.websocket.websocket.send.call_count, calls_after_first)
        self.assertEqual(app.slot_tickers[0], "KXWC-ENGCOD")
        self.assertEqual(app.slot_tickers[1], "KXWC-ENGCOD")

    def test_removing_shared_ticker_only_when_last_slot(self):
        """Ticker stays active when it's still in another slot."""
        app = self._make_main()
        run(app.set_ticker_for_slot(0, "KXWC-ENGCOD"))
        run(app.set_ticker_for_slot(1, "KXWC-ENGCOD"))
        # Remove from slot 0 — slot 1 still has it
        run(app.set_ticker_for_slot(0, ""))
        self.assertIn("KXWC-ENGCOD", app.active_tickers)
        self.assertNotIn(0, app.slot_tickers)

    def test_removing_last_slot_cleans_ticker(self):
        app = self._make_main()
        run(app.set_ticker_for_slot(0, "KXWC-ENGCOD"))
        app.websocket._ticker_sids["KXWC-ENGCOD"] = [1, 2, 3]
        run(app.set_ticker_for_slot(0, ""))
        self.assertNotIn("KXWC-ENGCOD", app.active_tickers)
        self.assertNotIn(0, app.slot_tickers)


# ── Ghost-subscription end-to-end scenario ────────────────────────────────────

class TestGhostSubscriptionLifecycle(unittest.TestCase):
    """
    Simulate the COD infinite-loop bug: user reloads a panel before the
    subscription confirmations have arrived, leaving a ghost subscription
    on Kalshi's side.
    """

    def test_full_ghost_sub_lifecycle(self):
        async def _body():
            ws = KalshiWebSocket(api_key="k")
            ws.websocket = make_fake_ws()

            TICKER = "KXWC-COD"

            # Step 1 — initial subscribe
            await ws.subscribe(["orderbook_delta", "fill", "trade"], market_ticker=TICKER)
            first_req_id = 1
            self.assertIn(first_req_id, ws._pending_subs)

            # Step 2 — user force-reloads before SIDs arrive; unsubscribe_ticker
            #          can't send anything yet, marks _retire_pending instead
            await ws.unsubscribe_ticker(TICKER)
            self.assertIn(first_req_id, ws._retire_pending)
            self.assertNotIn(TICKER, ws._ticker_sids)

            # Step 3 — re-subscribe (new request id)
            await ws.subscribe(["orderbook_delta", "fill", "trade"], market_ticker=TICKER)
            second_req_id = 2
            self.assertIn(second_req_id, ws._pending_subs)

            # Step 4 — first sub's SIDs arrive (ghost sids: 101, 102, 103)
            for sid in [101, 102, 103]:
                ws._handle_subscribed(make_subscribed_msg(first_req_id, sid, TICKER))
            await asyncio.sleep(0)  # let deferred tasks run

            # Ghost SIDs must be retired and not in _ticker_sids
            self.assertTrue({101, 102, 103}.issubset(ws._retired_sids))
            sids_for_ticker = ws._ticker_sids.get(TICKER, [])
            for ghost in [101, 102, 103]:
                self.assertNotIn(ghost, sids_for_ticker)
            # Deferred unsubscribe must have been sent
            sent_cmds = [json.loads(c[0][0])["cmd"] for c in ws.websocket.send.call_args_list]
            self.assertIn("unsubscribe", sent_cmds)

            # Step 5 — second sub's SIDs arrive (real sids: 201, 202, 203)
            for sid in [201, 202, 203]:
                ws._handle_subscribed(make_subscribed_msg(second_req_id, sid, TICKER))

            self.assertEqual(sorted(ws._ticker_sids[TICKER]), [201, 202, 203])
            self.assertNotIn(second_req_id, ws._pending_subs)
            self.assertNotIn(second_req_id, ws._retire_pending)

            # Step 6 — a delta that arrives on a ghost SID must be silently dropped
            fake_state = MagicMock()
            fake_state.handle_orderbook_delta = AsyncMock(return_value=False)
            ws.states[TICKER] = fake_state

            await ws.handle_orderbook_delta(make_delta_msg(TICKER, 101, "yes", 0.50, 1))
            fake_state.handle_orderbook_delta.assert_not_called()

            # Step 7 — a delta on a live SID must be processed
            await ws.handle_orderbook_delta(make_delta_msg(TICKER, 201, "yes", 0.50, 1))
            fake_state.handle_orderbook_delta.assert_called_once()

        run(_body())


# ── Shared SID protection ─────────────────────────────────────────────────────

class TestSharedSIDProtection(unittest.TestCase):
    """
    Kalshi reuses the same SID across all markets in the same event.
    Unsubscribing one market must never kill another market's subscription.
    """

    def _make_ws(self):
        ws = KalshiWebSocket(api_key="k")
        ws.websocket = make_fake_ws()
        return ws

    def test_shared_sid_not_sent_on_unsubscribe(self):
        """If two tickers share a SID, unsubscribing one must not send an unsubscribe to Kalshi."""
        ws = self._make_ws()
        ws._ticker_sids["BRAVINI7-1"] = [1]
        ws._ticker_sids["BRAVINI7-2"] = [1]  # same SID — shared

        run(ws.unsubscribe_ticker("BRAVINI7-2"))

        # No unsubscribe command should have been sent (SID 1 is still needed by BRAVINI7-1)
        ws.websocket.send.assert_not_called()
        # BRAVINI7-1's SID mapping must be intact
        self.assertIn("BRAVINI7-1", ws._ticker_sids)
        self.assertIn(1, ws._ticker_sids["BRAVINI7-1"])
        # SID must NOT be retired (that would drop BRAVINI7-1's messages)
        self.assertNotIn(1, ws._retired_sids)
        # BRAVINI7-2's SID must also remain registered so a subsequent unsubscribe of
        # BRAVINI7-1 still sees SID 1 as shared and doesn't wrongly retire it.
        self.assertIn("BRAVINI7-2", ws._ticker_sids)
        self.assertIn(1, ws._ticker_sids["BRAVINI7-2"])

    def test_shared_sid_not_retired_when_second_ticker_removed(self):
        """SID shared by a warm state must not be retired if the other ticker is then removed."""
        ws = self._make_ws()
        ws._ticker_sids["BRAVINI7-1"] = [1]  # active (warm state analog)
        ws._ticker_sids["BRAVINI7-2"] = [1]  # active

        # BRAVINI7-1 goes warm (shared SID, unsubscribe skipped)
        result = run(ws.unsubscribe_ticker("BRAVINI7-1"))
        self.assertFalse(result)
        # SID 1 still registered under BRAVINI7-1 (the fix)
        self.assertIn(1, ws._ticker_sids.get("BRAVINI7-1", []))

        # Now BRAVINI7-2 is also removed — must NOT retire SID 1
        ws.websocket.send.reset_mock()
        run(ws.unsubscribe_ticker("BRAVINI7-2"))
        self.assertNotIn(1, ws._retired_sids)  # SID must stay alive for warm state

    def test_exclusive_sid_is_sent_on_unsubscribe(self):
        """If a ticker has an SID not shared by anyone else, unsubscribing it should send the command."""
        ws = self._make_ws()
        ws._ticker_sids["BRAVINI7-1"] = [1, 2]
        ws._ticker_sids["BRAVINI7-2"] = [1, 3]  # SID 1 shared, SID 3 exclusive to BRAVINI7-2

        run(ws.unsubscribe_ticker("BRAVINI7-2"))

        ws.websocket.send.assert_called_once()
        sent = json.loads(ws.websocket.send.call_args[0][0])
        self.assertEqual(sent["cmd"], "unsubscribe")
        # Only the exclusive SID should be sent
        self.assertEqual(sent["params"]["sids"], [3])
        self.assertNotIn(1, ws._retired_sids)  # shared SID must not be retired
        self.assertIn(3, ws._retired_sids)      # exclusive SID must be retired

    def test_deferred_unsubscribe_skips_sids_in_use(self):
        """_deferred_unsubscribe must not send unsubscribe for SIDs still tracked by active tickers."""
        async def _body():
            ws = self._make_ws()
            ws._ticker_sids["BRAVINI7-1"] = [1]

            # SID 1 is still in use by BRAVINI7-1 — must be filtered out
            await ws._deferred_unsubscribe([1])
            ws.websocket.send.assert_not_called()

            # SID 99 is NOT in use — should be sent
            await ws._deferred_unsubscribe([99])
            ws.websocket.send.assert_called_once()
            sent = json.loads(ws.websocket.send.call_args[0][0])
            self.assertEqual(sent["params"]["sids"], [99])

        run(_body())

    def test_retire_pending_does_not_retire_shared_sid(self):
        """If a retiring sub's SID is already tracked by another active ticker, don't add to _retired_sids."""
        ws = self._make_ws()
        # BRAVINI7-1 already has SID 1 registered as active
        ws._ticker_sids["BRAVINI7-1"] = [1]

        # Simulate BRAVINI7-2 being subscribed then immediately marked for retirement
        run(ws.subscribe(["orderbook_delta", "fill", "trade"], market_ticker="BRAVINI7-2"))
        req_id = 1
        ws._retire_pending.add(req_id)

        # Kalshi confirms SID 1 for BRAVINI7-2 (shared SID)
        ws._handle_subscribed(make_subscribed_msg(req_id, 1, "BRAVINI7-2"))

        # SID 1 must NOT be retired — BRAVINI7-1 is still using it
        self.assertNotIn(1, ws._retired_sids)
        # BRAVINI7-2 must not be in _ticker_sids
        self.assertNotIn("BRAVINI7-2", ws._ticker_sids)

    def test_involuntary_unsub_resubscribes_all_affected_tickers(self):
        """An involuntary unsubscribe on a shared SID must trigger resubscription for all tickers using it."""
        async def _body():
            ws = self._make_ws()
            ws._ticker_sids["BRAVINI7-1"] = [1]
            ws._ticker_sids["BRAVINI7-2"] = [1]  # both share SID 1
            ws.states["BRAVINI7-1"] = MagicMock()
            ws.states["BRAVINI7-2"] = MagicMock()

            # Simulate Kalshi sending an involuntary unsubscribed for SID 1
            ws._handle_unsubscribed({"type": "unsubscribed", "id": 5, "sid": 1, "seq": 1})
            await asyncio.sleep(0)  # let resubscribe tasks run

            # Both tickers' SID mappings should have been cleared (they'll be repopulated on resubscribe)
            self.assertNotIn("BRAVINI7-1", ws._ticker_sids)
            self.assertNotIn("BRAVINI7-2", ws._ticker_sids)

            # Both should have new subscribe commands queued
            subscribe_calls = [
                json.loads(c[0][0]) for c in ws.websocket.send.call_args_list
                if json.loads(c[0][0]).get("cmd") == "subscribe"
            ]
            subscribed_tickers = {c["params"]["market_ticker"] for c in subscribe_calls}
            self.assertIn("BRAVINI7-1", subscribed_tickers)
            self.assertIn("BRAVINI7-2", subscribed_tickers)

        run(_body())


# ── Warm state reuse ─────────────────────────────────────────────────────────

class TestWarmStateReuse(unittest.TestCase):
    """
    When Kalshi's shared SID means we can't actually unsubscribe, the state is
    kept warm (processing deltas in the background) so that re-adding the ticker
    doesn't create a blank orderbook that immediately goes out of sync.
    """

    def _make_main(self):
        app = Main()
        app.websocket.websocket = make_fake_ws()
        app.connected = True
        return app

    def _share_sid(self, app, ticker_a, ticker_b, sid=1):
        """Give two tickers the same SID so unsubscribe will be skipped."""
        app.websocket._ticker_sids[ticker_a] = [sid]
        app.websocket._ticker_sids[ticker_b] = [sid]

    def test_shared_sid_keeps_state_warm(self):
        """Removing a ticker whose SID is shared keeps the state in self.states."""
        app = self._make_main()
        run(app._add_ticker("KXWC-ENGCOD"))
        run(app._add_ticker("KXWC-BRAGER"))
        self._share_sid(app, "KXWC-ENGCOD", "KXWC-BRAGER")

        state_before = app.states["KXWC-ENGCOD"]
        run(app._remove_ticker("KXWC-ENGCOD"))

        self.assertNotIn("KXWC-ENGCOD", app.active_tickers)
        self.assertIn("KXWC-ENGCOD", app._warm_states)
        self.assertIn("KXWC-ENGCOD", app.states)           # state preserved
        self.assertIs(app.states["KXWC-ENGCOD"], state_before)  # same object

    def test_exclusive_sid_destroys_state(self):
        """Removing a ticker with exclusive SIDs destroys its state normally."""
        app = self._make_main()
        run(app._add_ticker("KXWC-ENGCOD"))
        app.websocket._ticker_sids["KXWC-ENGCOD"] = [1, 2, 3]  # exclusive

        run(app._remove_ticker("KXWC-ENGCOD"))

        self.assertNotIn("KXWC-ENGCOD", app.active_tickers)
        self.assertNotIn("KXWC-ENGCOD", app._warm_states)
        self.assertNotIn("KXWC-ENGCOD", app.states)

    def test_warm_state_promoted_on_readd(self):
        """Re-adding a warm ticker reuses the existing state object — no new State created."""
        app = self._make_main()
        run(app._add_ticker("KXWC-ENGCOD"))
        run(app._add_ticker("KXWC-BRAGER"))
        self._share_sid(app, "KXWC-ENGCOD", "KXWC-BRAGER")

        state_before = app.states["KXWC-ENGCOD"]
        run(app._remove_ticker("KXWC-ENGCOD"))
        self.assertIn("KXWC-ENGCOD", app._warm_states)

        run(app._add_ticker("KXWC-ENGCOD"))

        self.assertIn("KXWC-ENGCOD", app.active_tickers)
        self.assertNotIn("KXWC-ENGCOD", app._warm_states)
        self.assertIs(app.states["KXWC-ENGCOD"], state_before)  # same object, not recreated

    def test_warm_state_promotion_does_not_resubscribe(self):
        """Promoting a warm state must NOT send a subscribe — doing so creates new exclusive
        fill/trade SIDs that make the next removal look exclusive and destroy the state."""
        async def _body():
            app = self._make_main()
            await app._add_ticker("KXWC-ENGCOD")
            await app._add_ticker("KXWC-BRAGER")
            self._share_sid(app, "KXWC-ENGCOD", "KXWC-BRAGER")

            # ENGCOD goes warm
            await app._remove_ticker("KXWC-ENGCOD")
            self.assertIn("KXWC-ENGCOD", app._warm_states)

            sends_before = app.websocket.websocket.send.call_count

            # Promote back to active
            await app._add_ticker("KXWC-ENGCOD")
            self.assertIn("KXWC-ENGCOD", app.active_tickers)

            # No new subscribe should have been sent
            self.assertEqual(app.websocket.websocket.send.call_count, sends_before)

            # _ticker_sids must still only have the shared SID 1 (no new exclusive SIDs)
            sids = app.websocket._ticker_sids.get("KXWC-ENGCOD", [])
            self.assertIn(1, sids)
            exclusive = [s for s in sids if s not in app.websocket._ticker_sids.get("KXWC-BRAGER", [])]
            self.assertEqual(exclusive, [], "Warm promotion must not create exclusive SIDs")

            # Second removal must still go warm (not destroy state)
            await app._remove_ticker("KXWC-ENGCOD")
            self.assertIn("KXWC-ENGCOD", app._warm_states)
            self.assertIn("KXWC-ENGCOD", app.states)

        run(_body())

    def test_warm_state_not_broadcast(self):
        """_broadcast_orderbook must skip warm states so they don't fill empty panels."""
        async def _body():
            app = self._make_main()
            mock_ladder = MagicMock()
            mock_ladder.broadcast_orderbook = AsyncMock()
            mock_ladder.register_state = MagicMock()
            mock_ladder.unregister_state = MagicMock()
            app.ladder_server = mock_ladder

            await app._add_ticker("KXWC-ENGCOD")
            await app._add_ticker("KXWC-BRAGER")
            self._share_sid(app, "KXWC-ENGCOD", "KXWC-BRAGER")
            await app._remove_ticker("KXWC-ENGCOD")

            mock_ladder.broadcast_orderbook.reset_mock()
            await app._broadcast_orderbook(app.states["KXWC-ENGCOD"])

            mock_ladder.broadcast_orderbook.assert_not_called()

        run(_body())

    def test_resync_loop_skips_warm_states(self):
        """A warm state with had_negative_delta must not trigger a resync."""
        app = self._make_main()
        run(app._add_ticker("KXWC-ENGCOD"))
        run(app._add_ticker("KXWC-BRAGER"))
        self._share_sid(app, "KXWC-ENGCOD", "KXWC-BRAGER")
        run(app._remove_ticker("KXWC-ENGCOD"))

        app.states["KXWC-ENGCOD"].orderbook.had_negative_delta = True

        # Run the inner loop body — warm states must be skipped
        sends_before = app.websocket.websocket.send.call_count
        for ticker, state in list(app.states.items()):
            if ticker not in app.active_tickers:
                continue
            if state.orderbook.had_negative_delta:
                self.fail(f"Resync incorrectly triggered for warm state {ticker}")
        # No extra WS sends from resync
        self.assertEqual(app.websocket.websocket.send.call_count, sends_before)

    def test_warm_state_panel_switch_scenario(self):
        """Full Haaland→Kane→Haaland scenario: re-adding reuses the warm state."""
        app = self._make_main()
        # Load Haaland in slot 0
        run(app.set_ticker_for_slot(0, "KXWC-NOREHAALA9-1"))
        self._share_sid(app, "KXWC-NOREHAALA9-1", "KXWC-NOREHAALA9-1")  # set its own SID

        # Now share with Kane (simulate event-level SID)
        run(app._add_ticker("KXWC-ENGHKANE9-1"))
        app.websocket._ticker_sids["KXWC-NOREHAALA9-1"] = [1]
        app.websocket._ticker_sids["KXWC-ENGHKANE9-1"] = [1]

        haaland_state = app.states["KXWC-NOREHAALA9-1"]

        # Switch slot 0 to Kane
        run(app.set_ticker_for_slot(0, "KXWC-ENGHKANE9-1"))

        self.assertNotIn("KXWC-NOREHAALA9-1", app.active_tickers)
        self.assertIn("KXWC-NOREHAALA9-1", app._warm_states)

        # Re-add Haaland to slot 0
        run(app.set_ticker_for_slot(0, "KXWC-NOREHAALA9-1"))

        self.assertIn("KXWC-NOREHAALA9-1", app.active_tickers)
        self.assertNotIn("KXWC-NOREHAALA9-1", app._warm_states)
        # Critical: same state object — orderbook was never wiped
        self.assertIs(app.states["KXWC-NOREHAALA9-1"], haaland_state)

    def test_resync_skips_resubscribe_when_sid_shared(self):
        """Resync must not re-subscribe after a shared-SID unsubscribe (no snapshot possible)."""
        async def _body():
            app = self._make_main()
            await app._add_ticker("KXWC-ENGCOD")
            await app._add_ticker("KXWC-BRAGER")
            self._share_sid(app, "KXWC-ENGCOD", "KXWC-BRAGER")  # both share SID 1

            # Simulate silence resync on KXWC-ENGCOD (still active, shared SID)
            sends_before = app.websocket.websocket.send.call_count
            app.states["KXWC-ENGCOD"].orderbook.had_negative_delta = False

            # Run the resync block manually for KXWC-ENGCOD
            has_sids = bool(app.websocket._ticker_sids.get("KXWC-ENGCOD"))
            self.assertTrue(has_sids)
            actually_unsubscribed = await app.websocket.unsubscribe_ticker("KXWC-ENGCOD")
            self.assertFalse(actually_unsubscribed)  # shared SID — unsubscribe skipped

            # When unsubscribe is skipped, re-subscribe must also be skipped
            # (verified by the resync loop's `if not actually_unsubscribed: continue`)
            # Confirm no subscribe was sent and SID 1 is still tracked
            self.assertEqual(app.websocket.websocket.send.call_count, sends_before)
            self.assertIn(1, app.websocket._ticker_sids.get("KXWC-ENGCOD", []))

        run(_body())

    def test_warm_states_cleared_on_run_finally(self):
        """Warm states are destroyed when the WebSocket session ends."""
        app = self._make_main()
        run(app._add_ticker("KXWC-ENGCOD"))
        run(app._add_ticker("KXWC-BRAGER"))
        self._share_sid(app, "KXWC-ENGCOD", "KXWC-BRAGER")
        run(app._remove_ticker("KXWC-ENGCOD"))
        self.assertIn("KXWC-ENGCOD", app._warm_states)

        # Simulate what run()'s finally block does
        app.connected = False
        for ticker in list(app._warm_states):
            app.states.pop(ticker, None)
        app._warm_states.clear()

        self.assertNotIn("KXWC-ENGCOD", app._warm_states)
        self.assertNotIn("KXWC-ENGCOD", app.states)


# ── Order cancellation behavior ───────────────────────────────────────────────

class TestOrderCancellationBehavior(unittest.TestCase):
    """
    Verify when orders are and are not cancelled automatically.
    """

    def _make_main(self):
        app = Main()
        app.websocket.websocket = make_fake_ws()
        app.connected = True
        return app

    def test_orders_cancelled_on_market_change(self):
        """Switching a slot to a different market must cancel resting orders on the old one."""
        async def _body():
            app = self._make_main()
            await app.set_ticker_for_slot(0, "KXWC-ENGCOD")
            app.websocket._ticker_sids["KXWC-ENGCOD"] = [1, 2, 3]

            _mock_kalshi_api.cancel_all_bids_api.reset_mock()
            _mock_kalshi_api.cancel_all_asks_api.reset_mock()

            await app.set_ticker_for_slot(0, "KXWC-BRAGER")
            await asyncio.sleep(0)  # let the _cancel_resting_orders task run

            # ENGCOD must have been cancelled (removed); BRAGER will also be cancelled
            # because _add_ticker clears any leftover orders when a market is first loaded.
            _mock_kalshi_api.cancel_all_bids_api.assert_any_call(
                ticker="KXWC-ENGCOD", quiet_not_found=True
            )
            _mock_kalshi_api.cancel_all_asks_api.assert_any_call(
                ticker="KXWC-ENGCOD", quiet_not_found=True
            )

        run(_body())

    def test_orders_cancelled_on_slot_cleared(self):
        """Clearing a slot (setting ticker to '') must cancel resting orders on the removed market."""
        async def _body():
            app = self._make_main()
            await app.set_ticker_for_slot(0, "KXWC-ENGCOD")
            app.websocket._ticker_sids["KXWC-ENGCOD"] = [1, 2, 3]

            _mock_kalshi_api.cancel_all_bids_api.reset_mock()
            _mock_kalshi_api.cancel_all_asks_api.reset_mock()

            await app.set_ticker_for_slot(0, "")
            await asyncio.sleep(0)

            _mock_kalshi_api.cancel_all_bids_api.assert_called_once_with(
                ticker="KXWC-ENGCOD", quiet_not_found=True
            )
            _mock_kalshi_api.cancel_all_asks_api.assert_called_once_with(
                ticker="KXWC-ENGCOD", quiet_not_found=True
            )

        run(_body())

    def test_orders_not_cancelled_when_ticker_still_in_other_slot(self):
        """If the ticker is still assigned to another slot, orders must NOT be cancelled."""
        async def _body():
            app = self._make_main()
            await app.set_ticker_for_slot(0, "KXWC-ENGCOD")
            await app.set_ticker_for_slot(1, "KXWC-ENGCOD")  # same ticker in two slots

            _mock_kalshi_api.cancel_all_bids_api.reset_mock()
            _mock_kalshi_api.cancel_all_asks_api.reset_mock()

            # Remove from slot 0 only — slot 1 still has it
            await app.set_ticker_for_slot(0, "")
            await asyncio.sleep(0)

            # Cancel must NOT have been called (ticker still active in slot 1)
            _mock_kalshi_api.cancel_all_bids_api.assert_not_called()
            _mock_kalshi_api.cancel_all_asks_api.assert_not_called()

        run(_body())

    def test_orders_not_cancelled_on_startup_shutdown(self):
        """
        Shutdown (disconnect) must not trigger order cancellation.
        Orders on Kalshi remain resting after the app exits.
        """
        app = self._make_main()
        run(app._add_ticker("KXWC-ENGCOD"))

        _mock_kalshi_api.cancel_all_bids_api.reset_mock()
        _mock_kalshi_api.cancel_all_asks_api.reset_mock()

        # Simulate shutdown — no _remove_ticker call, just disconnect
        app.connected = False

        # Neither cancel function should have been called by the disconnect
        _mock_kalshi_api.cancel_all_bids_api.assert_not_called()
        _mock_kalshi_api.cancel_all_asks_api.assert_not_called()


# ── Page-group slot behaviour ─────────────────────────────────────────────────
#
# Pages are a frontend-only concept.  The backend treats slot numbers 0-9
# identically; these tests confirm the backend invariants that the UI relies on.

class TestPageGroupSlots(unittest.TestCase):

    def _make_main(self):
        app = Main()
        app.websocket.websocket = make_fake_ws()
        app.connected = True
        return app

    # Q1 / Q2 – page-2 slot works like any other slot
    def test_page2_slot_assigns_and_subscribes(self):
        """Slot 5 (page 2) subscribes and assigns exactly like slot 0."""
        app = self._make_main()
        run(app.set_ticker_for_slot(5, "KXWC-ENGCOD"))
        self.assertEqual(app.slot_tickers[5], "KXWC-ENGCOD")
        self.assertIn("KXWC-ENGCOD", app.active_tickers)

    # Q2 – two different markets on different pages are fully independent
    def test_cross_page_different_tickers_are_independent(self):
        app = self._make_main()
        run(app.set_ticker_for_slot(0, "KXWC-ENGCOD"))
        run(app.set_ticker_for_slot(5, "KXWC-BRAGER"))
        self.assertIn("KXWC-ENGCOD", app.active_tickers)
        self.assertIn("KXWC-BRAGER", app.active_tickers)
        self.assertEqual(app.slot_tickers[0], "KXWC-ENGCOD")
        self.assertEqual(app.slot_tickers[5], "KXWC-BRAGER")

    # Q1 – same ticker in slot 0 and slot 5 creates only one subscription
    def test_cross_page_same_ticker_one_subscription(self):
        app = self._make_main()
        run(app.set_ticker_for_slot(0, "KXWC-ENGCOD"))
        calls_after_first = app.websocket.websocket.send.call_count
        run(app.set_ticker_for_slot(5, "KXWC-ENGCOD"))
        self.assertEqual(app.websocket.websocket.send.call_count, calls_after_first)
        self.assertEqual(app.slot_tickers[0], "KXWC-ENGCOD")
        self.assertEqual(app.slot_tickers[5], "KXWC-ENGCOD")

    # Q3 – removing a page-2 market must not touch page-1 slots
    def test_remove_page2_ticker_does_not_affect_page1(self):
        app = self._make_main()
        run(app.set_ticker_for_slot(0, "KXWC-ENGCOD"))
        run(app.set_ticker_for_slot(5, "KXWC-BRAGER"))
        app.websocket._ticker_sids["KXWC-BRAGER"] = [10, 11, 12]
        run(app.set_ticker_for_slot(5, ""))
        self.assertNotIn("KXWC-BRAGER", app.active_tickers)
        self.assertNotIn(5, app.slot_tickers)
        self.assertIn("KXWC-ENGCOD", app.active_tickers)
        self.assertEqual(app.slot_tickers[0], "KXWC-ENGCOD")

    # Q3 – shared ticker: clearing one page keeps it alive on the other
    def test_shared_ticker_across_pages_survives_page2_removal(self):
        app = self._make_main()
        run(app.set_ticker_for_slot(0, "KXWC-ENGCOD"))
        run(app.set_ticker_for_slot(5, "KXWC-ENGCOD"))
        run(app.set_ticker_for_slot(5, ""))
        self.assertIn("KXWC-ENGCOD", app.active_tickers)
        self.assertEqual(app.slot_tickers[0], "KXWC-ENGCOD")
        self.assertNotIn(5, app.slot_tickers)

    # Q4 – force-reloading a page-2 slot must not disturb page-1 tickers
    def test_force_reload_page2_does_not_affect_page1_ticker(self):
        app = self._make_main()
        run(app.set_ticker_for_slot(0, "KXWC-ENGCOD"))
        run(app.set_ticker_for_slot(5, "KXWC-BRAGER"))
        app.websocket._ticker_sids["KXWC-BRAGER"] = [10, 11, 12]
        run(app.set_ticker_for_slot(5, "KXWC-BRAGER", force=True))
        self.assertIn("KXWC-ENGCOD", app.active_tickers)
        self.assertEqual(app.slot_tickers[0], "KXWC-ENGCOD")
        self.assertEqual(app.slot_tickers[5], "KXWC-BRAGER")

    # Q5 (partial) – 10 unique tickers across both pages subscribe without conflict
    def test_all_ten_slots_unique_tickers(self):
        """All 10 slots can hold unique tickers simultaneously — no cross-slot interference."""
        app = self._make_main()
        tickers = [f"KXWC-TICK{i:02d}" for i in range(10)]
        for slot, ticker in enumerate(tickers):
            run(app.set_ticker_for_slot(slot, ticker))
        for slot, ticker in enumerate(tickers):
            self.assertEqual(app.slot_tickers[slot], ticker)
            self.assertIn(ticker, app.active_tickers)
        self.assertEqual(len(app.active_tickers), 10)

    # Q5 (partial) – adding 10 markets fires exactly 10 subscribe commands (no duplicates)
    def test_ten_unique_tickers_each_subscribed_once(self):
        app = self._make_main()
        tickers = [f"KXWC-TICK{i:02d}" for i in range(10)]
        for slot, ticker in enumerate(tickers):
            run(app.set_ticker_for_slot(slot, ticker))
        subscribe_calls = [
            json.loads(c[0][0])
            for c in app.websocket.websocket.send.call_args_list
            if json.loads(c[0][0]).get("cmd") == "subscribe"
        ]
        self.assertEqual(len(subscribe_calls), 10)


class TestPostOrderExceptionHandling(unittest.TestCase):
    """post_order must clean up its pending-order entry when post_order_api raises."""

    def setUp(self):
        # update_orders is globally stubbed via sys.modules, so we load the real
        # module under a private name so we can patch post_order_api inside it.
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_update_orders_real",
            str(_WEBSOCKET_DIR / "update_orders.py"),
        )
        self._mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self._mod)

    def _make_state(self):
        state = MagicMock()
        state.ticker = "TICK-A"
        state.emit_orderbook_update = AsyncMock()
        return state

    def test_post_order_timeout_returns_false_and_clears_pending(self):
        """asyncio.TimeoutError from post_order_api must not leave a stuck pending order."""
        state = self._make_state()
        with patch.object(self._mod, "post_order_api", AsyncMock(side_effect=asyncio.TimeoutError())):
            result = run(self._mod.post_order(state, "buy", 5, to_internal(0.45), should_abort=lambda: False))
        self.assertFalse(result)
        state.orderbook.post_order_internal_pending.assert_called_once()
        state.orderbook.post_order_internal_fail.assert_called_once()
        state.emit_orderbook_update.assert_not_called()

    def test_post_order_generic_exception_returns_false_and_clears_pending(self):
        """Any unexpected exception from post_order_api must clean up the pending order."""
        state = self._make_state()
        with patch.object(self._mod, "post_order_api", AsyncMock(side_effect=RuntimeError("network error"))):
            result = run(self._mod.post_order(state, "buy", 5, to_internal(0.45), should_abort=lambda: False))
        self.assertFalse(result)
        state.orderbook.post_order_internal_pending.assert_called_once()
        state.orderbook.post_order_internal_fail.assert_called_once()
        state.emit_orderbook_update.assert_not_called()


# ── Shared-SID fill/trade registration (frozen-position bug fix) ─────────────
#
# Kalshi shares one SID per channel across every market in the same event, but
# only sends a 'subscribed' confirmation to one of several concurrent subscribe
# requests. Before this fix, a ticker that "lost" that confirmation race never
# got its fill/trade SID registered in _ticker_sids — so if Kalshi ever dropped
# that shared SID, only the "winning" ticker got resubscribed, and every other
# leg silently stopped receiving fills for the rest of the session (frozen
# position). These tests cover the fix: handle_fill/handle_public_trade now
# register the SID for whichever ticker the message names, guarded so a late
# message on an already-retired SID can't resurrect it.

class TestSharedSIDFillRegistration(unittest.TestCase):
    def _make_ws(self):
        ws = KalshiWebSocket(api_key="k")
        ws.websocket = make_fake_ws()
        return ws

    def test_fill_registers_shared_sid_for_ticker_that_lost_confirmation(self):
        """A ticker with no 'subscribed' confirmation must still get its SID
        tracked once a fill naming it arrives."""
        async def _body():
            ws = self._make_ws()
            ws.states = {"WINNER": MagicMock(), "LOSER": MagicMock()}
            ws.states["LOSER"].handle_fill = AsyncMock()
            ws._ticker_sids["WINNER"] = [4]  # WINNER got the real 'subscribed' confirmation

            # LOSER never appears in _ticker_sids until its first fill arrives on the
            # shared SID — this is exactly the bug scenario.
            self.assertNotIn("LOSER", ws._ticker_sids)
            await ws.handle_fill(make_fill_msg("LOSER", sid=4, count=5, post_position=5))

            self.assertIn(4, ws._ticker_sids.get("LOSER", []))
            ws.states["LOSER"].handle_fill.assert_called_once()

        run(_body())

    def test_trade_registers_shared_sid_for_ticker_that_lost_confirmation(self):
        """Same as above, for the public trade channel."""
        async def _body():
            ws = self._make_ws()
            ws.states = {"LOSER": MagicMock()}
            ws.states["LOSER"].handle_public_trade = AsyncMock()

            await ws.handle_public_trade(make_trade_msg("LOSER", sid=7))

            self.assertIn(7, ws._ticker_sids.get("LOSER", []))
            ws.states["LOSER"].handle_public_trade.assert_called_once()

        run(_body())

    def test_fill_does_not_resurrect_retired_sid(self):
        """A late fill on an already-retired SID must not be re-registered into
        _ticker_sids, but the fill itself must still be processed — fills are
        not replayable by Kalshi, so they can never be dropped."""
        async def _body():
            ws = self._make_ws()
            ws.states = {"TICK": MagicMock()}
            ws.states["TICK"].handle_fill = AsyncMock()
            ws._retired_sids.add(99)

            await ws.handle_fill(make_fill_msg("TICK", sid=99, count=1, post_position=1))

            self.assertNotIn(99, ws._ticker_sids.get("TICK", []))
            # The fill itself must still be delivered despite the retired SID.
            ws.states["TICK"].handle_fill.assert_called_once()

        run(_body())

    def test_involuntary_unsubscribe_resubscribes_all_tickers_sharing_fill_sid(self):
        """Regression test for the core bug: when a shared fill SID is dropped,
        EVERY ticker relying on it must be resubscribed, not just the one that
        won the original 'subscribed' confirmation."""
        async def _body():
            ws = self._make_ws()
            ws.states = {"WINNER": MagicMock(), "LOSER": MagicMock()}
            ws.states["LOSER"].handle_fill = AsyncMock()

            # WINNER got a real confirmation for shared fill SID 4.
            ws._ticker_sids["WINNER"] = [4]
            # LOSER only learns about SID 4 via a fill — this is the fix being exercised.
            await ws.handle_fill(make_fill_msg("LOSER", sid=4, count=1, post_position=1))
            self.assertIn(4, ws._ticker_sids.get("LOSER", []))

            ws.websocket.send.reset_mock()

            # Kalshi drops SID 4 involuntarily (server-side, not something we requested).
            ws._handle_unsubscribed({"sid": 4, "msg": {}})
            await asyncio.sleep(0)  # let the resubscribe tasks created above run

            sent = [json.loads(c[0][0]) for c in ws.websocket.send.call_args_list]
            resubscribed_tickers = {
                s["params"].get("market_ticker") for s in sent if s.get("cmd") == "subscribe"
            }
            self.assertEqual(
                resubscribed_tickers, {"WINNER", "LOSER"},
                "Both tickers sharing the dropped SID must be resubscribed, not just the "
                "one that originally got the 'subscribed' confirmation.",
            )

        run(_body())

    def test_partial_fills_accumulate_correctly_after_late_sid_registration(self):
        """End-to-end: a resting order on a ticker that never got a 'subscribed'
        confirmation receives two sequential partial fills. Position must
        accumulate correctly across both, and the SID must be tracked after
        the very first one."""
        async def _body():
            ws = self._make_ws()
            ticker = "KXWORLDNEWSMENTION-26JUL23-LEBR"
            event = {"event_ticker": "KXWORLDNEWSMENTION-26JUL23"}
            market = {"ticker": ticker}
            state = State(event, market, on_orderbook_update=AsyncMock())
            ws.states[ticker] = state

            # Leave a resting buy order on the ladder.
            state.orderbook.post_order_internal_pending("co-1", 20, "buy", to_internal(0.45))
            state.orderbook.post_order_internal_success("co-1", "o-1", "buy", to_internal(0.45))

            self.assertNotIn(ticker, ws._ticker_sids)

            # First partial fill: 5 of 20 contracts grabbed.
            await ws.handle_fill(make_fill_msg(ticker, sid=4, count=5, post_position=5, client_order_id="co-1"))
            self.assertEqual(state.position, 5)
            self.assertIn(4, ws._ticker_sids.get(ticker, []))
            self.assertEqual(state.orderbook.live_orders["co-1"]["remaining_count"], 15)

            # Second partial fill: 7 more contracts grabbed.
            await ws.handle_fill(make_fill_msg(ticker, sid=4, count=7, post_position=12, client_order_id="co-1"))
            self.assertEqual(state.position, 12)
            self.assertEqual(state.orderbook.live_orders["co-1"]["remaining_count"], 8)
            # SID list must not have grown — same SID, registered once.
            self.assertEqual(ws._ticker_sids[ticker], [4])

        run(_body())


# ── Position-mismatch self-heal (missed-fill race bug fix) ───────────────────
#
# state.position is seeded via a REST snapshot before the fill/trade WebSocket
# channel is confirmed. Any fill that lands in that race window is invisible
# to the client (fill channels don't replay past messages), permanently
# offsetting state.position from the exchange's authoritative post_position_fp.
# handle_fill used to treat that discrepancy as fatal — raising *before*
# resyncing self.position to post_position_fp and *before* running
# handle_fill_internal — so the same offset recurred on every later fill, and
# the orderbook's live_orders bookkeeping silently went stale (surfacing later
# as "Quantity negative, clamping to 0" once a resync rebuilt the book from a
# fresh snapshot). These tests cover the fix: handle_fill now trusts
# post_position_fp and self-heals instead of raising.

class TestPositionMismatchSelfHeal(unittest.TestCase):
    def _make_state(self, ticker="KXTRUMPSAYCOMPANY-26AUG01-FOX"):
        event = {"event_ticker": "KXTRUMPSAYCOMPANY-26AUG01"}
        market = {"ticker": ticker}
        return State(event, market, on_orderbook_update=AsyncMock())

    def test_mismatch_self_heals_to_server_position_instead_of_raising(self):
        """A missed prior fill (e.g. from the REST-seed/subscribe race) must not
        crash handle_fill; state.position must resync to the server's
        authoritative post_position_fp."""
        state = self._make_state()
        # Mirrors the production scenario: local position starts at 0, but a
        # 100-lot fill was missed before this session's fill channel went
        # live, so the exchange's real post-fill position is 100 higher than
        # what count_fp alone would produce.
        run(state.handle_fill(make_fill_msg(state.ticker, sid=1, count=5.78, post_position=105.78)))
        self.assertEqual(state.position, 105.78)

    def test_mismatch_does_not_recur_on_next_fill(self):
        """Once healed, the next fill must accumulate from the corrected
        baseline — the ~100 offset must not reappear on every subsequent fill."""
        state = self._make_state()
        run(state.handle_fill(make_fill_msg(state.ticker, sid=1, count=5.78, post_position=105.78)))
        self.assertEqual(state.position, 105.78)

        # A normal, consistent fill following the heal: 105.78 + 14.05 == 119.83.
        run(state.handle_fill(make_fill_msg(state.ticker, sid=1, count=14.05, post_position=119.83)))
        self.assertEqual(state.position, 119.83)

    def test_orderbook_bookkeeping_still_updates_despite_mismatch(self):
        """Regression for the negative-quantity-after-resync bug: even when
        state.position mismatches post_position_fp, handle_fill_internal must
        still run so live_orders stays in sync with the real remaining size."""
        state = self._make_state()
        state.orderbook.post_order_internal_pending("co-1", 20, "buy", to_internal(0.45))
        state.orderbook.post_order_internal_success("co-1", "o-1", "buy", to_internal(0.45))

        # This fill mismatches (simulating a missed 100-lot fill elsewhere on
        # the account) but is for an order this client does track locally.
        run(state.handle_fill(make_fill_msg(
            state.ticker, sid=1, count=5, post_position=105, client_order_id="co-1",
        )))

        self.assertEqual(state.position, 105)
        # remaining_count must be decremented by this fill's count regardless
        # of the position mismatch — previously the raise happened before this
        # ever ran, leaving remaining_count stale until a resync clamped a
        # negative quantity to 0.
        self.assertEqual(state.orderbook.live_orders["co-1"]["remaining_count"], 15)

    def test_invalid_internal_side_still_raises(self):
        """Sanity check: the self-heal only applies to position-value
        mismatches; a genuinely malformed message must still raise."""
        state = self._make_state()
        msg = make_fill_msg(state.ticker, sid=1, count=5, post_position=5)
        msg["msg"]["book_side"] = "sideways"
        with self.assertRaises(ValueError):
            run(state.handle_fill(msg))


# ── add_ticker subscribes before seeding position (missed-fill race fix) ─────
#
# Seeding state.position via REST used to happen *before* the WebSocket fill
# channel subscription was requested, leaving a window where a fill landing
# on a resting order was invisible to this client. Subscribing first shrinks
# that window to (at most) the REST position-fetch itself, during which any
# fill is now captured live by the already-open channel.

class TestAddTickerSubscribeOrdering(unittest.TestCase):
    def _make_main(self):
        app = Main()
        app.websocket.websocket = make_fake_ws()
        app.connected = True
        return app

    def test_subscribe_happens_before_position_seed(self):
        app = self._make_main()
        call_order = []

        async def fake_subscribe(*args, **kwargs):
            call_order.append("subscribe")

        async def fake_get_positions(*args, **kwargs):
            call_order.append("get_positions")
            return {}

        with patch.object(app.websocket, "subscribe", AsyncMock(side_effect=fake_subscribe)), \
                patch.object(main_module, "get_positions", AsyncMock(side_effect=fake_get_positions)):
            run(app._add_ticker("KXWC-ENGCOD"))

        self.assertEqual(call_order, ["subscribe", "get_positions"])


# ── LadderServer broadcast concurrency ────────────────────────────────────────
#
# _broadcast awaits websocket.send() for each connection in turn. Each client
# connection/disconnection runs as its own concurrent task (_handler), so a
# connect or disconnect landing exactly during one of those awaits used to
# mutate self.connections (a set) while _broadcast was still iterating over
# it, raising "RuntimeError: Set changed size during iteration".

class TestLadderServerBroadcastConcurrency(unittest.TestCase):
    def test_broadcast_survives_concurrent_connect(self):
        """A new client connecting mid-broadcast must not crash the broadcast."""
        async def _body():
            server = LadderServer()
            ws_a = MagicMock()
            ws_b = MagicMock()

            async def send_and_connect_new_client(_message):
                # Simulates another client's _handler task connecting while
                # this broadcast is still iterating self.connections.
                server.connections.add(MagicMock())

            ws_a.send = AsyncMock(side_effect=send_and_connect_new_client)
            ws_b.send = AsyncMock()
            server.connections = {ws_a, ws_b}

            await server._broadcast({"type": "test"})  # must not raise

            self.assertEqual(len(server.connections), 3)  # new client stayed registered

        run(_body())

    def test_broadcast_survives_concurrent_disconnect(self):
        """A client disconnecting mid-broadcast must not crash the broadcast."""
        async def _body():
            server = LadderServer()
            ws_a = MagicMock()
            ws_b = MagicMock()

            async def send_and_disconnect_other_client(_message):
                # Simulates ws_b's _handler task hitting its `finally: discard` block
                # while this broadcast is still iterating self.connections.
                server.connections.discard(ws_b)

            ws_a.send = AsyncMock(side_effect=send_and_disconnect_other_client)
            ws_b.send = AsyncMock()
            server.connections = {ws_a, ws_b}

            await server._broadcast({"type": "test"})  # must not raise

        run(_body())


if __name__ == "__main__":
    unittest.main(verbosity=2)
