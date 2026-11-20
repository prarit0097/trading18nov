import fs from "node:fs";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { ArrayFeed, Engine, compile } from "./package/dist/index.js";

const location = name => new URL(name, import.meta.url);
const read = name => JSON.parse(fs.readFileSync(location(name)));
const write = (name, value) => fs.writeFileSync(location(name), JSON.stringify(value) + "\n");
const points = rows => rows.map(([time, open, high, low, close, volume]) => ({ time, open, high, low, close, volume }));

function heikin(chart) {
  let last;
  return chart.map(raw => {
    const close = (raw.open + raw.high + raw.low + raw.close) / 4;
    const open = last ? (last.open + last.close) / 2 : (raw.open + raw.close) / 2;
    last = { ...raw, open, close, high: Math.max(raw.high, open, close), low: Math.min(raw.low, open, close) };
    return last;
  });
}

async function main() {
  assert.deepEqual(read("./isolation-probe.json"), { privateDenied: true, networkDenied: true });
  const text = fs.readFileSync(location("./variant-3391.pine"), "utf8");
  const plan = compile(text);
  assert.equal(plan.metadata.isStrategy,true);
  assert.deepEqual(plan.diagnostics, []);
  assert.equal(plan.metadata.securityDependencies.length, 4);
  const settings = { initialCapital: 10000, qtyType: "cash", qtyValue: 1000,
    commissionType: "percent", commissionValue: 0.059, marginLong: 0, marginShort: 0, useBarMagnifier: true };
  const cases = [];
  for (const [period, markets] of Object.entries(read("./feeds.json"))) {
    for (const [market, data] of Object.entries(markets)) {
      const symbol = "BINANCE:" + market + ".P";
      const chart = points(data.chart);
      const lower = points(data.lower);
      const ha = heikin(chart);
      const outcomes = [];
      for (const backend of ["js", "interp"]) {
        const engine = new Engine(plan, new ArrayFeed(chart), { backend, strategy: settings });
        engine.ctx.securityBars.set(symbol + "_HA", ha);
        const range = { from: data.start, to: data.end };
        engine.ctx.magnifierData = {
          targetTimeframe: "1", bars: lower,
          chartIntervals: { closeTimes: chart.map(bar => bar.time + 600000), source: "utc-fixed" },
          coverage: { requested: range, covered: [range], gaps: [], complete: true },
        };
        await engine.run({ symbol, timeframe: "10", mintick: market === "BTCUSDT" ? 0.1 : 0.01 });
        const target = [...engine.outputs.plots.values()].find(p => p.title === "Audited smoothed reverse").data;
        const broker = engine.strategy;
        assert(broker.barMagnifier?.active);
        assert.equal(broker.barMagnifier.capFallbackBars, 0);
        assert.equal(broker.barMagnifier.dataFallbackBars, 0);
        assert.equal(broker.barMagnifier.coverage, "complete");
        outcomes.push({ target, requested: engine.outputs.securityRequests, closed: broker.closedTrades,
          unsettled: engine.ctx.strategyBroker.openTradeCount, coverage: broker.barMagnifier });
      }
      assert.deepEqual(outcomes[0], outcomes[1]);
      cases.push({ market, period, ...outcomes[0] });
    }
  }
  const hash = value => createHash("sha256").update(value).digest("hex");
  write("./receipt.json", { source_sha256: hash(fs.readFileSync(location("./source-3391.pine"))), variant_sha256: hash(text), settings, cases });
}

await main().catch(error => {
  write("./error.json", { error: String(error.stack || error) });
  process.exitCode = 1;
});
