import fs from "node:fs";
import assert from "node:assert/strict";
import { ArrayFeed, Engine, compile } from "./package/dist/index.js";
const local = name => new URL(name, import.meta.url);
const read = name => JSON.parse(fs.readFileSync(local(name)));
assert.deepEqual(read("isolation-probe.json"), { privateDenied: true, networkDenied: true });
const original = fs.readFileSync(local("r39-panel-source.pine"),"utf8").replace(/\r\n/g,"\n").replace(/^\/\*backtest[\s\S]*?\*\/\n*/,"");
const source = original.replace(/\bsma\(/g,"ta.sma(").replace(/^\/\/@version=4$/m,"//@version=5")
  .replace(/\bround\(/g,"math.round(").replace(/\bchange\(/g,"ta.change(").replace(/\btostring\(/g,"str.tostring(")
  .replace('input(size.large,','input.string(size.large,');
const active = source.split("//Lines")[0]+'\nplot(strategy.position_size, "Position")\nplot(strategy.equity,"Equity")';
const plan = compile(active);
const rows=read("r39-panel-feeds.json");
const results=[];
for(const [period, assets] of Object.entries(rows)) {
  for(const [market, packets] of Object.entries(assets)) {
    const tape=packets.chart.map(([time,open,high,low,close,volume])=>({time,open,high,low,close,volume}));
    for(const backend of ["js","interp"]) {
      const engine = new Engine(plan,new ArrayFeed(tape),{backend,strategy:{initialCapital:1000000, qtyType:"percent_of_equity", qtyValue:100, marginLong:0, marginShort:0}});
      await engine.run({symbol:`BINANCE:${market}.P`,timeframe:"1D",mintick:market === "BTCUSDT" ? .1 : .01});
      const pos=[...engine.outputs.plots.values()].find(p=>p.title==="Position").data;
      results.push({period,market,backend,closed:engine.strategy.closedTrades,unsettled:engine.ctx.strategyBroker.openTradeCount,pos});
    }
  }
}
fs.writeFileSync(local("r39-panel-piner.json"),JSON.stringify(results)+"\n");
