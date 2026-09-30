// Pure routing logic: given the list of panels and an incoming ticker, decide
// which panel(s) an orderbook update should be applied to. Split out from
// app.js so it can be unit tested without a DOM (see ladder/tests/).
function panelsMatchingTicker(panels, ticker) {
  return panels.filter((panel) => panel.currentTicker === ticker);
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { panelsMatchingTicker };
}
