// Run with: node --test ladder/tests/market-finder.test.js
// Fixtures in fixtures/nfl-slate.json are trimmed real /trade-api/v2/events payloads.
const test = require("node:test");
const assert = require("node:assert/strict");
const fixture = require("./fixtures/nfl-slate.json");
const {
  eventSuffix,
  dollarsToCents,
  compactLabel,
  normalizeMarket,
  buildGames,
  matchesQuery,
  rankGames,
  nearestToFifty,
  normalizeSearchItem,
  KICKOFF_SKEW_MS,
} = require("../market-finder.js");

const games = buildGames(fixture);
const carAtl = games.get("26SEP20CARATL");
const phiChi = games.get("26SEP28PHICHI");

// ── Parsing ───────────────────────────────────────────────────────────────────

test("eventSuffix pulls the shared game key out of an event ticker", () => {
  assert.equal(eventSuffix("KXNFLGAME-26SEP20CARATL"), "26SEP20CARATL");
  assert.equal(eventSuffix("KXNFLSPREAD-26SEP20CARATL"), "26SEP20CARATL");
  assert.equal(eventSuffix("NOSEGMENTS"), "");
  assert.equal(eventSuffix(undefined), "");
});

test("dollar strings convert to integer cents", () => {
  assert.equal(dollarsToCents("0.0600"), 6);
  assert.equal(dollarsToCents("0.4200"), 42);
  assert.equal(dollarsToCents("1.0000"), 100);
  assert.equal(dollarsToCents(null), null);
  assert.equal(dollarsToCents("nonsense"), null);
});

test("compactLabel decodes the half-point line encoded in the ticker", () => {
  // ATL17 is "Atlanta wins by over 16.5 points" — the ticker carries strike + 0.5.
  assert.equal(compactLabel("KXNFLSPREAD-26SEP20CARATL-ATL17", "spread"), "ATL -16.5");
  assert.equal(compactLabel("KXNFLSPREAD-26SEP20CARATL-CAR3", "spread"), "CAR -2.5");
  assert.equal(compactLabel("KXNFLTOTAL-26SEP20CARATL-24", "total"), "o23.5");
  assert.equal(compactLabel("KXNFLGAME-26SEP20CARATL-ATL", "moneyline"), "ATL");
});

test("compactLabel falls back to the raw suffix on an unexpected shape", () => {
  assert.equal(compactLabel("KXNFLSPREAD-26SEP20CARATL-WEIRD", "spread"), "WEIRD");
  assert.equal(compactLabel("KXNFLTOTAL-26SEP20CARATL-X9", "total"), "X9");
});

// ── Normalisation ─────────────────────────────────────────────────────────────

test("normalizeMarket drops anything not currently tradeable", () => {
  assert.equal(normalizeMarket({ ticker: "T-1", status: "settled" }, "spread"), null);
  assert.equal(normalizeMarket({ ticker: "T-1", status: "closed" }, "spread"), null);
  assert.equal(normalizeMarket({ status: "active" }, "spread"), null);
  assert.ok(normalizeMarket({ ticker: "T-1", status: "active" }, "spread"));
});

test("the settled spread strike never reaches a chip", () => {
  const tickers = carAtl.spread.map((m) => m.ticker);
  assert.ok(!tickers.includes("KXNFLSPREAD-26SEP20CARATL-CAR99"));
  assert.equal(carAtl.spread.length, 6);
});

// ── Game assembly ─────────────────────────────────────────────────────────────

test("the three series join into one game on the shared suffix", () => {
  assert.equal(carAtl.moneyline.length, 2);
  assert.equal(carAtl.spread.length, 6);
  assert.equal(carAtl.total.length, 5);
  assert.equal(carAtl.marketCount, 13);
  assert.equal(carAtl.title, "CAR Panthers vs ATL Falcons");
});

test("a game with no spread/total event posted yet still appears", () => {
  assert.ok(phiChi, "later-week game should be present");
  assert.equal(phiChi.moneyline.length, 2);
  assert.deepEqual(phiChi.spread, []);
  assert.deepEqual(phiChi.total, []);
});

test("kickoff corrects Kalshi's 3-hour skew to the real kickoff", () => {
  // Kalshi publishes CAR@ATL as 20:00Z; ESPN's scoreboard (checked 2026-09-20 for all 14
  // games that day) says the real kickoff is 17:00Z = 1:00 PM ET. Guards the constant so a
  // silent change here can't ship wrong times.
  assert.equal(carAtl.kickoffMs, Date.parse("2026-09-20T17:00:00Z"));
  assert.equal(
    new Date(carAtl.kickoffMs).toLocaleString("en-US", {
      hour: "numeric", minute: "2-digit", timeZone: "America/New_York",
    }),
    "1:00 PM"
  );
});

test("the skew is a flat 3h, so ordering is unchanged by the correction", () => {
  assert.equal(KICKOFF_SKEW_MS, 3 * 60 * 60 * 1000);
});

test("prices survive the dollar-string conversion end to end", () => {
  const atl = carAtl.moneyline.find((m) => m.ticker.endsWith("-ATL"));
  assert.equal(atl.bid, 42);
  assert.equal(atl.ask, 43);
});

test("spreads group by team then line; totals ascend by strike", () => {
  assert.deepEqual(
    carAtl.spread.map((m) => m.label),
    ["ATL -7.5", "ATL -9.5", "ATL -10.5", "ATL -13.5", "ATL -14.5", "ATL -16.5"]
  );
  assert.deepEqual(
    carAtl.total.map((m) => m.label),
    ["o23.5", "o26.5", "o29.5", "o32.5", "o35.5"]
  );
});

// ── Query matching ────────────────────────────────────────────────────────────

test("a team code matches its game", () => {
  assert.ok(matchesQuery(carAtl, "CAR"));
  assert.ok(matchesQuery(carAtl, "atl"));
  assert.ok(!matchesQuery(carAtl, "KC"));
});

test("nicknames and city names both match", () => {
  assert.ok(matchesQuery(carAtl, "panthers"));
  assert.ok(matchesQuery(carAtl, "carolina"));
  assert.ok(matchesQuery(carAtl, "falcons"));
});

test("city aliases work for a game with no spread event to borrow the name from", () => {
  // PHICHI has only the moneyline event, whose title is "PHI Eagles vs CHI Bears" — the
  // word "philadelphia" appears nowhere in the payload, only in TEAM_ALIASES.
  assert.ok(matchesQuery(phiChi, "philadelphia"));
  assert.ok(matchesQuery(phiChi, "chicago"));
});

test("every token must match, so two teams narrow to one game", () => {
  assert.ok(matchesQuery(carAtl, "car atl"));
  assert.ok(!matchesQuery(carAtl, "car kc"));
  assert.ok(!matchesQuery(phiChi, "phi atl"));
});

test("the date in the subtitle is searchable", () => {
  assert.ok(matchesQuery(carAtl, "sep 20"));
  assert.ok(!matchesQuery(carAtl, "sep 28"));
});

test("pasting a full market ticker finds its game", () => {
  assert.ok(matchesQuery(carAtl, "KXNFLSPREAD-26SEP20CARATL"));
});

test("an empty query matches everything", () => {
  assert.ok(matchesQuery(carAtl, ""));
  assert.ok(matchesQuery(carAtl, "   "));
});

test("rankGames filters then orders by kickoff, soonest first", () => {
  const ranked = rankGames(games, "");
  assert.deepEqual(ranked.map((g) => g.suffix), ["26SEP20CARATL", "26SEP28PHICHI"]);
  assert.deepEqual(rankGames(games, "eagles").map((g) => g.suffix), ["26SEP28PHICHI"]);
});

// ── Collapsed sections ────────────────────────────────────────────────────────

test("nearestToFifty keeps the most tradeable strikes, in display order", () => {
  const markets = [
    { ticker: "a", bid: 5, ask: 6 },
    { ticker: "b", bid: 48, ask: 49 },
    { ticker: "c", bid: 94, ask: 95 },
    { ticker: "d", bid: 55, ask: 56 },
  ];
  const picked = nearestToFifty(markets, 2);
  assert.deepEqual(picked.map((m) => m.ticker), ["b", "d"]);
});

test("nearestToFifty is a no-op when the section already fits", () => {
  const markets = [{ ticker: "a", bid: 5, ask: 6 }];
  assert.equal(nearestToFifty(markets, 6), markets);
});

test("nearestToFifty tolerates missing quotes", () => {
  const markets = [
    { ticker: "a", bid: null, ask: null },
    { ticker: "b", bid: 99, ask: 100 },
    { ticker: "c", bid: null, ask: 51 },
  ];
  assert.equal(nearestToFifty(markets, 2).length, 2);
});

// ── Generic search ────────────────────────────────────────────────────────────

test("search results keep integer cents as-is (not scaled like the v2 payload)", () => {
  const card = normalizeSearchItem({
    event_ticker: "KXFED-26DEC",
    event_title: "Fed funds rate after December meeting?",
    event_subtitle: "On Dec 9, 2026",
    active_market_count: 1,
    markets: [{ ticker: "KXFED-26DEC-T4.25", yes_subtitle: "Above 4.25%", yes_bid: 34, yes_ask: 35 }],
  });
  assert.equal(card.moneyline[0].bid, 34);
  assert.equal(card.moneyline[0].ask, 35);
  assert.equal(card.moneyline[0].label, "Above 4.25%");
  assert.equal(card.marketCount, 1);
});

test("search markets that already closed are dropped", () => {
  const card = normalizeSearchItem({
    event_ticker: "KXOLD-1",
    event_title: "Done",
    active_market_count: 2,
    markets: [
      { ticker: "KXOLD-1-A", yes_subtitle: "A", yes_bid: 0, yes_ask: 100, close_ts: "2025-10-07T03:19:39Z" },
      { ticker: "KXOLD-1-B", yes_subtitle: "B", yes_bid: 10, yes_ask: 11, close_ts: "2099-01-01T00:00:00Z" },
    ],
  });
  assert.deepEqual(card.moneyline.map((m) => m.ticker), ["KXOLD-1-B"]);
});

test("a search item with nothing left to trade is dropped entirely", () => {
  assert.equal(
    normalizeSearchItem({
      event_ticker: "KXOLD-2",
      markets: [{ ticker: "KXOLD-2-A", close_ts: "2020-01-01T00:00:00Z" }],
    }),
    null
  );
});
