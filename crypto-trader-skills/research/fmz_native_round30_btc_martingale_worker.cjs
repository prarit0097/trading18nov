process.env.TZ='UTC';
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const assert=require('node:assert/strict');
const {createHash}=require('node:crypto');
const {gunzipSync}=require('node:zlib');
const FMZ=require('./fmz-wasm-engine.cjs');
const H=3600000;
const DAY=24*H;
const STOP=Symbol('fixed stop');
const sha=b=>createHash('sha256').update(b).digest('hex');
const read=f=>fs.readFileSync(path.join(__dirname,f));
const write=(f,v)=>fs.writeFileSync(path.join(__dirname,f),JSON.stringify(v));
const time=t=>new Date(t).toISOString().slice(0,19).replace('T',' ');

function run(job,id,short) {
    const study=job.source[id];
    const begin=job.start;
    const end=short?job.start+7*DAY:study.end;
    const requests=[];
    global.__offlineProbe=urlString=>{
        const url=new URL(urlString);
        const q=url.searchParams;
        const alias=q.get('symbol').split('.')[1];
        const period=Number(q.get('period'));
        const event=q.get('event');
        const from=Number(q.get('from'))*1000;
        const to=Number(q.get('to'))*1000;
        const kind=event==='fill'&&alias==='swap'&&period>H?(period===4*H?'fill4h':'fill1d'):alias;
        const market=job.market[kind];
        assert.equal(q.get('eid'),'Futures_Binance');
        assert.equal(q.get('symbol').split('.')[0],'BTC_USDT');
        const data=market.data.filter(r=>from<=r[0]&&r[0]<=to);
        assert.ok(data.length,urlString);
        requests.push({event,kind,period,from,to,rows:data.length,url:urlString});
        return JSON.stringify({data,detail:market.detail,schema:market.schema});
    };
    const v=FMZ.VCtx({start:time(begin),end:time(end+H),basePeriod:'1h',period:'1d',
        exchanges:[{eid:'Futures_Binance',currency:'BTC_USDT',balance:job.balance,stocks:0,fee:job.fee_pct,lever:20,slippage:0}]});
    const s=v.scope;
    const ex=s.exchange;
    const n=Object.fromEntries(['GetTicker','GetPosition','GetAccount','GetOrders','GetOrder','GetHistoryOrders','GetRecords',
        'Buy','Sell','SetDirection','CancelOrder','SetMarginLevel','SetPrecision'].map(k=>[k,ex[k]]));
    const nativeSleep=s.Sleep;
    const now=()=>s.Date.now();
    assert.equal(now(),begin);
    let direction,ticker,sleepCalls=0,candles=0,tickCalls=0,unsupported=0;
    let bookPosition=[], latestRecordTime;
    const positions=[],submits=[],cancels=[],prices=[],filledStates=[],marks=[];
    const recorded=new Map();
    const maxRecords=[];
    const guard=()=>{if(now()>=end)throw STOP;};
    ex.GetTicker=(...a)=>{
        guard();tickCalls++;
        const result=n.GetTicker(...a);
        if (result) {
            assert.ok(result.Time<=now());
            ticker=[result.Time,result.Last,result.Buy,result.Sell];
            if(!prices.length||prices.at(-1)[0]!==ticker[0]) prices.push(ticker);
        }
        return result;
    };
    ex.GetRecords=(seconds)=>{
        guard();candles++;
        assert.equal(seconds,study.record_hours*3600);
        const bars=n.GetRecords(seconds);
        assert.ok(bars&&bars.length>=26);
        const current=bars.at(-1).Time;
        assert.ok(current<=now());
        if(current!==latestRecordTime) {
            latestRecordTime=current;
            maxRecords.push([now(),current,bars.length,bars.at(-2).Time,
                bars.at(-2).Open,bars.at(-2).High,bars.at(-2).Low,bars.at(-2).Close]);
        }
        return bars;
    };
    ex.GetAccount=(...a)=>{
        const r=n.GetAccount(...a);
        if(r) {
            const values=[r.Balance,r.FrozenBalance,r.Equity,r.UPnL];
            assert.ok(values.every(Number.isFinite));
            if(marks.length===0||values.some((value,i)=>value!==marks.at(-1)[1+i])) marks.push([now(),...values]);
        }
        return r;
    };
    ex.GetPosition=(...a)=>{
        const r=n.GetPosition(...a);
        if(r) {
            assert.ok(r.length<=1);
            const p=r.map(v=>[v.Type,v.Amount,v.Price,v.Margin,v.Profit,v.MarginLevel]);
            if(!positions.length||JSON.stringify(p.map(v=>v.slice(0,4)))!==JSON.stringify(positions.at(-1)[1].map(v=>v.slice(0,4)))) {
                positions.push([now(),p]);
            }
            bookPosition=p;
        }
        return r;
    };
    ex.GetOrder=(id)=>{
        const order=n.GetOrder(id);
        if(order&&order.Status!==0&&!recorded.has(id)) {
            recorded.set(id,order.Status);
            filledStates.push([now(),id,order.Status,order.DealAmount,order.AvgPrice]);
        }
        return order;
    };
    ex.SetDirection=key=>{direction=key;return n.SetDirection(key);};
    ex.SetMarginLevel=value=>{assert.equal(value,20);return n.SetMarginLevel(value);};
    ex.SetPrecision=(price,qty)=>{assert.deepEqual([price,qty],[5,3]);return n.SetPrecision(price,qty);};
    for(const side of ['Buy','Sell']) {
        ex[side]=(price,amount,...args)=>{
            guard();
            assert.ok(ticker&&Number.isFinite(amount)&&amount>0);
            const t=now();
            const id=n[side](price,amount,...args);
            submits.push({before:t,after:now(),side,direction,ticker,price,amount,id,position:bookPosition});
            return id;
        };
    }
    ex.CancelOrder=(id,...rest)=>{
        const t=now(), result=n.CancelOrder(id,...rest);
        cancels.push([t,id,result]);
        return result;
    };
    s.Sleep=ms=>{guard();sleepCalls++;return nativeSleep(Math.min(end-now(),ms));};
    s.Log=()=>{};s.LogStatus=()=>{};s.LogProfit=()=>{};
    s.GetCommand=()=>null;
    s.HttpQuery=()=>{unsupported++;throw Error('A live-only branch requested network');};
    const memory=new Map();
    s._G=(...a)=>{
        const [key,value]=a;
        if(a.length===1&&key===null){memory.clear();return null;}
        if(a.length===2){memory.set(key,value===undefined?null:structuredClone(value));return value;}
        return memory.get(key)??null;
    };
    Object.assign(s,study.params);
    vm.createContext(s,{codeGeneration:{strings:false,wasm:false}});
    try {
        vm.runInContext(study.source+'\nmain();',s,{timeout:180000,filename:'source-'+id+'.js'});
        assert.fail('source returned early');
    } catch(e) {
        if(e!==STOP) throw Error(JSON.stringify({cause:String(e.stack||e),id,now:now(),requests,orders:submits.slice(-3)}));
    }
    const endingTicker=n.GetTicker();
    const endingAccount=n.GetAccount();
    const endingPosition=n.GetPosition();
    const pending=n.GetOrders();
    const history=[];
    let since=begin;
    for(let i=0;i<100;i++){
        const page=n.GetHistoryOrders('BTC_USDT.swap',since,100);
        assert.ok(Array.isArray(page));
        history.push(...page);
        if(page.length<100)break;
        since=Math.max(...page.map(o=>o.Time))+1;
        assert.ok(i<99);
    }
    const unique=new Set(history.map(x=>x.Id));
    assert.equal(history.length,unique.size);
    assert.ok(pending.every(x=>!unique.has(x.Id)||history.some(o=>o.Id===x.Id&&o.Status===0)));
    assert.equal(unsupported,0);
    return {id,begin,end,requests,ending:{now:now(),ticker:endingTicker,account:endingAccount,position:endingPosition,pending},
        history,submits,cancels,positions,filledStates,marks,prices,maxRecords,counts:{sleepCalls,candles,tickCalls}};
}

(async()=>{
    await new Promise(r=>setTimeout(r,500));
    const raw=read('round30-btc-martingale-input.json.gz');
    const job=JSON.parse(gunzipSync(raw));
    for(const id of ['4834','4835'])assert.equal(sha(job.source[id].source),job.source[id].code_sha256);
    const short=process.argv.at(-1)==='quick';
    const results=['4834','4835'].map(id=>run(job,id,short));
    write(short?'round30-btc-martingale-quick.json':'round30-btc-martingale-receipt.json',
        {input_sha256:sha(raw),engine_sha256:sha(read('fmz-wasm-engine.cjs')),results});
})().catch(e=>{write('round30-btc-martingale-error.txt',String(e.stack||e));process.exitCode=1;});
