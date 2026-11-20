process.env.TZ='UTC';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {createHash}=require('node:crypto');
const {gunzipSync}=require('node:zlib');
const FMZ=require('./fmz-wasm-engine.cjs');

const D=86400000;
const H=3600000;
const STEP=900000;
const ROOT=__dirname;
const read=f=>fs.readFileSync(path.join(ROOT,f));
const write=(f,v)=>fs.writeFileSync(path.join(ROOT,f),JSON.stringify(v));
const sha=x=>createHash('sha256').update(x).digest('hex');
const time=t=>new Date(t).toISOString().slice(0,19).replace('T',' ');
const STOP=Symbol('scope cutoff');

function run(job,mode,start,end) {
 const coins=mode==='single'?['ETH']:['ETH','LTC'];
 const logs=[],requests=[],market=[],observations=[];
  let templates=0,currentRecordDay=0,currentCoin=null;
 const ev={};
 const ledgers={};
 for(const c of coins){ledgers[c]={balances:[],orders:[],indicators:[]};ev[c]=0;}
 global.__offlineProbe=u=>{
    const url=new URL(u), q=url.searchParams;
    const [currency,section]=q.get('symbol').split('.');
    const coin=currency.split('_')[0];
    const event=q.get('event');const period=Number(q.get('period'));const from=Number(q.get('from'))*1000;const to=Number(q.get('to'))*1000;
    const tape=job.feeds[coin][event==='fill'&&period===D&&section==='swap'?'daily':section];
    const rows=tape.data.filter(r=>r[0]>=from && r[0]<=to);
    assert.equal(q.get('eid'),'Futures_Binance');
    assert.ok(coins.includes(coin) && ['feed','fill'].includes(event));
    assert.ok(rows.length>0 || event==='fill',JSON.stringify({u,rows:rows.length}));
    requests.push({url:u,event,period,from,to,market:coin,section,rows:rows.length});
    return JSON.stringify({schema:tape.schema,detail:tape.detail,data:rows});
 };
 const settings=coins.map(coin=>({eid:'Futures_Binance',currency:coin+'_USDT',balance:coin==='ETH'?1000000:10000,
       stocks:0,fee:[0.02,0.04],lever:10,slippage:0}));
 const ctx=FMZ.VCtx({start:time(start),end:time(end+STEP),basePeriod:'15m',period:'1d',exchanges:settings});
 const scope=ctx.scope;
 const baseSleep=scope.Sleep;
 const now=()=>scope.Date.now();
 assert.equal(now(),start);
 let sleepCalls=0;
 const raw=scope.exchanges.map(ex=>({GetTicker:ex.GetTicker,GetPosition:ex.GetPosition,GetAccount:ex.GetAccount,GetOrders:ex.GetOrders,
    GetRecords:ex.GetRecords,CancelOrder:ex.CancelOrder,Buy:ex.Buy,Sell:ex.Sell,SetDirection:ex.SetDirection,GetOrder:ex.GetOrder,
    GetHistoryOrders:ex.GetHistoryOrders}));
 function update(c,r,kind) {
    const t=now();
    const acc=r.GetAccount();const pos=r.GetPosition();
    const sample={c,t,kind,acc,pos};
    if(kind==='day') {
        assert.ok(!ledgers[c].balances.length || ledgers[c].balances.at(-1).t<t);
        ledgers[c].balances.push(sample);
    }
    else observations.push(sample);
    return sample;
 }
 scope.exchanges.forEach((ex,k)=>{
    const c=coins[k];const api=raw[k];
    let direction=null, lastDay=0;
    ex.GetRecords=(n)=>{
       assert.equal(n,86400);
       if(now()>=end)throw STOP;
       const bars=api.GetRecords(n);
       assert.ok(bars&&bars.length>2);
       const bar=bars.at(-1).Time;
       assert.ok(bar<=now() && now()-bar<D);
       if(lastDay!==bar) {
          assert.equal(bar%D,16*H);
          assert.ok(bars.length>=40,`insufficient warmup ${bars.length}`);
          assert.ok(bars.at(-2).Time===bar-D);
          if(!ledgers[c].seed) ledgers[c].seed=bars.slice(0,-1).map(b=>[b.Time,b.Open,b.High,b.Low,b.Close,b.Volume]);
          const previous=bars.at(-2);
          const tape=job.feeds[c].swap.data; const w=(previous.Time-tape[0][0])/STEP; const span=tape.slice(w,w+96); assert.equal(span.length,96); const archived=[previous.Time,span[0][1],Math.max(...span.map(r=>r[2])),Math.min(...span.map(r=>r[3])),span.at(-1)[4]];
          assert.deepEqual([previous.Open,previous.High,previous.Low,previous.Close].map(x=>Math.round(x*100)),archived.slice(1,5));
          market.push([c,now(),bar,bars.length,previous.Close]);
          lastDay=bar; ev[c]++;
          update(c,api,'day');
       }
       currentCoin=c;
       currentRecordDay=bar;
       return bars;
    };
    ex.SetDirection=d=>{direction=d;return api.SetDirection(d);};
    for(const side of ['Buy','Sell']) {
       ex[side]=(price,qty,label,ct,ticker)=>{
          assert.equal(ct,'swap');assert.equal(qty,10);
          assert.equal(price,side==='Buy'?ticker.Sell+5:ticker.Buy-5);
          const before=update(c,api,'beforeOrder');
          const order=api[side](price,qty,label,ct,ticker);
          const o=api.GetOrder(order);
          const after=update(c,api,'afterOrder');
          assert.ok(o&&o.DealAmount===qty&&o.Status===1,JSON.stringify({before,o,after}));
          assert.equal(o.AvgPrice,side==='Buy'?ticker.Sell:ticker.Buy);
          const obs={c,direction,order:o,side,before,after,limit:price,last:ticker.Last,ticker,t:before.t};
          ledgers[c].orders.push(obs);
          return order;
       };
    }
 });
 scope.Sleep=ms=>{
    const t=now();
    if(t>=end)throw STOP;
    assert.equal(ms,500,`unexpected retry sleep ${ms}`);
    sleepCalls++;
    return baseSleep(Math.min(ms,end-t));
 };
 const nativeTA=scope.TA;
 let latestAtr;
 scope.TA={
   ATR(rows,n){
     const data=nativeTA.ATR(rows,n);
     latestAtr=data.slice(-3,-1);
     return data;
   },
   EMA(rows,n){
     const data=nativeTA.EMA(rows,n);
     const trace=ledgers[currentCoin].indicators;
     if(trace.at(-1)?.bar!==currentRecordDay) trace.push({bar:currentRecordDay,atr:latestAtr,ema:data.slice(-3,-1),n});
     return data;
   },
 };
 scope.Chart=()=>({reset(){},add(){}});
 scope._={each(a,f){a.forEach(f);}};
 scope.$={};
 scope.Log=(...a)=>{if(a.length && typeof a[0]==='string' && logs.length<700)logs.push([now(),...a]);};
 scope.LogStatus=()=>{};
 scope._G=(k,v)=>k==='arrState'?null:null;
 Object.assign(scope,job.source_public_form.args,job.template_public_form.args,
   mode==='single'?{}:{...job.embedded_params,onlyOne:false});
 vm.createContext(scope,{codeGeneration:{strings:false,wasm:false}});
 vm.runInContext(job.template,scope,{timeout:10000,filename:'archived-template-203258.js'});
 for(const name of ['OpenLong','OpenShort','CoverLong','CoverShort']) {
    const fn=scope.$[name];
    scope.$[name]=function(...a){templates++;return fn(...a);};
 }
 try {
    vm.runInContext(job.source+'\nmain();',scope,{timeout:180000,filename:'archived-4685.js'});
    assert.fail('unexpected early return');
 } catch(e) {if(e!==STOP){throw Error(JSON.stringify({cause:String(e.stack||e),safetyLog:logs.slice(-10),requests,market:market.slice(-12),now:now(),leaks:observations.slice(-3),mode}));}}
 for(let n=0;n<coins.length;n++) {
    const c=coins[n]; const api=raw[n];
    ledgers[c].ending=update(c,api,'end');
    assert.equal(api.GetOrders().length,0);
 }
 assert.ok(now()>=end && now()<end+STEP);
 return {mode,start,end,settings,requests,now:now(),sleepCalls,templates,market,logs,ledgers};
}

(async()=>{
 await new Promise(r=>setTimeout(r,500));
 const raw=read('round29-4685-input.json.gz');const job=JSON.parse(gunzipSync(raw));
 assert.equal(sha(job.source),job.source_sha256);assert.equal(sha(job.template),job.template_sha256);
 const runs=['single','author-two-legs'].map(mode=>run(job,mode,job.from_ms,job.to_ms));
 write('round29-4685-canonical.json',{input_sha256:sha(raw),source_sha256:job.source_sha256,
    engine_sha256:sha(read('fmz-wasm-engine.cjs')),template_sha256:job.template_sha256,runs});
})().catch(e=>{write('round29-4685-error.json',{message:String(e.stack||e)});process.exitCode=1;});
