import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import fs from "node:fs";
const read = name => fs.readFileSync(new URL(name, import.meta.url));
const digest = "9a4699655d9f5d0ad105b14cf68b60d6fa1cc8a608ed85b11deebaccbaccbdea";
assert.equal(createHash("sha256").update(read("./package/dist/index.js")).digest("hex"),digest);
assert.equal(createHash("sha512").update(read("piner-0.13.0.tgz")).digest("base64"),"wyZp7irvRiBBoSkLINDqufqRsc6rZH7uoIwk1dZHlKIkLBz+fpeBi7mbgumRxiyBNZf2dN6YmiE6swRhWE9wNw==");
const { compile, Engine, ArrayFeed } = await import("./package/dist/index.js");
const input = JSON.parse(read("5530-piner-input.json"));
const controls = { when_false: "//@version=4\nstrategy(\"false\")\nstrategy.entry(\"L\",strategy.long,when=false)\nstrategy.entry(\"S\",strategy.short,when=false)", guard_false: "//@version=4\nstrategy(\"false\")\nif false\n    strategy.entry(\"L\",strategy.long)\n    strategy.entry(\"S\",strategy.short)" };
controls.when_false_series = controls.when_false.replaceAll("when=false","when=close<0");
controls.guard_script = input.sources.vocabulary.replace('strategy.entry("Buy",strategy.long,when = golong)', 'if golong\n    strategy.entry("Buy",strategy.long)').replace('strategy.entry("Sell",strategy.short,when = goshort)', 'if goshort\n    strategy.entry("Sell",strategy.short)');
controls.when_false_series_spaces = controls.when_false.replaceAll("when=false","when = close<0");
controls.when_valid_flag = controls.when_false.replaceAll("when=false","when = signal").replace("strategy(\"false\")","strategy(\"false\")\nsignal = close < 0");
const results = {};
for (const [name,source] of Object.entries({...input.sources,vocabularyBound:input.sources.vocabulary,...controls})) {
  let program;
  try { program = compile(source); } catch (error) { results[name] = { compileException: String(error) }; continue; }
  let traces = {};
  if (!program.diagnostics.length) {
    for (const backend of ["js","interp"]) {
      try {
        const engine = new Engine(program,new ArrayFeed(input.bars),{backend,strategy:{minQty:.001,marginLong:0,marginShort:0}});
        if (name==="vocabularyBound") engine.ctx.securityBars.set("BINANCE:BTCUSDT@1440",input.bars);
        await engine.run({symbol:"BINANCE:BTCUSDT",timeframe:"D",mintick:.1});
        const plots = [...engine.outputs.plots.values()].filter(p=>p.title.startsWith("scope "));
        traces[backend]={frames:engine.strategy.barsProcessed, trades:engine.strategy.closedTrades.length, plotted:plots.map(p=>({title:p.title,last:p.data.slice(-4),defined:p.data.filter(v=>v!==null&&!Number.isNaN(v)).length,ones:p.data.filter(v=>v===1).length})), requests:engine.outputs.securityRequests};
      } catch(error) {
        traces[backend]={error:String(error)};
      }
    }
    traces.backendAgreement=JSON.stringify(traces.js)===JSON.stringify(traces.interp);
  }
  results[name]={diagnostics:program.diagnostics,traces};
}
fs.writeFileSync(new URL("5530-piner.json",import.meta.url),JSON.stringify({engine:digest,results}));
