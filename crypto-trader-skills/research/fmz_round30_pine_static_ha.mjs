import assert from "node:assert/strict";
import fs from "node:fs";
import { ArrayFeed, compile, Engine } from "./package/dist/index.js";
const path = x => new URL(x, import.meta.url);
const read = x => JSON.parse(fs.readFileSync(path(x)));
const source = fs.readFileSync(path("./round29-ha-variant.pine"),"utf8");
const plan = compile(source);
const model = { initialCapital:1000000, commissionType:"percent", commissionValue:.059, marginLong:0, marginShort:0 };
const points = rows => rows.map(([time,open,high,low,close,volume])=>({time,open,high,low,close,volume}));
const labels = ["Open","Close","Smoothed open","Smoothed close","Long","Short","Position"];
assert.deepEqual(read("./isolation-probe.json"),{privateDenied:true,networkDenied:true});
assert.deepEqual(plan.diagnostics,[]);
assert.equal(plan.metadata.securityDependencies.length,2);
const report=[];
for(const [period,markets] of Object.entries(read("./round29-ha-js-feeds.json"))){
  for(const [market,data] of Object.entries(markets)){
    const evidence=[];
    for(const backend of ["js","interp"]){
      const engine=new Engine(plan,new ArrayFeed(points(data.chart)),{backend,strategy:model});
      engine.ctx.securityBars.set("CONTEXT:OPEN",points(data.open));
      engine.ctx.securityBars.set("CONTEXT:CLOSE",points(data.close));
      await engine.run({symbol:"BINANCE:"+market+".P",timeframe:"240",mintick:market==="BTCUSDT"?.1:.01});
      const plots=[...engine.outputs.plots.values()];
      evidence.push({request:engine.outputs.securityRequests,witnesses:labels.map(title=>plots.find(p=>p.title===title).data),
          trades:engine.strategy.closedTrades,open:engine.ctx.strategyBroker.openTradeCount});
    }
    assert.deepEqual(evidence[0],evidence[1]);
    report.push({period,market,...evidence[0]});
  }
}
fs.writeFileSync(path("./round29-ha-js-receipt.json"),JSON.stringify(report)+"\n");
