import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import fs from "node:fs";

const path="./package/dist/index.js";
const digest="9a4699655d9f5d0ad105b14cf68b60d6fa1cc8a608ed85b11deebaccbaccbdea";
assert.equal(createHash("sha256").update(fs.readFileSync(new URL(path,import.meta.url))).digest("hex"),digest);
const {compile,Engine,ArrayFeed}=await import(path);

const script=`//@version=4
strategy("388 sibling fill timing",pyramiding=100,initial_capital=10000,default_qty_type=strategy.percent_of_equity,default_qty_value=50,calc_on_order_fills=false,commission_type=strategy.commission.percent,commission_value=0.03)
if bar_index == 0
    strategy.entry("S_1", strategy.short)
    strategy.entry("S_2", strategy.short)
if bar_index == 1
    strategy.close_all()`;
const p=compile(script);
assert.deepEqual(p.diagnostics,[]);
const out=[];
for (const close of [50, 150]) {
  const bars=[[100,101,99,100],[100,150,50,close],[100,101,99,100]].map(([open,high,low,close],i)=>
    ({time:1704067200000+i*3600000,open,high,low,close,volume:1}));
  const series=[];
  for(const backend of ["js","interp"]) {
    const e=new Engine(p,new ArrayFeed(bars),{backend,strategy:{minQty:.001,marginLong:0,marginShort:0}});
    await e.run({symbol:"BINANCE:BTCUSDT",timeframe:"60",mintick:.1});
    series.push(e.strategy.closedTrades);
  }
  assert.deepEqual(series[0],series[1]);
  out.push({bars,closed:series[0]});
}
assert.notEqual(out[0].closed.find(t=>t.entryId==="S_2").qty,out[1].closed.find(t=>t.entryId==="S_2").qty);
fs.writeFileSync(new URL("388-sibling-causality.json",import.meta.url),JSON.stringify({engine:digest,script,cases:out}));
