// Run with: node --test ladder/tests/panel-router.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const { panelsMatchingTicker } = require("../panel-router.js");

function fakePanel(currentTicker) {
  return { currentTicker };
}

test("returns no panels when nothing matches the ticker", () => {
  const panels = [fakePanel("TICK-A"), fakePanel("TICK-B"), fakePanel("")];
  assert.deepEqual(panelsMatchingTicker(panels, "TICK-C"), []);
});

test("returns the single panel showing that ticker", () => {
  const a = fakePanel("TICK-A");
  const b = fakePanel("TICK-B");
  const panels = [a, b];
  assert.deepEqual(panelsMatchingTicker(panels, "TICK-A"), [a]);
});

test("returns every panel showing the same ticker (regression: duplicate ticker across panels)", () => {
  const a = fakePanel("TICK-A");
  const b = fakePanel("TICK-B");
  const c = fakePanel("TICK-A"); // same market loaded in a second panel
  const panels = [a, b, c];

  const matches = panelsMatchingTicker(panels, "TICK-A");

  assert.equal(matches.length, 2);
  assert.ok(matches.includes(a));
  assert.ok(matches.includes(c));
  assert.ok(!matches.includes(b));
});

test("does not mutate the panels array or panel objects", () => {
  const a = fakePanel("TICK-A");
  const panels = [a];
  panelsMatchingTicker(panels, "TICK-A");
  assert.equal(panels.length, 1);
  assert.equal(a.currentTicker, "TICK-A");
});
