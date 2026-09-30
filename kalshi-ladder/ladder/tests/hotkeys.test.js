// Run with: node --test ladder/tests/hotkeys.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const {
  KEYMAP,
  SIZE_PRESETS,
  parseHotkey,
  formatBinding,
  buildKeymapRows,
  rowKeyFor,
  stepSize,
  resolveOrder,
  nextSlot,
  slotOnPage,
} = require("../hotkeys.js");

const STALE_MS = 30_000;
const NOW = 1_000_000;

function key(code, { alt = false, shift = false, ctrl = false, meta = false, keyChar } = {}) {
  return { code, altKey: alt, shiftKey: shift, ctrlKey: ctrl, metaKey: meta, key: keyChar };
}

function livePanel(over = {}) {
  return {
    currentTicker: "KXNFLGAME-26SEP20CARATL-ATL",
    lastUpdateMs: NOW - 1000,
    lastBestBid: 62,
    lastBestAsk: 63,
    defaultSize: 25,
    ...over,
  };
}

// ── The binding that must never fire by accident ──────────────────────────────

test("a bare letter never trades", () => {
  for (const code of ["KeyB", "KeyS", "KeyC", "KeyX"]) {
    assert.equal(parseHotkey(key(code)), null, `${code} alone must do nothing`);
    assert.equal(parseHotkey(key(code, { shift: true })), null, `Shift+${code} must do nothing`);
  }
});

test("Alt rests and Alt+Shift crosses", () => {
  assert.deepEqual(parseHotkey(key("KeyB", { alt: true })), {
    kind: "order", side: "buy", aggressive: false,
  });
  assert.deepEqual(parseHotkey(key("KeyB", { alt: true, shift: true })), {
    kind: "order", side: "buy", aggressive: true,
  });
  assert.deepEqual(parseHotkey(key("KeyS", { alt: true })), {
    kind: "order", side: "sell", aggressive: false,
  });
  assert.deepEqual(parseHotkey(key("KeyS", { alt: true, shift: true })), {
    kind: "order", side: "sell", aggressive: true,
  });
});

test("matching is on event.code, so macOS Alt characters still resolve", () => {
  // On macOS Alt+B emits "∫" and Alt+S emits "ß" as event.key.
  assert.deepEqual(parseHotkey(key("KeyB", { alt: true, keyChar: "∫" })), {
    kind: "order", side: "buy", aggressive: false,
  });
  assert.deepEqual(parseHotkey(key("KeyS", { alt: true, keyChar: "ß" })), {
    kind: "order", side: "sell", aggressive: false,
  });
});

test("browser and OS chords are left alone", () => {
  assert.equal(parseHotkey(key("KeyB", { alt: true, meta: true })), null);
  assert.equal(parseHotkey(key("KeyB", { alt: true, ctrl: true })), null);
  assert.equal(parseHotkey(key("Digit1", { meta: true })), null);
});

test("cancel bindings map to the right scope", () => {
  assert.deepEqual(parseHotkey(key("KeyC", { alt: true })), {
    kind: "cancel", scope: "bids", global: false,
  });
  assert.deepEqual(parseHotkey(key("KeyC", { alt: true, shift: true })), {
    kind: "cancel", scope: "asks", global: false,
  });
  assert.deepEqual(parseHotkey(key("KeyX", { alt: true })), {
    kind: "cancel", scope: "both", global: false,
  });
  assert.deepEqual(parseHotkey(key("KeyX", { alt: true, shift: true })), {
    kind: "cancel", scope: "both", global: true,
  });
});

test("navigation, size and help bindings resolve", () => {
  assert.deepEqual(parseHotkey(key("Digit3")), { kind: "page", index: 2 });
  assert.deepEqual(parseHotkey(key("ArrowRight")), { kind: "focus", delta: 1 });
  assert.deepEqual(parseHotkey(key("KeyE")), { kind: "focusPanel", index: 2 });
  assert.deepEqual(parseHotkey(key("ArrowUp")), { kind: "size", direction: 1 });
  assert.deepEqual(parseHotkey(key("ArrowUp", { shift: true })), { kind: "size", direction: "max" });
  assert.deepEqual(parseHotkey(key("Slash", { shift: true })), { kind: "help" });
});

test("Shift+digit does not page (regression: the old Number(key) guard)", () => {
  assert.equal(parseHotkey(key("Digit1", { shift: true })), null);
});

// ── Order resolution guards ───────────────────────────────────────────────────

test("passive buys join the bid, aggressive buys take the ask", () => {
  const p = livePanel();
  assert.deepEqual(resolveOrder(p, { kind: "order", side: "buy", aggressive: false }, NOW, STALE_MS),
    { side: "buy", price: 62, count: 25 });
  assert.deepEqual(resolveOrder(p, { kind: "order", side: "buy", aggressive: true }, NOW, STALE_MS),
    { side: "buy", price: 63, count: 25 });
});

test("passive sells join the ask, aggressive sells hit the bid", () => {
  const p = livePanel();
  assert.deepEqual(resolveOrder(p, { kind: "order", side: "sell", aggressive: false }, NOW, STALE_MS),
    { side: "sell", price: 63, count: 25 });
  assert.deepEqual(resolveOrder(p, { kind: "order", side: "sell", aggressive: true }, NOW, STALE_MS),
    { side: "sell", price: 62, count: 25 });
});

test("an empty bid side is refused, not posted at 0c", () => {
  // get_ladder_snapshot reports best_bid 0 when the book has no bids.
  const p = livePanel({ lastBestBid: 0 });
  assert.deepEqual(resolveOrder(p, { kind: "order", side: "buy", aggressive: false }, NOW, STALE_MS),
    { error: "no-bid" });
  assert.deepEqual(resolveOrder(p, { kind: "order", side: "sell", aggressive: true }, NOW, STALE_MS),
    { error: "no-bid" });
  // The ask side is still tradeable.
  assert.equal(resolveOrder(p, { kind: "order", side: "sell", aggressive: false }, NOW, STALE_MS).price, 63);
});

test("an empty ask side is refused, not posted at 100c", () => {
  const p = livePanel({ lastBestAsk: 100 });
  assert.deepEqual(resolveOrder(p, { kind: "order", side: "sell", aggressive: false }, NOW, STALE_MS),
    { error: "no-ask" });
  assert.deepEqual(resolveOrder(p, { kind: "order", side: "buy", aggressive: true }, NOW, STALE_MS),
    { error: "no-ask" });
  assert.equal(resolveOrder(p, { kind: "order", side: "buy", aggressive: false }, NOW, STALE_MS).price, 62);
});

test("a null quote is refused", () => {
  assert.deepEqual(
    resolveOrder(livePanel({ lastBestBid: null }), { kind: "order", side: "buy", aggressive: false }, NOW, STALE_MS),
    { error: "no-bid" });
});

test("a panel with no ticker is refused", () => {
  assert.deepEqual(
    resolveOrder(livePanel({ currentTicker: "" }), { kind: "order", side: "buy", aggressive: false }, NOW, STALE_MS),
    { error: "no-ticker" });
  assert.deepEqual(
    resolveOrder(null, { kind: "order", side: "buy", aggressive: false }, NOW, STALE_MS),
    { error: "no-ticker" });
});

test("a never-loaded or stale panel is refused", () => {
  assert.deepEqual(
    resolveOrder(livePanel({ lastUpdateMs: 0 }), { kind: "order", side: "buy", aggressive: false }, NOW, STALE_MS),
    { error: "stale" });
  assert.deepEqual(
    resolveOrder(livePanel({ lastUpdateMs: NOW - STALE_MS - 1 }), { kind: "order", side: "buy", aggressive: false }, NOW, STALE_MS),
    { error: "stale" });
  // Just inside the threshold still trades.
  assert.equal(
    resolveOrder(livePanel({ lastUpdateMs: NOW - STALE_MS + 1 }), { kind: "order", side: "buy", aggressive: false }, NOW, STALE_MS).price,
    62);
});

test("a nonsense size is refused", () => {
  for (const defaultSize of [0, -5, 2.5, NaN, undefined]) {
    assert.deepEqual(
      resolveOrder(livePanel({ defaultSize }), { kind: "order", side: "buy", aggressive: false }, NOW, STALE_MS),
      { error: "bad-size" }, `size ${defaultSize}`);
  }
});

// ── Size ladder ───────────────────────────────────────────────────────────────

test("stepSize walks the presets and clamps at both ends", () => {
  assert.equal(stepSize(10, 1), 25);
  assert.equal(stepSize(25, -1), 10);
  assert.equal(stepSize(1000, 1), 1000);
  assert.equal(stepSize(1, -1), 1);
});

test("stepSize snaps a hand-typed size to the neighbouring preset", () => {
  assert.equal(stepSize(37, 1), 50);
  assert.equal(stepSize(37, -1), 25);
  assert.equal(stepSize(3, 1), 5);
  assert.equal(stepSize(3, -1), 1);
});

test("stepSize jumps to the ends", () => {
  assert.equal(stepSize(10, "max"), 1000);
  assert.equal(stepSize(10, "min"), 1);
});

test("stepSize survives a garbage current value", () => {
  assert.equal(stepSize(NaN, 1), 5);
  assert.equal(stepSize(undefined, -1), 1);
});

// ── Focus ─────────────────────────────────────────────────────────────────────

test("nextSlot wraps in both directions", () => {
  assert.equal(nextSlot(0, 1, 45), 1);
  assert.equal(nextSlot(44, 1, 45), 0);
  assert.equal(nextSlot(0, -1, 45), 44);
  assert.equal(nextSlot(0, 1, 0), 0);
});

test("slotOnPage maps a page-relative index, refusing past the end", () => {
  assert.equal(slotOnPage(0, 0, 5, 45), 0);
  assert.equal(slotOnPage(2, 3, 5, 45), 13);
  assert.equal(slotOnPage(8, 4, 5, 45), 44);
  assert.equal(slotOnPage(9, 0, 5, 45), null);
});

// ── KEYMAP is the single source of truth ──────────────────────────────────────

test("no two bindings share the same key combination", () => {
  const seen = new Map();
  for (const e of KEYMAP) {
    const k = `${e.code}|${e.alt ? 1 : 0}|${e.shift ? 1 : 0}`;
    assert.equal(seen.has(k), false, `${k} is bound twice: "${seen.get(k)}" and "${e.label}"`);
    seen.set(k, e.label);
  }
});

test("every documented binding actually dispatches to its own intent", () => {
  for (const e of KEYMAP) {
    const got = parseHotkey(key(e.code, { alt: e.alt, shift: e.shift }));
    assert.deepEqual(got, e.intent, `${formatBinding(e)} (${e.label}) did not round-trip`);
  }
});

test("every binding appears in the cheat sheet exactly once", () => {
  const rows = buildKeymapRows();
  for (const e of KEYMAP) {
    // Merged entries (the nine page digits, the two focus arrows) share one row, so an
    // entry is located by its row key rather than by its own rendered binding.
    const matches = rows.filter((r) => r.key === rowKeyFor(e));
    assert.equal(matches.length, 1, `${formatBinding(e)} (${e.label}) -> ${matches.length} rows`);
    assert.equal(matches[0].group, e.group);
    assert.ok(matches[0].label, "row must carry a label");
  }
});

test("every cheat-sheet row traces back to at least one real binding", () => {
  const keys = new Set(KEYMAP.map(rowKeyFor));
  for (const row of buildKeymapRows()) {
    assert.ok(keys.has(row.key), `row ${row.binding} has no backing binding`);
  }
});

test("the cheat sheet has no rows that are not real bindings", () => {
  const groups = new Set(KEYMAP.map((e) => e.group));
  for (const row of buildKeymapRows()) {
    assert.ok(groups.has(row.group), `stray group ${row.group}`);
    assert.ok(row.binding && row.label, "every row needs a binding and a label");
  }
});

test("collapsed rows keep the sheet readable", () => {
  const rows = buildKeymapRows();
  // Nine page digits and five panel-jump keys must not produce fourteen rows.
  assert.equal(rows.filter((r) => r.label === "Switch page").length, 1);
  assert.equal(rows.filter((r) => r.label === "Focus panel 1–5 of this page").length, 1);
  assert.ok(rows.length < KEYMAP.length, "rows should collapse relative to raw bindings");
});

test("the dangerous bindings are flagged for the overlay", () => {
  const danger = buildKeymapRows().filter((r) => r.danger).map((r) => r.binding);
  assert.deepEqual(danger.sort(), ["Alt + Shift + B", "Alt + Shift + S", "Alt + Shift + X"]);
});

test("formatBinding renders modifiers and key names", () => {
  assert.equal(formatBinding({ code: "KeyB", alt: true, shift: false }), "Alt + B");
  assert.equal(formatBinding({ code: "KeyB", alt: true, shift: true }), "Alt + Shift + B");
  assert.equal(formatBinding({ code: "ArrowUp", alt: false, shift: false }), "↑");
  assert.equal(formatBinding({ code: "Digit4", alt: false, shift: false }), "4");
  assert.equal(formatBinding({ code: "Slash", alt: false, shift: true, displayBinding: "?" }), "?");
});

test("SIZE_PRESETS is sorted and positive", () => {
  assert.deepEqual(SIZE_PRESETS, [...SIZE_PRESETS].sort((a, b) => a - b));
  assert.ok(SIZE_PRESETS.every((n) => Number.isInteger(n) && n > 0));
});
