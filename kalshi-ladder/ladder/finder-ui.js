// Market finder: the search overlay that turns "cowboys" into clickable tickers.
//
// Data logic lives in market-finder.js (pure, unit tested). Panel state — panels,
// loadTickerIntoSlot, nextEmptySlot, setPage — comes from app.js: top-level declarations
// in classic scripts share one global lexical scope, which keeps ladder/ build-free.
//
// Every Kalshi call here is an unauthenticated public read made by the browser. This works
// only because the page is served from http://localhost (Kalshi's WAF 403s the `Origin:
// null` a file:// page sends), and it is deliberate: search never touches the trading
// process, so it cannot contend for the order throttler or block an order click.

(function initMarketFinder() {
const FINDER_SLATE_TTL_MS = 5 * 60 * 1000; // refetch quotes rather than show stale ones
const FINDER_COLLAPSED_COUNT = 6; // strikes shown before "show all" — 24 spreads is unusable
const FINDER_DEBOUNCE_MS = 250; // generic tab only; NFL filtering is local and instant

let finderGames = new Map();
let finderSlateFetchedMs = 0;
let finderSlateError = "";
let finderMode = "nfl";
const finderExpanded = new Set(); // "<suffix>:<kind>" sections the user opened in full
let finderChips = []; // flat, in render order, for arrow-key navigation
let finderHighlight = -1;
let finderDebounceTimer = null;
let finderGenericSeq = 0; // guards against a slow response overwriting a newer one

const finderOverlay = document.getElementById("finder-overlay");
const finderInput = document.getElementById("finder-input");
const finderResults = document.getElementById("finder-results");
const finderStatus = document.getElementById("finder-status");
const finderRefreshBtn = document.getElementById("finder-refresh");
const finderCloseBtn = document.getElementById("finder-close");
const finderTabs = [...document.querySelectorAll(".finder-tab")];
const finderToggleBtn = document.getElementById("finder-toggle");

// If the markup or the data module is missing (an older index.html, a partial deploy),
// leave the ladder exactly as it was rather than throwing on the way up.
if (!finderOverlay || !finderInput || !finderResults || !finderStatus ||
    !finderRefreshBtn || !finderCloseBtn || !finderToggleBtn) {
  console.warn("Market finder: overlay markup not found; search disabled, ladder unaffected.");
  return;
}
if (typeof window.MarketFinder === "undefined") {
  console.warn("Market finder: market-finder.js did not load; search disabled, ladder unaffected.");
  finderToggleBtn.style.display = "none";
  return;
}

const { fetchNflSlate, rankGames, genericSearch, nearestToFifty } = window.MarketFinder;

// ── Open / close ──────────────────────────────────────────────────────────────

function isFinderOpen() {
  return !finderOverlay.classList.contains("hidden");
}

function openFinder() {
  finderOverlay.classList.remove("hidden");
  finderInput.focus();
  finderInput.select();
  if (finderMode === "nfl") {
    ensureSlate(false);
  } else {
    runSearch();
  }
}

function closeFinder() {
  finderOverlay.classList.add("hidden");
  setFinderHighlight(-1);
}

// ── Slate loading ─────────────────────────────────────────────────────────────

// Quotes go stale, so anything older than the TTL is refetched when the finder opens.
async function ensureSlate(force) {
  const fresh = Date.now() - finderSlateFetchedMs < FINDER_SLATE_TTL_MS;
  if (!force && fresh && finderGames.size) {
    runSearch();
    return;
  }

  setFinderStatus("Loading NFL markets…");
  try {
    finderGames = await fetchNflSlate();
    finderSlateFetchedMs = Date.now();
    finderSlateError = "";
  } catch (error) {
    // A failed search must never take the ladder down with it.
    finderSlateError = error && error.message ? error.message : String(error);
    console.error("Market finder: failed to load NFL slate", error);
  }
  runSearch();
}

// ── Search dispatch ───────────────────────────────────────────────────────────

function runSearch() {
  const query = finderInput.value.trim();
  if (finderMode === "nfl") {
    if (finderSlateError) {
      renderCards([], `Could not reach Kalshi: ${finderSlateError}`);
      return;
    }
    const cards = rankGames(finderGames, query);
    renderCards(cards, cards.length ? "" : "No NFL games match that.");
    return;
  }

  if (!query) {
    renderCards([], "Type to search every open Kalshi market.");
    return;
  }
  // Network-bound, so debounce and drop stale responses.
  const seq = ++finderGenericSeq;
  setFinderStatus("Searching…");
  genericSearch(query)
    .then((cards) => {
      if (seq !== finderGenericSeq) return;
      renderCards(cards, cards.length ? "" : "Nothing open matches that.");
    })
    .catch((error) => {
      if (seq !== finderGenericSeq) return;
      console.error("Market finder: search failed", error);
      renderCards([], `Search failed: ${error.message || error}`);
    });
}

function scheduleSearch() {
  if (finderDebounceTimer) clearTimeout(finderDebounceTimer);
  if (finderMode === "nfl") {
    runSearch(); // local filter — no reason to wait
    return;
  }
  finderDebounceTimer = setTimeout(runSearch, FINDER_DEBOUNCE_MS);
}

// ── Rendering ─────────────────────────────────────────────────────────────────

function setFinderStatus(text) {
  finderStatus.textContent = text;
}

// Always Eastern, explicitly labelled: NFL slates are quoted in ET regardless of where
// the machine running the ladder happens to be.
function formatKickoff(ms) {
  if (!Number.isFinite(ms)) return "";
  const text = new Date(ms).toLocaleString("en-US", {
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/New_York",
  });
  return `${text} ET`;
}

function formatQuote(market) {
  const bid = Number.isFinite(market.bid) ? market.bid : null;
  const ask = Number.isFinite(market.ask) ? market.ask : null;
  if (bid === null && ask === null) return "--";
  return `${bid === null ? "--" : bid}/${ask === null ? "--" : ask}`;
}

function loadedTickers() {
  const loaded = new Set();
  for (const panel of panels) {
    if (panel.currentTicker) loaded.add(panel.currentTicker);
  }
  return loaded;
}

function renderCards(cards, emptyMessage) {
  finderResults.innerHTML = "";
  finderChips = [];
  setFinderHighlight(-1);

  const loaded = loadedTickers();
  for (const card of cards) {
    finderResults.appendChild(buildCard(card, loaded));
  }

  if (!cards.length) {
    const empty = document.createElement("div");
    empty.className = "finder-empty";
    empty.textContent = emptyMessage || "No results.";
    finderResults.appendChild(empty);
  }

  const age = finderSlateFetchedMs ? Math.round((Date.now() - finderSlateFetchedMs) / 1000) : null;
  if (finderMode === "nfl" && !finderSlateError) {
    setFinderStatus(
      `${cards.length} game${cards.length === 1 ? "" : "s"}` +
        (age === null ? "" : ` · quotes ${age}s old`)
    );
  } else if (finderMode === "generic") {
    setFinderStatus(`${cards.length} event${cards.length === 1 ? "" : "s"}`);
  } else {
    setFinderStatus("");
  }
}

function buildCard(card, loaded) {
  const section = document.createElement("section");
  section.className = "finder-card";

  const header = document.createElement("header");
  header.className = "finder-card-header";

  const title = document.createElement("span");
  title.className = "finder-card-title";
  title.textContent = card.title || card.suffix;

  const meta = document.createElement("span");
  meta.className = "finder-card-meta";
  const bits = [];
  const kickoff = formatKickoff(card.kickoffMs);
  if (kickoff) bits.push(kickoff);
  else if (card.subtitle) bits.push(card.subtitle);
  bits.push(`${card.marketCount} market${card.marketCount === 1 ? "" : "s"}`);
  meta.textContent = bits.join(" · ");

  header.append(title, meta);
  section.appendChild(header);

  const sections =
    finderMode === "nfl"
      ? [
          ["moneyline", "MONEYLINE"],
          ["spread", "SPREAD"],
          ["total", "TOTAL"],
        ]
      : [["moneyline", ""]];

  for (const [kind, label] of sections) {
    const markets = card[kind] || [];
    if (!markets.length) continue;
    section.appendChild(buildSection(card, kind, label, markets, loaded));
  }

  // Kalshi only lists KXNFLSPREAD/KXNFLTOTAL events for the current week — next week's
  // return 404 outright. Say so, rather than leaving a moneyline-only card looking broken.
  if (finderMode === "nfl" && !card.spread.length && !card.total.length) {
    const note = document.createElement("div");
    note.className = "finder-card-note";
    note.textContent = "Spreads & totals not listed by Kalshi yet — they appear during game week.";
    section.appendChild(note);
  }

  return section;
}

function buildSection(card, kind, label, markets, loaded) {
  const wrap = document.createElement("div");
  wrap.className = "finder-section";

  const key = `${card.suffix}:${kind}`;
  const expanded = finderExpanded.has(key);
  const shown = expanded ? markets : nearestToFifty(markets, FINDER_COLLAPSED_COUNT);

  if (label) {
    const head = document.createElement("div");
    head.className = "finder-section-head";

    const name = document.createElement("span");
    name.className = "finder-section-label";
    name.textContent = markets.length > shown.length || expanded ? `${label} (${markets.length})` : label;
    head.appendChild(name);

    if (markets.length > FINDER_COLLAPSED_COUNT) {
      const toggle = document.createElement("button");
      toggle.className = "finder-expand";
      toggle.type = "button";
      toggle.textContent = expanded ? "show near 50¢ ▴" : "show all ▾";
      toggle.addEventListener("click", () => {
        if (expanded) finderExpanded.delete(key);
        else finderExpanded.add(key);
        runSearch();
      });
      head.appendChild(toggle);
    }
    wrap.appendChild(head);
  }

  const chips = document.createElement("div");
  chips.className = "finder-chips";
  for (const market of shown) {
    chips.appendChild(buildChip(market, loaded));
  }
  wrap.appendChild(chips);
  return wrap;
}

function buildChip(market, loaded) {
  const chip = document.createElement("button");
  chip.className = "finder-chip";
  chip.type = "button";
  // Kalshi-supplied text goes in via textContent/title only — never innerHTML.
  chip.title = `${market.ticker}\n${market.fullLabel}`;

  const label = document.createElement("span");
  label.className = "finder-chip-label";
  label.textContent = market.label;

  const price = document.createElement("span");
  price.className = "finder-chip-price";
  price.textContent = formatQuote(market);

  chip.append(label, price);
  if (loaded.has(market.ticker)) {
    chip.classList.add("loaded");
    chip.title += "\n(already on the ladder)";
  }

  chip.addEventListener("click", () => addMarket(market, chip, price));
  finderChips.push({ element: chip, market, price });
  return chip;
}

// ── Adding to the ladder ──────────────────────────────────────────────────────

// Goes through app.js's shared loader, so this is the exact same set_ticker flow as
// typing the ticker into a panel by hand.
function addMarket(market, chip, priceEl) {
  const slot = nextEmptySlot();
  const panel = loadTickerIntoSlot(slot, market.ticker);
  if (!panel) return;

  // Keep the ladder on the page the market landed on, so closing the finder shows it
  // (and so the next click fills the panel beside it).
  const page = Math.floor(slot / PANELS_PER_PAGE);
  if (page !== currentPage) setPage(page);

  chip.classList.add("loaded");
  const previous = priceEl.textContent;
  priceEl.textContent = `→ #${slot + 1}`;
  chip.classList.add("just-added");
  setTimeout(() => {
    priceEl.textContent = previous;
    chip.classList.remove("just-added");
  }, 1200);
}

// ── Keyboard navigation ───────────────────────────────────────────────────────

function setFinderHighlight(index) {
  if (finderChips[finderHighlight]) {
    finderChips[finderHighlight].element.classList.remove("highlight");
  }
  finderHighlight = index;
  const entry = finderChips[index];
  if (entry) {
    entry.element.classList.add("highlight");
    entry.element.scrollIntoView({ block: "nearest" });
  }
}

function moveFinderHighlight(delta) {
  if (!finderChips.length) return;
  const next = finderHighlight < 0
    ? (delta > 0 ? 0 : finderChips.length - 1)
    : (finderHighlight + delta + finderChips.length) % finderChips.length;
  setFinderHighlight(next);
}

// Capture phase so this runs before app.js's page hotkeys: with the overlay open, a digit
// key must not flip the ladder page behind it.
document.addEventListener(
  "keydown",
  (event) => {
    if (event.key === "Escape" && isFinderOpen()) {
      closeFinder();
      event.stopPropagation();
      return;
    }

    if (isFinderOpen()) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        moveFinderHighlight(event.key === "ArrowDown" ? 1 : -1);
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      if (event.key === "Enter") {
        const entry = finderChips[finderHighlight];
        if (entry) {
          addMarket(entry.market, entry.element, entry.price);
          event.preventDefault();
          event.stopPropagation();
        }
        return;
      }
      if (/^[0-9]$/.test(event.key) && event.target !== finderInput) {
        event.stopPropagation(); // don't page the ladder behind the overlay
      }
      return;
    }

    // Opening shortcuts, guarded the same way app.js guards its page hotkeys.
    const tag = event.target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || event.target.isContentEditable) return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      openFinder();
      event.preventDefault();
      return;
    }
    if (event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey) {
      openFinder();
      event.preventDefault();
    }
  },
  true
);

// ── Wiring ────────────────────────────────────────────────────────────────────

finderInput.addEventListener("input", scheduleSearch);
finderCloseBtn.addEventListener("click", closeFinder);
finderRefreshBtn.addEventListener("click", () => {
  if (finderMode === "nfl") ensureSlate(true);
  else runSearch();
});

for (const tab of finderTabs) {
  tab.addEventListener("click", () => {
    finderMode = tab.dataset.mode;
    for (const other of finderTabs) other.classList.toggle("active", other === tab);
    finderInput.placeholder =
      finderMode === "nfl"
        ? "Search NFL games — team, city, or date…"
        : "Search every open Kalshi market…";
    finderInput.focus();
    if (finderMode === "nfl") ensureSlate(false);
    else runSearch();
  });
}

finderToggleBtn.addEventListener("click", () => {
  if (isFinderOpen()) closeFinder();
  else openFinder();
});

// Click the dimmed backdrop (but not the dialog) to dismiss.
finderOverlay.addEventListener("mousedown", (event) => {
  if (event.target === finderOverlay) closeFinder();
});
})();
