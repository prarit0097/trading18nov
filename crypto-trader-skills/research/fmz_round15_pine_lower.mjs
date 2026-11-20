import fs from "node:fs";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { ArrayFeed, Engine, compile } from "./package/dist/index.js";
const path = name => new URL(name, import.meta.url);
const read = name => JSON.parse(fs.readFileSync(path(name)));
const sha = bytes => createHash("sha256").update(bytes).digest("hex");
const points = rows => rows.map(([time, open, high, low, close, volume]) => ({ time, open, high, low, close, volume }));
const labelsById = {5474:["Daily","Hourly","Direction"],965:["FAST","SLOW","Direction"]};
const model = { initialCapital:10000, qtyType:"cash", qtyValue:1000,
  commissionType:"percent", commissionValue:0.059, marginLong:0, marginShort:0 };
assert.deepEqual(read("./isolation-probe.json"), { privateDenied:true, networkDenied:true });
const evidence = [];
for (const [rawId, periods] of Object.entries(read("./lower-feeds.json"))) {
  const id = Number(rawId);
  try {
    const source = fs.readFileSync(path("./source-"+id+".pine"));
    const variant = fs.readFileSync(path("./variant-"+id+".pine"));
    const plan = compile(variant.toString("utf8"));
    assert(plan.metadata.isStrategy);
    assert.equal(plan.metadata.securityDependencies.length,id===965?2:1);
    assert.deepEqual(plan.diagnostics,[]);
    const cases = [];
    const labels = labelsById[id];
    for (const [period, markets] of Object.entries(periods)) {
      for (const [market, sample] of Object.entries(markets)) {
        const symbol = id===965 ? "BINANCE:" + market + ".P" : "BITFINEX:" + market;
        const chart = points(sample.chart);
        const results = [];
        for (const backend of ["js","interp"]) {
          const engine = new Engine(plan, new ArrayFeed(chart), { backend, strategy:model });
          engine.ctx.securityBars.set(symbol+(id===965?"@30":"@60"),points(sample.reference));
          await engine.run({ symbol, timeframe:sample.frame, mintick:id===5474 ? 1e-8 : market === "BTCUSDT" ? .1 : .01 });
          const plots = [...engine.outputs.plots.values()];
          results.push({ witnesses:labels.map(name => plots.find(plot => plot.title === name).data),
            requested:engine.outputs.securityRequests, closed:engine.strategy.closedTrades,
            unsettled:engine.ctx.strategyBroker.openTradeCount });
        }
        assert.deepEqual(results[0],results[1]);
        cases.push({ market, period, ...results[0] });
      }
    }
    evidence.push({ id, sourceHash:sha(source), variantHash:sha(variant), cases, model });
  } catch(error) {
    evidence.push({ id, error:String(error.stack || error) });
  }
}
fs.writeFileSync(path("./lower-receipt.json"),JSON.stringify(evidence)+"\n");
