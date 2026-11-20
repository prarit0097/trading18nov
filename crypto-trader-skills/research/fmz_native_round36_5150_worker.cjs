process.env.TZ='UTC';
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const {gunzipSync}=require('node:zlib');
const {createHash}=require('node:crypto');
const fmz=require('./fmz-wasm-engine.cjs');
const STOP=Symbol('four-hour cutoff');
const read=f=>fs.readFileSync(path.join(__dirname,f));
const write=(f,v)=>fs.writeFileSync(path.join(__dirname,f),JSON.stringify(v));
const sha=b=>createHash('sha256').update(b).digest('hex');
const moment=ms=>new Date(ms).toISOString().slice(0,19).replace('T',' ');

function run(source,spec){
    const requests=[];
    global.__offlineProbe=url=>{
        const uri=new URL(url);
        const q=uri.searchParams;
        const [coin,key]=q.get('symbol').split('.');
        assert.equal(uri.origin+uri.pathname,'https://q.fmz.com/data/history');
        assert.ok(coin==='BTC_USDT'&&['swap','index','funding'].includes(key));
        assert.equal(q.get('eid'),'Futures_Binance');
        assert.equal(Number(q.get('period')),3600000);
        const from=Number(q.get('from'))*1000,to=Number(q.get('to'))*1000;
        const market=spec.data[key];
        const out=market.data.filter(row=>from<=row[0]&&row[0]<=to);
        assert.ok(out.length);
        requests.push({key,from,to,rows:out.length});
        return JSON.stringify({data:out,detail:market.detail,schema:market.schema});
    };
    const ctx=fmz.VCtx({start:moment(spec.begin),end:moment(spec.end+3600000),period:'1d',basePeriod:'1h',
        exchanges:[{eid:'Futures_Binance',currency:'BTC_USDT'}]});
    const s=ctx.scope,E=s.exchange, now=()=>s.Date.now();
    const a={get:E.GetPosition,sell:E.Sell,buy:E.Buy,e:E.GetAccount,orders:E.GetHistoryOrders,side:E.SetDirection};
    let direction=null, draws=0,buy_attempts=0,short_attempts=0,setupCalls=0,empty_positions=0, lastShortClock=null,firstShortClock=null;
    const rules=[];
    function guard(){if(now()>=spec.end)throw STOP;}
    E.SetDirection=d=>{direction=d;return a.side(d);};
    E.GetPosition=()=>{
        guard();const before=now(); const out=a.get();
        assert.equal(now()-before,200);
        assert.deepEqual(out,[]);
        empty_positions++;
        return out;
    };
    E.Sell=(px,qty,...other)=>{
        guard();assert.equal(direction,'sell');assert.equal(px,-1);assert.equal(qty,100);
        const before=now();const attempted=a.sell(px,qty,...other);
        assert.equal(now()-before,200);
        assert.equal(attempted,null);
        short_attempts++;
        firstShortClock??=now();
        lastShortClock=now();
        return attempted;
    };
    E.Buy=(...p)=>{buy_attempts++;assert.fail('source should never enter long at archived defaults');};
    for(const [k,v] of Object.entries(source.defaults)) {assert.ok(!(k in s));s[k]=v;}
    const m=Object.create(Math);
    Object.defineProperty(m,'random',{value:()=>++draws%2 ? 0.25 : 0.75});
    Object.assign(s,{Math:m,Log(){},LogProfit(){},Sleep(){assert.fail('flat rejection loop must not sleep');}});
    const n=E.SetMarginLevel;
    E.SetMarginLevel=(leverage)=>{assert.equal(leverage,50);setupCalls++;return n(leverage);};
    try{
        try {
            vm.createContext(s,{codeGeneration:{strings:false,wasm:false}});
            vm.runInContext(source.script+'\nmain();',s,{timeout:90000,filename:'FMZ-5150.js'});
            assert.fail('source returned');
        }catch(e){if(e!==STOP)throw e;}
        assert.equal(now(),spec.end);
        const cutoff=now(), account=a.e(), final=a.get(),history=a.orders('BTC_USDT.swap',spec.begin,30);
        assert.deepEqual(final,[]);assert.deepEqual(history,[]);
        assert.equal(account.Balance,10000);assert.equal(account.Equity,10000);assert.equal(account.UPnL,0);
        return {short_attempts,buy_attempts,empty_positions,draws,setupCalls,firstShortClock,lastShortClock,cutoff,account,final,history,requests};
    }finally{ctx.Join();}
}

(async()=>{
    await new Promise(resolve=>setTimeout(resolve,450));
    const input=read('round36-martingale-input.json.gz');
    const job=JSON.parse(gunzipSync(input));
    assert.equal(sha(job.sources[5150].script),job.sources[5150].script_sha256);
    const rows={};
    for(const [day,spec] of Object.entries(job.native_hourly))rows[day]=run(job.sources[5150],spec);
    write('round36-5150-native-receipt.json',{input_sha256:sha(input),native_engine_sha256:sha(read('fmz-wasm-engine.cjs')),rows});
})().catch(e=>{write('round36-5150-native-error.json',String(e.stack||e));process.exit(1);});
