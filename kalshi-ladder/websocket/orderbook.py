from typing import Dict, List, Optional
import copy
from datetime import datetime, timezone, timedelta

DECIMAL_PLACES = 4
PRICE_MULTIPLIER = 10 ** DECIMAL_PLACES  # 10000
MAX_PRICE = PRICE_MULTIPLIER              # $1.00 = 10000 internal units


def to_internal(dollars_price) -> int:
    """Convert a dollar price (0-1) to internal int representation."""
    return round(float(dollars_price) * PRICE_MULTIPLIER)


def to_dollars_str(internal_price) -> str:
    """Convert internal price to Kalshi API dollar string (e.g. '0.1900')."""
    return f"{int(internal_price) / PRICE_MULTIPLIER:.{DECIMAL_PLACES}f}"


DEFAULT_ORDER_SIZE = 25
SCALE_ORDERS = {
    0: DEFAULT_ORDER_SIZE,
    200: DEFAULT_ORDER_SIZE,
}

CENTS_PER_INTERNAL = PRICE_MULTIPLIER // 100  # 100 internal units = 1 cent


def _aggregate_to_cents(levels: Dict[int, float]) -> List[List]:
    """Aggregate internal-price levels into integer cent buckets."""
    cents: Dict[int, float] = {}
    for internal_price, qty in levels.items():
        cent = round(internal_price / CENTS_PER_INTERNAL)
        cents[cent] = round(cents.get(cent, 0) + qty, 2)
    return [[cent, qty] for cent, qty in cents.items() if qty > 0]


class OrderBook:
    """
    Maintains the current state of a market's orderbook and updates it based on WebSocket deltas.
    NOTE: ONLY FOR THE YES SIDE OF THE BOOK.
    """

    #########################################################
    # Constructor and Initialization
    #########################################################

    def __init__(self, ticker: str):
        """
        Initialize an orderbook for a specific market ticker.
        Internally only tracks YES book, but handles both YES/NO for Kalshi communication.

        Args:
            ticker: Market ticker symbol
        """
        self.ticker = ticker
        self.orderbook: Dict[str, Dict[int, float]] = {'bid': {}, 'ask': {}}
        self.sorted_prices: Dict[str, List[int]] = {'bid': [], 'ask': []}
        self.sequence_number: int = 0
        self.last_update_ts: Optional[datetime] = None
        self.live_orders: Dict[str, Dict] = {}  # internal_order_id -> order_data
        self.pending_post_orders: Dict[str, Dict] = {}
        self.num_trades: int = 0
        self.had_negative_delta: bool = False  # set when out-of-sync; triggers resync

    def initialize_from_snapshot(self, snapshot_data: Dict, market: Dict) -> None:
        """
        Initialize orderbook from a snapshot message.
        Uses the new yes_dollars_fp / no_dollars_fp fields.
        """
        msg = snapshot_data.get('msg', {})
        market_id = msg['market_id']
        yes_dollars = msg.get('yes_dollars_fp', [])
        no_dollars = msg.get('no_dollars_fp', [])

        self.orderbook['bid'] = {}
        self.orderbook['ask'] = {}

        for price, quantity in yes_dollars:
            internal_price = to_internal(price)
            quantity_fp = float(quantity)
            if quantity_fp > 0:
                self.orderbook['bid'][internal_price] = quantity_fp
        for price, quantity in no_dollars:
            internal_price = MAX_PRICE - to_internal(price)
            quantity_fp = float(quantity)
            if quantity_fp > 0:
                self.orderbook['ask'][internal_price] = quantity_fp
        self.sorted_prices['bid'] = sorted(self.orderbook['bid'].keys())
        self.sorted_prices['ask'] = sorted(self.orderbook['ask'].keys(), reverse=True)

        self.sequence_number = snapshot_data.get('seq', 0)
        sid = snapshot_data['sid']
        self.last_update_ts = datetime.now(timezone.utc)
        self.had_negative_delta = False  # fresh snapshot clears the resync flag


    #########################################################
    # Update Orderbook
    #########################################################

    def update_from_delta(self, delta_data: Dict) -> None:
        """
        Update orderbook based on a delta message.
        Uses new price_dollars and delta_fp fields.
        """
        msg = delta_data.get('msg', {})

        price = to_internal(msg['price_dollars']) if msg['side'] == 'yes' else MAX_PRICE - to_internal(msg['price_dollars'])
        delta = float(msg.get('delta_fp', '0.0'))
        side = msg['side']
        ts = msg['ts']
        self.last_update_ts = datetime.fromisoformat(ts)

        if delta_data['type'] == 'orderbook_delta':
            market_id = msg['market_id']
            self.sequence_number = delta_data['seq']
            sid = delta_data['sid']

        if side == 'yes':
            if price not in self.orderbook['bid']:
                self.orderbook['bid'][price] = 0
                self.sorted_prices['bid'].append(price)
                self.sorted_prices['bid'].sort()

            self.orderbook['bid'][price] = round(self.orderbook['bid'][price] + delta, 2)
            if self.orderbook['bid'][price] < 0:
                print(f"Orderbook (update_from_delta): Bid quantity negative at {price}, clamping to 0 (out-of-sync, will resync)")
                self.had_negative_delta = True
                del self.orderbook['bid'][price]
                self.sorted_prices['bid'].remove(price)
            elif self.orderbook['bid'][price] == 0:
                del self.orderbook['bid'][price]
                self.sorted_prices['bid'].remove(price)
        elif side == 'no':
            if price not in self.orderbook['ask']:
                self.orderbook['ask'][price] = 0
                self.sorted_prices['ask'].append(price)
                self.sorted_prices['ask'].sort(reverse=True)

            self.orderbook['ask'][price] = round(self.orderbook['ask'][price] + delta, 2)
            if self.orderbook['ask'][price] < 0:
                print(f"Orderbook (update_from_delta): Ask quantity negative at {price}, clamping to 0 (out-of-sync, will resync)")
                self.had_negative_delta = True
                del self.orderbook['ask'][price]
                self.sorted_prices['ask'].remove(price)
            elif self.orderbook['ask'][price] == 0:
                del self.orderbook['ask'][price]
                self.sorted_prices['ask'].remove(price)


    #########################################################
    # Internal Posting, Cancelling, and Handling Fills
    #########################################################

    def post_order_internal_pending(self, internal_order_id: str, count: float, action: str, price: int) -> None:
        if internal_order_id in self.pending_post_orders:
            msg = f"OrderBook (post_order_internal_pending): Internal order {internal_order_id} already exists"
            print(msg)
            raise ValueError(msg)
        self.pending_post_orders[internal_order_id] = {
            'id': None,
            'internal_id': internal_order_id,
            'ticker': self.ticker,
            'action': action,
            'original_count': count,
            'remaining_count': count,
            'price': price,
            'type': 'limit',
            'pending_cancel': False
        }

    def post_order_internal_success(self, internal_order_id: str, order_id: str, action: str, price: int, order_type: str = 'limit') -> None:
        if internal_order_id not in self.pending_post_orders:
            msg = f"OrderBook (post_order_internal_success): Internal order {internal_order_id} not found in pending post orders"
            print(msg)
            raise ValueError(msg)
        order_data = self.pending_post_orders[internal_order_id]
        order_data['id'] = order_id
        del self.pending_post_orders[internal_order_id]

        if order_data['remaining_count'] != 0:
            self.live_orders[internal_order_id] = order_data
            self.update_from_delta({
                'type': 'orderbook_delta_internal',
                'msg': {
                    'side': 'yes' if action == 'buy' else 'no',
                    'delta_fp': order_data['remaining_count'],
                    'ts': datetime.now(timezone.utc).isoformat(),
                    'market_ticker': self.ticker,
                    'price_dollars': price / PRICE_MULTIPLIER if action == 'buy' else (MAX_PRICE - price) / PRICE_MULTIPLIER
                }
            })

    def post_order_internal_fail(self, internal_order_id: str) -> None:
        if internal_order_id not in self.pending_post_orders:
            msg = f"OrderBook (post_order_internal_fail): Internal order {internal_order_id} not found in pending post orders"
            print(msg)
            raise ValueError(msg)
        del self.pending_post_orders[internal_order_id]

    def cancel_order_internal_pending(self, internal_order_id: str) -> bool:
        if internal_order_id in self.live_orders:
            self.live_orders[internal_order_id]['pending_cancel'] = True
            return True
        elif internal_order_id in self.pending_post_orders:
            self.pending_post_orders[internal_order_id]['pending_cancel'] = True
            return True
        else:
            msg = f"OrderBook (cancel_order_internal_pending): Internal order {internal_order_id} not found in live orders for {self.ticker}"
            print(msg)
            return False

    def is_order_pending_cancel(self, internal_order_id: str) -> bool:
        if internal_order_id in self.live_orders:
            return bool(self.live_orders[internal_order_id]['pending_cancel'])
        elif internal_order_id in self.pending_post_orders:
            return bool(self.pending_post_orders[internal_order_id]['pending_cancel'])
        else:
            return True

    def cancel_order_internal_fail(self, internal_order_id: str) -> bool:
        if internal_order_id in self.live_orders:
            self.live_orders[internal_order_id]['pending_cancel'] = False
            return True
        else:
            msg = f"OrderBook (cancel_order_internal_fail): Internal order {internal_order_id} not found in live orders for {self.ticker}"
            print(msg)
            return False

    def cancel_order_internal_success(self, internal_order_id: str) -> bool:
        if internal_order_id in self.live_orders:
            count = self.live_orders[internal_order_id]['remaining_count']
            action = self.live_orders[internal_order_id]['action']
            price = self.live_orders[internal_order_id]['price']
            if not self.live_orders[internal_order_id]['pending_cancel']:
                msg = f"OrderBook (cancel_order_internal_success): Internal order {internal_order_id} is not pending cancel"
                print(msg)
            del self.live_orders[internal_order_id]
            if count != 0:
                self.update_from_delta({
                    'type': 'orderbook_delta_internal',
                    'msg': {
                        'side': 'yes' if action == 'buy' else 'no',
                        'delta_fp': -count,
                        'ts': datetime.now(timezone.utc).isoformat(),
                        'market_ticker': self.ticker,
                        'price_dollars': price / PRICE_MULTIPLIER if action == 'buy' else (MAX_PRICE - price) / PRICE_MULTIPLIER
                    }
                })
            return True
        else:
            msg = f"OrderBook (cancel_order_internal_success): Internal order {internal_order_id} not found in live orders for {self.ticker}"
            print(msg)
            return False

    def handle_fill_internal(self, internal_order_id: str, order_id: str, count: float, internal_side: str, price: int) -> None:
        """Handle fill/trade execution updates and update live orders."""
        assert internal_side in ('bid', 'ask'), "(Handle fill internal) internal_side must be bid or ask"
        action = 'buy' if internal_side == 'bid' else 'sell'
        if internal_order_id in self.live_orders:
            assert self.live_orders[internal_order_id]['action'] == action, f"Order action mismatch: {self.live_orders[internal_order_id]['action']} != {action}"
            stored_price = self.live_orders[internal_order_id]['price']
            self.live_orders[internal_order_id]['remaining_count'] = round(self.live_orders[internal_order_id]['remaining_count'] - count, 2)
            if self.live_orders[internal_order_id]['remaining_count'] == 0:
                if not self.live_orders[internal_order_id]['pending_cancel']:
                    del self.live_orders[internal_order_id]
            elif self.live_orders[internal_order_id]['remaining_count'] < 0:
                msg = f"Orderbook (handle_fill_internal): Internal order {internal_order_id} has negative remaining count: {self.live_orders[internal_order_id]['remaining_count']}"
                print(msg)
                raise ValueError(msg)

            self.update_from_delta({
                'type': 'orderbook_delta_internal',
                'msg': {
                    'side': 'yes' if internal_side == 'bid' else 'no',
                    'delta_fp': -count,
                    'ts': datetime.now(timezone.utc).isoformat(),
                    'market_ticker': self.ticker,
                    'price_dollars': stored_price / PRICE_MULTIPLIER if internal_side == 'bid' else (MAX_PRICE - stored_price) / PRICE_MULTIPLIER
                }
            })
        elif internal_order_id in self.pending_post_orders:
            self.pending_post_orders[internal_order_id]['remaining_count'] = round(self.pending_post_orders[internal_order_id]['remaining_count'] - count, 2)
            if self.pending_post_orders[internal_order_id]['remaining_count'] < 0:
                msg = f"Orderbook (handle_fill_internal): Internal order {internal_order_id} has negative remaining count: {self.pending_post_orders[internal_order_id]['remaining_count']}"
                print(msg)
                raise ValueError(msg)
        else:
            print(f"Orderbook (handle_fill_internal): Order {internal_order_id} not found locally (likely from previous session), skipping orderbook update")


    #########################################################
    # Useful Getter Functions
    #########################################################

    def get_my_orders_by_price(self) -> Dict[str, Dict[int, float]]:
        """
        Get our live orders grouped by internal price.

        Returns:
            Dictionary with 'bid' and 'ask' sides, each containing internal_price -> quantity mappings
        """
        my_bids: Dict[int, float] = {}
        my_asks: Dict[int, float] = {}
        for order in self.live_orders.values():
            remaining = order.get('remaining_count', 0)
            if remaining <= 0:
                continue
            price = order['price']
            if order['action'] == 'buy':
                my_bids[price] = round(my_bids.get(price, 0) + remaining, 2)
            elif order['action'] == 'sell':
                my_asks[price] = round(my_asks.get(price, 0) + remaining, 2)
        return {'bid': my_bids, 'ask': my_asks}

    def get_ladder_snapshot(self) -> Dict[str, object]:
        """
        Build a snapshot for the ladder UI.
        Aggregates fractional internal prices into integer cent buckets.
        """
        orderbook_without_us = self.get_orderbook_without_us()
        my_orders = self.get_my_orders_by_price()

        bids_cents = sorted(_aggregate_to_cents(orderbook_without_us['bid']), key=lambda x: x[0], reverse=True)
        asks_cents = sorted(_aggregate_to_cents(orderbook_without_us['ask']), key=lambda x: x[0])
        my_bids_cents = sorted(_aggregate_to_cents(my_orders['bid']), key=lambda x: x[0], reverse=True)
        my_asks_cents = sorted(_aggregate_to_cents(my_orders['ask']), key=lambda x: x[0])

        bid_cent_prices = [p for p, _ in bids_cents]
        ask_cent_prices = [p for p, _ in asks_cents]
        best_bid = max(bid_cent_prices) if bid_cent_prices else 0
        best_ask = min(ask_cent_prices) if ask_cent_prices else 100

        return {
            'bids': bids_cents,
            'asks': asks_cents,
            'my_bids': my_bids_cents,
            'my_asks': my_asks_cents,
            'best_bid': best_bid,
            'best_ask': best_ask,
            'sequence_number': self.sequence_number,
            'last_update_ts': self.last_update_ts.isoformat() if self.last_update_ts else None,
        }

    def get_orderbook_without_us(self) -> Dict[str, Dict[int, float]]:
        """
        Get the orderbook without our live orders.
        """
        orderbook_without_us = {
            'bid': copy.deepcopy(self.orderbook['bid']),
            'ask': copy.deepcopy(self.orderbook['ask'])
        }

        for order in self.live_orders.values():
            internal_side = 'bid' if order['action'] == 'buy' else 'ask'
            price = order['price']
            remaining = order['remaining_count']

            if price in orderbook_without_us[internal_side]:
                orderbook_without_us[internal_side][price] = round(orderbook_without_us[internal_side][price] - remaining, 2)
                if orderbook_without_us[internal_side][price] == 0:
                    del orderbook_without_us[internal_side][price]
                elif orderbook_without_us[internal_side][price] < 0:
                    print(f"Orderbook (get_orderbook_without_us): Quantity negative at {price}, clamping to 0")
                    del orderbook_without_us[internal_side][price]

        return orderbook_without_us

    def get_best_bid_without_us(self) -> int:
        if len(self.sorted_prices['bid']) > 0:
            return self.sorted_prices['bid'][-1]
        return 0

    def get_best_ask_without_us(self) -> int:
        if len(self.sorted_prices['ask']) > 0:
            return self.sorted_prices['ask'][-1]
        return MAX_PRICE


    #########################################################
    # String Representation Functions
    #########################################################

    def get_orderbook_wo_us_string(self, tabs: int = 0) -> str:
        tab_string = '\t' * tabs
        bids = []
        asks = []
        orderbook_without_us = self.get_orderbook_without_us()
        for price, quantity in orderbook_without_us['bid'].items():
            bids.append((price / PRICE_MULTIPLIER, quantity))
        for price, quantity in orderbook_without_us['ask'].items():
            asks.append((price / PRICE_MULTIPLIER, quantity))
        bids.sort(key=lambda x: x[0], reverse=True)
        asks.sort(key=lambda x: x[0])
        return tab_string + 'Bids: ' + str(bids) + '\n' + tab_string + 'Asks: ' + str(asks)

    def get_live_orders_string(self) -> str:
        live_orders_bids = []
        live_orders_asks = []
        for order in self.live_orders.values():
            if order['action'] == 'buy':
                live_orders_bids.append((order['price'] / PRICE_MULTIPLIER, order['remaining_count']))
            elif order['action'] == 'sell':
                live_orders_asks.append((order['price'] / PRICE_MULTIPLIER, order['remaining_count']))
        live_orders_bids.sort(key=lambda x: x[0])
        live_orders_asks.sort(key=lambda x: x[0])
        return 'Bids: ' + str(live_orders_bids) + ' Asks: ' + str(live_orders_asks)
