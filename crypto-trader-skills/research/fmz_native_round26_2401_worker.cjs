const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {createHash} = require('node:crypto');
const {gunzipSync} = require('node:zlib');
const Library = require('./fmz-wasm-engine.cjs');

const QTY = 100;
const PERIOD = 900;
const N = 90;
const TAKER = 0.00075;
const US = 1_000_000;
const sha = raw => createHash('sha256').update(raw).digest('hex');
const CLOSE = Symbol('declared window finished');

function replay(day, spec, source, ta) {
    const {begin,end,history,data} = spec;
    const C = spec.wallet_xbt;
    const records = history.map(([t,o,h,l,c,v]) => ({Time:t*1000,Open:o,High:h,Low:l,Close:c,Volume:v}));
    assert.equal(records.length,200);
    assert.equal(records.at(-1).Time,(begin-PERIOD)*1000);
    let i=0, cash=C, qty=0, entry=0, direction=null, stale=0, negative=0, costs=0;
    const orders=[], funding=[], points=[], indicators=[], barriers=[];
    const counts={init:0,account:0,positions:0,records:0,ticker:0,sleep:0,plots:0,flags:0};
    const row = () => data[i];
    const now = () => row()[0];
    const pnlAt = (price) => qty===0 ? 0 : qty*(1/entry-1/price);
    function getRecords() {
        counts.records++;
        const [local,ex,bar,o,h,l,c,v] = row()[1];
        assert.ok(ex<=local && local<=now()*US && bar<=now() && bar%PERIOD===0);
        const active = {Time:bar*1000,Open:o,High:h,Low:l,Close:c,Volume:v};
        if (records.at(-1).Time < active.Time) {
            assert.equal(active.Time-records.at(-1).Time,PERIOD*1000);
            records.push(active);
        } else {
            assert.equal(records.at(-1).Time, active.Time);
            records[records.length-1]=active;
        }
        return records;
    }

    function benchmark(operand, period, op) {
        assert.equal(period,N);
        const prior=operand.slice(-period-1,-1);
        assert.equal(prior.length, period);
        if (op==='high' && Math.max(...prior)<=0) negative++;
        const expected=op==='high' ? Math.max(Number.MIN_VALUE,...prior) : Math.min(...prior);
        const actual=ta[op==='high'?'Highest':'Lowest'](operand,period);
        assert.equal(actual,expected);
        return actual;
    }

    function order(side, price, amount) {
        const t=now();
        assert.equal(amount,QTY);
        const trade=row()[1], quote=row()[2], mark=row()[3];
        const buy=side===1;
        assert.equal(price,quote[buy?3:2]);
        assert.ok(0<=t*US-quote[0] && t*US-quote[0]<=5*US);
        if (!(quote[buy?9:8] && quote[buy?7:6]>=amount)) {
            barriers.push({at:t,side,direction,amount,price,quote});
            throw Error(JSON.stringify({stable_fill_barrier:barriers.at(-1),orders:orders.length}));
        }
        const open=direction==='buy'||direction==='sell';
        assert.equal(direction,buy?(open?'buy':'closesell'):(open?'sell':'closebuy'));
        assert.equal(qty,open?0:-side*amount);
        const fee=amount/price*TAKER;
        const slip=side*amount*(1/trade[6]-1/price);
        assert.ok(Number.isFinite(slip));
        let gross=0;
        if (open) {
            assert.ok(cash>amount/price+2*fee);
            qty=side*amount;
            entry=price;
        } else {
            gross=pnlAt(price);
            qty=0;
            entry=0;
        }
        cash+=gross-fee;
        costs+=slip;
        orders.push({id:orders.length+1,at:t,side,open,direction,price,amount,fee,gross,slip,
            cash,qty,mark:mark[2],last:trade[6],quote,chart:records.at(-1).Time});
        direction=null;
        return orders.length;
    }

    function settle(at) {
        if (!Object.hasOwn(spec.funding_near,at)) return;
        const around=spec.funding_near[at];
        const before=around.filter(x=>x[0]<=at*US && x[4]===at*US);
        const prior=before.at(-1);
        const later=around.find(x=>x[4]>at*US);
        assert.ok(prior&&later && before.every(x=>x[5]===prior[5]));
        const rate=Number(prior[5]);
        const amount=-(qty/prior[2])*rate;
        cash+=amount;
        funding.push({at,qty,rate,amount,mark:prior[2],laterMark:later[2],prior,later,cash});
    }

    function sleep(ms) {
        assert.equal(ms,5000);
        counts.sleep++;
        record();
        i++;
        settle(now());
        if (now()===end) throw CLOSE;
    }

    const fixedDate=class extends Date {
        constructor(...args) { super(...(args.length?args:[now()*1000])); }
        static now() { return now()*1000; }
    };
    const exchange={SetContractType(id){assert.equal(id,'XBTUSD');counts.init++;},
        GetAccount(){counts.account++;return {Stocks:cash};},
        GetPosition(){counts.positions++;return qty?[{Type:qty>0?0:1,Amount:Math.abs(qty),Price:entry}]:[];},
        GetRecords:getRecords,
        GetTicker(){counts.ticker++;const tr=row()[1],q=row()[2];return {Last:tr[6],Buy:q[2],Sell:q[3]};},
        SetDirection(value){assert.equal(direction,null);direction=value;},
        Buy(p,a){return order(1,p,a);}, Sell(p,a){return order(-1,p,a);}};
    const math={MA(a,n){return ta.MA(a,n);},Highest(a,n){return benchmark(a,n,'high');},Lowest(a,n){return benchmark(a,n,'low');}};
    const plot={PlotLine(){counts.plots++;},PlotFlag(){counts.flags++;}};
    const context={exchange,N,Amount:QTY,TA:math,Date:fixedDate,$:plot,_C:f=>f(),Log(){},Sleep:sleep};
    let lastCalculated=0;
    function record() {
        const [t,tr,q,m]=row();
        const p=pnlAt(m[2]);
        const maintenance=qty?Math.abs(qty)/m[2]*(0.005+TAKER):0;
        assert.ok(cash+p>maintenance);
        points.push([t,cash,qty,entry,p,m[2],costs]);
        const bar=context.LastBarTime;
        if (bar!==lastCalculated) {
            assert.ok(bar>lastCalculated);
            lastCalculated=bar;
            const index=records.length-1;
            const observed=Math.log(records[index].Close)/Math.log(records[records.length-N].Close)-1;
            assert.equal(context.vix_arr.at(-1),observed);
            indicators.push([t,bar,observed,context.vix_ma_up.at(-1),context.vix_ma_dw.at(-1),context.vix_ma.at(-1),records[index].Close,records[records.length-N].Close]);
        }
        if (t*US-q[0]>5*US) stale++;
    }

    vm.createContext(context,{codeGeneration:{strings:false,wasm:false}});
    try {
        vm.runInContext(source+'\nmain();',context,{timeout:25_000});
        assert.fail('The source returned before the scheduled end');
    } catch (error) {
        if (error!==CLOSE) throw error;
    }
    record();
    assert.equal(counts.init,1);
    assert.equal(counts.ticker,14400);
    assert.equal(counts.flags,orders.length);
    assert.equal(points.length,14401);
    assert.equal(indicators.length,new Set(data.slice(0,-1).map(r=>r[1][2])).size);
    return {day,begin,end,orders,funding,points,indicators,counts,negative_band_windows:negative,
        stale_quotes_with_no_orders:stale,ending:{cash,qty,entry,mark:row()[3][2],unrealized:pnlAt(row()[3][2])}};
}

(async()=>{
    await new Promise(r=>setTimeout(r,300));
    let options=[];
    global.__offlineProbe=(...args)=>{options.push(args);throw Error('Network request disabled');};
    const ctx=Library.VCtx({start:'2019-05-01 02:00:00',end:'2019-05-01 22:00:00',period:'15m',basePeriod:'5m',
        exchanges:[{eid:'Futures_BitMEX',currency:'XBT_USD',balance:0,stocks:2}]});
    const ta=ctx.scope.TA;
    assert.deepEqual([ta.Highest([1,12,99],2),ta.Lowest([12,99,1],2),ta.Highest([-5,-1,0],2)],[12,12,Number.MIN_VALUE]);
    const raw=fs.readFileSync(require('node:path').join(__dirname,'round26-2401-xbtusd-tape.json.gz'));
    const job=JSON.parse(gunzipSync(raw));
    assert.equal(sha(job.source),job.source_sha256);
    const scopes=Object.entries(job.scenarios).map(([day,spec])=>replay(day,spec,job.source,ta));
    assert.deepEqual(options,[]);
    fs.writeFileSync(require('node:path').join(__dirname,'round26-2401-xbtusd-receipt.json'),JSON.stringify({job_sha256:sha(raw),source_sha256:job.source_sha256,
        native_engine_sha256:sha(fs.readFileSync(require('node:path').join(__dirname,'fmz-wasm-engine.cjs'))),network_requests:options.length,scopes}));
})().catch(e=>{fs.writeFileSync(require('node:path').join(__dirname,'round26-2401-errors.txt'),String(e.stack||e));process.exitCode=1;});
