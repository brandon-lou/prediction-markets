const PRICE_MIN = 1;
const PRICE_MAX = 99;
const DEFAULT_SIZE = 10;
const PANEL_COUNT = 45;
const PANELS_PER_PAGE = 5;
const SOCKET_URL = "ws://localhost:8765";
const STALE_THRESHOLD_MS = 30_000; // show STALE badge after 30 s of no updates
const LIBRARY_STORAGE_KEY = "kalshi_ticker_library";

const statusLabel = document.getElementById("status-label");
const marketGrid = document.getElementById("market-grid");
const shardBalanceEl = document.getElementById("shard-balance");

// Latest per-shard collateral (exchange_index -> dollars) and the configured target
// split. Read-only cache the panel badges consult; never touched on the order-send path.
const shardBalances = new Map();
let shardTargets = {};

const panels = [];
let activeSocket = null;
let focusedSlot = 0; // which panel the ticker-library click targets
let currentPage = 0;

// ── WebSocket helpers ─────────────────────────────────────────────────────────

function sendOrder(side, price, count, ticker) {
  if (!activeSocket || activeSocket.readyState !== WebSocket.OPEN) return;
  if (!ticker) return;
  activeSocket.send(JSON.stringify({ type: "post_order", side, price, count, ticker }));
}

function sendCancelAtPrice(side, price, ticker) {
  if (!activeSocket || activeSocket.readyState !== WebSocket.OPEN) return;
  if (!ticker) return;
  activeSocket.send(JSON.stringify({ type: "cancel_orders_at_price", side, price, ticker }));
}

// ticker omitted = every market the server has registered (the panic key).
function sendCancelAll(scope, ticker) {
  if (!activeSocket || activeSocket.readyState !== WebSocket.OPEN) return false;
  const message = { type: "cancel_all", scope };
  if (ticker) message.ticker = ticker;
  activeSocket.send(JSON.stringify(message));
  return true;
}

function sendSetTicker(slot, ticker, force = false) {
  if (!activeSocket || activeSocket.readyState !== WebSocket.OPEN) return;
  activeSocket.send(JSON.stringify({ type: "set_ticker", slot, ticker, force }));
}

// ── Panel construction ────────────────────────────────────────────────────────

function buildPanel(slotIndex) {
  const panel = document.createElement("div");
  panel.className = "market-panel";
  panel.innerHTML = `
    <div class="market-header">
      <input class="title-input" type="text" placeholder="Enter ticker and press Enter" />
      <div class="market-title">--</div>
    </div>
    <div class="ladder">
      <div class="ladder-header">
        <div class="header-left">
          <div class="position-banner">Position: --</div>
          <span class="shard-badge"></span>
          <span class="stale-badge">⚠ STALE</span>
          <button class="reload-btn" title="Force reload">↺</button>
          <button class="cancel-btn" data-scope="bids" title="Cancel my bids (Alt+C)">xB</button>
          <button class="cancel-btn" data-scope="asks" title="Cancel my asks (Alt+Shift+C)">xA</button>
          <button class="cancel-btn strong" data-scope="both" title="Cancel both sides (Alt+X)">X</button>
          <span class="panel-flash"></span>
        </div>
        <div class="controls">
          <label class="control-label">Size per click</label>
          <input class="control-input" type="number" min="1" step="1" value="${DEFAULT_SIZE}" />
        </div>
      </div>
      <div class="body">
        <div class="row header">
          <div class="cell">My Bids</div>
          <div class="cell">Bid Size</div>
          <div class="cell">Price</div>
          <div class="cell">Odds</div>
          <div class="cell">Ask Size</div>
          <div class="cell">My Asks</div>
        </div>
      </div>
    </div>
  `;

  const tickerInput = panel.querySelector(".title-input");
  const sizeInput = panel.querySelector(".control-input");
  const marketTitle = panel.querySelector(".market-title");
  const positionLabel = panel.querySelector(".position-banner");
  const shardBadge = panel.querySelector(".shard-badge");
  const staleBadge = panel.querySelector(".stale-badge");
  const reloadBtn = panel.querySelector(".reload-btn");
  const flashEl = panel.querySelector(".panel-flash");
  const ladderBody = panel.querySelector(".body");

  const rowsByPrice = new Map();
  const state = {
    slot: slotIndex,
    root: panel,
    tickerInput,
    sizeInput,
    positionLabel,
    shardBadge,
    staleBadge,
    reloadBtn,
    flashEl,
    flashTimer: 0,
    marketTitle,
    ladderBody,
    rowsByPrice,
    defaultSize: DEFAULT_SIZE,
    currentTicker: "",
    exchangeIndex: 0,
    lastBestBid: null,
    lastBestAsk: null,
    lastUpdateMs: 0,
    tickerSetMs: 0,
  };

  // Focus tracking — clicking anywhere on the panel marks it as the active target for
  // the ticker library.
  panel.addEventListener("mousedown", () => setFocusedSlot(slotIndex));

  sizeInput.addEventListener("input", () => {
    const nextValue = Number.parseInt(sizeInput.value, 10);
    if (Number.isFinite(nextValue) && nextValue > 0) {
      state.defaultSize = nextValue;
    }
  });

  tickerInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      const nextValue = tickerInput.value.trim().toUpperCase();
      if (nextValue !== state.currentTicker) {
        clearPanel(state);
      }
      state.currentTicker = nextValue;
      state.tickerSetMs = nextValue ? Date.now() : 0;
      sendSetTicker(state.slot, nextValue);
    }
  });

  for (const button of panel.querySelectorAll(".cancel-btn")) {
    button.addEventListener("click", () => requestCancel(state, button.dataset.scope));
  }

  reloadBtn.addEventListener("click", () => {
    if (state.currentTicker) {
      clearPanel(state);
      state.tickerSetMs = Date.now();
      sendSetTicker(state.slot, state.currentTicker, true);
    }
  });

  // Build price rows
  for (let price = PRICE_MAX; price >= PRICE_MIN; price -= 1) {
    const row = document.createElement("div");
    row.className = "row";

    const myBids = document.createElement("div");
    myBids.className = "cell my-bids clickable";

    const bidSize = document.createElement("div");
    bidSize.className = "cell bid-size";

    const priceCell = document.createElement("div");
    priceCell.className = "cell price";
    priceCell.textContent = price.toString();

    const oddsCell = document.createElement("div");
    oddsCell.className = "cell odds";
    oddsCell.textContent = formatAmericanOdds(price);

    const askSize = document.createElement("div");
    askSize.className = "cell ask-size";

    const myAsks = document.createElement("div");
    myAsks.className = "cell my-asks clickable";

    myBids.addEventListener("click", () => sendOrder("buy", price, state.defaultSize, state.currentTicker));
    myAsks.addEventListener("click", () => sendOrder("sell", price, state.defaultSize, state.currentTicker));
    myBids.addEventListener("contextmenu", (e) => { e.preventDefault(); sendCancelAtPrice("buy", price, state.currentTicker); });
    myAsks.addEventListener("contextmenu", (e) => { e.preventDefault(); sendCancelAtPrice("sell", price, state.currentTicker); });

    row.append(myBids, bidSize, priceCell, oddsCell, askSize, myAsks);
    ladderBody.appendChild(row);
    rowsByPrice.set(price, { row, myBids, bidSize, askSize, myAsks });
  }

  return state;
}

// ── Focused-slot tracking ─────────────────────────────────────────────────────

function setFocusedSlot(slot) {
  focusedSlot = slot;
  for (const p of panels) {
    p.root.classList.toggle("focused", p.slot === slot);
  }
}

// ── Loading a ticker into a panel ─────────────────────────────────────────────

// The one path for putting a ticker in a panel, shared by the ticker library and the
// market finder. Keep it shared: tickerSetMs is what the stale sweep uses to tell "bad
// ticker, never loaded" from "was live, then froze", so a copy of this sequence that
// forgets to stamp it would break the NO DATA badge without any visible error.
function loadTickerIntoSlot(slot, ticker) {
  const panel = panels[slot];
  if (!panel) return null;
  if (panel.currentTicker !== ticker) clearPanel(panel);
  panel.currentTicker = ticker;
  panel.tickerInput.value = ticker;
  panel.tickerSetMs = ticker ? Date.now() : 0;
  sendSetTicker(panel.slot, ticker);
  return panel;
}

// First free panel, preferring the page the user is currently looking at so a click lands
// somewhere they can see. Falls back to the focused panel once every panel is occupied.
function nextEmptySlot() {
  const pageStart = currentPage * PANELS_PER_PAGE;
  const pageEnd = Math.min(pageStart + PANELS_PER_PAGE, panels.length);
  for (let i = pageStart; i < pageEnd; i += 1) {
    if (!panels[i].currentTicker) return i;
  }
  for (let i = 0; i < panels.length; i += 1) {
    if (!panels[i].currentTicker) return i;
  }
  return focusedSlot;
}

// ── Ladder update ─────────────────────────────────────────────────────────────

function toMap(levels) {
  const map = new Map();
  if (!levels) return map;
  if (Array.isArray(levels)) {
    for (const [price, size] of levels) map.set(Number(price), Number(size));
    return map;
  }
  for (const [price, size] of Object.entries(levels)) map.set(Number(price), Number(size));
  return map;
}

function formatSize(value) {
  if (!value || value === 0) return "";
  if (Number.isInteger(value)) return value.toString();
  return parseFloat(value.toFixed(2)).toString();
}

function formatAmericanOdds(price) {
  const probability = price / 100;
  if (probability <= 0 || probability >= 1) return "";
  if (probability >= 0.5) {
    return `-${Math.round((100 * probability) / (1 - probability))}`;
  }
  return `+${Math.round((100 * (1 - probability)) / probability)}`;
}

// ── Shard balance ─────────────────────────────────────────────────────────────

function formatUsd(value) {
  if (value == null || !Number.isFinite(value)) return "$--";
  return "$" + value.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

// Renders the header strip and refreshes every panel's shard badge. Runs only when
// a "balance" message arrives (~every 10s) — nowhere near the order-send path.
function renderShardBalance(payload) {
  const breakdown = Array.isArray(payload.breakdown) ? payload.breakdown : [];
  shardTargets = payload.targets || {};

  shardBalances.clear();
  for (const item of breakdown) {
    shardBalances.set(Number(item.exchange_index), Number(item.balance) || 0);
  }

  // Show every shard that has funds or a configured target, even if Kalshi omitted
  // a zero-balance targeted shard from the breakdown.
  const indices = new Set(breakdown.map((i) => Number(i.exchange_index)));
  for (const k of Object.keys(shardTargets)) indices.add(Number(k));
  const sorted = [...indices].sort((a, b) => a - b);

  const total =
    typeof payload.total === "number"
      ? payload.total
      : sorted.reduce((sum, idx) => sum + (shardBalances.get(idx) || 0), 0);

  const parts = sorted.map((idx) => {
    const bal = shardBalances.get(idx) || 0;
    const targetPct = shardTargets[String(idx)];
    const actualPct = total > 0 ? Math.round((bal / total) * 100) : 0;
    let cls = "shard-item";
    let targetTxt = "";
    if (targetPct != null) {
      targetTxt = ` ${actualPct}/${targetPct}%`;
      if (Math.abs(actualPct - targetPct) > 10) cls += " drift";
    }
    return `<span class="${cls}">S${idx} ${formatUsd(bal)}${targetTxt}</span>`;
  });
  parts.push(`<span class="shard-total">&Sigma; ${formatUsd(total)}</span>`);
  shardBalanceEl.innerHTML = parts.join('<span class="shard-sep">·</span>');

  for (const panel of panels) updateShardBadge(panel);
}

// Per-panel "is this market's shard funded for my click size?" indicator. Pure
// read from the cached map — no network, no work on the trade path.
function updateShardBadge(panel) {
  const badge = panel.shardBadge;
  if (!badge) return;
  const idx = panel.exchangeIndex || 0;

  if (!panel.currentTicker || idx === 0) {
    badge.style.display = "none";
    badge.className = "shard-badge";
    badge.title = "";
    return;
  }

  const bal = shardBalances.has(idx) ? shardBalances.get(idx) : null;
  // Contracts cost < $1 each, so one click needs at most ~$defaultSize of collateral.
  const need = Math.max(1, panel.defaultSize || DEFAULT_SIZE);

  let level = "ok";
  let mark = "●";
  if (bal == null) {
    level = "unknown";
    mark = "○";
  } else if (bal < need) {
    level = "bad";
  } else if (bal < need * 5) {
    level = "warn";
  }

  badge.textContent = `S${idx} ${mark}`;
  badge.className = `shard-badge ${level}`;
  badge.style.display = "inline-block";
  badge.title =
    bal == null
      ? `Shard ${idx}: collateral unknown`
      : `Shard ${idx}: ${formatUsd(bal)} collateral`;
}

function clearPanel(panel) {
  panel.positionLabel.textContent = "Position: --";
  panel.marketTitle.textContent = "--";
  panel.exchangeIndex = 0;
  if (panel.shardBadge) {
    panel.shardBadge.style.display = "none";
    panel.shardBadge.className = "shard-badge";
    panel.shardBadge.title = "";
  }
  panel.lastBestBid = null;
  panel.lastBestAsk = null;
  panel.lastUpdateMs = 0;
  panel.tickerSetMs = 0;
  panel.staleBadge.textContent = "⚠ STALE";
  panel.staleBadge.classList.remove("visible");
  for (const entry of panel.rowsByPrice.values()) {
    entry.bidSize.textContent = "";
    entry.askSize.textContent = "";
    entry.myBids.textContent = "";
    entry.myAsks.textContent = "";
    entry.row.classList.remove("best-bid", "best-ask");
  }
}

function applyOrderbookToPanel(panel, payload) {
  // Mark update time and clear stale badge
  panel.lastUpdateMs = Date.now();
  panel.staleBadge.classList.remove("visible");

  if (typeof payload.position === "number") {
    const posDisplay = Number.isInteger(payload.position)
      ? payload.position
      : parseFloat(payload.position.toFixed(2));
    panel.positionLabel.textContent = `Position: ${posDisplay}`;
  } else if (payload.position_description) {
    const m = payload.position_description.match(/-?\d+\.?\d*/);
    panel.positionLabel.textContent = `Position: ${m ? m[0] : "--"}`;
  }

  if (payload.market_title) {
    panel.marketTitle.textContent = payload.market_title;
  } else {
    panel.marketTitle.textContent = "--";
  }

  if (typeof payload.exchange_index === "number") {
    panel.exchangeIndex = payload.exchange_index;
  }
  updateShardBadge(panel);

  const bids = toMap(payload.bids);
  const asks = toMap(payload.asks);
  const myBids = toMap(payload.my_bids);
  const myAsks = toMap(payload.my_asks);

  if (panel.lastBestBid !== null) {
    const prev = panel.rowsByPrice.get(panel.lastBestBid);
    if (prev) prev.row.classList.remove("best-bid");
  }
  if (panel.lastBestAsk !== null) {
    const prev = panel.rowsByPrice.get(panel.lastBestAsk);
    if (prev) prev.row.classList.remove("best-ask");
  }

  const bestBid = payload.best_bid;
  const bestAsk = payload.best_ask;
  panel.lastBestBid = Number.isFinite(bestBid) ? bestBid : null;
  panel.lastBestAsk = Number.isFinite(bestAsk) ? bestAsk : null;

  if (panel.lastBestBid !== null) {
    const r = panel.rowsByPrice.get(panel.lastBestBid);
    if (r) r.row.classList.add("best-bid");
  }
  if (panel.lastBestAsk !== null) {
    const r = panel.rowsByPrice.get(panel.lastBestAsk);
    if (r) r.row.classList.add("best-ask");
  }

  for (let price = PRICE_MAX; price >= PRICE_MIN; price -= 1) {
    const entry = panel.rowsByPrice.get(price);
    if (!entry) continue;
    entry.bidSize.textContent = formatSize(bids.get(price) || 0);
    entry.askSize.textContent = formatSize(asks.get(price) || 0);
    entry.myBids.textContent = formatSize(myBids.get(price) || 0);
    entry.myAsks.textContent = formatSize(myAsks.get(price) || 0);
  }
}

function updateLadder(payload) {
  if (payload.type !== "orderbook") return;
  const ticker = payload.ticker || "";
  if (!ticker) return;

  let targetPanels = panelsMatchingTicker(panels, ticker);
  if (!targetPanels.length) {
    const panel = panels.find((e) => !e.currentTicker);
    if (panel) {
      panel.currentTicker = ticker;
      if (document.activeElement !== panel.tickerInput) {
        panel.tickerInput.value = ticker;
      }
      targetPanels = [panel];
    }
  }
  if (!targetPanels.length) return;

  for (const panel of targetPanels) {
    applyOrderbookToPanel(panel, payload);
  }
}

// ── Stale / no-data detection ─────────────────────────────────────────────────
// tickerSetMs tracks when the ticker was last submitted so we can distinguish
// "never loaded" (bad ticker / server error) from "was working, then froze".

setInterval(() => {
  const now = Date.now();
  for (const panel of panels) {
    if (!panel.currentTicker) {
      panel.staleBadge.classList.remove("visible");
      continue;
    }
    if (panel.lastUpdateMs === 0) {
      // Ticker was set but no update ever arrived — flag after 10 s
      const waitMs = panel.tickerSetMs ? now - panel.tickerSetMs : 0;
      if (waitMs > 10_000) {
        panel.staleBadge.textContent = "⚠ NO DATA";
        panel.staleBadge.classList.add("visible");
      }
    } else {
      const isStale = now - panel.lastUpdateMs > STALE_THRESHOLD_MS;
      if (isStale) {
        panel.staleBadge.textContent = "⚠ STALE";
      }
      panel.staleBadge.classList.toggle("visible", isStale);
    }
  }
}, 5000);

// ── WebSocket connection ──────────────────────────────────────────────────────

function setStatus(connected) {
  statusLabel.textContent = connected ? "Connected" : "Disconnected";
  statusLabel.classList.toggle("connected", connected);
}

function connect() {
  const socket = new WebSocket(SOCKET_URL);

  socket.addEventListener("open", () => {
    activeSocket = socket;
    setStatus(true);
  });

  socket.addEventListener("close", () => {
    if (activeSocket === socket) activeSocket = null;
    setStatus(false);
    setTimeout(connect, 1500);
  });

  socket.addEventListener("error", () => {
    if (activeSocket === socket) activeSocket = null;
    setStatus(false);
  });

  socket.addEventListener("message", (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (payload.type === "balance") {
        renderShardBalance(payload);
      } else {
        updateLadder(payload);
      }
    } catch (error) {
      console.error("Failed to parse ladder update", error);
    }
  });
}

// ── Ticker library ────────────────────────────────────────────────────────────

function loadLibrary() {
  try {
    return JSON.parse(localStorage.getItem(LIBRARY_STORAGE_KEY) || "[]");
  } catch {
    return [];
  }
}

function saveLibrary(tickers) {
  localStorage.setItem(LIBRARY_STORAGE_KEY, JSON.stringify(tickers));
}

function renderLibrary() {
  const tickers = loadLibrary();
  const container = document.getElementById("library-chips");
  container.innerHTML = "";
  for (const ticker of tickers) {
    const chip = document.createElement("span");
    chip.className = "ticker-chip";
    chip.innerHTML = `${ticker}<span class="chip-remove" data-ticker="${ticker}">×</span>`;

    chip.addEventListener("click", (e) => {
      if (e.target.classList.contains("chip-remove")) return;
      loadTickerIntoSlot(focusedSlot, ticker);
    });

    chip.querySelector(".chip-remove").addEventListener("click", () => {
      const current = loadLibrary().filter((t) => t !== ticker);
      saveLibrary(current);
      renderLibrary();
    });

    container.appendChild(chip);
  }
}

function setLibraryVisible(visible) {
  const lib = document.getElementById("ticker-library");
  const btn = document.getElementById("library-toggle");
  lib.classList.toggle("hidden", !visible);
  btn.textContent = visible ? "Hide Library" : "Ticker Library";
  localStorage.setItem("kalshi_library_open", visible ? "1" : "0");
}

document.getElementById("library-toggle").addEventListener("click", () => {
  const lib = document.getElementById("ticker-library");
  setLibraryVisible(lib.classList.contains("hidden"));
});

document.getElementById("library-input").addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  const val = e.target.value.trim().toUpperCase();
  if (!val) return;
  const current = loadLibrary();
  if (!current.includes(val)) {
    current.push(val);
    saveLibrary(current);
    renderLibrary();
  }
  e.target.value = "";
});

document.getElementById("library-clear").addEventListener("click", () => {
  saveLibrary([]);
  renderLibrary();
});

// ── Page groups ───────────────────────────────────────────────────────────────

function setPage(page) {
  currentPage = page;
  for (let i = 0; i < panels.length; i += 1) {
    const onThisPage = Math.floor(i / PANELS_PER_PAGE) === page;
    panels[i].root.classList.toggle("page-hidden", !onThisPage);
  }
  setFocusedSlot(page * PANELS_PER_PAGE);
  document.querySelectorAll(".page-btn").forEach((btn, i) => {
    btn.classList.toggle("active", i === page);
  });
}

function buildPageSwitcher() {
  const totalPages = Math.ceil(PANEL_COUNT / PANELS_PER_PAGE);
  if (totalPages <= 1) return;
  const switcher = document.getElementById("page-switcher");
  for (let i = 0; i < totalPages; i += 1) {
    const btn = document.createElement("button");
    btn.className = "page-btn";
    btn.textContent = `Page ${i + 1}`;
    btn.addEventListener("click", () => setPage(i));
    switcher.appendChild(btn);
  }
}

// ── Hotkeys ───────────────────────────────────────────────────────────────────
// Bindings and the rules that gate an order live in hotkeys.js (pure, unit tested).
// This layer is DOM only: read the focused panel, dispatch the intent, show feedback.

const HK = window.LadderHotkeys || null;
if (!HK) {
  console.warn("hotkeys.js did not load; keybinds disabled, mouse trading unaffected.");
}

const PANIC_CONFIRM_MS = 3000; // window for the second Alt+Shift+X press
let panicArmedUntil = 0;
let globalNoticeTimer = 0;

function isOverlayOpen(id) {
  const el = document.getElementById(id);
  return !!el && !el.classList.contains("hidden");
}

// Transient line in a panel header. Keyboard trading gives no other confirmation that
// an order actually went out, and silence after a keystroke is indistinguishable from
// a blocked one.
function flashPanelStatus(panel, text, tone) {
  if (!panel || !panel.flashEl) return;
  panel.flashEl.textContent = text;
  panel.flashEl.className = `panel-flash visible ${tone || "info"}`;
  clearTimeout(panel.flashTimer);
  panel.flashTimer = setTimeout(() => {
    panel.flashEl.className = "panel-flash";
    panel.flashEl.textContent = "";
  }, 2200);
}

function setGlobalNotice(text, tone) {
  const el = document.getElementById("global-notice");
  if (!el) return;
  el.textContent = text;
  el.className = `global-notice ${tone || "info"}${text ? " visible" : ""}`;
  clearTimeout(globalNoticeTimer);
  if (text) {
    globalNoticeTimer = setTimeout(() => setGlobalNotice("", ""), PANIC_CONFIRM_MS);
  }
}

// Focus a slot on any page, switching page first — setPage resets the focused slot to
// the start of the page, so the order here matters.
function focusSlot(slot) {
  const page = Math.floor(slot / PANELS_PER_PAGE);
  if (page !== currentPage) setPage(page);
  setFocusedSlot(slot);
}

function applyOrderIntent(panel, intent) {
  const resolved = HK.resolveOrder(panel, intent, Date.now(), STALE_THRESHOLD_MS);
  if (resolved.error) {
    flashPanelStatus(panel, `⚠ ${HK.ORDER_ERROR_TEXT[resolved.error] || resolved.error}`, "warn");
    return;
  }
  sendOrder(resolved.side, resolved.price, resolved.count, panel.currentTicker);
  flashPanelStatus(
    panel,
    `${resolved.side === "buy" ? "BUY" : "SELL"} ${resolved.count} @ ${resolved.price}` +
      (intent.aggressive ? " ⚡" : ""),
    resolved.side === "buy" ? "buy" : "sell"
  );
}

function applySizeIntent(panel, direction) {
  if (!panel) return;
  const next = HK.stepSize(panel.defaultSize, direction);
  panel.defaultSize = next;
  panel.sizeInput.value = String(next); // keep the box and the click size in step
  updateShardBadge(panel); // badge thresholds are derived from defaultSize
  flashPanelStatus(panel, `Size ${next}`, "info");
}

function requestCancel(panel, scope) {
  if (!panel || !panel.currentTicker) {
    flashPanelStatus(panel, "⚠ no market", "warn");
    return;
  }
  if (!sendCancelAll(scope, panel.currentTicker)) {
    flashPanelStatus(panel, "⚠ disconnected", "warn");
    return;
  }
  const label = scope === "bids" ? "bids" : scope === "asks" ? "asks" : "all";
  flashPanelStatus(panel, `CXL ${label}`, "info");
}

// Two presses within PANIC_CONFIRM_MS. Deliberately not a modal: in a scramble a dialog
// is one more thing to find with the mouse.
function requestGlobalCancel() {
  const now = Date.now();
  if (now < panicArmedUntil) {
    panicArmedUntil = 0;
    if (sendCancelAll("both", null)) setGlobalNotice("Cancelling ALL resting orders…", "warn");
    else setGlobalNotice("Disconnected — nothing sent", "warn");
    return;
  }
  panicArmedUntil = now + PANIC_CONFIRM_MS;
  setGlobalNotice("Press Alt+Shift+X again to cancel ALL orders", "warn");
}

function handleHotkey(event) {
  if (!HK) return;
  const tag = event.target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || event.target.isContentEditable) return;

  // Accept either: the rest of the keymap matches on code, and a synthetic event that
  // only carries one of the two should still close the sheet.
  if ((event.key === "Escape" || event.code === "Escape") && isOverlayOpen("keys-overlay")) {
    closeKeysOverlay();
    return;
  }

  const intent = HK.parseHotkey(event);
  if (!intent) return;

  const finderOpen = isOverlayOpen("finder-overlay");
  if (intent.kind === "help") {
    if (finderOpen) return;
    event.preventDefault();
    toggleKeysOverlay();
    return;
  }

  // Nothing else fires behind a dialog — an order key must not reach the ladder while
  // the finder or the cheat sheet is covering it.
  if (finderOpen || isOverlayOpen("keys-overlay")) return;

  const panel = panels[focusedSlot];

  switch (intent.kind) {
    case "page": {
      const totalPages = Math.ceil(PANEL_COUNT / PANELS_PER_PAGE);
      if (intent.index < totalPages) setPage(intent.index);
      return;
    }
    case "focus":
      event.preventDefault();
      focusSlot(HK.nextSlot(focusedSlot, intent.delta, panels.length));
      return;
    case "focusPanel": {
      const slot = HK.slotOnPage(currentPage, intent.index, PANELS_PER_PAGE, panels.length);
      if (slot !== null) setFocusedSlot(slot);
      return;
    }
    case "size":
      event.preventDefault();
      applySizeIntent(panel, intent.direction);
      return;
    case "order":
      event.preventDefault();
      applyOrderIntent(panel, intent);
      return;
    case "cancel":
      event.preventDefault();
      if (intent.global) requestGlobalCancel();
      else requestCancel(panel, intent.scope);
      return;
    default:
  }
}

document.addEventListener("keydown", handleHotkey);

// ── Keyboard cheat sheet ──────────────────────────────────────────────────────
// Rendered from the same KEYMAP that dispatches the keys, so it cannot drift.

function renderKeysOverlay() {
  const body = document.getElementById("keys-body");
  if (!HK || !body || body.childElementCount) return; // build once
  const groups = [];
  for (const row of HK.buildKeymapRows()) {
    let group = groups.find((g) => g.group === row.group);
    if (!group) {
      group = { group: row.group, groupLabel: row.groupLabel, rows: [] };
      groups.push(group);
    }
    group.rows.push(row);
  }

  for (const group of groups) {
    const section = document.createElement("section");
    section.className = "keys-group";

    const heading = document.createElement("div");
    heading.className = "keys-group-head";
    const name = document.createElement("span");
    name.className = "keys-group-label";
    name.textContent = group.groupLabel;
    heading.appendChild(name);
    if (HK.GROUP_NOTES[group.group]) {
      const note = document.createElement("span");
      note.className = "keys-group-note";
      note.textContent = HK.GROUP_NOTES[group.group];
      heading.appendChild(note);
    }
    section.appendChild(heading);

    for (const row of group.rows) {
      const line = document.createElement("div");
      line.className = `keys-row${row.danger ? " danger" : ""}`;

      const binding = document.createElement("kbd");
      binding.className = "keys-binding";
      binding.textContent = row.binding;

      const label = document.createElement("span");
      label.className = "keys-label";
      label.textContent = row.label;

      line.append(binding, label);
      if (row.note) {
        const note = document.createElement("span");
        note.className = "keys-note";
        note.textContent = row.note;
        line.appendChild(note);
      }
      section.appendChild(line);
    }
    body.appendChild(section);
  }
}

function openKeysOverlay() {
  renderKeysOverlay();
  document.getElementById("keys-overlay").classList.remove("hidden");
}

function closeKeysOverlay() {
  document.getElementById("keys-overlay").classList.add("hidden");
}

function toggleKeysOverlay() {
  if (isOverlayOpen("keys-overlay")) closeKeysOverlay();
  else openKeysOverlay();
}

document.getElementById("keys-toggle").addEventListener("click", toggleKeysOverlay);
document.getElementById("keys-close").addEventListener("click", closeKeysOverlay);
document.getElementById("keys-overlay").addEventListener("mousedown", (event) => {
  if (event.target.id === "keys-overlay") closeKeysOverlay();
});

// ── Init ──────────────────────────────────────────────────────────────────────

for (let i = 0; i < PANEL_COUNT; i += 1) {
  const panel = buildPanel(i);
  panels.push(panel);
  marketGrid.appendChild(panel.root);
}

buildPageSwitcher();
setPage(0);
renderLibrary();

// Restore library open/closed state (default: open)
const libPref = localStorage.getItem("kalshi_library_open");
setLibraryVisible(libPref !== "0");

connect();
