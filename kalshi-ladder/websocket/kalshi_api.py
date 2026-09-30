import asyncio
import aiohttp
import json as _json
from collections import deque
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.exceptions import InvalidSignature
import datetime
import time
import uuid
from typing import Optional, Any, Dict, Deque

from orderbook import PRICE_MULTIPLIER, MAX_PRICE, to_dollars_str

_MODULE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _MODULE_DIR.parent


def _resolve_path(file_path: str) -> Path:
    candidate = Path(file_path)
    if candidate.is_absolute() and candidate.exists():
        return candidate
    if candidate.exists():
        return candidate.resolve()
    module_candidate = _MODULE_DIR / candidate
    if module_candidate.exists():
        return module_candidate
    root_candidate = _REPO_ROOT / candidate
    if root_candidate.exists():
        return root_candidate
    return candidate


def load_api_key(file_path: str = 'api-key.txt') -> str:
    resolved = _resolve_path(file_path)
    with open(resolved, 'r') as f:
        return f.read().strip()


API_KEY = load_api_key()
MAX_API_WRITES_PER_SECOND = 30
MAX_API_RETRY_ATTEMPTS = 4


def load_private_key_from_file(file_path: str) -> rsa.RSAPrivateKey:
    resolved = _resolve_path(file_path)
    with open(resolved, "rb") as key_file:
        return serialization.load_pem_private_key(
            key_file.read(),
            password=None,
            backend=default_backend()
        )


# Load once at startup — avoids disk I/O + PEM parse on every API call.
_PRIVATE_KEY = load_private_key_from_file('../api-private-key.key')


def generate_internal_order_id() -> str:
    return str(uuid.uuid4())


class ApiCallThrottler:
    def __init__(self, max_calls_per_second: int):
        self._rate = max_calls_per_second
        self._semaphore = asyncio.Semaphore(max_calls_per_second)
        self._waiting = 0
        self._last_alert_time = time.monotonic()

    async def wait_turn(self):
        self._waiting += 1
        backlog = max(0, self._waiting - self._rate)
        now = time.monotonic()
        if backlog >= 10 and now - self._last_alert_time > 10:
            print(f">> [API Backlog Alert]: {backlog} Kalshi API calls pending")
            self._last_alert_time = now

        await self._semaphore.acquire()
        self._waiting -= 1

        released = False

        def release_after(delay: float = 1.010) -> None:
            nonlocal released
            if released:
                return
            released = True
            loop = asyncio.get_running_loop()
            loop.call_later(delay, self._semaphore.release)

        return release_after

_API_THROTTLER = ApiCallThrottler(MAX_API_WRITES_PER_SECOND)


class _Response:
    """Thin wrapper so all callers can use .status_code and .json() unchanged."""
    __slots__ = ('status_code', '_json_data', 'text')

    def __init__(self, status: int, json_data: Any, text: str) -> None:
        self.status_code = status
        self._json_data = json_data
        self.text = text

    def json(self) -> Any:
        return self._json_data


_SESSION: Optional[aiohttp.ClientSession] = None


async def _get_session() -> aiohttp.ClientSession:
    global _SESSION
    if _SESSION is None or _SESSION.closed:
        connector = aiohttp.TCPConnector(limit=20, ttl_dns_cache=300)
        _SESSION = aiohttp.ClientSession(connector=connector)
    return _SESSION


async def close_session() -> None:
    global _SESSION
    if _SESSION and not _SESSION.closed:
        await _SESSION.close()
        _SESSION = None


def sign_pss_text(private_key: rsa.RSAPrivateKey, text: str) -> str:
    message = text.encode('utf-8')
    try:
        signature = private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode('utf-8')
    except InvalidSignature as e:
        msg = f"Kalshi API (sign_pss_text): RSA sign PSS failed: {e}"
        print(msg)
        raise ValueError(msg) from e


def create_kalshi_headers(
    method: str,
    path: str,
    api_key: Optional[str] = API_KEY,
) -> Dict[str, str]:
    timestamp_str = str(int(datetime.datetime.now().timestamp() * 1000))
    signature = sign_pss_text(_PRIVATE_KEY, timestamp_str + method + path)
    return {
        'KALSHI-ACCESS-KEY': api_key,
        'KALSHI-ACCESS-SIGNATURE': signature,
        'KALSHI-ACCESS-TIMESTAMP': timestamp_str,
    }


async def _throttled_request(method: str, url: str, path: Optional[str] = None, **kwargs):
    method = method.lower()
    if method not in ('get', 'post', 'delete', 'put', 'patch', 'head'):
        msg = f"Kalshi API (_throttled_request): Unsupported HTTP method: {method}"
        print(msg)
        raise ValueError(msg)

    timeout = aiohttp.ClientTimeout(total=kwargs.pop('timeout', 5))
    session = await _get_session()
    request_fn = getattr(session, method)

    for _ in range(MAX_API_RETRY_ATTEMPTS):
        release_token = await _API_THROTTLER.wait_turn()
        if path is not None:
            fresh_headers = create_kalshi_headers(method.upper(), path)
            kwargs.setdefault('headers', {})
            kwargs['headers'].update(fresh_headers)

        try:
            async with request_fn(url, timeout=timeout, **kwargs) as resp:
                body = await resp.read()
                try:
                    json_data = _json.loads(body)
                except Exception:
                    json_data = None
                result = _Response(resp.status, json_data, body.decode('utf-8', errors='replace'))
                if resp.status != 429:
                    return result
        except aiohttp.ClientError as exc:
            print(f"Kalshi API (_throttled_request): Connection error: {exc}")
        finally:
            release_token()

        await asyncio.sleep(0)

    print("Kalshi API (_throttled_request): Retry limit exceeded")
    return None


async def get_positions(ticker: Optional[str] = None, base_url: str = 'https://api.elections.kalshi.com') -> Optional[Dict[str, Any]]:
    path = '/trade-api/v2/portfolio/positions'
    response = await _throttled_request('get', base_url + path, path=path)
    if response is None:
        return None
    if response.status_code == 200:
        data = response.json()
        if ticker is not None and isinstance(data, dict):
            market_positions = data.get('market_positions', []) or []
            data['market_positions'] = [p for p in market_positions if p.get('ticker') == ticker]
        return data
    else:
        print(f"Kalshi API (get_positions): Error getting positions: {response.status_code}")
        print(response.text)
        return None


async def position_getter(base_url: str = 'https://api.elections.kalshi.com') -> Optional[Dict[str, float]]:
    path = '/trade-api/v2/portfolio/positions'
    all_positions = {}
    cursor = None
    page_count = 0

    try:
        while True:
            page_count += 1
            print(f"Fetching positions page {page_count}...")

            params = {'limit': 100}
            if cursor:
                params['cursor'] = cursor

            response = await _throttled_request('get', base_url + path, path=path, params=params)

            if response is None:
                return None
            if response.status_code == 200:
                data = response.json()
                if 'market_positions' in data:
                    market_positions = data['market_positions']
                    for position in market_positions:
                        ticker = position.get('ticker')
                        yes_position = float(position.get('position_fp', '0.0'))
                        all_positions[ticker] = yes_position
                    print(f"  Found {len(market_positions)} positions on page {page_count}")
                cursor = data.get('cursor')
                if not cursor:
                    print(f"Completed fetching all positions across {page_count} pages")
                    break
            else:
                print(f"Kalshi API (position_getter page {page_count}): Error: {response.status_code}")
                print(response.text)
                return None

        return all_positions

    except Exception as e:
        print(f"Kalshi API (position_getter): Error: {e}")
        return None


async def get_live_orders(
    ticker: Optional[str] = None,
    event_ticker: Optional[str] = None,
    min_ts: Optional[str] = None,
    max_ts: Optional[str] = None,
    limit: int = 100,
    cursor: Optional[str] = None,
    side: Optional[str] = None,
    order_type: Optional[str] = None,
    status: str = 'resting',
    base_url: str = 'https://api.elections.kalshi.com',
) -> Optional[Dict[str, Any]]:
    path = '/trade-api/v2/portfolio/orders'
    params: Dict[str, Any] = {'status': status, 'limit': limit}
    if ticker is not None:
        params['ticker'] = ticker
    if event_ticker is not None:
        params['event_ticker'] = event_ticker
    if cursor is not None:
        params['cursor'] = cursor
    if side is not None:
        params['side'] = side
    if order_type is not None:
        params['order_type'] = order_type

    response = await _throttled_request('get', base_url + path, path=path, params=params)

    if response is None:
        print("Kalshi API (get_live_orders): No response (retry limit or timeout)")
        return None
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Kalshi API (get_live_orders): Error: {response.status_code}")
        print(response.text)
        return None


async def get_balance(
    exchange_index: Optional[int] = None,
    base_url: str = 'https://api.elections.kalshi.com',
) -> Optional[Dict[str, Any]]:
    """
    Account balance. With no exchange_index the response covers the whole account and
    includes `balance_breakdown` (a list of {exchange_index, balance} where balance is
    a fixed-point dollar string); top-level `balance`/`portfolio_value` are in cents.
    Read-only poll for the UI — not on the order path.
    """
    path = '/trade-api/v2/portfolio/balance'
    params: Dict[str, Any] = {}
    if exchange_index is not None:
        params['exchange_index'] = exchange_index
    response = await _throttled_request('get', base_url + path, path=path, params=params or None)
    if response is None:
        return None
    if response.status_code == 200:
        return response.json()
    print(f"Kalshi API (get_balance): Error: {response.status_code}")
    print(response.text)
    return None


async def set_target_balance_allocation(
    allocations: Dict[int, int],
    resting_margin_reservation: str = 'sum',
    base_url: str = 'https://api.elections.kalshi.com',
) -> Optional[Dict[str, Any]]:
    """
    Configure the standing cross-shard bankroll split. This is a one-time config write:
    Kalshi then rebalances server-side (~every 10s) to hold these percentages, with no
    further calls from us and nothing added to the order path. `allocations` maps
    exchange_index -> percent and must sum to 100. Passing an empty dict disables
    auto-rebalancing.
    """
    if allocations and sum(allocations.values()) != 100:
        print(f"Kalshi API (set_target_balance_allocation): percents must sum to 100, got {allocations}")
        return None
    path = '/trade-api/v2/portfolio/target_balance_allocation'
    body = {
        'allocations': [
            {'exchange_index': idx, 'percent': pct}
            for idx, pct in sorted(allocations.items())
        ],
        'resting_margin_reservation': resting_margin_reservation,
    }
    response = await _throttled_request('post', base_url + path, path=path, json=body)
    if response is None:
        print("Kalshi API (set_target_balance_allocation): No response")
        return None
    if response.status_code in (200, 201):
        return response.json()
    print(f"Kalshi API (set_target_balance_allocation): Error: {response.status_code}")
    print(response.text)
    return None


async def post_order_api(
    ticker,
    action,
    count,
    price,
    order_type='limit',
    client_order_id=None,
    base_url='https://api.elections.kalshi.com',
    exchange_index=None,
):
    path = '/trade-api/v2/portfolio/events/orders'

    if client_order_id is None:
        client_order_id = str(uuid.uuid4())

    body = {
        'ticker': ticker,
        'side': 'bid' if action == 'buy' else 'ask',
        'count': f"{float(count):.2f}",
        'price': to_dollars_str(price),
        'time_in_force': 'good_till_canceled',
        'self_trade_prevention_type': 'taker_at_cross',
        'client_order_id': client_order_id,
        'post_only': False,
    }
    # Route straight to the market's shard. Passing it explicitly avoids the
    # "auto-routing incurs an additional latency cost" hit on the order path.
    if exchange_index is not None:
        body['exchange_index'] = exchange_index

    url = base_url + path
    response = await _throttled_request('post', url, path=path, json=body)

    if response is None:
        print("Kalshi API (post_order_api): No response (retry limit or timeout)")
        return None
    if response.status_code in (200, 201):
        return response.json()

    print(f"Kalshi API (post_order_api): Error posting order: {response.status_code}\n{response.text}")
    return None


async def cancel_order_api(
    order_id: str,
    base_url: str = 'https://api.elections.kalshi.com',
    *,
    exchange_index: Optional[int] = None,
    market_ticker: Optional[str] = None,
    quiet_not_found: bool = False,
):
    # Since exchange sharding (Aug 2026) a cancel must be routed to the shard the
    # order lives on. With neither exchange_index nor market_ticker the request
    # defaults to shard 0, so cancels for orders on shards 1-3 come back 404
    # ("order does not exist" on that shard) and the order stays resting.
    # Prefer the explicit shard index; fall back to market_ticker auto-routing.
    path = f'/trade-api/v2/portfolio/events/orders/{order_id}'
    url = base_url + path
    params: Dict[str, Any] = {}
    if exchange_index is not None:
        params['exchange_index'] = exchange_index
    elif market_ticker:
        params['market_ticker'] = market_ticker
    resp = await _throttled_request('delete', url, path=path, params=params or None)
    if resp is None:
        print(f"Kalshi API (cancel_order): No response for order {order_id} (retry limit or timeout)")
        return False
    if resp.status_code == 200:
        return resp.json()

    if resp.status_code == 404:
        # Order not on the routed shard. With routing now supplied this means the
        # order is genuinely gone (already filled/cancelled) — treat as success.
        if not quiet_not_found:
            route = params.get('exchange_index', params.get('market_ticker', 'shard 0'))
            print(f"Kalshi API (cancel_order): order {order_id} not found (route={route}) — treating as already gone")
        return True

    if not quiet_not_found:
        print(f"Kalshi API (cancel_order): Failed to cancel order {order_id}: {resp.status_code}")

    try:
        print(resp.text)
    except Exception:
        pass
    return False


def _is_bid_order(o: dict) -> bool:
    return (
        (o.get('action') == 'buy' and o.get('side') in ('yes', 'bid')) or
        o.get('side') == 'bid'
    )


def _is_ask_order(o: dict) -> bool:
    return (
        (o.get('action') == 'buy' and o.get('side') == 'no') or
        o.get('action') == 'sell' or
        o.get('side') in ('ask', 'no')
    )


async def cancel_all_bids_api(
    ticker: Optional[str] = None,
    base_url: str = 'https://api.elections.kalshi.com',
    *,
    quiet_not_found: bool = False,
) -> dict:
    orders = []
    cursor = None
    while True:
        resp = await get_live_orders(ticker=ticker, status='resting', limit=200, cursor=cursor, base_url=base_url)
        if not resp:
            break
        batch = resp.get('orders', []) if isinstance(resp, dict) else resp
        batch = [o for o in (batch or []) if isinstance(o, dict) and _is_bid_order(o)]
        orders.extend(batch)
        cursor = resp.get('cursor') if isinstance(resp, dict) else None
        if not cursor:
            break

    success = 0
    failed = 0
    for o in orders:
        order_id = o.get('id') or o.get('order_id')
        if not order_id:
            failed += 1
            continue
        if await cancel_order_api(
            str(order_id), base_url=base_url,
            exchange_index=o.get('exchange_index'),
            market_ticker=o.get('ticker') or ticker,
            quiet_not_found=quiet_not_found,
        ):
            success += 1
        else:
            failed += 1
    return {'attempted': len(orders), 'cancelled': success, 'failed': failed}


async def cancel_all_asks_api(
    ticker: Optional[str] = None,
    base_url: str = 'https://api.elections.kalshi.com',
    *,
    quiet_not_found: bool = False,
) -> dict:
    orders = []
    cursor = None
    while True:
        resp = await get_live_orders(ticker=ticker, status='resting', limit=200, cursor=cursor, base_url=base_url)
        if not resp:
            break
        batch = resp.get('orders', []) if isinstance(resp, dict) else resp
        batch = [o for o in (batch or []) if isinstance(o, dict) and _is_ask_order(o)]
        orders.extend(batch)
        cursor = resp.get('cursor') if isinstance(resp, dict) else None
        if not cursor:
            break

    success = 0
    failed = 0
    for o in orders:
        order_id = o.get('id') or o.get('order_id')
        if not order_id:
            failed += 1
            continue
        if await cancel_order_api(
            str(order_id), base_url=base_url,
            exchange_index=o.get('exchange_index'),
            market_ticker=o.get('ticker') or ticker,
            quiet_not_found=quiet_not_found,
        ):
            success += 1
        else:
            failed += 1
    return {'attempted': len(orders), 'cancelled': success, 'failed': failed}


async def get_markets_by_event(
    event_ticker: str,
    base_url: str = 'https://api.elections.kalshi.com',
) -> Optional[list]:
    path = '/trade-api/v2/markets'
    params = {'event_ticker': event_ticker}
    response = await _throttled_request('get', base_url + path, path=path, params=params)
    if response is None:
        return None
    if response.status_code == 200:
        data = response.json()
        return data.get('markets', []) if isinstance(data, dict) else data
    else:
        print(f"Kalshi API (get_markets_by_event): Error for event {event_ticker}: {response.status_code}")
        print(response.text)
        return None


async def get_all_events(
    base_url: str = 'https://api.elections.kalshi.com',
    limit: int = 100,
    cursor: Optional[str] = None,
    status: Optional[str] = None,
    series_ticker: Optional[Any] = None,
) -> Optional[list]:
    if isinstance(series_ticker, list):
        all_events = []
        for series in series_ticker:
            events = await get_all_events(
                base_url=base_url, limit=limit, cursor=cursor,
                status=status, series_ticker=series,
            )
            if events is None:
                return None
            all_events.extend(events)
        return all_events

    path = '/trade-api/v2/events'
    all_events = []
    current_cursor = cursor

    while True:
        params: Dict[str, Any] = {'limit': limit}
        if current_cursor is not None:
            params['cursor'] = current_cursor
        if status is not None:
            params['status'] = status
        if series_ticker is not None:
            params['series_ticker'] = series_ticker

        response = await _throttled_request('get', base_url + path, path=path, params=params)
        if response is None:
            return None
        if response.status_code == 200:
            data = response.json()
            events = data.get('events', []) if isinstance(data, dict) else []
            all_events.extend(events)
            current_cursor = data.get('cursor') if isinstance(data, dict) else None
            if not current_cursor:
                break
        else:
            print(f"Kalshi API (get_all_events): Error: {response.status_code}")
            print(response.text)
            return None

    return all_events
