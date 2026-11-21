'use strict';
process.env.TZ='UTC';
const fs=require('node:fs'), path=require('node:path'), assert=require('node:assert/strict');
const sha=b=>require('node:crypto').createHash('sha256').update(b).digest('hex');
const fmz=require('./fmz-wasm-engine.cjs');
const read=p=>fs.readFileSync(path.join(__dirname,p));
const write=(p,d)=>fs.writeFileSync(path.join(__dirname,p),JSON.stringify(d));

(async()=>{
  await new Promise(done=>setTimeout(done,450));
  const data=read('round45-5094-abi-input.json');
  const feed=JSON.parse(data);
  global.__offlineProbe=url=>{
    const q=new URL(url).searchParams;
    assert.equal(q.get('eid'),'Binance');
    assert.equal(q.get('period'),'60000');
    assert.equal(q.get('symbol'),'BTC_USDT');
    const from=Number(q.get('from'))*1000,to=Number(q.get('to'))*1000;
    return JSON.stringify({detail:feed.detail,schema:feed.schema,data:feed.data.filter(r=>from<=r[0]&&r[0]<=to)});
  };
  const ctx=fmz.VCtx({start:'2019-09-01 00:00:00',end:'2019-09-01 00:25:00',period:'1h',basePeriod:'1m',
    exchanges:[{eid:'Binance',currency:'BTC_USDT',fee:[0,0]}]});
  const s=ctx.scope, e=s.exchange;
  try{
    const clock=()=>s.Date.now();
    const reads=[];
    function observe(method,...args){
      const t=clock();const value=e[method](...args);reads.push({method,t,after:clock(),args,value});return value;
    }
    const account=observe('GetAccount');
    const ticker=observe('GetTicker');
    observe('GetDepth');
    const book=[];
    for(const [side,off] of [['Buy',-10],['Sell',10]]){
      for(const [dec,size] of [[.0049,.0100014],[.005,.0100055],[.0051,.0100096]]){
        const p=ticker.Last+off+dec;
        const id=observe(side,p,size);assert.ok(id);
        const native=observe('GetOrder',id);
        assert.equal(native.Status,0);
        const loaded=observe('GetOrders');assert.equal(loaded[0].Id,id);
        assert.ok(observe('CancelOrder',id));
        assert.equal(observe('GetOrder',id).Status,2);
        book.push({side,p,size,nativePrice:native.Price,nativeAmount:native.Amount});
      }
    }
    write('round45-5094-abi.json',{deposit:account,reads,rounding:book,engine_sha256:sha(read('fmz-wasm-engine.cjs')),input_sha256:sha(data)});
  } finally {ctx.Join();}
})().catch(e=>{write('round45-5094-abi-error.json',String(e.stack||e));process.exit(1);});
