process.env.TZ='UTC';
const fs=require('node:fs'), path=require('node:path'), gzip=require('node:zlib');
const F=require('./fmz-wasm-engine.cjs');
const dir=__dirname;
new Promise(r=>setTimeout(r,450)).then(()=>{
  const input=JSON.parse(gzip.gunzipSync(fs.readFileSync(path.join(dir,'round31-1942-input.json.gz'))));
  const spec=input.scope['2021-06-01'];
  global.__offlineProbe=source=>{
    const p=new URL(source).searchParams,
        s=spec.market[p.get('symbol').split('.')[1]], from=1000*Number(p.get('from')),to=1000*Number(p.get('to'));
    return JSON.stringify({schema:s.schema,detail:s.detail,data:s.data.filter(r=>r[0]>=from&&r[0]<=to)});
  };
  const ctx=F.VCtx({start:'2021-06-01 00:00:00',end:'2021-06-01 01:00:00',period:'1m',basePeriod:'1m',
      exchanges:[{eid:'Futures_Binance',currency:'BTC_USDT'}]});
  const s=ctx.scope,E=s.exchange, r=[];
  const p=(name,...args)=>{const before=s.Date.now();let out;try{out=E[name](...args);}catch(e){out=String(e)}r.push([name,args,before,s.Date.now(),out]);return out;};
  p('SetContractType','swap');p('GetAccount');p('SetMarginLevel',50);p('GetPosition');p('GetTicker');
  p('SetDirection','buy');p('Sell',-1,0.001);p('GetPosition');p('GetAccount');p('SetDirection','buy');p('Buy',-1,0.001);p('GetPosition');
  p('SetDirection','closebuy');p('Sell',-1,0.001);p('GetPosition');p('GetHistoryOrders','BTC_USDT.swap',s.Date.now()-60000,100);
  ctx.Join();fs.writeFileSync(path.join(dir,'r34-native-binance-host-contract.json'),JSON.stringify(r,null,2));
}).catch(e=>{fs.writeFileSync(path.join(dir,'r34-native-binance-host-error.log'),String(e.stack||e));process.exitCode=1;});
