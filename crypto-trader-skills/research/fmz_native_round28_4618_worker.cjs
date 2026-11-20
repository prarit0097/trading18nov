const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createHash} = require('node:crypto');
const {gunzipSync} = require('node:zlib');
const Library = require('./fmz-wasm-engine.cjs');

const END=Symbol('exclusive benchmark cutoff');
const US=1_000_000;
const P15=900;
const file=name=>path.join(__dirname,name);
const read=name=>fs.readFileSync(file(name));
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');

function backtest(day,spec,job,seed,math) {
    let i=0, balance=Number(job.cash_btc), position=0, entry=0, direction=null, rng=seed;
    let minExcess=balance, lastPlot=0;
    const maker=job.published_fees_pct[0]/100;
    const taker=job.published_fees_pct[1]/100;
    const fundingAt=spec.today+4*3600;
    const funds=spec.funding;
    const observed=funds.filter(x=>x[0]<=fundingAt*US && x[5]===fundingAt*US);
    const prior=observed.at(-1);
    const after=funds.find(x=>x[5]>fundingAt*US);
    assert.ok(prior&&after&&observed.every(o=>o[6]===prior[6]));
    const rate=Number(prior[6]);
    const orders=[], path=[], draws=[], cashflow=[], chart=[], seen=new Set();
    const count={records:0,ticker:0,account:0,position:0,plot:0,flag:0};
    const row=()=>spec.tape[i];
    const now=()=>row()[0];
    const pnl=p=>position?position*(1/entry-1/p):0;

    function point() {
        const p=row();
        const unreal=pnl(p[15]);
        const maint=Math.abs(position)/p[15]*(0.005+taker);
        const excess=balance+unreal-maint;
        minExcess=Math.min(minExcess,excess);
        assert.ok(excess>0);
        path.push([now(),balance,position,entry,p[15],unreal]);
    }

    function advance() {
        point();
        i++;
        if(now()===fundingAt) {
            const btc=-(position/prior[2])*rate;
            balance+=btc;
            cashflow.push({at:now(),position,rate,amount:btc,mark:prior[2],alternateMark:after[2],balance});
        }
        if(now()===spec.end) throw END;
        seen.clear();
    }

    function market(key, fn) {
        if(seen.has(key)) advance();
        assert.ok(!seen.has(key));
        seen.add(key); count[key]++;
        return fn();
    }

    function records() {
        return market('records',()=>{
            const time=Math.floor(now()/P15)*P15*1000;
            const last=row()[6];
            if(time!==lastPlot) {
                chart.push({Time:time,Open:last,High:last,Low:last,Close:last,Volume:0});
                lastPlot=time;
            } else {
                const c=chart.at(-1);
                c.High=Math.max(c.High,last);c.Low=Math.min(c.Low,last);c.Close=last;
            }
            return chart;
        });
    }

    function trade(sign,price,qty) {
        const t=now();
        const r=row(), q=spec.quote_horizons[i];
        const open=direction==='buy'||direction==='sell';
        const leg=sign===1?1:0;
        assert.equal(direction,sign===1?(open?'buy':'closesell'):(open?'sell':'closebuy'));
        assert.ok(Number.isInteger(qty)&&qty>0);
        assert.equal(position,open?0:-sign*qty);
        const at=r[9+leg];
        assert.equal(price,at);
        assert.ok(r[8]<=r[7]&&r[7]<=t*US&&t*US-r[7]<=5*US);
        assert.ok(r[10]>r[9]&&r[11+leg]>=qty);
        const delayed=q[2+leg]===true&&q[leg]>=qty;
        const fee=qty/price*taker;
        const referenceFee=qty/price*0.00075;
        const execution=sign*qty*(1/r[6]-1/price);
        let gross=0;
        if(open) {
            assert.ok(balance>qty/price/job.leverage+fee);
            position=sign*qty;
            entry=price;
        } else {
            gross=pnl(price);
            position=0;
            entry=0;
        }
        balance+=gross-fee;
        orders.push([t,direction,qty,price,fee,referenceFee,execution,gross,balance,position,delayed]);
        direction=null;
        return orders.length;
    }

    function random() {
        rng^=rng<<13;rng^=rng>>>17;rng^=rng<<5;
        const value=(rng>>>0)/4294967296;
        draws.push([now(),Math.floor(value*10),position]);
        return value;
    }

    const exchange={
        SetContractType(t){assert.equal(t,'XBTUSD');},
        GetAccount(){count.account++;return {Stocks:balance-Math.abs(position)/row()[6]/job.leverage};},
        GetPosition(){count.position++;return position?[{Type:position>0?0:1,Price:entry,Amount:Math.abs(position)}]:[];},
        GetRecords:records,
        GetTicker(){return market('ticker',()=>({Last:row()[6],Buy:row()[9],Sell:row()[10]}));},
        SetDirection(d){assert.equal(direction,null);direction=d;},
        Buy(p,n){return trade(1,p,n);},Sell(p,n){return trade(-1,p,n);},
    };
    const DateAt=class extends Date {
        constructor(...a){super(...(a.length?a:[now()*1000]));}
        static now(){return now()*1000;}
    };
    const sourceMath=Object.create(Math);
    Object.defineProperty(sourceMath,'random',{value:random});
    const context={...job.params,exchange,_N:math._N,Math:sourceMath,Date:DateAt,_CDelay(n){assert.equal(n,100);},
        $:{PlotRecords(){count.plot++;},PlotFlag(){count.flag++;}},Log(){},LogStatus(){}};
    vm.createContext(context,{codeGeneration:{strings:false,wasm:false}});
    try {
        vm.runInContext(job.source+'\nmain();',context,{timeout:20_000});
        assert.fail('Unexpected strategy exit');
    } catch(e){if(e!==END)throw e;}
    point();
    assert.equal(path.length,spec.tape.length);
    assert.equal(count.flag,orders.length);
    assert.equal(cashflow.length,1);
    assert.equal(maker,0.00008);
    return {day,seed,orders,path,draws,cashflow,count,minExcess,
        sourceCounts:{closes:context.pt_times+context.st_times,wins:context.pt_times,losses:context.st_times,entries:context.total_times},
        ending:{balance,position,entry,mark:row()[15],unrealized:pnl(row()[15])}};
}

(async()=>{
    await new Promise(r=>setTimeout(r,250));
    const raw=read('round28-4618-input.json.gz');
    const job=JSON.parse(gunzipSync(raw));
    assert.equal(sha(job.source),job.source_sha256);
    assert.deepEqual(job.seeds,[1,42,20201120]);
    let net=0;
    global.__offlineProbe=()=>{net++;throw Error('Network disabled');};
    const math=Library.VCtx({start:'2020-02-01 02:00:00',end:'2020-02-01 10:00:00',period:'15m',basePeriod:'5m',
                  exchanges:[{eid:'Futures_BitMEX',currency:'XBT_USD',balance:0,stocks:0.001,fee:[0.008,0.1]}]}).scope;
    assert.equal(math._N(16.8,0),16);
    const results=[];
    for(const [day,s] of Object.entries(job.scopes)) {
        for(const seed of job.seeds) results.push(backtest(day,s,job,seed,math));
    }
    assert.equal(net,0);
    fs.writeFileSync(file('round28-4618-receipt.json'),JSON.stringify({input_sha256:sha(raw),source_sha256:job.source_sha256,
        engine_sha256:sha(read('fmz-wasm-engine.cjs')),external_requests:net,results}));
})().catch(e=>{fs.writeFileSync(file('round28-4618-error.txt'),String(e.stack||e));process.exitCode=1});
