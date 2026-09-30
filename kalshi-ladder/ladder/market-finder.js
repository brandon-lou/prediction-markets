// Pure market-discovery logic: fetch Kalshi's public event/search endpoints and turn the
// payloads into the card + chip shapes the finder UI renders. No DOM access here, so it
// can be unit tested under `node --test` (see ladder/tests/) the same way panel-router.js is.
//
// These endpoints need no authentication. The API key never leaves the Python process —
// the browser only ever reads public market data.

const MarketFinder = (function buildMarketFinder() {
const KALSHI_BASE = "https://api.elections.kalshi.com";

// The three NFL series that together describe one game. They share an event-ticker
// suffix (KXNFLGAME-26SEP20CARATL / KXNFLSPREAD-26SEP20CARATL / ...), which is what
// buildGames joins on.
const NFL_SERIES = [
  { kind: "moneyline", series: "KXNFLGAME" },
  { kind: "spread", series: "KXNFLSPREAD" },
  { kind: "total", series: "KXNFLTOTAL" },
];

// Kalshi's occurrence_datetime for NFL games is a uniform 3 hours late: they convert the
// Eastern kickoff wall-clock as if it were Pacific. Verified 2026-09-20 against ESPN's
// scoreboard for all 14 games that Sunday — 17:00Z/20:05Z/20:25Z/00:20Z real kickoffs are
// published as 20:00Z/23:05Z/23:25Z/03:20Z. Every other Kalshi time field for the game
// (expected_expiration_time, the v1 search expected_expiration_ts) carries the same skew.
// US Eastern and Pacific change DST on the same dates, so the gap is a constant 3h
// year-round and a flat subtraction is correct in both halves of the year.
// If Kalshi ever fixes this, kickoffs will read 3h early — delete this constant.
const KICKOFF_SKEW_MS = 3 * 60 * 60 * 1000;

// Extra search terms per Kalshi team code. Event titles carry the code and the nickname
// ("CAR Panthers vs ATL Falcons"), but the city name only shows up in the spread/total
// titles ("Carolina vs Atlanta: Spread") — and those events aren't posted until game week.
// Without this map, searching "carolina" would miss next month's games entirely.
const TEAM_ALIASES = {
  ARI: "arizona cardinals",
  ATL: "atlanta falcons",
  BAL: "baltimore ravens",
  BUF: "buffalo bills",
  CAR: "carolina panthers",
  CHI: "chicago bears",
  CIN: "cincinnati bengals",
  CLE: "cleveland browns",
  DAL: "dallas cowboys",
  DEN: "denver broncos",
  DET: "detroit lions",
  GB: "green bay packers",
  HOU: "houston texans",
  IND: "indianapolis colts",
  JAC: "jacksonville jaguars jax",
  KC: "kansas city chiefs",
  LAC: "los angeles chargers la",
  LAR: "los angeles rams la",
  LV: "las vegas raiders oakland",
  MIA: "miami dolphins",
  MIN: "minnesota vikings",
  NE: "new england patriots",
  NO: "new orleans saints",
  NYG: "new york giants",
  NYJ: "new york jets",
  PHI: "philadelphia eagles",
  PIT: "pittsburgh steelers",
  SEA: "seattle seahawks",
  SF: "san francisco 49ers niners",
  TB: "tampa bay buccaneers bucs",
  TEN: "tennessee titans",
  WAS: "washington commanders",
};

// ── Parsing helpers ───────────────────────────────────────────────────────────

// "KXNFLGAME-26SEP20CARATL" -> "26SEP20CARATL"
function eventSuffix(eventTicker) {
  const parts = String(eventTicker || "").split("-");
  return parts.length >= 2 ? parts[1] : "";
}

// Prices on /trade-api/v2 arrive as dollar strings ("0.0600"); the ladder works in cents.
function dollarsToCents(value) {
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed)) return null;
  return Math.round(parsed * 100);
}

function toNumber(value) {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

// Short chip text derived from the ticker itself, so it stays correct even when Kalshi's
// yes_sub_title wording changes. The strike encoded in the ticker is always the half-point
// line rounded up: ATL17 means "Atlanta wins by over 16.5", 24 means "over 23.5 scored".
function compactLabel(ticker, kind) {
  const suffix = String(ticker || "").split("-").pop() || "";
  if (kind === "total") {
    const n = suffix.match(/^(\d+)$/);
    return n ? `o${Number(n[1]) - 0.5}` : suffix;
  }
  if (kind === "spread") {
    const m = suffix.match(/^([A-Z]+)(\d+)$/);
    return m ? `${m[1]} -${Number(m[2]) - 0.5}` : suffix;
  }
  return suffix; // moneyline: the team code
}

// Sort within a section: totals by strike, spreads grouped by team then by line, so each
// team's ladder reads top to bottom instead of interleaving the two sides.
function marketSortKey(ticker, kind) {
  const suffix = String(ticker || "").split("-").pop() || "";
  if (kind === "total") {
    const n = suffix.match(/^(\d+)$/);
    return n ? Number(n[1]) : 0;
  }
  if (kind === "spread") {
    const m = suffix.match(/^([A-Z]+)(\d+)$/);
    return m ? `${m[1]}:${String(m[2]).padStart(4, "0")}` : suffix;
  }
  return suffix;
}

// ── Normalisation ─────────────────────────────────────────────────────────────

// Returns null for anything not currently tradeable, so dead strikes never reach a chip.
function normalizeMarket(raw, kind) {
  if (!raw || !raw.ticker) return null;
  if (raw.status && raw.status !== "active") return null;
  return {
    ticker: raw.ticker,
    kind,
    label: compactLabel(raw.ticker, kind),
    fullLabel: raw.yes_sub_title || raw.title || raw.ticker,
    bid: dollarsToCents(raw.yes_bid_dollars),
    ask: dollarsToCents(raw.yes_ask_dollars),
    volume: toNumber(raw.volume_fp),
    sortKey: marketSortKey(raw.ticker, kind),
  };
}

function normalizeMarkets(rawMarkets, kind) {
  return (rawMarkets || [])
    .map((m) => normalizeMarket(m, kind))
    .filter(Boolean)
    .sort((a, b) => (a.sortKey > b.sortKey ? 1 : a.sortKey < b.sortKey ? -1 : 0));
}

// ── Game assembly ─────────────────────────────────────────────────────────────

// Joins the three NFL series into one card per game. Games whose spread/total events
// haven't been posted yet (common for anything past the current week) still appear, just
// with only a moneyline section.
function buildGames(eventsByKind) {
  const games = new Map();

  for (const { kind } of NFL_SERIES) {
    for (const event of eventsByKind[kind] || []) {
      const suffix = eventSuffix(event.event_ticker);
      if (!suffix) continue;

      let game = games.get(suffix);
      if (!game) {
        game = {
          suffix,
          title: "",
          subtitle: "",
          kickoffMs: null,
          titles: [],
          eventTickers: [],
          moneyline: [],
          spread: [],
          total: [],
        };
        games.set(suffix, game);
      }

      game.eventTickers.push(event.event_ticker);
      if (event.title) game.titles.push(event.title);
      if (kind === "moneyline") {
        // The KXNFLGAME event has the canonical "CAR Panthers vs ATL Falcons" phrasing.
        game.title = event.title || game.title;
        game.subtitle = event.sub_title || game.subtitle;
      } else if (!game.title) {
        game.title = event.title || "";
        game.subtitle = event.sub_title || game.subtitle;
      }

      const markets = normalizeMarkets(event.markets, kind);
      game[kind] = game[kind].concat(markets);

      if (game.kickoffMs === null) {
        const kickoff = (event.markets || []).map((m) => m.occurrence_datetime).find(Boolean);
        if (kickoff) {
          const ms = Date.parse(kickoff);
          // Corrected here, once, so display and sort both use the true instant.
          if (Number.isFinite(ms)) game.kickoffMs = ms - KICKOFF_SKEW_MS;
        }
      }
    }
  }

  for (const game of games.values()) {
    game.haystack = buildHaystack(game);
    game.marketCount = game.moneyline.length + game.spread.length + game.total.length;
  }
  return games;
}

// Everything a query token is allowed to match against: both team codes plus their city
// and nickname aliases, every event title, the "CAR vs ATL (Sep 20)" subtitle, and the
// raw event tickers (so pasting a ticker finds its game).
function buildHaystack(game) {
  const parts = [game.suffix, game.title, game.subtitle, ...game.titles, ...game.eventTickers];
  for (const code of teamCodes(game)) {
    parts.push(code);
    if (TEAM_ALIASES[code]) parts.push(TEAM_ALIASES[code]);
  }
  return parts.join(" ").toLowerCase();
}

// Team codes come from the moneyline tickers (KXNFLGAME-<suffix>-ATL), which are the one
// place both sides are stated unambiguously.
function teamCodes(game) {
  const codes = new Set();
  for (const market of game.moneyline) {
    const code = String(market.ticker).split("-").pop();
    if (code) codes.add(code);
  }
  return [...codes];
}

// ── Query matching ────────────────────────────────────────────────────────────

// Every whitespace-separated token must appear somewhere in the haystack, so "dal nyg"
// narrows to the one game rather than returning both teams' full schedules.
function matchesQuery(game, query) {
  const tokens = String(query || "").toLowerCase().trim().split(/\s+/).filter(Boolean);
  if (!tokens.length) return true;
  return tokens.every((token) => game.haystack.includes(token));
}

function rankGames(games, query) {
  const list = Array.isArray(games) ? games : [...games.values()];
  return list
    .filter((game) => matchesQuery(game, query))
    .sort((a, b) => {
      const aMs = a.kickoffMs === null ? Infinity : a.kickoffMs;
      const bMs = b.kickoffMs === null ? Infinity : b.kickoffMs;
      if (aMs !== bMs) return aMs - bMs;
      return a.suffix < b.suffix ? -1 : 1;
    });
}

// Which strikes to show before the section is expanded: the ones trading nearest a coin
// flip, which is where the tradeable lines live. Returned in display order, not by distance.
function nearestToFifty(markets, count) {
  if (markets.length <= count) return markets;
  const mid = (m) => {
    const bid = Number.isFinite(m.bid) ? m.bid : null;
    const ask = Number.isFinite(m.ask) ? m.ask : null;
    if (bid === null && ask === null) return 50;
    if (bid === null) return ask;
    if (ask === null) return bid;
    return (bid + ask) / 2;
  };
  const picked = new Set(
    [...markets]
      .sort((a, b) => Math.abs(mid(a) - 50) - Math.abs(mid(b) - 50))
      .slice(0, count)
      .map((m) => m.ticker)
  );
  return markets.filter((m) => picked.has(m.ticker));
}

// ── Fetching ──────────────────────────────────────────────────────────────────

async function fetchJson(url, fetchImpl) {
  const doFetch = fetchImpl || fetch;
  const response = await doFetch(url);
  if (!response.ok) {
    throw new Error(`Kalshi request failed (${response.status}) for ${url}`);
  }
  return response.json();
}

// Follows the cursor even though the NFL slate currently fits in one page — a bye-free
// week plus playoffs could push it over, and a silently truncated slate is worse than a
// second request.
async function fetchSeriesEvents(seriesTicker, fetchImpl) {
  const events = [];
  let cursor = null;
  do {
    const params = new URLSearchParams({
      series_ticker: seriesTicker,
      status: "open",
      limit: "200",
      with_nested_markets: "true",
    });
    if (cursor) params.set("cursor", cursor);
    const data = await fetchJson(`${KALSHI_BASE}/trade-api/v2/events?${params}`, fetchImpl);
    events.push(...(data.events || []));
    cursor = data.cursor || null;
  } while (cursor);
  return events;
}

async function fetchNflSlate(fetchImpl) {
  const results = await Promise.all(
    NFL_SERIES.map(({ series }) => fetchSeriesEvents(series, fetchImpl))
  );
  const eventsByKind = {};
  NFL_SERIES.forEach(({ kind }, i) => {
    eventsByKind[kind] = results[i];
  });
  return buildGames(eventsByKind);
}

// ── Generic search ────────────────────────────────────────────────────────────

// Kalshi's own full-text search, normalised into the same card shape the NFL path
// produces so one renderer serves both tabs. Its relevance ranking is loose (searching
// "eagles" surfaces KBO and NPB teams too), which is why NFL gets the structured path
// above and this is the catch-all for everything else.
function normalizeSearchItem(item) {
  const nowMs = Date.now();
  const markets = (item.markets || [])
    .filter((m) => {
      if (!m.ticker) return false;
      // No status field on this endpoint; a close time in the past means it's done.
      const closeMs = m.close_ts ? Date.parse(m.close_ts) : NaN;
      return !Number.isFinite(closeMs) || closeMs > nowMs;
    })
    .map((m) => ({
      ticker: m.ticker,
      kind: "generic",
      label: m.yes_subtitle || m.ticker,
      fullLabel: m.yes_subtitle || m.ticker,
      // This endpoint already reports integer cents — do not scale these.
      bid: Number.isFinite(m.yes_bid) ? m.yes_bid : null,
      ask: Number.isFinite(m.yes_ask) ? m.yes_ask : null,
      volume: toNumber(m.volume),
      sortKey: m.ticker,
    }));

  if (!markets.length) return null;
  return {
    suffix: item.event_ticker,
    title: item.event_title || item.series_title || item.event_ticker,
    subtitle: item.event_subtitle || item.series_title || "",
    kickoffMs: null,
    marketCount: markets.length,
    moneyline: markets,
    spread: [],
    total: [],
  };
}

async function genericSearch(query, fetchImpl) {
  const trimmed = String(query || "").trim();
  if (!trimmed) return [];
  const params = new URLSearchParams({ query: trimmed });
  const data = await fetchJson(`${KALSHI_BASE}/v1/search/series?${params}`, fetchImpl);
  return (data.current_page || [])
    .filter((item) => (item.active_market_count || 0) > 0)
    .map(normalizeSearchItem)
    .filter(Boolean);
}

return {
    KALSHI_BASE,
    KICKOFF_SKEW_MS,
    NFL_SERIES,
    TEAM_ALIASES,
    eventSuffix,
    dollarsToCents,
    compactLabel,
    marketSortKey,
    normalizeMarket,
    normalizeMarkets,
    buildGames,
    matchesQuery,
    rankGames,
    nearestToFifty,
    fetchSeriesEvents,
    fetchNflSlate,
    normalizeSearchItem,
    genericSearch,
};
})();

if (typeof module !== "undefined" && module.exports) {
  module.exports = MarketFinder;
}
if (typeof window !== "undefined") {
  window.MarketFinder = MarketFinder;
}
