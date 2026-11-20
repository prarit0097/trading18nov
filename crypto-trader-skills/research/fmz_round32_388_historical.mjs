import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import fs from "node:fs";

const read=(path)=>fs.readFileSync(new URL(path,import.meta.url));
const enginePath="./package/dist/index.js";
const digest="9a4699655d9f5d0ad105b14cf68b60d6fa1cc8a608ed85b11deebaccbaccbdea";
assert.equal(createHash("sha256").update(read(enginePath)).digest("hex"),digest);
const {compile,Engine,ArrayFeed}=await import(enginePath);
const cases=JSON.parse(read("388-probe.json"));
const out=[];
for (const item of cases) {
  const market=item.market;
  const data=JSON.parse(read("1070-"+market+".json"));
  const bars=[];
  for(let i=0;i<data.base.length;i+=4) {
    const group=data.base.slice(i,i+4);
    const [time, open]=group[0];
    const high=Math.max(...group.map(r=>r[2]));
    const low=Math.min(...group.map(r=>r[3]));
    const close=group.at(-1)[4];
    const volume=group.reduce((sum,r)=>sum+r[5],0);
    bars.push({time,open,high,low,close,volume});
  }
  const plots=item.v4_lot_units.plots;
  const flag=(name,key)=>{
    const lines=plots[key].flatMap((v,i)=>v===1?[`    ${i} => true`]:[]);
    return [name+" = switch bar_index",...lines,"    => false"].join("\n");
  };
  const track=(name,key)=>{
    const entries=plots[key].flatMap((v,i)=>i===0||v!==plots[key][i-1]?
      [`    ${i} => ${v===null?"na":(Number.isInteger(v)?v+".0":v)}`]:[]);
    return [`var float ${name} = na`,name+" := switch bar_index",...entries,"    => "+name+"[1]"].join("\n");
  };
  const sourceText=read("source-388.md").toString("utf8");
  const orders=sourceText.split(/\r?\n/).filter(line=>
    /^strategy\("Goblin Town|^ *strategy\.entry\(|^strategy\.exit\(/.test(line));
  assert.equal(orders.length,9);
  const [header,a,b,c,d,...originalExits]=orders;
  const exits=originalExits.map(line=>line.replaceAll("last_open_longCondition","referenceL").replaceAll("last_open_shortCondition","referenceS"));
  const script=["//@version=5",header,flag("long_flag","observed L"),flag("short_flag","observed S"),
    track("referenceL","observed reference L"),track("referenceS","observed reference S"),
    `tp=0.9
tp2=1.7
sl=7.0
ACT_BT=true
testPeriod=true
if long_flag`,a,b,"if short_flag",c,d,...exits,
    "plot(strategy.position_size,title=\"Observed size\")",
    "plot(strategy.position_avg_price,title=\"Observed basis\")"].join("\n");
  const program=compile(script);
  if(program.diagnostics.length) {
    out.push({market,diagnostics:program.diagnostics});
    continue;
  }
  const details={};
  const mintick=market==="BTCUSDT"?.1:.01;
  for(const backend of ["js","interp"]) {
    const engine=new Engine(program,new ArrayFeed(bars),{backend,strategy:{minQty:.001,marginLong:0,marginShort:0}});
    await engine.run({symbol:"BINANCE:"+market,timeframe:"60",mintick});
    details[backend]=engine.strategy;
  }
  assert.deepEqual(details.js,details.interp);
  out.push({market,runner_sha256:createHash("sha256").update(script).digest("hex"),result:details.js});
}
fs.writeFileSync(new URL("388-piner-historical.json",import.meta.url),JSON.stringify({engine:digest,cases:out}));
