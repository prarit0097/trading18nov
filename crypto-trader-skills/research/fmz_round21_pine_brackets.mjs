import fs from "node:fs";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { ArrayFeed, Engine, compile } from "./package/dist/index.js";
const path = name => new URL(name, import.meta.url);
const read = name => JSON.parse(fs.readFileSync(path(name)));
const sha = bytes => createHash("sha256").update(bytes).digest("hex");
const points = rows => rows.map(([time, open, high, low, close, volume]) => ({ time, open, high, low, close, volume }));
const series = {1990:["Weekly","Fast","Slow","Bear","Bull","Slope","Buy","Sell","Position"],3172:["Upper","Lower","RSI","Long gate","Short-named gate","Position"]};
const model = { initialCapital:10000, commissionType:"percent", commissionValue:0.059, marginLong:0, marginShort:0 };
assert.deepEqual(read("./isolation-probe.json"), { privateDenied:true, networkDenied:true });
const evidence = [];
for (const [rawId, periods] of Object.entries(read("./weekly-bracket-feeds.json"))) {
  const id = Number(rawId);
  try {
    const source = fs.readFileSync(path("./weekly-source-"+id+".pine"));
    const variant = fs.readFileSync(path("./weekly-variant-"+id+".pine"));
    const plan = compile(variant.toString("utf8"));
    assert(plan.metadata.isStrategy);
    assert.equal(plan.metadata.securityDependencies.length,id===1990?1:0);
    assert.deepEqual(plan.diagnostics,[]);
    const cases = [];

    for (const [period, markets] of Object.entries(periods)) {
      for (const [market, sample] of Object.entries(markets)) {
        const symbol = "BINANCE:" + market + ".P";
        const chart = points(sample.chart);
        const results = [];
        for (const backend of ["js","interp"]) {
          const engine = new Engine(plan, new ArrayFeed(chart), { backend, strategy:model });
          if (id === 1990) engine.ctx.securityBars.set(symbol+"@W",points(sample.reference));
          await engine.run({ symbol, timeframe:sample.frame, mintick:market === "BTCUSDT" ? .1 : .01 });
          const plots = [...engine.outputs.plots.values()];
          results.push({ witnesses:series[id].map(name => plots.find(plot => plot.title === name).data),
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
fs.writeFileSync(path("./weekly-bracket-receipt.json"),JSON.stringify(evidence)+"\n");
