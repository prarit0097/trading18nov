import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import fs from "node:fs";

const read = (path) => fs.readFileSync(new URL(path, import.meta.url));
const enginePath = "./package/dist/index.js";
const digest = "9a4699655d9f5d0ad105b14cf68b60d6fa1cc8a608ed85b11deebaccbaccbdea";
assert.equal(createHash("sha256").update(read(enginePath)).digest("hex"),digest);
assert.equal(createHash("sha512").update(read("piner-0.13.0.tgz")).digest("base64"),
  "wyZp7irvRiBBoSkLINDqufqRsc6rZH7uoIwk1dZHlKIkLBz+fpeBi7mbgumRxiyBNZf2dN6YmiE6swRhWE9wNw==");
const {compile,Engine,ArrayFeed}=await import(enginePath);
const inputs=JSON.parse(read("388-stacked-fixture.json"));
const out={};
for (const [key,{source,bars}] of Object.entries(inputs)) {
  for(const version of [4,5]) {
    const program=compile(source.replace("//@version=4","//@version="+version));
    assert.deepEqual(program.diagnostics,[]);
    const outputs={};
    for (const backend of ["js","interp"]) {
      const engine=new Engine(program,new ArrayFeed(bars),{backend,strategy:{minQty:1,marginLong:0,marginShort:0}});
      await engine.run({ symbol:"BINANCE:BTCUSDT", timeframe:"60",mintick:1});
      outputs[backend]=engine.strategy;
    }
    assert.deepEqual(outputs.js,outputs.interp);
    out[key+"_"+version]=outputs.js.closedTrades;
  }
}
fs.writeFileSync(new URL("388-piner.json",import.meta.url),JSON.stringify({engine:digest,cases:out}));
