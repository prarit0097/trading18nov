process.env.TZ='UTC';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {gunzipSync}=require('node:zlib');
const {createHash}=require('node:crypto');
const fmz=require('./fmz-wasm-engine.cjs');
const read=f=>fs.readFileSync(path.join(__dirname,f));const write=(f,v)=>fs.writeFileSync(path.join(__dirname,f),JSON.stringify(v));
const sha=b=>createHash('sha256').update(b).digest('hex');
(async()=>{
 await new Promise(r=>setTimeout(r,450));
 const data=read('round33-4899-input.json.gz');assert.equal(sha(data),'648652411370c83bfaa64e038ae3b360d0d66139aecde8d6f328b61b607720fe');
 const want=JSON.parse(gunzipSync(data)).scope['2021-05-01'];
 global.__offlineProbe=url=>{
   const q=new URL(url).searchParams;const [symbol,key]=q.get('symbol').split('.');assert.equal(symbol,'ETH_USDT');
   const from=1000*Number(q.get('from')),to=1000*Number(q.get('to'));const m=want.market[key];
   return JSON.stringify({detail:m.detail,schema:m.schema,data:m.data.filter(r=>from<=r[0]&&r[0]<=to)});
 };
 const ctx=fmz.VCtx({start:'2021-05-01 00:00:00',end:'2021-05-01 01:00:00',period:'30m',basePeriod:'15m',
    exchanges:[{eid:'Futures_Binance',currency:'ETH_USDT'}]});
 const s=ctx.scope,E=s.exchange;
 const prices=[3304.3149999999996,3304.315,3304.3150000000005,3304.3149,3304.3151];
 const replay=read('round41-2693-first.json');
 const captured=JSON.parse(replay).results.flatMap(w=>w.events.filter(e=>e.kind==='placement'&&e.desired>0).map(e=>e.desired));
 const values=[...new Set([...prices,...captured])];
 try{
   E.SetContractType('swap');E.SetPrecision(2,3);E.SetMarginLevel(10);
   const center=E.GetTicker().Last;
   const calls=[];
   for(const desired of values){
      const buy=desired<center;
      E.SetDirection(buy?'buy':'sell');
      const id=(buy?E.Buy:E.Sell)(desired,.014);assert.ok(id);
      const o=E.GetOrder(id);assert.equal(o.Status,0);assert.equal(o.Amount,.014);
      calls.push({desired,native:o.Price,nearest_js_binary:Math.round(desired*100)/100});
      assert.ok(E.CancelOrder(id));
   }
   write('round41-2693-rounding-control.json',{virtual:s.IsVirtual(),default_balance:E.GetAccount().Balance,
     engine_sha256:sha(read('fmz-wasm-engine.cjs')),input_sha256:sha(data),replay_receipt_sha256:sha(replay),calls});
 }finally{ctx.Join();}
})().catch(e=>{write('round41-2693-rounding-error.json',String(e.stack||e));process.exit(1);});
