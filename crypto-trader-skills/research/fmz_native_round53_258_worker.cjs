'use strict';
// Exercise original JavaScript Dual Thrust source on the official offline FMZ engine.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const crypto=require('node:crypto'),zlib=require('node:zlib'),vm=require('node:vm');
const fmz=require('./fmz-wasm-engine.cjs');
const decimal=require('./round53-258-decimal.cjs');
const sha=x=>crypto.createHash('sha256').update(x).digest('hex');
const one=x=>path.join(__dirname,x);
const read=x=>fs.readFileSync(one(x));
const write=(x,v)=>fs.writeFileSync(one(x),v);
const args=process.argv.slice(2);
const control=args[1]==='control';
const stop=Symbol('end of selected market scenario');

let stage='start';
function replay(job) {
  const {begin_ms:start,end_ms:end,market}=job;
  const requests=[];
  global.__offlineProbe=text=>{
    const u=new URL(text),q=u.searchParams;
    assert.equal(u.origin+u.pathname,'https://q.fmz.com/data/history');
    assert.equal(q.get('eid'),'Futures_OKCoin');
    assert.equal(q.get('symbol'),'BTC_USD.this_week');
    assert.equal(q.get('period'),'60000');
    const from=+q.get('from')*1000,to=+q.get('to')*1000;
    const candles=market.data.filter(r=>from<=r[0]&&r[0]<=to);
    assert.ok(candles.length);
    requests.push([q.get('eid'),from,to,candles.length,q.get('event')]);
    return JSON.stringify({...market,data:candles});
  };
  const config={start:'2019-09-01 06:00:00 +0000',end:'2019-09-01 22:00:00 +0000',period:'1h',basePeriod:'1m',
   exchanges:[{eid:'Futures_OKCoin',currency:'BTC_USD',balance:0,stocks:.1,fee:[.02,.05]}]};
  stage='VCtx';
  const ctx=fmz.VCtx(config);
  const s=ctx.scope,e=s.exchange;
  const scopeKeys=Object.keys(s);
  const now=()=>s.Date.now();
  const contracts=[];
  const rate=[];
  const requestsOrders=[];
  const observed={};
  const sourceAccounts=[];
  let firstRecords=[];
  let direction=null;
  assert.equal(e.GetName(),'Futures_OKCoin');
  const originalContract=e.SetContractType, originalRate=e.SetRate, originalDirection=e.SetDirection;
  e.SetRate=(x)=>{assert.equal(x,1);const r=originalRate(x);rate.push(['rate',now(),x]);return r;};
  e.SetContractType=(x)=>{
    assert.equal(x,'this_week');
    const r=originalContract(x);
    assert.equal(r.InstrumentID,job.named_market);
    assert.equal(r.VolumeMultiple,100);
    contracts.push(r);
    return r;
  };
  e.SetDirection=x=>{direction=x;return originalDirection(x);};
  for(const [slot,side] of [['Buy','buy'],['Sell','sell']]){
    const original=e[slot];
    e[slot]=(price,q,...extra)=>{
      const id=original(price,q,...extra);
      requestsOrders.push([now(),side,direction,price,q,id]);
      return id;
    };
  }
  const originalOrders=e.GetOrders,originalLookup=e.GetOrder, originalRecords=e.GetRecords;
  e.GetOrders=(...x)=>{
    const active=originalOrders(...x);
    if(control)return active;
    for(const order of requestsOrders){
      const id=order.at(-1);
      if(observed[id]?.at(-1)[1].Status===1)continue;
      const r=originalLookup(id);
      if(!r)continue;
      const key=[r.Status,r.AvgPrice,r.DealAmount];
      if(!observed[id]||JSON.stringify(observed[id].at(-1)[2])!==JSON.stringify(key))
        (observed[id]??=[]).push([now(),r,key]);
    }
    return active;
  };
  e.GetRecords=(...x)=>{
    const records=originalRecords(...x);
    if(!firstRecords.length)firstRecords=records;
    return records;
  };
  const originalAccount=e.GetAccount;
  e.GetAccount=(...x)=>{const r=originalAccount(...x);sourceAccounts.push([now(),r]);return r;};
  const sleep=s.Sleep;
  s.Sleep=(ms)=>{
    const t=now();
    assert.ok(ms>0&&ms<=2000&&t>=start&&t<end,[t,ms]);
    if(t+ms>=end){sleep(end-t-1);throw stop;}
    return sleep(ms);
  };
  Object.assign(s,job.params,{Decimal:decimal});
  assert.equal(typeof s.Decimal,'function',scopeKeys);
  assert.equal(typeof s.Chart,'function',scopeKeys);
  assert.equal(now(),start);
  assert.equal(sha(Buffer.from(job.script)),job.source_sha256);
  let stopped=false;
  try {
    stage='main';
    vm.runInNewContext(job.script+'\nmain();',s,{timeout:120000,filename:'FMZ-258.js',contextCodeGeneration:{strings:false,wasm:false}});
  } catch(e) {
    if(e!==stop&&e!=='EOF')throw e;
    stopped=true;
  }
  const ended=now();
  stage='join';


  const result=ctx.Join();
  assert.ok(stopped&&Math.abs(ended-end)<1000);
  return {requests,contracts,rate,orders:requestsOrders,order_observations:observed,first_records:firstRecords,
          source_account_observations:sourceAccounts,ended,
          result:typeof result==='string'?JSON.parse(result):result};
}

setTimeout(()=>{
  try{
    const raw=read('round53-258-input.json.gz');
    const result=replay(JSON.parse(zlib.gunzipSync(raw)));
    result.input_sha256=sha(raw);
    result.engine_sha256=sha(read('fmz-wasm-engine.cjs'));
    result.worker_sha256=sha(fs.readFileSync(__filename));
    write(args[0],zlib.gzipSync(JSON.stringify(result)));
  }catch(e){
    write('round53-258-error.txt',stage+': '+String(e.stack||e));
    process.exitCode=1;
  }
},500);
