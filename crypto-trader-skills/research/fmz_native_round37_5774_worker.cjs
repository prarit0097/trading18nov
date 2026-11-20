const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const {createHash}=require('node:crypto');
const {gunzipSync}=require('node:zlib');
const END=Symbol('Historical boundary');
const STEP=200;
const read=f=>fs.readFileSync(path.join(__dirname,f));
const write=(f,v)=>fs.writeFileSync(path.join(__dirname,f),JSON.stringify(v));
const sha=b=>createHash('sha256').update(b).digest('hex');

function run(job,spec,seed,mirror,delay){
    const positions=[{size:0,notional:0},{size:0,notional:0}];
    let clock=spec.begin_ms,randomBits=seed,wallet=job.starting_cash_USDT,direction=null,unsupported=null;
    let both=0,marginBuffer=wallet;
    const records=[],draws=[],orders=[],funding=[],sweptBook=new Map();
    const index=()=> (clock-spec.begin_ms)/STEP;
    const mark=()=>spec.marks[index()][3];
    const last=()=>spec.marks[index()][2]/100;
    const unreal=(side,price)=> (side===0?1:-1)*(positions[side].size/1000*price-positions[side].notional);
    const combined=price=>unreal(0,price)+unreal(1,price);
    const total=()=>positions[0].size+positions[1].size;
    const initial=()=>positions.reduce((out,p)=>out+p.notional/job.leverage,0);
    const cashAt=Math.ceil(spec.funding.exchange_settlement_ms/STEP)*STEP;
    function invalid(reason,more){unsupported={clock,reason,...more};throw END;}
    function advance(ms){
        assert.ok(ms>0&&ms%STEP===0);
        const target=Math.min(clock+ms,spec.end_ms);
        while(clock<target){
            clock+=STEP;
            if(clock===cashAt){
                const proof=spec.funding;
                const sum=positions.map((p,s)=> -(s===0?1:-1)*p.size/1000*proof.prior_mark[3]*proof.rate);
                sum.forEach(v=>wallet+=v);
                funding.push({clock,rate:proof.rate,venue_ms:proof.exchange_settlement_ms,quantity:positions.map(p=>p.size),
                              price:proof.prior_mark[3],sum,wallet});
            }
            const available=wallet+combined(mark())-total()/1000*mark()/job.leverage;
            marginBuffer=Math.min(marginBuffer,available);
            if(available<=0)invalid('marked equity reached conservative initial margin bound',{wallet,available});
            if(positions.every(p=>p.size))both++;
        }
        if(clock===spec.end_ms)throw END;
    }
    function positionInfo(){
        return positions.flatMap((p,type)=>p.size?[{Type:type,Amount:p.size/1000,Price:p.notional*1000/p.size,
                    Profit:unreal(type,last()),Margin:p.notional/job.leverage,MarginLevel:job.leverage}]:[]);
    }
    function submit(api,price,qty){
        assert.equal(price,-1);
        const units=Math.round(qty*1000);
        assert.ok(units>0&&Math.abs(qty*1000-units)<1e-7);
        advance(STEP+delay);
        const [seen,venue,asks,bids]=spec.depth[index()];
        const q=spec.quotes[index()];
        assert.deepEqual([bids[0][0],asks[0][0],bids[0][1],asks[0][1]],q.slice(2,6));
        const age=clock*1000-seen;
        assert.ok(venue<=seen&&age>=0);
        if(age>5_000_000)invalid('stale recorded depth',{seen,age});
        const isBuy=direction==='buy'||direction==='closesell';
        const exits=direction.startsWith('close');
        const side=direction==='buy'||direction==='closebuy'?0:1;
        assert.equal(api,isBuy?'Buy':'Sell');
        const id=String(seen)+(isBuy?' ask':' bid');
        const consumed=sweptBook.get(id)??new Map();
        const offer=isBuy?asks:bids;
        const portions=[];
        let remain=units,sum=0;
        for(const [px,size] of offer){
            const used=consumed.get(px)??0;
            assert.ok(size>=used);
            const take=Math.min(remain,size-used);
            if(!take)continue;
            portions.push([px,take]);sum+=take*px;remain-=take;
            if(!remain)break;
        }
        if(remain)invalid('order exceeds causal observed book size',{direction,units,left:remain,snapshot_us:seen,offer});
        for(const [px,take] of portions)consumed.set(px,(consumed.get(px)??0)+take);
        sweptBook.set(id,consumed);
        const value=sum/100_000;
        const cost=value*job.taker_rate;
        const pos=positions[side];
        let gross=0;
        if(exits){
            assert.equal(pos.size,units);
            gross=(side===0?1:-1)*(value-pos.notional);
            pos.notional=pos.size=0;
        }else{
            const required=value/job.leverage+cost;
            if(wallet-initial()<=required)invalid('first opening order fails conservative initial collateral',{direction,units,required,available:wallet-initial()});
            pos.size+=units;
            pos.notional+=value;
        }
        wallet+=gross-cost;
        orders.push({clock,api,direction,units,portions,snapshot_us:seen,age,notional:value,fee:cost,gross,wallet,
                    quant:positions.map(x=>x.size),basis:positions.map(x=>x.notional),mark:mark()});
        return orders.length;
    }
    const M=Object.create(Math);
    Object.defineProperty(M,'random',{value(){
        randomBits^=randomBits<<13;randomBits^=randomBits>>>17;randomBits^=randomBits<<5;
        const bits=mirror?0xffffffff-(randomBits>>>0):randomBits>>>0;
        draws.push([clock,bits,...positions.map(p=>p.size)]);
        return bits/2**32;
    }});
    const exchange={SetContractType(k){assert.equal(k,'swap');},SetMarginLevel(v){assert.equal(v,job.leverage);},
        SetDirection(s){assert.ok(['buy','sell','closebuy','closesell'].includes(s));direction=s;},
        GetPosition(){advance(STEP);const p=positionInfo();records.push([clock,p.map(row=>({...row}))]);return p;},
        Buy(price,qty){return submit('Buy',price,qty);},Sell(price,qty){return submit('Sell',price,qty);}};
    const context=vm.createContext({Math:M,exchange,Log(){},Sleep(ms){assert.equal(ms,60000);advance(ms);}},
                                   {codeGeneration:{strings:false,wasm:false}});
    try{
        vm.runInContext(job.source+'\nmain();',context,{filename:'FMZ-5774.js',timeout:120000});
        assert.fail('archived loop returned early');
    }catch(e){if(e!==END)throw e;}
    return {seed,mirror,delay,unsupported,records,draws,orders,funding,marginBuffer,concurrent_hold_steps:both,
        tail:{clock,wallet,positions,mark:mark(),UPnL:combined(mark())}};
}
const input=read('round37-5774-input.json.gz');
const job=JSON.parse(gunzipSync(input));
assert.equal(sha(job.source),job.source_sha256);
assert.equal(job.leverage,20);
assert.equal(job.sample_step_ms,STEP);
const result=[];
for(const [day,spec] of Object.entries(job.scope))for(const seed of job.seeds)for(const mirror of [false,true])for(const delay of [0,200]){
    try{result.push({day,...run(job,spec,seed,mirror,delay)});}
    catch(e){write('round37-5774-error.json',{day,seed,mirror,delay,error:String(e.stack||e)});process.exit(1);}
}
write('round37-5774-receipt.json',{input_sha256:sha(input),worker_sha256:sha(read('fmz_native_round37_5774_worker.cjs')),results:result});
