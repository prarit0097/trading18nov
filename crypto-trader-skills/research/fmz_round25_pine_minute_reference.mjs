import fs from "node:fs";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { ArrayFeed, Engine, compile } from "./package/dist/index.js";
const path = name => new URL(name, import.meta.url);
const read = name => JSON.parse(fs.readFileSync(path(name)));
const sha = bytes => createHash("sha256").update(bytes).digest("hex");
const points = rows => rows.map(([time, open, high, low, close, volume]) => ({ time, open, high, low, close, volume }));
const labels = {1586:["Minute TEMA slope","Minute RSI slope","Volatility","Quiet mode average","Quiet","Long","Short","Position","Equity"],2751:["Minute histogram","Upper","Lower","EMA9","EMA50","EMA200","RSI11","RSI29","Long","Short","Position"]};
const baseModel = { initialCapital:10000, commissionType:"percent", commissionValue:0.059, marginLong:0, marginShort:0 };
assert.deepEqual(read("./isolation-probe.json"), { privateDenied:true, networkDenied:true });
const evidence = [];
for (const [rawId, periods] of Object.entries(read("./minute-reference-feeds.json"))) {
  const id = Number(rawId);
  const model = id===1586 ? {...baseModel,initialCapital:1000,qtyType:"percent_of_equity",qtyValue:100} : {...baseModel,initialCapital:1000000,marginLong:100,marginShort:100};
  try {
    const source = fs.readFileSync(path("./minute-reference-source-"+id+".pine"));
    const variant = fs.readFileSync(path("./minute-reference-variant-"+id+".pine"));
    const plan = compile(variant.toString("utf8"));
    assert(plan.metadata.isStrategy);
    assert.equal(plan.metadata.securityDependencies.length,id===1586?2:1);
    assert.deepEqual(plan.diagnostics,[]);
    const cases = [];

    for (const [period, markets] of Object.entries(periods)) {
      for (const [market, sample] of Object.entries(markets)) {
        const symbol = "BINANCE:" + market + ".P";
        const chart = points(sample.chart);
        const results = [];
        for (const backend of ["js","interp"]) {
          const engine = new Engine(plan, new ArrayFeed(chart), { backend, strategy:model });
          engine.ctx.securityBars.set(symbol+"@1",points(sample.reference));
          await engine.run({ symbol, timeframe:sample.frame, mintick:market === "BTCUSDT" ? .1 : .01 });
          const plots = [...engine.outputs.plots.values()];
          results.push({ witnesses:labels[id].map(name => plots.find(plot => plot.title === name).data),
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
fs.writeFileSync(path("./minute-reference-receipt.json"),JSON.stringify(evidence)+"\n");
