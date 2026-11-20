process.env.TZ='UTC';
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const {createHash}=require('node:crypto');
const {gunzipSync}=require('node:zlib');
const FMZ=require('./fmz-wasm-engine.cjs');

const STOP=Symbol('fixed cutoff');
const H=3600000;
const STEP=60000;
const time=t=>new Date(t).toISOString().slice(0,19).replace('T',' ');
const read=f=>fs.readFileSync(path.join(__dirname,f));
const write=(f,v)=>fs.writeFileSync(path.join(__dirname,f),JSON.stringify(v));
const sha=b=>createHash('sha256').update(b).digest('hex');

function session(job,spec) {
    const asks=[];
    global.__offlineProbe=u=>{
        const url=new URL(u), q=url.searchParams;
        const kind=q.get('symbol').split('.')[1];
        const market=spec.market[kind];
        assert.ok(['swap','index','funding'].includes(kind));
        assert.equal(q.get('symbol').split('.')[0],'BTC_USDT');
        assert.equal(q.get('eid'),'Futures_Binance');
        assert.equal(Number(q.get('period')),STEP);
        const from=Number(q.get('from'))*1000,to=Number(q.get('to'))*1000;
        const data=market.data.filter(r=>from<=r[0]&&r[0]<=to);
        assert.ok(data.length);
        asks.push([kind,q.get('event'),from,to,data.length]);
        return JSON.stringify({data,schema:market.schema,detail:market.detail});
    };
    const context=FMZ.VCtx({start:time(spec.begin),end:time(spec.end+STEP),period:'1m',basePeriod:'1m',
        exchanges:[{eid:'Futures_Binance',currency:'BTC_USDT',balance:job.wallet_USDT,stocks:0,fee:job.fees_pct,lever:10,slippage:0}]});
    assert.equal(context.scope.Date.now(),spec.begin);
    return {scope:context.scope,asks};
}

function tape(job,spec) {
    const {scope,asks}=session(job,spec);
    const prices=[];
    while(scope.Date.now()<=spec.end) {
        const t=scope.exchange.GetTicker();
        assert.ok(t&&t.Time<=scope.Date.now());
        if(!prices.length||prices.at(-1)[0]!==t.Time) prices.push([t.Time,t.Last,t.Buy,t.Sell]);
        assert.ok(prices.length<30_000);
    }
    assert.ok(prices.length>5000 && prices.at(-1)[0]>=spec.end);
    return {prices,asks};
}

function probeFunding(job,spec,side) {
    const {scope,asks}=session(job,spec);
    const E=scope.exchange;
    const now=()=>scope.Date.now();
    E.SetContractType('swap'); E.SetDirection(side==='long'?'buy':'sell');
    const o=E[side==='long'?'Buy':'Sell'](-1,0.001);
    const long=E.GetOrder(o);
    assert.ok(long&&long.Status===1&&long.DealAmount===0.001);
    const settle=[];
    function account() {
        const a=E.GetAccount();const [pos]=E.GetPosition();
        assert.equal(pos.Amount,0.001); assert.equal(pos.Type,side==="long"?0:1);
        const wallet=a.Equity-a.UPnL;
        assert.ok(Math.abs(wallet-(a.Balance+a.FrozenBalance+pos.Margin))<1e-8);
        return [now(),wallet,a,pos];
    }
    for(const hour of [8,16,24]) {
        const at=spec.begin+hour*H;
        scope.Sleep(at-5000-now());
        const before=account();
        scope.Sleep(at+4500-now());
        const after=account();
        settle.push({at,before,after,held:0.001});
    }
    return {settle,asks};
}

function replay(day,job,spec,observeFunds) {
    const {scope,asks}=session(job,spec);
    const E=scope.exchange;
    const n=Object.fromEntries(['GetTicker','GetOrder','GetPosition','GetAccount','SetDirection','GetOrders','Buy','Sell','CancelOrder',
                    'GetHistoryOrders'].map(k=>[k,E[k]]));
    const sleep=scope.Sleep;
    const now=()=>scope.Date.now();
    let direction,ticker;
    const submitted=[],settled=[],seen=new Map(),queries=[],cancel=[];
    let sleepCalls=0, orderStatusQueries=0, ticks=0; const fundingObservations=[];
    function guard() {if(now()>=spec.end)throw STOP;}
    E.GetTicker=(...a)=>{
        guard();ticks++;
        const r=n.GetTicker(...a);
        if(r)ticker=[r.Time,r.Last,r.Buy,r.Sell];
        if(ticker&&queries.at(-1)?.[0]!==ticker[0])queries.push(ticker);
        return r;
    };
    E.SetDirection=x=>{direction=x;return n.SetDirection(x);};
    E.GetOrder=id=>{
        guard();orderStatusQueries++;
        const r=n.GetOrder(id);
        if(!r)return r;
        const state={get_ms:now(),status:r.Status,deal:r.DealAmount};
        if(r.Status!==0) {
            if(!settled.some(x=>x.id===id))settled.push({id,last_pending:seen.get(id)??null,first_terminal:state,order:r});
        } else seen.set(id,state);
        return r;
    };
    E.CancelOrder=(id,...a)=>{
        guard();const at=now();const result=n.CancelOrder(id,...a);
        cancel.push([id,at,now(),result]);
        return result;
    };
    for(const side of ['Buy','Sell'])
        E[side]=(price,qty,...a)=>{
            guard();
            assert.ok(ticker&&price===ticker[1]&&qty>0);
            const before=now();const id=n[side](price,qty,...a);
            submitted.push({id,side,direction,before,after:now(),ticker,price,qty});
            return id;
        };
        scope.Sleep=ms=>{
        guard();assert.equal(ms,60000);sleepCalls++;
        const target=Math.min(now()+ms,spec.end);
        if(observeFunds) {
            for(const h of [observeFunds]) {
                const at=spec.begin+h*H;
                if(now()<=at-2000&&target>=at+2000) {
                    sleep(at-1500-now());
                    const prior=n.GetAccount();
                    sleep(at+1200-now());
                    const after=n.GetAccount();
                    const wallet=a=>a.Equity-a.UPnL;
                    fundingObservations.push([at,wallet(prior),wallet(after)]);
                }
            }
        }
        return sleep(target-now());
    };
    scope.Log=()=>{};scope.LogStatus=()=>{};scope.LogProfit=()=>{};
    vm.createContext(scope,{codeGeneration:{strings:false,wasm:false}});
    try {
        vm.runInContext(job.source+'\nmain();',scope,{timeout:120000,filename:'FMZ-1942.js'});
        assert.fail('source unexpectedly returned');
    } catch(e){if(e!==STOP)throw e;}
    const finalTicker=n.GetTicker();
    const account=n.GetAccount(); const positions=n.GetPosition();const pending=n.GetOrders();
    const history=[];
    let since=spec.begin;
    for(let page=0;page<100;page++) {
        const next=n.GetHistoryOrders('BTC_USDT.swap',since,100);
        assert.ok(Array.isArray(next));
        history.push(...next);
        if(next.length<100)break;
        since=Math.max(...next.map(r=>r.Time))+1;
        assert.ok(page<99);
    }
    assert.equal(finalTicker.Time,spec.end);
    assert.ok(now()<spec.end+2*STEP);
    assert.equal(new Set(history.map(o=>o.Id)).size,history.length);
    assert.equal(new Set(submitted.map(o=>o.id).filter(Boolean)).size,history.length+pending.length);
    return {day,submitted,settled,cancel,queries,history,asks,fundingObservations,position:{account,positions,pending,ticker:finalTicker,at:now()},
            counts:{sleepCalls,ticks,orderStatusQueries}};
}

(async()=>{
    await new Promise(r=>setTimeout(r,500));
    const raw=read('round31-1942-input.json.gz');
    const job=JSON.parse(gunzipSync(raw));
    assert.equal(sha(job.source),job.source_sha256);
    const results=[]; const obsArg=process.argv.at(-1); const observe=obsArg==="fund-observe8"?8:obsArg==="fund-observe16"?16:0;
    for(const [day,spec] of Object.entries(job.scope)) {
        const chart=tape(job,spec);
        const funding={long:probeFunding(job,spec,"long"),short:probeFunding(job,spec,"short")};
        const model=replay(day,job,spec,day==="2021-01-01"?observe:0);
        results.push({model,chart,funding});
    }
    write(observe?'round31-1942-observed-fund-'+observe+'.json':'round31-1942-receipt.json',{input_sha256:sha(raw),source_sha256:job.source_sha256,
        emitter_sha256:sha(read('fmz-wasm-engine.cjs')),results});
})().catch(e=>{write('round31-1942-error.txt',String(e.stack||e));process.exitCode=1;});
