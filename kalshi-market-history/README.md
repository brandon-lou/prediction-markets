# Kalshi market history

Find any Kalshi market and chart its complete trade history.

Kalshi splits its data at a moving cutoff (`GET /historical/cutoff`). Markets and trades from before
the cutoff are served only under `/historical/...`, and newer ones under `/markets/...`. Both tools
here read the two tiers and merge them at the cutoff, so a market that settled months ago charts the
same way as a live one.

## Command line

`kalshi_market_history.py` needs no API key: every endpoint it uses is public. It requires Python 3.10+.

```
pip install -r requirements.txt
python kalshi_market_history.py --search "Kane" --series KXWCGOAL             # find markets
python kalshi_market_history.py --ticker KXWCGOAL-26JUN23ENGGHA-ENGHKANE9-1   # chart one
```

- `--ticker` prints a summary and plots the yes price with every taker buy and sell marked, above a
  volume chart. `--min-ts` / `--max-ts` (Unix seconds) limit the time window.
- `--search` matches market titles and tickers. `--status` filters the results. Add `--series` to
  include markets that have already been archived; without a series, the archive is too large to scan.

```
=== Harry Kane: 1+ goals (KXWCGOAL-26JUN23ENGGHA-ENGHKANE9-1) ===
Result:        NO
Trades:        28036
Total volume:  3872516 contracts
Time range:    2026-06-21 20:18:45.487878+00:00 → 2026-06-23 22:01:00.148779+00:00
Price range:   1.0¢ → 68.0¢
Open:          58.0¢
Close:         1.0¢
VWAP:          51.9¢
```

## Notebook

`kalshi_market_history.ipynb` is an interactive version for Google Colab, built for studying how a
market trades around the event it resolves on:

- browse series by keyword, and search markets within a date range
- chart price and volume, with game start and settlement marked
- bucket trading activity over time and list the busiest windows
- split trades and dollar volume into pre-game, in-game and post-settlement
- show a filterable trade table with a running VWAP

The notebook signs its requests with a Kalshi API key. You upload the key files to the Colab session
when prompted.
