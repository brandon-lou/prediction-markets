// Keyboard trading logic: the binding table, the size ladder, and the rules that decide
// whether a keystroke is allowed to become an order. No DOM access, so `node --test` can
// reach all of it (see ladder/tests/) the same way panel-router.js is tested.
//
// KEYMAP is the single source of truth. Both parseHotkey (what a keystroke does) and
// buildKeymapRows (what the ? overlay shows) are derived from it, so a binding cannot be
// documented wrongly or silently left undocumented — tests assert the two agree.

const LadderHotkeys = (function buildLadderHotkeys() {
// Size ladder for the ↑/↓ keys. Multiplicative-ish so a few taps cross an order of
// magnitude, instead of the 48 taps a fixed +5 step would need to get from 10 to 250.
const SIZE_PRESETS = [1, 5, 10, 25, 50, 100, 250, 500, 1000];

const PANELS_PER_PAGE_DEFAULT = 5;

// Panel-jump keys, left hand on the top row. Deliberately not the home row: `s` there
// would sit next to the sell binding.
const PANEL_JUMP_CODES = ["KeyQ", "KeyW", "KeyE", "KeyR", "KeyT"];

function pageEntries() {
  const entries = [];
  for (let i = 1; i <= 9; i += 1) {
    entries.push({
      group: "navigation",
      code: `Digit${i}`,
      alt: false,
      shift: false,
      label: "Switch page",
      intent: { kind: "page", index: i - 1 },
      rowKey: "page",
      displayBinding: "1 – 9",
    });
  }
  return entries;
}

function panelJumpEntries() {
  return PANEL_JUMP_CODES.map((code, i) => ({
    group: "navigation",
    code,
    alt: false,
    shift: false,
    label: "Focus panel 1–5 of this page",
    intent: { kind: "focusPanel", index: i },
    rowKey: "focusPanel",
    displayBinding: "Q W E R T",
  }));
}

const KEYMAP = [
  // ── Navigation ──────────────────────────────────────────────────────────────
  ...pageEntries(),
  {
    group: "navigation",
    code: "ArrowLeft",
    alt: false,
    shift: false,
    label: "Focus previous / next panel",
    intent: { kind: "focus", delta: -1 },
    rowKey: "focus",
    displayBinding: "← / →",
  },
  {
    group: "navigation",
    code: "ArrowRight",
    alt: false,
    shift: false,
    label: "Focus previous / next panel",
    intent: { kind: "focus", delta: 1 },
    rowKey: "focus",
  },
  ...panelJumpEntries(),

  // ── Size ────────────────────────────────────────────────────────────────────
  {
    group: "size",
    code: "ArrowUp",
    alt: false,
    shift: false,
    label: "Step size up / down",
    intent: { kind: "size", direction: 1 },
    rowKey: "size",
    displayBinding: "↑ / ↓",
  },
  {
    group: "size",
    code: "ArrowDown",
    alt: false,
    shift: false,
    label: "Step size up / down",
    intent: { kind: "size", direction: -1 },
    rowKey: "size",
  },
  {
    group: "size",
    code: "ArrowUp",
    alt: false,
    shift: true,
    label: "Jump to largest / smallest size",
    intent: { kind: "size", direction: "max" },
    rowKey: "sizeJump",
    displayBinding: "Shift + ↑ / ↓",
  },
  {
    group: "size",
    code: "ArrowDown",
    alt: false,
    shift: true,
    label: "Jump to largest / smallest size",
    intent: { kind: "size", direction: "min" },
    rowKey: "sizeJump",
  },

  // ── Orders ──────────────────────────────────────────────────────────────────
  {
    group: "orders",
    code: "KeyB",
    alt: true,
    shift: false,
    label: "Buy — join the best bid",
    intent: { kind: "order", side: "buy", aggressive: false },
  },
  {
    group: "orders",
    code: "KeyS",
    alt: true,
    shift: false,
    label: "Sell — join the best ask",
    intent: { kind: "order", side: "sell", aggressive: false },
  },
  {
    group: "orders",
    code: "KeyB",
    alt: true,
    shift: true,
    label: "Buy at the best ask",
    intent: { kind: "order", side: "buy", aggressive: true },
    danger: true,
    note: "crosses — fills immediately",
  },
  {
    group: "orders",
    code: "KeyS",
    alt: true,
    shift: true,
    label: "Sell at the best bid",
    intent: { kind: "order", side: "sell", aggressive: true },
    danger: true,
    note: "crosses — fills immediately",
  },

  // ── Cancel ──────────────────────────────────────────────────────────────────
  {
    group: "cancel",
    code: "KeyC",
    alt: true,
    shift: false,
    label: "Cancel my bids on this market",
    intent: { kind: "cancel", scope: "bids", global: false },
  },
  {
    group: "cancel",
    code: "KeyC",
    alt: true,
    shift: true,
    label: "Cancel my asks on this market",
    intent: { kind: "cancel", scope: "asks", global: false },
  },
  {
    group: "cancel",
    code: "KeyX",
    alt: true,
    shift: false,
    label: "Cancel both sides on this market",
    intent: { kind: "cancel", scope: "both", global: false },
  },
  {
    group: "cancel",
    code: "KeyX",
    alt: true,
    shift: true,
    label: "Cancel everything, every market",
    intent: { kind: "cancel", scope: "both", global: true },
    danger: true,
    note: "press twice within 3s",
  },

  // ── Help ────────────────────────────────────────────────────────────────────
  {
    group: "help",
    code: "Slash",
    alt: false,
    shift: true,
    label: "Show this list",
    intent: { kind: "help" },
    displayBinding: "?",
  },
];

const GROUP_LABELS = {
  navigation: "Navigation",
  size: "Size",
  orders: "Orders",
  cancel: "Cancel",
  help: "Help",
};

const GROUP_NOTES = {
  size: "changes nothing on the exchange",
  orders: "Alt rests in the queue · Alt+Shift crosses the spread",
  cancel: "acts on the focused panel unless noted",
};

// ── Binding lookup ────────────────────────────────────────────────────────────

function bindingKey(code, alt, shift) {
  return `${code}|${alt ? 1 : 0}|${shift ? 1 : 0}`;
}

// Built once. A duplicate here would mean one binding silently shadowing another, which
// a test checks for explicitly.
const BINDING_INDEX = new Map();
for (const entry of KEYMAP) {
  BINDING_INDEX.set(bindingKey(entry.code, entry.alt, entry.shift), entry);
}

// Keys off event.code, never event.key: on macOS Alt+B emits "∫" and Alt+S emits "ß", so
// matching on key would break every order binding on the machine this runs on.
function parseHotkey(event) {
  if (!event || typeof event.code !== "string") return null;
  // Leave browser and OS chords alone (Cmd+R, Ctrl+W, …).
  if (event.ctrlKey || event.metaKey) return null;
  const entry = BINDING_INDEX.get(bindingKey(event.code, !!event.altKey, !!event.shiftKey));
  return entry ? entry.intent : null;
}

// ── Display ───────────────────────────────────────────────────────────────────

const KEY_NAMES = {
  ArrowLeft: "←",
  ArrowRight: "→",
  ArrowUp: "↑",
  ArrowDown: "↓",
  Slash: "/",
};

function keyName(code) {
  if (KEY_NAMES[code]) return KEY_NAMES[code];
  if (code.startsWith("Key")) return code.slice(3);
  if (code.startsWith("Digit")) return code.slice(5);
  return code;
}

function formatBinding(entry) {
  if (entry.displayBinding) return entry.displayBinding;
  const parts = [];
  if (entry.alt) parts.push("Alt");
  if (entry.shift) parts.push("Shift");
  parts.push(keyName(entry.code));
  return parts.join(" + ");
}

// The row an entry collapses into. Entries sharing a rowKey share a row.
function rowKeyFor(entry) {
  return entry.rowKey || bindingKey(entry.code, entry.alt, entry.shift);
}

// One row per user-visible binding. Entries sharing a rowKey (the nine page digits, the
// two focus arrows) collapse into a single row so the overlay reads as a cheat sheet
// rather than a dump of every keycode.
function buildKeymapRows() {
  const rows = [];
  const seen = new Set();
  for (const entry of KEYMAP) {
    const key = rowKeyFor(entry);
    if (seen.has(key)) continue;
    seen.add(key);
    rows.push({
      key,
      group: entry.group,
      groupLabel: GROUP_LABELS[entry.group] || entry.group,
      binding: formatBinding(entry),
      label: entry.label,
      danger: !!entry.danger,
      note: entry.note || "",
    });
  }
  return rows;
}

// ── Size stepping ─────────────────────────────────────────────────────────────

// direction: 1 | -1 | "max" | "min". A hand-typed size that isn't a preset (37) snaps to
// the neighbouring preset in the direction of travel rather than restarting the ladder.
function stepSize(current, direction) {
  if (direction === "max") return SIZE_PRESETS[SIZE_PRESETS.length - 1];
  if (direction === "min") return SIZE_PRESETS[0];

  const value = Number.isFinite(current) ? current : SIZE_PRESETS[0];
  if (direction > 0) {
    const next = SIZE_PRESETS.find((p) => p > value);
    return next === undefined ? SIZE_PRESETS[SIZE_PRESETS.length - 1] : next;
  }
  const lower = SIZE_PRESETS.filter((p) => p < value);
  return lower.length ? lower[lower.length - 1] : SIZE_PRESETS[0];
}

// ── Order resolution ──────────────────────────────────────────────────────────

// Every precondition that stands between a keystroke and a live order lives here, so the
// guards are one testable function rather than scattered through the key handler.
//
// Returns {side, price, count} or {error}. Error codes: no-ticker, stale, no-bid, no-ask,
// bad-price, bad-size.
function resolveOrder(panel, intent, nowMs, staleThresholdMs) {
  if (!panel || !panel.currentTicker) return { error: "no-ticker" };

  // lastUpdateMs === 0 means the panel has never received a book — a ticker that failed
  // to load looks identical to one that loaded fine until you check this.
  if (!panel.lastUpdateMs) return { error: "stale" };
  if (Number.isFinite(staleThresholdMs) && nowMs - panel.lastUpdateMs > staleThresholdMs) {
    return { error: "stale" };
  }

  const side = intent.side;
  if (side !== "buy" && side !== "sell") return { error: "bad-price" };

  // buy passive → bid, buy aggressive → ask; sell is the mirror.
  const usesAsk = (side === "buy") === !!intent.aggressive;
  const price = usesAsk ? panel.lastBestAsk : panel.lastBestBid;

  // get_ladder_snapshot reports best_bid 0 when there are no bids and best_ask 100 when
  // there are no asks. Without these two checks, Alt+B into an empty book posts a buy at
  // 0¢ and Alt+S posts a sell at 100¢.
  if (!Number.isFinite(price)) return { error: usesAsk ? "no-ask" : "no-bid" };
  if (usesAsk && price >= 100) return { error: "no-ask" };
  if (!usesAsk && price <= 0) return { error: "no-bid" };
  if (!Number.isInteger(price) || price < 1 || price > 99) return { error: "bad-price" };

  const count = panel.defaultSize;
  if (!Number.isInteger(count) || count <= 0) return { error: "bad-size" };

  return { side, price, count };
}

const ORDER_ERROR_TEXT = {
  "no-ticker": "no market",
  stale: "stale book",
  "no-bid": "no bid",
  "no-ask": "no ask",
  "bad-price": "bad price",
  "bad-size": "bad size",
};

// ── Focus movement ────────────────────────────────────────────────────────────

// Wraps, so → off the end of page 9 lands back on panel 1 of page 1.
function nextSlot(current, delta, panelCount) {
  if (!Number.isInteger(panelCount) || panelCount <= 0) return 0;
  return (((current + delta) % panelCount) + panelCount) % panelCount;
}

// Panel N of whichever page is showing.
function slotOnPage(page, index, panelsPerPage, panelCount) {
  const perPage = panelsPerPage || PANELS_PER_PAGE_DEFAULT;
  const slot = page * perPage + index;
  return slot < panelCount ? slot : null;
}

return {
    KEYMAP,
    SIZE_PRESETS,
    GROUP_LABELS,
    GROUP_NOTES,
    ORDER_ERROR_TEXT,
    parseHotkey,
    formatBinding,
    buildKeymapRows,
    rowKeyFor,
    stepSize,
    resolveOrder,
    nextSlot,
    slotOnPage,
};
})();

if (typeof module !== "undefined" && module.exports) {
  module.exports = LadderHotkeys;
}
if (typeof window !== "undefined") {
  window.LadderHotkeys = LadderHotkeys;
}
