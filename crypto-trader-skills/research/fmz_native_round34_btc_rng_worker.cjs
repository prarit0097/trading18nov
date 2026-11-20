const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const {createHash}=require('node:crypto');
const {gunzipSync}=require('node:zlib');

const END=Symbol('exclusive cutoff');
const read=f=>fs.readFileSync(path.join(__dirname,f));
const write=(f,o)=>fs.writeFileSync(path.join(__dirname,f),JSON.stringify(o));
const sha=v=>createHash('sha256').update(v).digest('hex');

function replay(id,job,spec,seed,mirror,delay){
    const step=job.sample_step_ms;
    let time=spec.begin_ms,rng=seed,leverage=0,wallet=job.starting_cash_USDT,direction=null,seenFunding=false,unsupported=null;
    let position=0, basis=0, sleepCalls=0, tickerReads=0, balanceReads=0, depthReads=0;
    const decisions=[],draws=[],orders=[],funding=[];
    const i=()=>Math.floor((time-spec.begin_ms)/step);
    const book=()=>spec.quotes[i()];
    const marks=()=>spec.marks[i()];
    const last=()=>marks()[2]/100;
    const amount=()=>Math.abs(position);
    const mid=()=>position ? basis/amount() : 0;
    const pnl=mark=>position*(mark-mid());
    const pos=()=>position?[{Type:position>0?0:1, Price:mid(), Amount:amount(),Profit:pnl(last()),Margin:basis/leverage,
                                MarginLevel:leverage, Symbol:'BTC_USDT.swap',ContractType:'swap'}]:[];
    const borrow=()=>basis/leverage;
    function advance(ms){
        assert.ok(Number.isInteger(ms)&&ms>0&&ms%step===0);
        if(!seenFunding&&time<spec.funding.boundary_ms&&time+ms>=spec.funding.boundary_ms){
            const data=spec.funding;
            seenFunding=true;
            const carry=-position*data.prior_mark[3]*data.rate;
            wallet+=carry;
            funding.push([data.boundary_ms,position,data.prior_mark[3],data.rate,carry,wallet]);
        }
        time=Math.min(time+ms,spec.end_ms);
        if(time===spec.end_ms)throw END;
    }
    function random(){
        rng^=rng<<13;rng^=rng>>>17;rng^=rng<<5;
        const bits=mirror?0xFFFFFFFF-(rng>>>0):rng>>>0;
        draws.push([time,bits,position]);
        return bits/4294967296;
    }
    function submit(api,price,qty){
        assert.equal(price,-1);
        assert.ok(qty>=0.001 && Math.abs(Math.round(1e3*qty)-1e3*qty)<1e-7);
        advance(step+delay);
        // Native SetDirection determines futures side/offset even when source calls the opposite function name.
        const sign=direction==='buy'||direction==='closesell'?1:-1;
        const open=direction==='buy'||direction==='sell';
        const q=book(), j=sign>0?1:0;
        const px=q[2+j]/100;
        const cap=q[4+j]/1000;
        const low=q[6+j]/1000;
        const age=time*1000-q[0];
        if(!(q[1]<=q[0]&&age>=0&&age<=5e6&&cap>=qty)){
            unsupported={time,api,direction,qty,book:q,visible_size:cap,quote_age_us:age};
            throw END;
        }
        assert.ok(marks()[0]<=time*1000&&time*1000-marks()[0]<=5e6);
        const fee=qty*px*job.commission_rate;
        let gross=0;
        if(open){
            assert.ok(!position||Math.sign(position)===sign);
            assert.ok(wallet-borrow()>qty*px/leverage+fee,'initial margin unavailable');
            position+=sign*qty;
            basis+=qty*px;
        } else {
            assert.ok(Math.sign(position)===-sign&&Math.abs(Math.abs(position)-qty)<1e-7);
            gross=position*(px-mid());
            basis=position=0;
        }
        wallet+=gross-fee;
        orders.push([time,api,direction,qty,px,fee,gross,wallet,position,cap,low,age,q[0],last(),marks()[3]]);
        return orders.length;
    }
    const exchange={
        SetContractType(name){assert.equal(name,'swap');return true;},
        SetMarginLevel(n){assert.ok([20,30,50].includes(n)); leverage=n; return true;},
        SetDirection(d){assert.ok(['buy','sell','closebuy','closesell'].includes(d)); direction=d;return true;},
        GetAccount(){advance(step);balanceReads++;return {Balance:wallet-borrow(), FrozenBalance:0, Stocks:3,FrozenStocks:0};},
        GetPosition(){advance(step);const result=pos();decisions.push([time,position,mid(),pnl(last()),borrow()]);return result;},
        GetTicker(){advance(step);tickerReads++;const q=book();return {Time:time,Last:last(),Buy:q[2]/100,Sell:q[3]/100};},
        GetDepth(){advance(step);depthReads++;const q=book();return {Asks:[{Price:q[3]/100,Amount:q[5]/1000}],Bids:[{Price:q[2]/100,Amount:q[4]/1000}]};},
        GetName(){return 'Futures_Binance';},
        Buy(price,n){return submit('Buy',price,n);},
        Sell(price,n){return submit('Sell',price,n);},
    };
    const MathSeeded=Object.create(Math);
    Object.defineProperty(MathSeeded,'random',{value:random});
    const scope={Math:MathSeeded,exchange,Sleep(ms){sleepCalls++;advance(ms);},Log(){},LogProfit(){}};
    vm.createContext(scope,{codeGeneration:{strings:false,wasm:false}});
    try {
        vm.runInContext(job.sources[id].source+'\nmain();',scope,{timeout:30000,filename:'FMZ-'+id+'.js'});
        assert.fail('archived source returned unexpectedly');
    } catch(e){if(e!==END)throw e;}
    return {id,seed,mirror,delay,leverage,orders,decisions,draws,funding,unsupported,sleepCalls,depthReads,tickerReads,balanceReads,
            ending:{time,wallet,position,basis,last:last(),mark:marks()[3],unrealized:pnl(marks()[3])}};
}

const raw=read('round34-btc-rng-input.json.gz');
const job=JSON.parse(gunzipSync(raw));
const output=[];
for(const src of Object.values(job.sources)) assert.equal(sha(src.source),src.source_sha256);
for(const id of Object.keys(job.sources)){
    for(const [day,spec] of Object.entries(job.scope)){
        for(const seed of job.seeds) for(const mirror of [false,true]) for(const delay of [0,200]) {
            try{output.push({day,...replay(Number(id),job,spec,seed,mirror,delay)});}
            catch(error){write('round34-btc-rng-error.json',{id,day,seed,mirror,delay,error:String(error.stack||error)}); process.exit(1);}
        }
    }
}
write('round34-btc-rng-receipt.json',{input_sha256:sha(raw),host_sha256:sha(read('fmz_native_round34_btc_rng_worker.cjs')),results:output});
