import asyncio
import logging
import time
from typing import Dict, Optional, Callable, Awaitable

from orderbook import OrderBook, DEFAULT_ORDER_SIZE, PRICE_MULTIPLIER, MAX_PRICE, to_internal
from update_orders import reconcile_live_orders
logger = logging.getLogger(__name__)


class State:
    """
    Represents the state of a market ticker, including its orderbook and positions.
    """

    def __init__(
        self, event: Dict, market: Dict,
        print_orderbook_strings: bool = False,
        print_fill_strings: bool = False,
        on_orderbook_update: Optional[Callable[['State'], Awaitable[None]]] = None
    ):
        """Initialize state for a specific market."""
        self.event = event
        self.market = market
        self.event_ticker = event['event_ticker']
        self.ticker = market['ticker']
        self.market_title = market.get('title')
        # Which exchange shard this market lives on (0 = default). Collateral must be
        # funded on this shard for orders to pass the matching-engine check.
        self.exchange_index: int = int(market.get('exchange_index') or 0)

        self.print_orderbook_strings = print_orderbook_strings
        self.print_fill_strings = print_fill_strings

        self.has_snapped_to_yes = False

        self.orderbook = OrderBook(self.ticker)
        self.position: float = 0  # Fractional contracts supported
        self.on_orderbook_update = on_orderbook_update
        # Tracks the last time any WS message (snapshot or delta) was received.
        # Initialized to now so newly-added markets don't immediately trigger a resync.
        self.last_ws_message_at: float = time.monotonic()
        self._reconciling: bool = False

    async def emit_orderbook_update(self) -> None:
        if self.on_orderbook_update:
            await self.on_orderbook_update(self)

    def request_reconcile(self) -> None:
        """
        Fire-and-forget resync of live orders against the exchange's authoritative
        resting-order list. Coalesces concurrent requests for this ticker into a
        single in-flight call so a burst of triggers doesn't fan out into a burst
        of REST calls.
        """
        if self._reconciling:
            return
        self._reconciling = True
        asyncio.create_task(self._run_reconcile())

    async def _run_reconcile(self) -> None:
        try:
            await reconcile_live_orders(self)
        except Exception as exc:
            print(f"State (reconcile): Error reconciling live orders for {self.ticker}: {exc}")
        finally:
            self._reconciling = False

    async def shutdown(self) -> None:
        """Shutdown hook (no-op now that auto-updates are removed)."""
        return None


    #########################################################
    # Orderbook and Fill Handling
    #########################################################

    async def handle_orderbook_snapshot(self, snapshot_data: Dict) -> None:
        self.last_ws_message_at = time.monotonic()
        self.orderbook.initialize_from_snapshot(snapshot_data, self.market)
        print(f">> Updated orderbook snapshot for {self.ticker}")
        if self.print_orderbook_strings:
            print("\tOrderbook without us:")
            print(self.orderbook.get_orderbook_wo_us_string(tabs=2))

        await self.emit_orderbook_update()
        await asyncio.sleep(0)

    async def handle_orderbook_delta(self, delta_data: Dict) -> bool:
        self.last_ws_message_at = time.monotonic()
        if 'client_order_id' not in delta_data['msg']:
            prev_best_bid = self.orderbook.get_best_bid_without_us()
            prev_best_ask = self.orderbook.get_best_ask_without_us()

            self.orderbook.update_from_delta(delta_data)
            if self.print_orderbook_strings:
                print(f">> {self.ticker}: Orderbook without us:")
                print(self.orderbook.get_orderbook_wo_us_string(tabs=1))

            current_best_bid = self.orderbook.get_best_bid_without_us()
            current_best_ask = self.orderbook.get_best_ask_without_us()

            await self.emit_orderbook_update()
            if (prev_best_bid != current_best_bid) or (prev_best_ask != current_best_ask):
                if self.print_orderbook_strings:
                    print(f">> {self.ticker}: Orderbook live orders:")
                    print("\t" + self.orderbook.get_live_orders_string())
                await asyncio.sleep(0)
                return True

            return False

        return False

    async def handle_fill(self, fill_data: Dict) -> None:
        """
        Handle fill/trade execution updates and update position and live orders.
        Uses new floating-point fields (yes_price_dollars, count_fp, post_position_fp).
        """
        msg = fill_data['msg']
        sid = fill_data['sid']

        trade_id = msg['trade_id']
        order_id = msg['order_id']
        is_taker = msg['is_taker']
        internal_side = msg.get('book_side') or ('bid' if msg['side'] == 'yes' else 'ask')
        if 'yes_price_dollars' in msg:
            yes_price = to_internal(msg['yes_price_dollars'])
        elif 'no_price_dollars' in msg:
            yes_price = MAX_PRICE - to_internal(msg['no_price_dollars'])
        else:
            raise ValueError(f"Invalid price: {msg}")
        count = float(msg['count_fp'])
        action = msg['action']
        ts = msg['ts']
        client_order_id = msg['client_order_id']
        pre_position = self.position
        post_position = float(msg['post_position_fp'])
        purchased_side = msg['purchased_side']

        if self.print_fill_strings:
            print(
                f">> [Fill]: {self.event_ticker} {self.ticker}: "
                f"Position {pre_position} -> {post_position} at price {yes_price / PRICE_MULTIPLIER}"
            )

        if internal_side == 'bid':
            self.position += count
        elif internal_side == 'ask':
            self.position -= count
        else:
            errmsg = f"State (handle_fill): Invalid internal_side: {internal_side}"
            print(errmsg)
            raise ValueError(errmsg)
        if abs(self.position - post_position) > 0.005:
            # Our locally-accumulated position has drifted from the exchange's authoritative
            # post_position_fp (e.g. a fill was missed during the REST-seed/subscribe race at
            # ticker-add time). Trust the server and self-heal instead of raising, otherwise the
            # gap recurs on every subsequent fill forever.
            print(
                f"State (handle_fill): Position mismatch: {self.position} != {post_position}, "
                f"resyncing to server value"
            )
        self.position = post_position
        if abs(self.position) >= 6 * DEFAULT_ORDER_SIZE:
            print(f">> [Position Alert]: {self.event_ticker} position {self.position}")

        try:
            self.orderbook.handle_fill_internal(client_order_id, order_id, count, internal_side, yes_price)
        except Exception as exc:
            # Local live-order bookkeeping can fall over on duplicate/out-of-order fill
            # delivery (e.g. during shared-SID resubscribe recovery), but self.position was
            # already resynced to the exchange's authoritative post_position_fp above. Don't
            # let a bookkeeping error here suppress the broadcast below — that would leave
            # the UI showing a stale position until some unrelated update happens to fire.
            print(f"State (handle_fill): Orderbook bookkeeping error for {self.ticker}, continuing to broadcast authoritative position: {exc}")
            self.request_reconcile()
        if self.print_orderbook_strings:
            print(f">> {self.ticker}: Orderbook live orders:")
            print("\t" + self.orderbook.get_live_orders_string())
            print(f">> {self.ticker}: Orderbook without us:")
            print(self.orderbook.get_orderbook_wo_us_string(tabs=1))

        await self.emit_orderbook_update()
        await asyncio.sleep(0)

    async def handle_public_trade(self, trade_data: Dict) -> None:
        """Handle public trade channel messages."""
        try:
            msg = trade_data['msg']
            self.orderbook.num_trades += 1
        except Exception as e:
            print(f"State (handle_public_trade): Error handling trade: {e}")
        if self.print_orderbook_strings:
            print(f">> {self.ticker}: Orderbook live orders:")
            print("\t" + self.orderbook.get_live_orders_string())
            print(f">> {self.ticker}: Orderbook without us:")
            print(self.orderbook.get_orderbook_wo_us_string(tabs=1))
        await asyncio.sleep(0)


    #########################################################
    # String Representation Functions
    #########################################################

    def get_position_description(self) -> str:
        """Get human-readable position description."""
        if self.position != 0:
            return f"{self.position} Yes contracts"
        else:
            return "No position"

    def __repr__(self) -> str:
        """String representation of the state."""
        return f"State({self.ticker}) | Position: {self.get_position_description()} | Orderbook: {self.orderbook.get_orderbook_without_us()}"
