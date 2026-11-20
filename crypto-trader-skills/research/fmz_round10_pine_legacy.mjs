import fs from "node:fs";
import assert from "node:assert/strict";
import { ArrayFeed, Engine, compile } from "./package/dist/index.js";
import { createHash } from "node:crypto";
const path = name => new URL(name, import.meta.url);
const read = name => JSON.parse(fs.readFileSync(path(name)));
const checksum = value => createHash("sha256").update(value).digest("hex");
const fields = {
  5704: ["Ret1 proof", "Ret2 proof", "Ret3 proof", "Ret4 proof"],
  2609: ["ATR proof", "Up proof", "Dn proof", "Trend proof"],
  5274: ["Upper proof", "Lower proof", "Long proof", "Short proof"],
};
const result = [];
assert.deepEqual(read("./isolation-probe.json"), { privateDenied: true, networkDenied: true });
for (const [rawId, periods] of Object.entries(read("./feeds.json"))) {
  const id = Number(rawId);
  try {
    const code = fs.readFileSync(path("./variant-" + id + ".pine"));
    const source = fs.readFileSync(path("./source-" + id + ".pine"));
    const plan = compile(code.toString("utf8"));
    const settings = {
      initialCapital: 10000,
      qtyType: id===5274 ? "percent_of_equity" : "cash",
      qtyValue: id===5274 ? 100 : 1000,
      commissionType: "percent", commissionValue: 0.059,
      marginLong: 0, marginShort: 0,
    };
    assert(plan.metadata.isStrategy);
    assert.deepEqual(plan.metadata.securityDependencies, []);
    assert.deepEqual(plan.diagnostics, []);
    const cases = [];
    for (const [period, markets] of Object.entries(periods)) {
      for (const [market, points] of Object.entries(markets)) {
        const bars = points.map(([time, open, high, low, close, volume]) => ({time, open, high, low, close, volume}));
        const runs = [];
        for (const backend of ["js", "interp"]) {
          const engine = new Engine(plan, new ArrayFeed(bars), {backend, strategy: settings});
          await engine.run({ symbol: "BINANCE:" + market + ".P", timeframe: "D",
            mintick: market === "BTCUSDT" ? 0.1 : 0.01 });
          const outputs = [...engine.outputs.plots.values()];
          const witnesses = fields[id].map(name => outputs.find(plot => plot.title === name).data);
          runs.push({ witnesses, closed: engine.strategy.closedTrades,
            unsettled: engine.ctx.strategyBroker.openTradeCount });
        }
        assert.deepEqual(runs[0], runs[1]);
        cases.push({ period, market, ...runs[0] });
      }
    }
    result.push({ id, sourceHash: checksum(source), variantHash: checksum(code), diagnostics: plan.diagnostics, cases, settings });
  } catch(error) {
    result.push({ id, error: String(error.stack || error) });
  }
}
fs.writeFileSync(path("./receipt.json"), JSON.stringify(result) + "\n");
