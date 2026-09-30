#!/usr/bin/env python3
"""
Stream live trades for a Kalshi market.

Usage (from the websocket/ directory):
    python live_trades.py <ticker>
    python live_trades.py <ticker> --debug   # print raw trade messages

Example:
    python live_trades.py KXWCGOAL-26JUN26URUESP-ESPLYAMAL10-1
"""

import asyncio
import json
import sys
import time
from datetime import datetime, timezone

import websockets

from kalshi_api import load_api_key, load_private_key_from_file, sign_pss_text

API_KEY     = load_api_key()
PRIVATE_KEY = load_private_key_from_file('../api-private-key.key')
WS_URL      = 'wss://api.elections.kalshi.com/trade-api/ws/v2'


def _auth_headers():
    ts  = str(int(time.time() * 1000))
    sig = sign_pss_text(PRIVATE_KEY, ts + 'GET' + '/trade-api/ws/v2')
    return {
        'KALSHI-ACCESS-KEY':       API_KEY,
        'KALSHI-ACCESS-SIGNATURE': sig,
        'KALSHI-ACCESS-TIMESTAMP': ts,
    }


def _parse_ts(raw) -> datetime:
    v = int(raw)
    if v > 1e16:    # nanoseconds
        return datetime.fromtimestamp(v / 1e9, tz=timezone.utc)
    if v > 1e13:    # microseconds
        return datetime.fromtimestamp(v / 1e6, tz=timezone.utc)
    if v > 1e10:    # milliseconds
        return datetime.fromtimestamp(v / 1e3, tz=timezone.utc)
    return datetime.fromtimestamp(v, tz=timezone.utc)  # seconds


def _format_trade(m: dict) -> str:
    ts_raw = m.get('ts') or m.get('created_ts')
    if ts_raw:
        ts_str = _parse_ts(ts_raw).strftime('%H:%M:%S.%f')[:-3]
    else:
        ts_str = datetime.now(timezone.utc).strftime('%H:%M:%S.%f')[:-3]

    yes_price_cents   = m.get('yes_price')
    yes_price_dollars = m.get('yes_price_dollars')
    if yes_price_cents is not None:
        price_str = f'{int(yes_price_cents)}.0¢'
    elif yes_price_dollars is not None:
        price_str = f'{float(yes_price_dollars) * 100:.1f}¢'
    else:
        price_str = '?¢'

    count     = m.get('count') or m.get('count_fp') or 0
    count_str = f'x{float(count):.2f}'
    side      = m.get('taker_side') or m.get('taker_book_side') or ''

    return f'{ts_str:<15} {price_str:>7}  {count_str:>9}  {side}'


async def stream(ticker: str, debug: bool = False):
    print(f'Connecting to {ticker}...')
    async with websockets.connect(
        WS_URL,
        additional_headers=_auth_headers(),
        ping_interval=20,
        ping_timeout=30,
        max_size=2 ** 23,
    ) as ws:
        await ws.send(json.dumps({
            'id': 1,
            'cmd': 'subscribe',
            'params': {'channels': ['trade'], 'market_ticker': ticker},
        }))

        print(f"{'Time (UTC)':<15} {'Price':>7}  {'Volume':>9}  Side")
        print('─' * 44)

        async for raw in ws:
            data = json.loads(raw)
            t    = data.get('type')

            if t == 'subscribed':
                continue
            elif t == 'trade':
                m = data.get('msg', {})
                if m.get('market_ticker') != ticker:
                    continue
                if debug:
                    print('RAW:', json.dumps(m))
                print(_format_trade(m))
            elif t == 'error':
                print(f'Kalshi error: {data}')
                break


def main():
    args  = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = [a for a in sys.argv[1:] if a.startswith('--')]

    if not args:
        print(__doc__)
        sys.exit(1)

    ticker = args[0].strip().upper()
    debug  = '--debug' in flags

    try:
        asyncio.run(stream(ticker, debug=debug))
    except KeyboardInterrupt:
        print('\nStopped.')


if __name__ == '__main__':
    main()
