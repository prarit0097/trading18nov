'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const assert=require('node:assert/strict'),crypto=require('node:crypto'),zlib=require('node:zlib');
const nativeProcess=require('node:process');
const engine=require('./fmz-wasm-engine.cjs');
const selected=nativeProcess.argv[3]||'halfyear';
const tail=nativeProcess.argv[4]==='audit';
const sha=x=>crypto.createHash('sha256').update(x).digest('hex');
const here=name=>path.join(__dirname,name);

function replay(job) {
  const {feeds}=job;
  const full=selected==='halfyear';
  assert.ok(full||selected==='may19');
  const start=full?job.begin_ms:Date.parse('2021-05-18T16:00:00Z');
  const end=full?job.end_ms:Date.parse('2021-05-19T16:00:00Z');
  const marketRequests=[];
  global.__offlineProbe=text=>{
    const url=new URL(text),q=url.searchParams;
    assert.equal(url.origin+url.pathname,'https://q.fmz.com/data/history');
    assert.equal(q.get('eid'),'Futures_Binance');
    const type=q.get('symbol').split('.').at(-1);
    assert.equal(q.get('period'),'300000');
    const from=+q.get('from')*1000,to=+q.get('to')*1000;
    assert.ok(feeds[type]&&q.get('symbol')==='ETH_USDT.'+type,text);
    const f=feeds[type];
    const data=f.data.filter(r=>from<=r[0]&&r[0]<=to);
    assert.ok(data.length);
    marketRequests.push([type,from,to,data.length,q.get('event')]);
    return JSON.stringify({...f,data});
  };
  const fmt=t=>new Date(t).toISOString().replace('T',' ').replace('.000Z',' +0000');
  const opts={start:fmt(start),end:fmt(end),period:'1d',basePeriod:'5m',
    exchanges:[{eid:'Futures_Binance',currency:'ETH_USDT',balance:10000,stocks:0,fee:[.008,.01]}]};
  const ctx=engine.VCtx(opts),s=ctx.scope,e=s.exchange;
  const now=()=>s.Date.now();
  assert.equal(now(),start);
  const contracts=[],orders=[],cancels=[],listedChanges=[],positions=[],phase=[];
  let direction,previous,lastPos,currentTicker;
  const c=e.SetContractType,sets=e.SetDirection,prec=e.SetPrecision;
  const g=e.GetOrders,p=e.GetPosition,x=e.GetTicker,cancel=e.CancelOrder;
  e.SetContractType=which=>{const ret=c(which);contracts.push([which,ret]);return ret;};
  e.SetDirection=d=>{direction=d;return sets(d);};
  e.SetPrecision=(...a)=>{phase.push([now(),'SetPrecision',a]);return prec(...a);};
  e.GetTicker=(...a)=>{const ret=x(...a);currentTicker=ret;return ret;};
  e.GetPosition=(...a)=>{
    const ret=p(...a);
    const subset=ret.map(x=>[x.Type,x.Amount,x.Price,x.CloseProfit]);
    const state=JSON.stringify(subset);
    if(state!==lastPos){positions.push([now(),ret]);lastPos=state;}
    return ret;
  };
  e.GetOrders=(...a)=>{
    const ret=g(...a),subset=ret.map(x=>[x.Id,x.Status,x.DealAmount,x.AvgPrice]);
    const state=JSON.stringify(subset);
    if(state!==previous){listedChanges.push([now(),ret]);previous=state;}
    return ret;
  };
  e.CancelOrder=(id,...a)=>{const ret=cancel(id,...a);cancels.push([now(),id,ret]);return ret;};
  for(const host of ['Buy','Sell']){
    const callback=e[host];
    e[host]=(p,q,...a)=>{
      const ret=callback(p,q,...a);
      orders.push([now(),host,direction,p,q,ret,currentTicker]);
      return ret;
    };
  }
  const audited=[];
  if(tail){
    assert.equal(selected,'may19');
    const sleeper=s.Sleep;
    s.Sleep=ms=>{
      const at=now();
      if(at>=end-600000&&at<end-70000&&!audited.length){
        const first=at;
        for(const [, , , , ,id] of orders) audited.push([now(),e.GetOrder(id)]);
        assert.ok(now()-first<60000&&now()<end-30000);
      }
      sleeper(ms);
    };
  }
  Object.assign(s,job.parameters);
  assert.equal(sha(Buffer.from(job.source)),job.source_sha256);
  let stop,exitClock;
  try{
    vm.runInNewContext(job.source+'\nmain();',s,{timeout:600_000,filename:'FMZ-4686.js',contextCodeGeneration:{strings:false,wasm:false}});
  }catch(e){stop=String(e);exitClock=now();}
  const raw=ctx.Join(),r=typeof raw==='string'?JSON.parse(raw):raw;
  return {scope:selected,start,end,exitClock,audited,marketRequests,contracts,orders,cancels,listedChanges,positions,phase,stop,
    completion:{Finished:r.Finished,Progress:r.Progress,Time:r.Time,Status:r.Status,TaskStatus:r.TaskStatus},
    snapshots:r.Snapshots,nativeLogs:r.RuntimeLogs,profit:r.Profit};
}
setTimeout(()=>{
  try{
    const raw=fs.readFileSync(here('r55-4686-input.json.gz'));
    const job=JSON.parse(zlib.gunzipSync(raw));
    const receipt={...replay(job),worker_sha256:sha(fs.readFileSync(__filename)),input_sha256:sha(raw),
      engine_sha256:sha(fs.readFileSync(here('fmz-wasm-engine.cjs')))};
    fs.writeFileSync(here(nativeProcess.argv[2]),zlib.gzipSync(JSON.stringify(receipt)));
  }catch(e){
    fs.writeFileSync(here('r55-4686-error.txt'),String(e.stack||e));
    nativeProcess.exitCode=1;
  }
},500);
