# Prediction markets

Tools and models for trading and studying Kalshi event contracts.

## [kalshi-ladder](kalshi-ladder/)

A keyboard-driven trading ladder for Kalshi. A Python asyncio process keeps live order books from
Kalshi's WebSocket and signs every order, and a browser UI shows up to 45 markets as price ladders
with click and hotkey trading.

- **Self-repairing books:** they are built from the snapshot and delta stream, and a market is
  resubscribed when its book falls out of sync.
- **Order guards:** orders refuse to fire on a stale book or an empty side, and the API key never
  reaches the browser.
- **Per-shard collateral:** handles Kalshi's August 2026 exchange sharding with a target allocation
  across shards, cancels routed to each market's shard, and per-shard balances in the header.
- **Tests:** 75 in Python and 60 in JavaScript.

## [world-cup-2026](world-cup-2026/)

A 2026 World Cup model that replicates Groll et al. (2019). It estimates team strengths with a
weighted Poisson regression and prices every group match: win/draw/loss, exact scores, and goal and
margin lines. It then simulates the full 48-team tournament 20,000 times.

- **The real 2026 format:** the best third-placed teams are assigned to Round-of-32 slots by bipartite
  matching.
- **Scored against the actual 2026 results** with the ranked probability score.
- **The paper's random-forest extension,** with a check that warns when 2026 matches have leaked into
  its training data.

## [kalshi-market-history](kalshi-market-history/)

Find any Kalshi market and chart its full trade history. It merges Kalshi's historical and live data
tiers at the cutoff, so long-settled markets chart the same way as live ones. The notebook splits
trading into pre-game, in-game and post-settlement phases.

---

Each folder has its own README with setup instructions and design notes.
