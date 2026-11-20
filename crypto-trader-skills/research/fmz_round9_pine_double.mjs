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
  const source = fs.readFileSync(loc('./variant-2733.pine'));
  const original = fs.readFileSync(loc('./source-2733.pine'));
  const plan=compile(source.toString('utf8'));
  assert(plan.metadata.isStrategy);
  assert.equal(plan.metadata.strategy.processOrdersOnClose,true);
  assert.deepEqual(plan.diagnostics,[]);
  assert.deepEqual(plan.metadata.securityDependencies,[]);
  const output=[];
  const settings={initialCapital:1000000,qtyType:'fixed',qtyValue:2,pyramiding:1,commissionType:'percent',commissionValue:.059,marginLong:0,marginShort:0};
  for(const [period,markets] of Object.entries(read('./double-feeds.json'))){
    for(const [market,rows] of Object.entries(markets)){
      const opts={symbol:`BINANCE:${market}.P`,timeframe:'60',mintick:market==='BTCUSDT'?0.1:.01};
      const bars=rows.map(([time,open,high,low,close,volume])=>({time,open,high,low,close,volume}));
      const combos=[];
      for(const backend of ['js','interp']){
        const engine=new Engine(plan,new ArrayFeed(bars),{backend,strategy:settings});
        await engine.run(opts);
        assert(engine.ctx.strategyBroker.active);
        combos.push({closed:engine.strategy.closedTrades,unsettled:engine.ctx.strategyBroker.openTradeCount});
      }
      assert.deepEqual(combos[0],combos[1]);
      output.push({market,period,...combos[0]});
    }
  }
  write('./double-receipt.json',{source_sha256:sha(original),variant_sha256:sha(source),settings,cases:output});
}
await main().catch(error=>{write('./double-error.json',{error:String(error.stack || error)});process.exitCode=1});
