import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import fs from "node:fs";

const read=(path)=>fs.readFileSync(new URL(path,import.meta.url));
const enginePath="./package/dist/index.js";
const SHA="9a4699655d9f5d0ad105b14cf68b60d6fa1cc8a608ed85b11deebaccbaccbdea";
assert.equal(createHash("sha256").update(read(enginePath)).digest("hex"),SHA);
const {compile,Engine,ArrayFeed}=await import(enginePath);

const source=JSON.parse(read("3038-source-variants.json"));
const data=JSON.parse(read("3038-inputs.json"));
const out=[];
for(const {market,chart} of data.cases) {
  const bars=chart.map(([time,open,high,low,close,volume])=>({time,open,high,low,close,volume}));
  const result={market};
  for(const [name, src] of Object.entries(source)) {
    const relocated=src.replace(/\b(floor|ceil)\(/g,"math.$1(");
    const program=compile(relocated);
    if(program.diagnostics.length>0) {
      result[name]={diagnostics:program.diagnostics};
      continue;
    }
    const vals=[];
    for(const backend of ["js","interp"]) {
      const engine=new Engine(program,new ArrayFeed(bars),{backend,strategy:{minQty:.001,marginLong:0,marginShort:0}});
      await engine.run({symbol:"BINANCE:"+market,timeframe:"D",mintick:market==="BTCUSDT"?.1:.01});
      vals.push(engine.strategy);
    }
    assert.deepEqual(vals[0],vals[1]);
    result[name]={closed:vals[0].closedTrades,initialCapital:vals[0].initialCapital};
  }
  out.push(result);
}
fs.writeFileSync(new URL("3038-piner.json",import.meta.url),JSON.stringify({engine:SHA,cases:out}));
