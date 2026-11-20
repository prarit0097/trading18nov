process.env.TZ='UTC';
const fs=require('node:fs');
const path=require('node:path');
const zip=require('node:zlib');
const assert=require('node:assert/strict');
const F=require('./fmz-wasm-engine.cjs');
const {createHash}=require('node:crypto');
const read=n=>fs.readFileSync(path.join(__dirname,n));
const write=(n,v)=>fs.writeFileSync(path.join(__dirname,n),JSON.stringify(v));
const sha=v=>createHash('sha256').update(v).digest('hex');
(async()=>{
    await new Promise(resolve=>setTimeout(resolve,450));
    const raw=read('round31-1942-input.json.gz');
    assert.equal(sha(raw),'87a1a5d9bc818c85656248891f49d74bd62dd251b12e70f0ce606e750fb2245c');
    const job=JSON.parse(zip.gunzipSync(raw));
    const spec=job.scope['2021-06-01'];
    global.__offlineProbe=url=>{
        const q=new URL(url).searchParams;
        const m=spec.market[q.get('symbol').split('.')[1]];
        assert.ok(m && q.get('eid')==='Futures_Binance');
        const from=1000*Number(q.get('from')), to=1000*Number(q.get('to'));
        return JSON.stringify({schema:m.schema,detail:m.detail,data:m.data.filter(r=>from<=r[0]&&r[0]<=to)});
    };
    const ctx=F.VCtx({start:'2021-06-01 00:00:00',end:'2021-06-01 01:00:00',period:'1m',basePeriod:'1m',
        exchanges:[{eid:'Futures_Binance',currency:'BTC_USDT'}]});
    const s=ctx.scope, E=s.exchange;
    const checks=[];
    function probe(k,arg=[]){
        const before=s.Date.now();
        let result=E[k](...arg);
        const at=s.Date.now();
        if(k==='GetDepth')result={topBid:result.Bids[0],topAsk:result.Asks[0],bidLevels:result.Bids.length,askLevels:result.Asks.length};
        checks.push({k,arg,before,at,result});
        return result;
    }
    try{
        probe('SetContractType',['swap']);probe('SetMarginLevel',[20]);
        probe('GetAccount');probe('GetDepth');probe('GetPosition');probe('SetDirection',['buy']);
        probe('Buy',[-1,0.015]);probe('GetPosition');probe('SetDirection',['closebuy']);probe('Sell',[-1,0.015]);probe('GetPosition');
        probe('GetHistoryOrders',['BTC_USDT.swap',spec.begin,100]);
        assert.equal(checks[3].at-checks[3].before,200);
    }finally{ctx.Join();}
    write('round35-197-native-control.json',{market_sha256:sha(raw),engine_sha256:sha(read('fmz-wasm-engine.cjs')),checks});
})().catch(e=>{write('round35-197-native-control-error.json',String(e.stack||e));process.exit(1);});
