const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const {gunzipSync}=require('node:zlib');
const {createHash}=require('node:crypto');
const FMZ=require('./fmz-wasm-engine.cjs');
const STOP=Symbol('Historical cutoff');
const STEP=200,HOUR=3600000;
const S=1e5;
const read=f=>fs.readFileSync(path.join(__dirname,f));
const write=(f,v)=>fs.writeFileSync(path.join(__dirname,f),JSON.stringify(v));
const sha=b=>createHash('sha256').update(b).digest('hex');
function venueCents(value){
    const scaled=value*100;
    const lower=Math.floor(scaled);
    const midpoint=lower+0.5;
    // Native SetPrecision normalizes decimal midpoint ties to the even tick.
    if(Math.abs(scaled-midpoint)<=1e-9)return lower+lower%2;
    return Math.round(scaled);
}


function replay(job,spec,mode,native){
    let at=spec.begin_ms,wallet=job.initial_cash_USDT,lev=NaN,direction=null,tape=0,settled=false;
    let hour0=null,partial=null,recordCache=null,minMargin=wallet,earliestEMA=null,maxGap=0;
    const qty=[0,0],basis=[0,0],live=new Map(),all=new Map(),keys=new Map(),events=[],reads={},emaProof=[],poll=[],quotesUsed=new Map();
    let firstEMA=null,priorOrders='',currentTicker=null,currentRecords=null;
    const index=()=> (at-spec.begin_ms)/STEP;
    const marks=()=>spec.marks[index()];
    const last=()=>tape?spec.tape[tape-1][2]/100:marks()[2]/100;
    const unreal=mark=>(qty[0]-qty[1])*mark/1000-basis[0]+basis[1];
    const margin=()=> (basis[0]+basis[1])/lev;
    const fund_ms=spec.funding.exchange_settlement_ms;
    const fund_us=fund_ms*1000;
    function funding(){
        assert.ok(!settled);
        settled=true;
        const mark=spec.funding.prior_mark[3],r=spec.funding.rate;
        const signed=[-qty[0]/1000*mark*r,qty[1]/1000*mark*r];
        signed.forEach(x=>{wallet+=x;});
        events.push({kind:'funding',t:at,us:fund_us,mark,rate:r,signed,qty:[...qty],wallet});
    }
    function fill(order,value,kind,when,details){
        const {side,offset,units}=order;
        assert.equal(order.Status,0);
        const rate=kind==='maker'?job.fees_pct[0]/100:job.fees_pct[1]/100;
        const fee=value*rate;
        let gross=0;
        if(offset){
            assert.ok(qty[side]>=units);
            const allocated=basis[side]*units/qty[side];
            qty[side]-=units;
            basis[side]-=allocated;
            gross=(value-allocated)*(side===0?1:-1);
        }else{qty[side]+=units;basis[side]+=value;}
        wallet+=gross-fee;
        order.Status=1;
        live.delete(order.Id);
        events.push({kind:'fill',t:at,us:when,id:order.Id,fill_type:kind,value,fee,gross,qty:[...qty],basis:[...basis],wallet,proof:details});
    }
    function applyPrint(tick){
        const [seen,id,px,volume,aggressor]=tick;
        let left=volume;
        const matches=[...live.values()].filter(o=>o.Time*1000<seen&&aggressor===o.Type&&(o.Type===0?px<o.cents:px>o.cents));
        matches.sort((a,b)=>(aggressor===1?a.cents-b.cents:b.cents-a.cents)||a.Id-b.Id);
        for(const o of matches){
            const used=Math.min(left,o.needed-o.witnessed);
            o.witnessed+=used;left-=used;o.witnesses.push([id,seen,px,used,aggressor]);
            if(o.witnessed===o.needed)fill(o,o.units*o.cents/S,'maker',seen,o.witnesses);
            if(!left)break;
        }
    }
    function next(ms,name){
        if(at>=spec.end_ms)throw STOP;
        reads[name]=(reads[name]??0)+1;
        const target=Math.min(at+ms,spec.end_ms);
        while(at<target){
            at=Math.min(at+STEP,target);
            assert.equal((at-spec.begin_ms)%STEP,0);
            while(tape<spec.tape.length&&spec.tape[tape][0]<=at*1000){
                const item=spec.tape[tape++];
                if(!settled&&fund_us<=item[0])funding();
                const [,,,volume,,exchangeTime]=item;
                const px=item[2];
                const h=Math.floor(exchangeTime/1000/HOUR)*HOUR;
                if(hour0!==h||partial===null){hour0=h;partial={Time:h,Open:px/100,High:px/100,Low:px/100,Close:px/100,Volume:volume/1000};}
                else{partial.High=Math.max(partial.High,px/100);partial.Low=Math.min(partial.Low,px/100);partial.Close=px/100;partial.Volume+=volume/1000;}
                if(live.size)applyPrint(item);
            }
            if(!settled&&fund_us<=at*1000)funding();
            if(Number.isFinite(lev)){
                const mark=marks()[3];
                const c=wallet+unreal(mark)-(qty[0]+qty[1])/1000*mark/lev;
                assert.ok(c>0,'below conservative margin');minMargin=Math.min(minMargin,c);
            }
        }
        if(at===spec.end_ms)throw STOP;
    }
    const bars=spec.bars.map(([Time,Open,High,Low,Close,Volume])=>({Time,Open,High,Low,Close,Volume}));
    let knownHour=null;
    function records(period=3600){
        next(STEP,'records');assert.equal(period,3600);
        const h=Math.floor(at/HOUR)*HOUR;
        if(h!==knownHour){
            knownHour=h;
            const from=(h-bars[0].Time)/HOUR;
            assert.ok(from>=job.native_warm_hours && from<=bars.length);
            recordCache=bars.slice(from-job.native_warm_hours+1,from);
        }
        const active=hour0===h?{...partial}:{Time:h,Open:last(),High:last(),Low:last(),Close:last(),Volume:0};
        currentRecords=[...recordCache,active];
        return currentRecords;
    }
    function calcEMA(v,n){
        assert.equal(v,currentRecords);assert.equal(n,60);
        const result=native.TA.EMA(v,n);
        assert.ok(result.length===v.length&&v.at(-2).Time<v.at(-1).Time);
        const current=result.at(-2),prev=v.at(-2);
        const diff=Math.abs(currentTicker[1]-current)/current;
        assert.ok(Number.isFinite(current)&&prev.Time+HOUR<=at);
        earliestEMA??=prev.Time;
        const evidence={at,last:currentTicker[1],hour:prev.Time,ema:current,deviation:diff,usedRecords:v.length};
        firstEMA??=evidence;
        maxGap=Math.max(maxGap,diff);
        emaProof.push(evidence);
        return result;
    }
    function sellBuy(verb,desired,amount){
        next(STEP,'submit');
        const buy=verb==='Buy',offset=direction.startsWith('close'),side=direction==='buy'||direction==='closebuy'?0:1;
        assert.equal(buy,direction==='buy'||direction==='closesell');
        const n=Math.round(amount*1000),limit=desired===-1?0:venueCents(desired);
        assert.ok(n>0 && Math.abs(n-amount*1000)<1e-6 && (limit>0||desired===-1));
        const [local,venue,asks,bids]=spec.depth[index()];
        const quote=spec.quotes[index()];
        assert.deepEqual([bids[0][0],asks[0][0],bids[0][1],asks[0][1]],quote.slice(2,6));
        assert.ok(venue<=local&&local<=at*1000&&at*1000-local<=5e6);
        const stack=buy?asks:bids,clipped=limit===0||(buy?stack[0][0]<=limit:stack[0][0]>=limit);
        const plausible=limit?n*limit/S:n*Math.min(last(),marks()[3],stack[0][0]/100)/1000;
        if(!offset&&plausible<job.opening_notional_minimum_USDT){
            events.push({kind:'exchange_notional_reject',t:at,direction,n,limit,desired,amount,plausible});
            return null;
        }
        const id=all.size+1;
        const o={Id:id,Symbol:'ETH_USDT.swap',Status:0,Type:buy?0:1,Time:at,Price:limit/100,Amount:n/1000,
            units:n,cents:limit,side,offset,needed:n*mode,witnessed:0,witnesses:[]};
        if(offset)assert.ok(qty[side]>=n);
        else assert.ok(wallet-margin()>plausible*(1/lev+job.fees_pct[1]/100));
        all.set(id,o);
        events.push({kind:'placement',t:at,id,direction,desired,amount,n,limit,clipped,offset,sourceTicker:currentTicker,
            latestEMA:emaProof.at(-1)??null,qty:[...qty],basis:[...basis]});
        if(!clipped){live.set(id,o);return id;}
        const mapKey=String(local)+(buy?'buy':'sell');
        const seen=quotesUsed.get(mapKey)??new Map();
        let sum=0,left=n;
        const used=[];
        for(const [px,volume] of stack){
            if(limit&&(buy?px>limit:px<limit))break;
            const previously=seen.get(px)??0;
            const take=Math.min(left,volume-previously);
            assert.ok(take>=0);
            if(take){seen.set(px,previously+take);used.push([px,take]);sum+=px*take;left-=take;}
            if(!left)break;
        }
        assert.ok(!left,'marketable order lacks supported visible size');
        quotesUsed.set(mapKey,seen);
        fill(o,sum/S,'taker',at*1000,{local,venue,used});
        return id;
    }
    const exchange={GetName(){return 'Futures_Binance';},SetContractType(k){assert.equal(k,'swap');},
        SetPrecision(p,q){assert.equal(p,2);assert.equal(q,3);},SetMarginLevel(n){lev=n;assert.equal(lev,10);},
        SetDirection(value){assert.ok(['buy','sell','closebuy','closesell'].includes(value));direction=value;},
        Buy(p,q){return sellBuy('Buy',p,q);},Sell(p,q){return sellBuy('Sell',p,q);},
        GetTicker(){next(STEP,'ticker');currentTicker=[at,last()];const r=spec.quotes[index()];return {Time:at,Last:last(),Buy:r[2]/100,Sell:r[3]/100};},
        GetPosition(){next(STEP,'position');return qty.flatMap((v,i)=>v?[{Symbol:'ETH_USDT.swap',Type:i,Amount:v/1000,Price:basis[i]*1000/v,Margin:basis[i]/lev}]:[]);},
        GetRecords:records,
        GetAccount(){next(STEP,'account');return {Balance:wallet-margin(),Equity:wallet+unreal(marks()[3])};},
        GetOrders(){
            next(STEP,'orders');
            const ids=[...live.keys()];const label=ids.join(',');
            if(label!==priorOrders){poll.push([at,ids]);priorOrders=label;}
            return [...live.values()].map(o=>({Id:o.Id,Symbol:o.Symbol,Type:o.Type,Price:o.Price,Amount:o.Amount}));
        },
        CancelOrder(id){
            next(STEP,'cancel');const o=live.get(id);
            if(o){live.delete(id);o.Status=2;}
            events.push({kind:'cancel',t:at,id,was_resting:!!o});return !!o;
        }};
    const scope={...job.author_args_with_overrides,exchange,TA:{EMA:calcEMA},PD_LONG:0,PD_SHORT:1,ORDER_TYPE_BUY:0,
        _G(k,...args){if(args.length)keys.set(k,args[0]);return keys.get(k)??null;},_C(fn,...args){return fn(...args);},
        _N:native._N,_D(){return new Date(at).toISOString();},IsVirtual(){return true;},Sleep(ms){assert.equal(ms,3000);next(ms,'sleep');},
        Log(){},LogStatus(){},LogProfit(){},KLineChart(v){assert.equal(v.overlay,true);return {begin(){},close(){},hline(){}};}};
    vm.createContext(scope,{codeGeneration:{strings:false,wasm:false}});
    let error=null;
    try{
        vm.runInContext(job.source+'\nmain();',scope,{filename:'FMZ-2693.js',timeout:140000});
        assert.fail('archived loop returned prematurely');
    }catch(e){if(e!==STOP)error=String(e.stack||e);}
    const tail={clock:at,wallet,qty,basis,mark:marks()[3],equity:wallet+unreal(marks()[3]),remaining:[...live.keys()],kv:[...keys]};
    return {mode,error,events,reads,emaProof,poll,tail,minMargin,firstEMA,earliestEMA,maxGap,consumedTapeRows:tape};
}

(async()=>{
    await new Promise(r=>setTimeout(r,500));
    const bytes=read('round41-2693-input.json.gz');const job=JSON.parse(gunzipSync(bytes));
    assert.equal(sha(job.source),job.source_sha256);
    let network=0;
    global.__offlineProbe=()=>{network++;throw Error('Unbound native data request');};
    const indicator=FMZ.VCtx({start:'2025-01-01 06:00:00',end:'2025-01-01 10:00:00',period:'1h',basePeriod:'1m',
        exchanges:[{eid:'Futures_Binance',currency:'ETH_USDT',balance:10000}]}).scope;
    const results=[];
    for(const [day,spec] of Object.entries(job.scope))for(const mode of [1,2])results.push({day,...replay(job,spec,mode,indicator)});
    assert.equal(network,0);
    write('round41-2693-receipt.json',{input_sha256:sha(bytes),worker_sha256:sha(read('fmz_native_round41_2693_worker.cjs')),
        native_engine_sha256:sha(read('fmz-wasm-engine.cjs')),results});
})().catch(e=>{write('round41-2693-error.json',String(e.stack||e));process.exit(1);});
