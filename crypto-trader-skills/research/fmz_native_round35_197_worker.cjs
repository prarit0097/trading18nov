const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const {createHash}=require('node:crypto');
const {gunzipSync}=require('node:zlib');

const STOP=Symbol('historical boundary');
const PHASE=197;
const LEVERAGE=20;
const STEP=200;
const read=name=>fs.readFileSync(path.join(__dirname,name));
const write=(name,value)=>fs.writeFileSync(path.join(__dirname,name),JSON.stringify(value));
const sha=value=>createHash('sha256').update(value).digest('hex');

function orderDepth(levels, size){
    let sum=0, remaining=size;
    const portions=[];
    for(const [px,cap] of levels){
        const take=Math.min(remaining,cap);
        sum+=take*px;
        portions.push([px,take]);
        remaining-=take;
        if(remaining===0)break;
    }
    return {portions, n:sum, remaining};
}

function run(job,spec,seed,mirror,delay){
    let clock=spec.begin_ms, direction=null, wallet=job.starting_cash_USDT, posUnits=0, basis=0;
    let rng=seed, unsupported=null, minimumInitialMarginBuffer=wallet, minQuoteAge=Infinity, maxQuoteAge=0;
    let calls={depth:0,position:0,sleep:0};
    const decisions=[], draws=[], orders=[], funding=[];
    const index=()=> (clock-spec.begin_ms)/STEP;
    const depth=()=>{
        const [arrival,venue,asks,bids]=spec.depth[index()];
        if(Array.isArray(asks))return [arrival,venue,asks,bids];
        const decode=side=>{
            const flat=side.split(',').map(Number);
            const levels=[];
            for(let i=0;i<flat.length;i+=2)levels.push([flat[i],flat[i+1]]);
            return levels;
        };
        return [arrival,venue,decode(asks),decode(bids)];
    };
    const last=()=>spec.marks[index()][2]/100;
    const mark=()=>spec.marks[index()][3];
    const q=()=>posUnits/1000;
    const average=()=>posUnits ? basis/Math.abs(q()) : 0;
    const unreal=p=>q()*(p-average());
    function stop(reason,detail){
        unsupported={reason,clock,...detail};
        throw STOP;
    }
    function advance(ms){
        assert.ok(Number.isInteger(ms)&&ms>0&&ms%STEP===0);
        const end=Math.min(clock+ms,spec.end_ms);
        while(clock<end){
            clock+=STEP;
            if(clock===Math.ceil(spec.funding.exchange_settlement_ms/STEP)*STEP){
                const known=spec.funding;
                const value=-q()*known.prior_mark[3]*known.rate;
                funding.push({clock,venueClock:known.exchange_settlement_ms,notional_BTC:q(),mark:known.prior_mark[3],rate:known.rate,value});
                wallet+=value;
            }
            const equity=wallet+unreal(mark());
            const buffer=equity-Math.abs(q())*mark()/LEVERAGE;
            minimumInitialMarginBuffer=Math.min(minimumInitialMarginBuffer,buffer);
            if(buffer<=0)stop('marked equity reached the conservative initial margin bound',{wallet,qBTC:q(),mark:mark(),equity,buffer});
        }
        if(clock===spec.end_ms)throw STOP;
    }
    function verifySnapshot(){
        const [arrive, ex, asks, bids]=depth();
        assert.ok(ex<=arrive&&arrive<=clock*1000);
        const age=clock*1000-arrive;
        const quoting=spec.quotes[index()];
        const projected=[bids[0][0],asks[0][0],bids[0][1],asks[0][1]];
        if(age>job.max_market_order_snapshot_age_us||projected.some((v,i)=>v!==quoting[i+2])){
            stop('order book freshness or top quote crosswalk failed',{age,projected,quote:quoting,depth:depth()});
        }
        return {age,asks,bids};
    }
    function execOrder(api,limit,size){
        assert.equal(limit,-1);
        const units=Math.round(size*1000);
        assert.ok(Number.isSafeInteger(units)&&units>0&&Math.abs(size*1000-units)<1e-7);
        advance(STEP+delay);
        const {age,asks,bids}=verifySnapshot();
        const side=direction==='buy'||direction==='closesell'?1:-1;
        const opening=direction==='buy'||direction==='sell';
        assert.equal(api,side===1?'Buy':'Sell');
        const levels=side===1?asks:bids;
        assert.ok(levels.length<=job.max_observed_levels);
        const swept=orderDepth(levels,units);
        if(swept.remaining){
            stop('market order exceeds the observed levels',{api,direction,units,availableUnits:units-swept.remaining,levels});
        }
        minQuoteAge=Math.min(minQuoteAge,age);
        maxQuoteAge=Math.max(maxQuoteAge,age);
        const executedNotional=swept.n/100_000;
        const fee=executedNotional*job.commission_rate;
        let pnl=0;
        if(opening){
            assert.ok(!posUnits||Math.sign(posUnits)===side);
            const required=executedNotional/LEVERAGE+fee;
            const available=wallet-basis/LEVERAGE;
            if(available<=required)stop('first new order fails modeled initial margin',{direction,units,available,required});
            basis+=executedNotional;
            posUnits+=side*units;
        } else {
            assert.equal(-side*units,posUnits);
            pnl=(executedNotional-basis)*Math.sign(posUnits);
            basis=posUnits=0;
        }
        wallet+=pnl-fee;
        orders.push({clock,api,direction,units,portions:swept.portions,executedNotional,fee,pnl,wallet,posUnits,age,last:last(),mark:mark()});
        return orders.length;
    }
    const exchange={
        SetContractType(x){assert.equal(x,'swap');},
        SetMarginLevel(x){assert.equal(x,LEVERAGE);},
        SetDirection(s){assert.ok(['buy','sell','closebuy','closesell'].includes(s));direction=s;},
        GetDepth(){
            advance(STEP);calls.depth++;
            const {asks,bids}=verifySnapshot();
            const side=book=>book.map(([price,amount])=>({Price:price/100,Amount:amount/1000}));
            return {Asks:side(asks),Bids:side(bids)};
        },
        GetPosition(){
            advance(STEP);calls.position++;
            const p={Type:posUnits>0?0:1,Amount:Math.abs(q()),Profit:unreal(last()),Price:average(),Margin:basis/LEVERAGE};
            decisions.push([clock,posUnits,p.Profit,p.Price,p.Margin]);
            return posUnits?[p]:[];
        },
        Buy(p,s){return execOrder('Buy',p,s);},
        Sell(p,s){return execOrder('Sell',p,s);},
    };
    const seeded=Object.create(Math);
    Object.defineProperty(seeded,'random',{value(){
        rng^=rng<<13;rng^=rng>>>17;rng^=rng<<5;
        const bits=mirror?0xffffffff-(rng>>>0):rng>>>0;
        draws.push([clock,bits,posUnits]);
        return bits/2**32;
    }});
    const scope={exchange,Math:seeded,Sleep(ms){assert.equal(ms,1000);calls.sleep++;advance(ms);}};
    vm.createContext(scope,{codeGeneration:{strings:false,wasm:false}});
    try{
        vm.runInContext(job.sources[PHASE].source+'\nmain();',scope,{filename:'FMZ-197.js',timeout:90000});
        assert.fail('archived source returned before expected cutoff');
    }catch(err){if(err!==STOP)throw err;}
    return {seed,mirror,delay,unsupported,calls,decisions,draws,orders,funding,minimumInitialMarginBuffer,minQuoteAge,maxQuoteAge,
        ending:{clock,wallet,posUnits,basis,last:last(),mark:mark(),floating:unreal(mark())}};
}

const control=process.argv.includes('top5-control');
const input=read(control?'round35-197-input.json.gz':'round35-197-full-input.json.gz');
const job=JSON.parse(gunzipSync(input));
assert.equal(job.sample_step_ms,STEP);
if(control)job.max_observed_levels=5;
assert.equal(job.max_observed_levels,control?5:25);
job.max_market_order_snapshot_age_us=5_000_000;
assert.equal(sha(job.sources[PHASE].source),job.sources[PHASE].source_sha256);
const results=[];
for(const [day,spec] of Object.entries(job.scope))for(const seed of job.seeds)for(const mirror of [false,true])for(const delay of [0,200]){
    try{results.push({day,...run(job,spec,seed,mirror,delay)});}
    catch(error){write('round35-197-error.json',{day,seed,mirror,delay,error:String(error.stack||error)});process.exit(1);}
}
write(control?'round35-197-top5-receipt.json':'round35-197-receipt.json',{depth_levels:job.max_observed_levels,input_sha256:sha(input),runner_sha256:sha(read('fmz_native_round35_197_worker.cjs')),results});
