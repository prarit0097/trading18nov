import fs from "node:fs";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { ArrayFeed, Engine, compile } from "./package/dist/index.js";

const path = name => new URL(name, import.meta.url);
const read = name => JSON.parse(fs.readFileSync(path(name)));
const write = (name, value) => fs.writeFileSync(path(name), JSON.stringify(value) + "\n");
const sha256 = bytes => createHash("sha256").update(bytes).digest("hex");
const point = ([time, open, high, low, close, volume]) => ({ time, open, high, low, close, volume });
const toHeikinAshi = chart => {
  let previous;
  return chart.map(raw => {
    const close = (raw.open + raw.high + raw.low + raw.close) / 4;
    const open = previous ? (previous.open + previous.close) / 2 : (raw.open + raw.close) / 2;
    previous = { ...raw, open, close, high: Math.max(raw.high, open, close), low: Math.min(raw.low, open, close) };
    return previous;
  });
};
const settings = {
  initialCapital: 10000,
  qtyType: "cash",
  qtyValue: 1000,
  commissionType: "percent",
  commissionValue: 0.059,
  marginLong: 0,
  marginShort: 0,
};

async function execute(plan, bars, ha, symbol, mintick, backend) {
  const engine = new Engine(plan, new ArrayFeed(bars), { strategy: settings, backend });
  engine.ctx.securityBars.set(`${symbol}_HA`, ha);
  await engine.run({ symbol, timeframe: "60", mintick });
  const signalPlot = [...engine.outputs.plots.values()];
  return {
    requested: engine.outputs.securityRequests,
    closed: engine.strategy.closedTrades,
    unsettled: engine.ctx.strategyBroker.openTradeCount,
    ha: signalPlot.find(x => x.title === "Round 8 audited Heikin-Ashi close")?.data,
    signal: signalPlot.find(x => x.title === "Round 8 audited direction")?.data,
  };
}

const isolation = read("./isolation-probe.json");
assert.deepEqual(isolation, { privateDenied: true, networkDenied: true });
const bytes = fs.readFileSync(path("./source-1044.pine"));
const archived = bytes.toString("utf8");
assert.equal([...archived.matchAll(/^src = close$/gm)].length, 1);
assert.equal([...archived.matchAll(/^src\s*:?=/gm)].length, 1);
const oldRequest = "request.security(ticker.heikinashi(syminfo.tickerid), timeframe.period, src)";
assert.equal(archived.split(oldRequest).length, 2);
const code = archived.replace(oldRequest,
  "request.security(ticker.heikinashi(syminfo.tickerid), timeframe.period, close)");
const plotOnly = '\nplot(hclose, "Round 8 audited Heikin-Ashi close")\nplot(crossup ? 1 : crossdown ? -1 : 0, "Round 8 audited direction")\n';
const plan = compile(code);
const witnessed = compile(code + plotOnly);
assert(plan.metadata.isStrategy);
assert.deepEqual(plan.diagnostics, []);
assert.deepEqual(witnessed.diagnostics, []);
assert.equal(plan.metadata.strategy.processOrdersOnClose, true);
const match = [{ lowerTf: false, self: false, symbol: null, tfSelf: true, timeframe: null, dynamic: true, lookahead: false, expressionPriorBars: 0 }];
assert.deepEqual(plan.metadata.securityDependencies, match);
const cases = [];
for (const [period, markets] of Object.entries(read("./feeds.json"))) {
  for (const [market, rows] of Object.entries(markets)) {
    const symbol = `BINANCE:${market}.P`;
    const mintick = market === "BTCUSDT" ? 0.1 : 0.01;
    const bars = rows.map(point);
    const ha = toHeikinAshi(bars);
    const js = await execute(plan, bars, ha, symbol, mintick, "js");
    const interp = await execute(plan, bars, ha, symbol, mintick, "interp");
    assert.deepEqual(js, interp);
    const observed = await execute(witnessed, bars, ha, symbol, mintick, "js");
    assert.deepEqual(js.closed, observed.closed);
    assert.equal(js.unsettled, observed.unsettled);
    assert.deepEqual(js.requested, [{ symbol: `${symbol}_HA`, timeframe: "60", lowerTf: false }]);
    assert.deepEqual(observed.ha, ha.map(bar => bar.close));
    cases.push({ period, market, ...observed });
  }
}
write("./ha-receipt.json", { source_sha256: sha256(bytes), executed_source_sha256: sha256(code), mode: "equivalent request and plot witness agree", settings, cases });
