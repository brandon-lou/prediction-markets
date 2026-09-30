"""
Pull and chart historical trade data for a Kalshi market.

Modes:
    Search for a market by player/team name:
        python kalshi_market_history.py --search "Haaland"
        python kalshi_market_history.py --search "Haaland" --series KXWCGOAL

    Chart a specific market by ticker:
        python kalshi_market_history.py --ticker KXWCGOAL-26JUN23ENGGHA-ENGHKANE9-1

Kalshi serves market data in two tiers split at a moving cutoff (GET /historical/cutoff):
markets and trades from before it live under /historical/..., newer ones under /markets/....
Both tiers are read and merged, so markets that settled before the cutoff still chart.
Every endpoint used here is public, so no API key is needed.
"""

import argparse
import requests
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

BASE_URL = 'https://api.elections.kalshi.com/trade-api/v2'


# ── Search ────────────────────────────────────────────────────────────────────

def search_markets(query: str, series_ticker: str = None, status: str = None) -> list[dict]:
    """Fetch markets from Kalshi and filter client-side by title.

    Live markets are always scanned. Markets archived before the historical cutoff are
    scanned too when a series is given; without one, that archive is every market Kalshi
    has ever listed, which is too much to page through.
    """
    params = {'limit': 1000}
    if series_ticker:
        params['series_ticker'] = series_ticker
    if status:
        params['status'] = status

    paths = ['/markets']
    if series_ticker and status in (None, 'settled'):
        paths.append('/historical/markets')  # everything archived has already settled

    query_lower = query.lower()
    matches = []

    print(f'Searching for "{query}"...')
    for path in paths:
        tier_params = dict(params)
        if path == '/historical/markets':
            tier_params.pop('status', None)
        page = 0
        while True:
            resp = requests.get(f'{BASE_URL}{path}', params=tier_params)
            resp.raise_for_status()
            data = resp.json()
            batch = data.get('markets', [])
            page += 1

            for market in batch:
                title = (market.get('title') or '').lower()
                subtitle = (market.get('subtitle') or '').lower()
                ticker = (market.get('ticker') or '').lower()
                if query_lower in title or query_lower in subtitle or query_lower in ticker:
                    matches.append(market)

            cursor = data.get('cursor')
            if not cursor or not batch:
                break
            tier_params['cursor'] = cursor
            print(f'  Scanned {page * 1000} markets...', end='\r')

    return matches


def print_search_results(markets: list[dict], query: str) -> None:
    if not markets:
        print(f'No markets found matching "{query}".')
        return

    print(f'\nFound {len(markets)} market(s) matching "{query}":\n')
    for m in markets:
        status = m.get('status', '').upper()
        close_time = m.get('close_time', '')[:10] if m.get('close_time') else '?'
        result = m.get('result', '')
        settled = f'  → {result}' if result else ''
        print(f'  [{status}] {m["ticker"]}')
        print(f'          {m.get("title", "")} (closes {close_time}){settled}')
        print()


# ── Trades ────────────────────────────────────────────────────────────────────

def fetch_market(ticker: str) -> dict:
    """Market details, falling back to the historical tier for markets archived before the cutoff."""
    for path in (f'/markets/{ticker}', f'/historical/markets/{ticker}'):
        resp = requests.get(f'{BASE_URL}{path}')
        if resp.status_code == 404:
            continue
        resp.raise_for_status()
        return resp.json().get('market', {})
    return {}


def get_historical_cutoff_ts() -> int | None:
    """Unix time before which trades are served only by /historical/trades."""
    resp = requests.get(f'{BASE_URL}/historical/cutoff')
    resp.raise_for_status()
    raw = resp.json().get('trades_created_ts')
    return int(pd.Timestamp(raw).timestamp()) if raw else None


def _fetch_trades(path: str, params: dict) -> list[dict]:
    params = dict(params)
    trades = []
    while True:
        resp = requests.get(f'{BASE_URL}{path}', params=params)
        resp.raise_for_status()
        data = resp.json()
        batch = data.get('trades', [])
        trades.extend(batch)
        cursor = data.get('cursor')
        if not cursor or not batch:
            break
        params['cursor'] = cursor
    return trades


def fetch_all_trades(ticker: str, min_ts: int = None, max_ts: int = None) -> list[dict]:
    """Merge the historical tier (before the cutoff) with the live tier (after it)."""
    params = {'ticker': ticker, 'limit': 1000}
    if min_ts:
        params['min_ts'] = min_ts
    if max_ts:
        params['max_ts'] = max_ts

    cutoff = get_historical_cutoff_ts()
    if cutoff is None:
        tiers = [('/markets/trades', params)]
    else:
        tiers = []
        if not min_ts or min_ts < cutoff:
            tiers.append(('/historical/trades', {**params, 'max_ts': min(max_ts or cutoff, cutoff)}))
        if not max_ts or max_ts > cutoff:
            tiers.append(('/markets/trades', {**params, 'min_ts': max(min_ts or cutoff, cutoff)}))

    trades, seen = [], set()
    for path, tier_params in tiers:
        for t in _fetch_trades(path, tier_params):
            trade_id = t.get('trade_id')
            if trade_id is not None and trade_id in seen:
                continue  # a trade at the cutoff instant can come back from both tiers
            seen.add(trade_id)
            trades.append(t)
    return trades


def trades_to_df(trades: list[dict]) -> pd.DataFrame:
    rows = []
    for t in trades:
        rows.append({
            'time': pd.to_datetime(t['created_time']),
            'price': float(t['yes_price_dollars']) * 100,
            'volume': float(t['count_fp']),
            'side': t.get('taker_book_side', ''),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values('time').reset_index(drop=True)


# ── Chart ─────────────────────────────────────────────────────────────────────

def plot_market(df: pd.DataFrame, ticker: str, market: dict = None) -> None:
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), sharex=True,
                                    gridspec_kw={'height_ratios': [3, 1]})
    title = (market or {}).get('title')
    fig.suptitle(f'{title} ({ticker})' if title else f'Kalshi Market: {ticker}', fontsize=13)

    ax1.plot(df['time'], df['price'], color='steelblue', linewidth=1.2, zorder=3)
    ax1.set_ylabel('Yes Price (cents)')
    ax1.set_ylim(0, 100)
    ax1.axhline(50, color='gray', linestyle='--', linewidth=0.7, alpha=0.5)
    ax1.grid(True, alpha=0.3)

    bids = df[df['side'] == 'bid']
    asks = df[df['side'] == 'ask']
    ax1.scatter(bids['time'], bids['price'], color='green', s=15, alpha=0.5, zorder=4, label='Taker buy')
    ax1.scatter(asks['time'], asks['price'], color='red', s=15, alpha=0.5, zorder=4, label='Taker sell')
    ax1.legend(fontsize=8)

    colors = ['green' if s == 'bid' else 'red' for s in df['side']]
    ax2.bar(df['time'], df['volume'], width=0.0005, color=colors, alpha=0.7)
    ax2.set_ylabel('Contracts')
    ax2.set_xlabel('Time (UTC)')
    ax2.grid(True, alpha=0.3)

    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    fig.autofmt_xdate()
    plt.tight_layout()
    plt.show()


def print_summary(df: pd.DataFrame, ticker: str, market: dict = None) -> None:
    market = market or {}
    print(f'\n=== {market.get("title") or ticker} ({ticker}) ===')
    if market.get('result'):
        print(f'Result:        {market["result"].upper()}')
    print(f'Trades:        {len(df)}')
    print(f'Total volume:  {df["volume"].sum():.0f} contracts')
    print(f'Time range:    {df["time"].min()} → {df["time"].max()}')
    print(f'Price range:   {df["price"].min():.1f}¢ → {df["price"].max():.1f}¢')
    print(f'Open:          {df["price"].iloc[0]:.1f}¢')
    print(f'Close:         {df["price"].iloc[-1]:.1f}¢')
    vwap = (df['price'] * df['volume']).sum() / df['volume'].sum()
    print(f'VWAP:          {vwap:.1f}¢')


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Search and chart Kalshi market trade history')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--search', metavar='QUERY', help='Search for markets by player/team name')
    mode.add_argument('--ticker', help='Chart a specific market ticker')

    parser.add_argument('--series', metavar='SERIES_TICKER', help='Narrow search to a series (e.g. KXWCGOAL)')
    parser.add_argument('--status', choices=['open', 'closed', 'settled'], help='Filter search by market status')
    parser.add_argument('--min-ts', type=int, help='Start Unix timestamp for trade history')
    parser.add_argument('--max-ts', type=int, help='End Unix timestamp for trade history')
    args = parser.parse_args()

    if args.search:
        markets = search_markets(args.search, series_ticker=args.series, status=args.status)
        print_search_results(markets, args.search)
        if not args.series:
            print('Tip: add --series to also search settled markets archived before the historical cutoff.')
        print('To chart one of these, run:')
        print('  python kalshi_market_history.py --ticker <TICKER>')

    elif args.ticker:
        print(f'Fetching trades for {args.ticker}...')
        market = fetch_market(args.ticker)
        trades = fetch_all_trades(args.ticker, min_ts=args.min_ts, max_ts=args.max_ts)
        if not trades:
            print('No trades found.')
            return
        df = trades_to_df(trades)
        print_summary(df, args.ticker, market)
        plot_market(df, args.ticker, market)


if __name__ == '__main__':
    main()
