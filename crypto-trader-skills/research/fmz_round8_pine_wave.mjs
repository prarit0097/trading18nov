import fs from 'node:fs';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { ArrayFeed, Engine, compile } from './package/dist/index.js';
const loc = name => new URL(name, import.meta.url);
const read = name => JSON.parse(fs.readFileSync(loc(name)));
const write = (name,obj) => fs.writeFileSync(loc(name), JSON.stringify(obj)+'\n');
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
async function main(){
  assert.deepEqual(read('./isolation-probe.json'),{privateDenied:true,networkDenied:true});
  const source = fs.readFileSync(loc('./variant-5582.pine'));
  const original = fs.readFileSync(loc('./source-5582.pine'));
  const plan=compile(source.toString('utf8'));
  assert(plan.metadata.isStrategy);
  assert.equal(plan.metadata.strategy.initialCapital,1000);
  assert.deepEqual(plan.diagnostics,[]);
  assert.deepEqual(plan.metadata.securityDependencies,[]);
  const output=[];
  const settings={initialCapital:1000,qtyType:'cash',qtyValue:1000,commissionType:'percent',commissionValue:.059,marginLong:0,marginShort:0};
  for(const [period,markets] of Object.entries(read('./wave-feeds.json'))){
    for(const [market,rows] of Object.entries(markets)){
      const opts={symbol:`BINANCE:${market}.P`,timeframe:'D',mintick:market==='BTCUSDT'?0.1:.01};
      const bars=rows.map(([time,open,high,low,close,volume])=>({time,open,high,low,close,volume}));
      const combos=[];
      for(const backend of ['js','interp']){
        const engine=new Engine(plan,new ArrayFeed(bars),{backend,strategy:settings});
        await engine.run(opts);
        const wave=[...engine.outputs.plots.values()].find(p=>p.title==='Bar Change');
        assert(wave && wave.data.length===bars.length);
        combos.push({wave:wave.data,closed:engine.strategy.closedTrades,unsettled:engine.ctx.strategyBroker.openTradeCount});
      }
      assert.deepEqual(combos[0],combos[1]);
      output.push({market,period,...combos[0]});
    }
  }
  write('./wave-receipt.json',{source_sha256:sha(original),variant_sha256:sha(source),settings,cases:output});
}
await main().catch(error=>{write('./wave-error.json',{error:String(error.stack || error)});process.exitCode=1});
