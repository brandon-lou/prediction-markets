# kalshi-ladder

A keyboard-driven trading ladder for Kalshi. A Python process holds the exchange connection. It
streams order books and fills over Kalshi's WebSocket, places and cancels orders over the REST API,
and serves a browser UI that shows up to 45 markets as price ladders (five per page, nine pages).

## Features

- **Live ladders.** Each panel shows one market's order book from 1¢ to 99¢, with your own resting
  orders in separate columns. Click your bid or ask column at a price to post an order there, or
  right-click it to cancel at that price.
- **Keyboard trading.** Keys set focus and size and place orders; see [Keyboard](#keyboard). Order
  keys need `Alt` held, and they refuse to fire on a stale book or an empty side.
- **Market finder.** `/` searches Kalshi's NFL game, spread and total markets by team, city or date,
  and loads the market you click into the next empty panel.
- **Per-shard collateral.** Since Kalshi's August 2026 exchange sharding, collateral is held per
  shard. On startup the app sets a target allocation across shards (`TARGET_BALANCE_ALLOCATION` in
  `websocket/main.py`). It routes each cancel to its market's shard and shows each shard's balance in
  the header.
- **Ticker library.** Saves tickers in the browser so you can reload them quickly.
- **Trade stream.** `websocket/live_trades.py` streams one market's public trades to the terminal.

## How it's built

```
websocket/               Python (asyncio): the only process that talks to Kalshi
  main.py                startup, market subscriptions, resync and balance loops
  kalshi_websocket.py    Kalshi WebSocket client: book snapshots and deltas, fills, trades
  state.py, orderbook.py per-market order book, your resting orders, position
  update_orders.py       place, cancel and reconcile orders
  kalshi_api.py          signed REST calls (RSA-PSS), write throttle, retries
  ladder_server.py       local WebSocket (ws://localhost:8765) the UI connects to
  static_server.py       serves ladder/ at http://localhost:8080
ladder/                  browser UI, plain JavaScript, no build step
  app.js                 panels, pages and ladder rendering
  hotkeys.js             key bindings, and the rules that decide whether a key may place an order
  market-finder.js       market search over Kalshi's public endpoints
  finder-ui.js           the search overlay
  panel-router.js        routes order book updates to panels
```

Design choices:

- **The API key never reaches the browser.** The UI sends order requests to the local Python process,
  which signs them.
  - Market search runs in the browser against Kalshi's public endpoints, so it never competes with
    order traffic.
  - This only works because the UI is served from localhost: Kalshi's firewall rejects requests from
    pages opened as `file://`.
- **Order books repair themselves.** Each book is built from Kalshi's snapshot and delta stream. A
  market is resubscribed if it goes silent for 20 seconds, or if a delta would push a price level
  below zero.
- **Order state is checked against the exchange.**
  - Your position is set from the exchange's own figure on every fill.
  - Local bookkeeping of resting orders can drift, for example after a cancel sent outside the normal
    path or duplicate fills during a resubscribe. When that happens, the app re-reads your resting
    orders from Kalshi.
- **Rate limits.** REST writes pass through a throttle of 30 per second. A request that gets a 429 or
  a connection error is tried up to 4 times in total, and re-signed each time.
- **Integer prices.** Prices are stored as whole ten-thousandths of a dollar, so sub-cent levels roll
  up cleanly into the 1¢–99¢ ladder.

## Setup

Tested with Python 3.11 (aiohttp 3.14, websockets 16, cryptography 46). The frontend tests need
Node 18+.

    pip install -r requirements.txt

Create a Kalshi API key. Put the key ID in `api-key.txt` and the private key in
`api-private-key.key`, both in this folder, next to this README. Both file names are gitignored.

## Running

    cd websocket && python main.py

Then open **http://localhost:8080/**, not the `ladder/index.html` file. `main.py` serves `ladder/` on
a background thread. The localhost origin is required because Kalshi's API rejects requests from
`file://` pages, and the market finder calls that API from the browser.

Press `/` or `Ctrl`/`Cmd`+`K` for the market finder: search NFL games by team, city or date, and click
a market to load it into the next empty panel. If port 8080 is taken, the ladder still starts; it
prints a notice, and only search is unavailable.

## Keyboard

Press `?` (or the **Keys** button) in the app for the cheat sheet. It is rendered from the same
`KEYMAP` in `ladder/hotkeys.js` that handles the keys, so it can't go out of date.

All keys act on the **focused panel** (bright blue outline). Nothing fires while you are typing in
a field or while the finder or cheat sheet is open.

| | |
|---|---|
| `1`–`9` | Switch page |
| `←` `→` | Focus previous / next panel (wraps across pages) |
| `Q W E R T` | Focus panel 1–5 of this page |
| `↑` `↓` | Step size: 1, 5, 10, 25, 50, 100, 250, 500, 1000 |
| `Shift+↑` `Shift+↓` | Jump to largest / smallest size |
| `Alt+B` / `Alt+S` | Buy at the bid / sell at the ask: **rests in the queue** |
| `Alt+Shift+B` / `Alt+Shift+S` | Buy at the ask / sell at the bid: **crosses, fills immediately** |
| `Alt+C` / `Alt+Shift+C` / `Alt+X` | Cancel my bids / asks / both on this market |
| `Alt+Shift+X` | Cancel everything on every market (press twice within 3s) |

Order keys need `Alt` held, so a bare letter never trades. They also refuse to fire on a stale book
or on a side with no quote, and flash the reason in the panel header instead. An empty book reports a
bid of 0 and an ask of 100, and without this check an order would post at those prices.

The `xB` / `xA` / `X` buttons in each panel header do the same cancels with the mouse.

## Tests

    python -m pytest websocket/tests            # 75 tests; the Kalshi API module is mocked, so no keys are needed
    cd ladder && node --test tests/*.test.js    # 60 tests
