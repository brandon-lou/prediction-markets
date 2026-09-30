import asyncio
from datetime import datetime, timezone
from typing import Callable, Dict

from kalshi_api import post_order_api, cancel_order_api, generate_internal_order_id, get_live_orders
from orderbook import MAX_PRICE, PRICE_MULTIPLIER


##### Cancel functions: cancel API and cancel internally #####

async def cancel_order(state, internal_order_id: str) -> bool:
    """Skips cancel if order is pending cancel"""
    if state.orderbook.is_order_pending_cancel(internal_order_id):
        return True
    state.orderbook.cancel_order_internal_pending(internal_order_id)

    if internal_order_id in state.orderbook.live_orders:
        valid = await cancel_order_api(
            state.orderbook.live_orders[internal_order_id]['id'],
            exchange_index=getattr(state, 'exchange_index', None),
            market_ticker=state.ticker,
        )
        if not valid:
            state.orderbook.cancel_order_internal_fail(internal_order_id)
        else:
            state.orderbook.cancel_order_internal_success(internal_order_id)
            await state.emit_orderbook_update()
        return valid


async def cancel_all_bids(state) -> bool:
    for order in state.orderbook.pending_post_orders.values():
        if order['action'] == 'buy':
            order['pending_cancel'] = True

    local_order_ids = [
        order_id
        for order_id, order in state.orderbook.live_orders.items()
        if order['action'] == 'buy' and order_id
    ]
    cancel_ok = True
    for order_id in local_order_ids:
        if order_id not in state.orderbook.live_orders:
            continue
        if not await cancel_order(state, str(order_id)):
            cancel_ok = False

    return cancel_ok


async def cancel_all_asks(state) -> bool:
    for order in state.orderbook.pending_post_orders.values():
        if order['action'] == 'sell':
            order['pending_cancel'] = True

    local_order_ids = [
        order_id
        for order_id, order in state.orderbook.live_orders.items()
        if order['action'] == 'sell' and order_id
    ]
    cancel_ok = True
    for order_id in local_order_ids:
        if order_id not in state.orderbook.live_orders:
            continue
        if not await cancel_order(state, str(order_id)):
            cancel_ok = False

    return cancel_ok


async def cancel_orders_at_price(state, action: str, price: int) -> bool:
    """Cancel all orders at a specific internal price."""
    if action not in ("buy", "sell"):
        raise ValueError("(cancel_orders_at_price) action must be buy or sell")
    if not (0 <= price <= MAX_PRICE):
        raise ValueError(f"(cancel_orders_at_price) price must be between 0 and {MAX_PRICE}")

    cancel_ok = True
    local_order_ids = [
        order_id
        for order_id, order in state.orderbook.live_orders.items()
        if order.get('action') == action and order.get('price') == price and order_id
    ]
    for order_id in local_order_ids:
        if order_id not in state.orderbook.live_orders:
            continue
        if not await cancel_order(state, str(order_id)):
            cancel_ok = False

    for order_id, order in state.orderbook.pending_post_orders.items():
        if order.get('action') == action and order.get('price') == price:
            order['pending_cancel'] = True

    return cancel_ok


#### Post functions: post API and post internally #####

async def post_order(state, action, count, price, should_abort: Callable[[], bool]) -> bool:
    assert action == 'buy' or action == 'sell', "(Post order) Action must be buy or sell"
    assert 0 <= price <= MAX_PRICE, f"Price must be between 0 and {MAX_PRICE}"
    assert count > 0, "Count must be greater than 0"

    if should_abort():
        return False

    internal_order_id = generate_internal_order_id()
    state.orderbook.post_order_internal_pending(internal_order_id, count, action, price)
    try:
        order_result = await post_order_api(
            state.ticker, action, count, price,
            client_order_id=internal_order_id,
            exchange_index=getattr(state, 'exchange_index', None),
        )
    except Exception as exc:
        print(f"UpdateOrders (post_order): Unexpected exception for {state.ticker} ({type(exc).__name__}): {exc}")
        state.orderbook.post_order_internal_fail(internal_order_id)
        return False
    if order_result:
        order_id = order_result.get('order_id') or order_result.get('order', {}).get('order_id')
        if order_id:
            state.orderbook.post_order_internal_success(internal_order_id, order_id, action, price)
            await state.emit_orderbook_update()

            if state.orderbook.is_order_pending_cancel(internal_order_id) and internal_order_id in state.orderbook.live_orders and state.orderbook.live_orders[internal_order_id]['remaining_count'] != 0:
                valid = await cancel_order_api(
                    state.orderbook.live_orders[internal_order_id]['id'],
                    exchange_index=getattr(state, 'exchange_index', None),
                    market_ticker=state.ticker,
                )
                if not valid:
                    state.orderbook.cancel_order_internal_fail(internal_order_id)
                else:
                    state.orderbook.cancel_order_internal_success(internal_order_id)
                    await state.emit_orderbook_update()
            if should_abort():
                return False
            return True

    state.orderbook.post_order_internal_fail(internal_order_id)
    msg = f"UpdateOrders (post_order): Failed to post {action} order at {price} for {state.ticker}"
    print(msg)
    return False


#### Reconciliation: resync local live-order bookkeeping against the exchange #####

async def reconcile_live_orders(state) -> None:
    """
    Resync state.orderbook.live_orders against Kalshi's authoritative resting-order
    list for this ticker. Local bookkeeping can drift from reality when a cancel
    bypasses it (e.g. the background REST cancel fired when a ticker goes warm on
    ticker-swap) or when fill delivery is duplicated/out-of-order during shared-SID
    resubscribe recovery. Mirrors how state.position self-heals from the exchange's
    post_position_fp on every fill — same idea, applied to resting orders.
    """
    orderbook = state.orderbook
    if not orderbook.live_orders:
        return  # nothing locally tracked to check against

    resting = []
    cursor = None
    while True:
        resp = await get_live_orders(ticker=state.ticker, status='resting', limit=200, cursor=cursor)
        if not resp:
            break
        batch = resp.get('orders', []) if isinstance(resp, dict) else resp
        resting.extend(o for o in (batch or []) if isinstance(o, dict))
        cursor = resp.get('cursor') if isinstance(resp, dict) else None
        if not cursor:
            break

    exchange_remaining_by_id: Dict[str, float] = {}
    for o in resting:
        order_id = o.get('order_id') or o.get('id')
        if not order_id:
            continue
        exchange_remaining_by_id[str(order_id)] = float(o.get('remaining_count', 0))

    changed = False
    for internal_order_id, order in list(orderbook.live_orders.items()):
        order_id = order.get('id')
        if not order_id:
            continue
        local_remaining = order['remaining_count']
        exchange_remaining = exchange_remaining_by_id.get(str(order_id), 0.0)
        drift = round(exchange_remaining - local_remaining, 2)
        if drift == 0:
            continue

        changed = True
        print(
            f"UpdateOrders (reconcile_live_orders): {state.ticker} order {order_id} drifted "
            f"(local={local_remaining}, exchange={exchange_remaining}), correcting"
        )
        order['remaining_count'] = exchange_remaining
        if exchange_remaining <= 0:
            del orderbook.live_orders[internal_order_id]
        orderbook.update_from_delta({
            'type': 'orderbook_delta_internal',
            'msg': {
                'side': 'yes' if order['action'] == 'buy' else 'no',
                'delta_fp': drift,
                'ts': datetime.now(timezone.utc).isoformat(),
                'market_ticker': state.ticker,
                'price_dollars': order['price'] / PRICE_MULTIPLIER if order['action'] == 'buy'
                    else (MAX_PRICE - order['price']) / PRICE_MULTIPLIER,
            }
        })

    if changed:
        await state.emit_orderbook_update()
