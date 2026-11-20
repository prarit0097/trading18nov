const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createHash} = require('node:crypto');
const {gunzipSync} = require('node:zlib');
const Library = require('./fmz-wasm-engine.cjs');

const HOUR=3600;
const US=1_000_000;
const END=Symbol('fixed scope complete');
const FACE=10;
const filename=name=>path.join(__dirname,name);
const read=name=>fs.readFileSync(filename(name));
const write=(name,payload)=>fs.writeFileSync(filename(name),JSON.stringify(payload));
const sha=raw=>createHash('sha256').update(raw).digest('hex');

function replay(day,spec,job,core) {
    const settings=job.author.settings;
    const fee=Number(job.fee);
    const leverage=settings.MarginLevel;
    const rows=spec.samples;
    const records=spec.history.map(([t,o,h,l,c,v])=>({Time:t*1000,Open:o,High:h,Low:l,Close:c,Volume:v}));
    const cashStart=Number(job.starting_cash_eth);
    let cash=cashStart, qty=0, entry=0, direction=null, i=0, signal=null, historicSeen=0;
    let lastFillClock=-1, sameSide=[0,0], criticalDepth=Infinity, minimumExcess=Infinity;
    const orders=[], path=[], signals=[], settingsEvents=[], saved=new Map();
    const counts={record:0,ticker:0,orders:0,sleep:0,ema:0,std:0,profit:0,commands:0};
    const sample=()=>rows[i];
    const now=()=>sample()[0];
    const mark=()=>sample()[3][2];
    const trade=()=>sample()[1];
    const currentExposure=price=>Math.abs(qty)*FACE/price;
    const pnl=price=>qty?qty*FACE*(1/entry-1/price):0;
    const input = () => {
        const tr=trade();
        assert.ok(tr[0]<=now()*US && tr[1]<=now()*US);
        const active={Time:tr[2]*1000,Open:tr[3],High:tr[4],Low:tr[5],Close:tr[6],Volume:tr[7]};
        if(records.at(-1).Time<active.Time) {
            assert.equal(active.Time-records.at(-1).Time,HOUR*1000);
            records.push(active);
        } else {
            assert.equal(records.at(-1).Time,active.Time);
            records[records.length-1]=active;
        }
        return records;
    };
    const account=()=>({Stocks:cash-currentExposure(trade()[6])/leverage,FrozenStocks:0});
    const ticker=()=>{counts.ticker++;const r=sample();return {Last:r[1][6],Buy:r[2][2],Sell:r[2][3]};};
    const position=()=>qty?[{Amount:Math.abs(qty),Price:entry,Type:qty>0?0:1}]:[];
    const precision=(v,n)=>core._N(v,n);

    function send(side,px,amount) {
        counts.orders++;
        assert.equal(px,-1);
        assert.ok(amount>0&&Number.isInteger(amount));
        const [t,tr,q,m]=sample();
        const open=direction==='buy'||direction==='sell';
        const isBuy=side===1;
        const leg=isBuy?1:0;
        assert.equal(qty,open?0:-side*amount);
        assert.equal(direction,isBuy?(open?'buy':'closesell'):(open?'sell':'closebuy'));
        assert.ok(q[1]<=t*US && q[0]<=t*US && q[2]<q[3]);
        const observedAge=t*US-q[0];
        if(lastFillClock!==t){sameSide=[0,0];lastFillClock=t;}
        sameSide[leg]+=amount;
        const remainingDepth=q[leg+6]-sameSide[leg];
        if(observedAge>job.age_max_us || q[leg+8]!==true || remainingDepth<0)
            throw Error(JSON.stringify({historicalFillBarrier:day,at:t,direction,amount,quote:q,observedAge,remainingDepth,orders}));
        criticalDepth=Math.min(criticalDepth,remainingDepth);
        const fill=q[2+leg];
        const cost=amount*FACE/fill*fee;
        const execution=side*amount*FACE*(1/tr[6]-1/fill);
        let gross=0;
        if(open) {
            assert.equal(amount,precision(cashStart*0.5*leverage*tr[6]/FACE,0));
            assert.ok(cash>=amount*FACE/fill/leverage+cost);
            qty=side*amount; entry=fill;
        } else {
            gross=pnl(fill);
            qty=0;entry=0;
        }
        cash+=gross-cost;
        orders.push({at:t,direction,side,amount,fill,fee:cost,execution,gross,cash,qty,open,quote:q,
            ether_mark:m[2],last:tr[6],chart:records.at(-1).Time,ema_status:context._PriceCrossEMAStatus,remainingDepth});
        direction=null;
        return orders.length;
    }

    function point() {
        const t=now(), m=mark();
        const unrealized=pnl(m);
        const excess=cash+unrealized-currentExposure(m)*(0.004+fee);
        minimumExcess=Math.min(minimumExcess,excess);
        assert.ok(excess>0);
        path.push([t,cash,qty,entry,m,unrealized]);
    }

    const TA={EMA(a,n){
        assert.equal(n,90); counts.ema++;
        const out=core.TA.EMA(a,n);
        assert.ok(Number.isFinite(out.at(-2)));
        signal={time:now(),bar:a.at(-1).Time,previous_close:a.at(-2).Close,ema:out.at(-2),
                active_high:a.at(-1).High,active_low:a.at(-1).Low};
        return out;
    }};
    const talib={STDDEV(a,n,k){
        assert.equal(n,33); assert.equal(k,1); counts.std++;
        const out=core.talib.STDDEV(a,n,k);
        Object.assign(signal,{std:out.at(-1),previous_std:out.at(-2),ema_cross:context._PriceCrossEMAStatus});
        assert.notEqual(signal.bar,historicSeen);
        historicSeen=signal.bar;
        signals.push(signal);
        return out;
    }};
    const exchange={
        SetContractType(value){assert.equal(value,'quarter');settingsEvents.push(['contract',value]);},
        SetMarginLevel(value){assert.equal(value,5);settingsEvents.push(['leverage',value]);},
        SetPrecision(a,b){assert.deepEqual([a,b],[2,0]);settingsEvents.push(['precision',a,b]);},
        SetDirection(value){assert.equal(direction,null);direction=value;},
        GetRecords(sec){assert.equal(sec,HOUR);counts.record++;return input();},
        GetTicker:ticker, GetAccount:account, GetPosition:position,
        GetLabel:()=>job.symbol, GetCurrency:()=>settings.TradeCurrency,
        Buy(p,n){return send(1,p,n);}, Sell(p,n){return send(-1,p,n);},
    };
    const context={...settings,exchange,TA,talib,_C:(f,...args)=>f(...args),_N:precision,_D:t=>String(t),Unix:now,
        IsVirtual:()=>true,PD_LONG:0,PD_SHORT:1,GetCommand(){counts.commands++;return null;},
        Log(){},LogStatus(){},LogProfit(){counts.profit++;},
        _G(...args){const [key,value]=args;if(args.length===2)saved.set(key,structuredClone(value)); return saved.get(key)??null;},
        Sleep(ms){assert.equal(ms,5000);counts.sleep++;point();i++;if(i===rows.length-1) throw END;},
    };
    vm.createContext(context,{codeGeneration:{strings:false,wasm:false}});
    try {vm.runInContext(job.source+'\nmain();',context,{timeout:24000});assert.fail('unexpected strategy exit');}
    catch(e){if(e!==END)throw e;}
    point();
    assert.equal(path.length,rows.length);
    assert.equal(context._TradeCount,orders.filter(o=>!o.open).length);
    assert.equal(counts.profit,context._TradeCount);
    assert.equal(signals.length,new Set(rows.slice(0,-1).map(r=>r[1][2])).size);
    return {day,signals,orders,path,counts,settingsEvents,criticalDepth:Number.isFinite(criticalDepth)?criticalDepth:null,minimumExcess,
        ending:{cash,qty,entry,mark:mark(),unrealized:pnl(mark())}};
}

(async()=>{
    await new Promise(r=>setTimeout(r,250));
    let req=0;
    global.__offlineProbe=()=>{req++;throw Error('Network denied');};
    const core=Library.VCtx({start:'2021-10-01 00:00:00',end:'2021-10-02 00:00:00',period:'1h',basePeriod:'5m',
                  exchanges:[{eid:'Futures_Binance',currency:'ETH_USD',balance:0,stocks:0.02}]}).scope;
    assert.equal(core._N(2.9,0),2);
    const raw=read('round27-5398-input.json.gz');
    const job=JSON.parse(gunzipSync(raw));
    assert.equal(sha(job.source),job.source_sha256);
    const results=Object.entries(job.scope).map(([d,s])=>replay(d,s,job,core));
    assert.equal(req,0);
    write('round27-5398-receipt.json',{input_sha256:sha(raw),source_sha256:job.source_sha256,native_engine_sha256:sha(read('fmz-wasm-engine.cjs')),requests:req,results});
})().catch(e=>{write('round27-5398-error.json',{message:String(e.stack||e)});process.exitCode=1;});
