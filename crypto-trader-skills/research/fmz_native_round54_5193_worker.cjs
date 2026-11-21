'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const assert=require('node:assert/strict'),crypto=require('node:crypto'),zlib=require('node:zlib');
const engine=require('./fmz-wasm-engine.cjs');
const nativeProcess=require('node:process');
const sha=x=>crypto.createHash('sha256').update(x).digest('hex');
const here=name=>path.join(__dirname,name);
const stop=Symbol('end of declared historical scenario');

function replay(job) {
  const {begin_ms:start,end_ms:end,market}=job;
  const marker=[];
  global.__offlineProbe=text=>{
    const url=new URL(text),q=url.searchParams;
    assert.equal(url.origin+url.pathname,'https://q.fmz.com/data/history');
    assert.equal(q.get('eid'),'Futures_OKCoin');
    assert.equal(q.get('symbol'),'BTC_USD.this_week');
    assert.equal(q.get('period'),'60000');
    const from=+q.get('from')*1000,to=+q.get('to')*1000;
    const candles=market.data.filter(r=>from<=r[0]&&r[0]<=to);
    assert.ok(candles.length);
    marker.push([q.get('eid'),from,to,candles.length,q.get('event')]);
    return JSON.stringify({...market,data:candles});
  };
  const options={start:'2019-09-01 06:00:00 +0000',end:'2019-09-01 22:00:00 +0000',period:'1h',basePeriod:'1m',
                exchanges:[{eid:'Futures_OKCoin',currency:'BTC_USD',balance:0,stocks:job.initial_wallet_BTC,fee:[.02,.05]}]};
  const ctx=engine.VCtx(options),s=ctx.scope,e=s.exchange;
  const now=()=>s.Date.now();
  const contracts=[],orders=[],cancellations=[],outstanding=[],leverage=[],directions=[];
  const nativeContract=e.SetContractType,nativeMargin=e.SetMarginLevel,nativeDirection=e.SetDirection;
  let state=null, changed=null, inspected=0;
  e.SetContractType=x=>{const r=nativeContract(x);contracts.push([x,r]);return r;};
  e.SetMarginLevel=x=>{const r=nativeMargin(x);leverage.push([now(),x,r]);return r;};
  e.SetDirection=x=>{state=x;directions.push([now(),x]);return nativeDirection(x);};
  for(const method of ['Buy','Sell']){
    const submit=e[method];
    e[method]=(p,q,...extras)=>{
      const r=submit(p,q,...extras);
      orders.push([now(),method,state,p,q,r]);
      return r;
    };
  }
  const cancel=e.CancelOrder;
  e.CancelOrder=(id,...extras)=>{const r=cancel(id,...extras);cancellations.push([now(),id,r]);return r;};
  const list=e.GetOrders;
  e.GetOrders=(...args)=>{
    inspected++;
    const values=list(...args);
    const next=values.map(o=>[o.Id,o.Status,o.DealAmount,o.Price,o.Amount]);
    const repr=JSON.stringify(next);
    if(repr!==changed){outstanding.push([now(),next]);changed=repr;}
    return values;
  };
  const sleep=s.Sleep;
  s.Sleep=(ms)=>{
    assert.ok(Number.isFinite(ms)&&ms>0&&ms<=2000);
    if(now()+ms>=end){
      if(now()<end-1)sleep(end-now()-1);
      throw stop;
    }
    return sleep(ms);
  };
  assert.equal(sha(Buffer.from(job.script)),job.source_sha256);
  const nativeCommands=s.GetCommand;
  let commandChecks=0;
  s.GetCommand=(...args)=>{
    commandChecks++;
    const result=nativeCommands(...args);
    assert.ok(!result);
    return result;
  };
  Object.assign(s,job.params);
  assert.equal(now(),start);
  let stopped=false;
  try{
    vm.runInNewContext(job.script+'\nmain();',s,{timeout:120_000,filename:'FMZ-5193.js',contextCodeGeneration:{strings:false,wasm:false}});
  }catch(e){
    if(e!==stop&&e!=='EOF')throw e;
    stopped=true;
  }
  assert.ok(stopped&&end-now()<3000);
  const result=ctx.Join(),report=typeof result==='string'?JSON.parse(result):result;
  assert.ok(report.Finished&&report.Progress===100&&report.Time===end);
  return {market_fetches:marker,contracts,orders,cancellations,outstanding,inspected,leverage,directions,
          commandChecks,snapshots:report.Snapshots,summary:report.Task,finish:report.Time};
}

setTimeout(()=>{
  try{
    const input=fs.readFileSync(here('round54-5193-input.json.gz'));
    const job=JSON.parse(zlib.gunzipSync(input));
    const receipt={...replay(job),worker_sha256:sha(fs.readFileSync(__filename)),input_sha256:sha(input),
                  engine_sha256:sha(fs.readFileSync(here('fmz-wasm-engine.cjs')))};
    fs.writeFileSync(here(nativeProcess.argv[2]),zlib.gzipSync(JSON.stringify(receipt)));
  }catch(e){
    fs.writeFileSync(here('round54-5193-error.txt'),String(e.stack||e));
    nativeProcess.exitCode=1;
  }
},500);
