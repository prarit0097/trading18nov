'use strict';
// Execute the pinned FMZ source against recorded Binance Spot depth and signed trades.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {createHash}=require('node:crypto');
const {gunzipSync,gzipSync}=require('node:zlib');
const vm=require('node:vm');
const nativeProcess=require('node:process');
const receipt=nativeProcess.argv[2]||'round45-5094-receipt.json.gz';
const fmz=require('./fmz-wasm-engine.cjs');
const read=f=>fs.readFileSync(path.join(__dirname,f));
const write=(f,v)=>fs.writeFileSync(path.join(__dirname,f),v);
const sha=b=>createHash('sha256').update(b).digest('hex');
const US=1_000_000, BTC=100_000_000, LOT=1000, CENTS=100;
const CURRENCY_DENOMINATOR=BTC*CENTS;

class Stop extends Error{}

function roundEven(x){
  const floor=Math.floor(x), tail=x-floor;
  if(tail===.5) return floor+floor%2;
  return Math.round(x);
}

function run(job,style,format){
  const start=job.begin*US, end=job.end*US;
  const pool=new Map(), orders=new Map(), trace=[];
  const counts={};
  const samples=[];
  const markChanges=[];
  const fees=[style.fee,style.fee];
  let priceLevelBook=new Map(), quote=job.book[0];
  let heldBTC=3*BTC, lockedBTC=0, freeUSDT=10000, lockedUSDT=0;
  let at=start, i=0, readTradePosition=0, last=0, b=0, markMinute=-1;
  let peak=null, dd=0, maxQuoteAge=0;
  let priorBid=null,priorEquity=null;

  function nav(mark){ return freeUSDT+lockedUSDT+mark*(heldBTC+lockedBTC)/CURRENCY_DENOMINATOR; }
  function setMarket(){
    while(b+1<job.book.length&&job.book[b+1][1]<=at)b++;
    if(quote[1]!==job.book[b][1]){ quote=job.book[b];priceLevelBook=new Map(); }
    assert.ok(quote[1]<=at);
  }

  const startMark=quote[4][2];
  const initial=nav(startMark);

  function mark(force=false){
    const bid=quote[4][2];
    const equity=nav(bid);
    const minute=Math.floor(at/60/US);
    peak=peak===null?equity:Math.max(peak,equity);
    dd=Math.max(dd,(peak-equity)/peak);
    if(force||markMinute!==minute){samples.push([at,bid,equity]);markMinute=minute;}
    if(force||bid!==priorBid||Math.abs(equity-priorEquity)>1e-8){
      markChanges.push([at,bid,equity]);priorBid=bid;priorEquity=equity;
    }
  }

  function settle(o,amount,price,kind,when,proof){
    assert.ok(amount>0&&amount<=o.left);
    const notional=amount*price/CURRENCY_DENOMINATOR;
    const fee=notional*fees[kind==='maker'?0:1];
    if(o.buy){
      if(kind==='maker'){
        freeUSDT+=o.reserve;
        lockedUSDT-=o.reserve;
        o.reserve=0;
      }
      freeUSDT-=notional+fee;
      heldBTC+=amount;
    }else{
      if(kind==='maker')lockedBTC-=amount;
      else heldBTC-=amount;
      freeUSDT+=notional-fee;
    }
    assert.ok(heldBTC>=0&&lockedBTC>=0&&freeUSDT>=-1e-7&&lockedUSDT>=-1e-7);
    o.left-=amount;
    o.deal+=amount;
    o.value+=notional;
    if(!o.left)o.state=1;
    trace.push(['fill',when,o.id,Number(o.buy),amount,price,kind,proof,fee]);
  }

  function signed(event){
    const [when,,,id,aggressiveBuy,price,quantity]=event;
    let left=quantity;
    const candidate=[];
    for(const o of pool.values()){
      if(o.posted>=when||Boolean(aggressiveBuy)===o.buy)continue;
      if(o.buy?price<o.price:price>o.price)candidate.push(o);
    }
    candidate.sort((a,b)=>(a.buy?b.price-a.price:a.price-b.price)||a.id-b.id);
    for(const o of candidate){
      const assigned=Math.min(left,o.left*style.volume-o.volume);
      if(!assigned)break;
      o.volume+=assigned;
      o.witness.push([id,assigned]);
      left-=assigned;
      if(o.volume===o.left*style.volume){
        settle(o,o.left,o.price,'maker',when,o.witness);
        pool.delete(o.id);
      }
      if(!left)break;
    }
  }

  function advance(next){
    const cutoff=Math.min(end-1,next);
    while(i<job.tape.length&&job.tape[i][0]<=cutoff){
      const trade=job.tape[i++];
      at=trade[0];
      if(at>=quote[1])setMarket();
      last=trade[5];
      signed(trade);
      if(at>=quote[1])mark();
    }
    at=cutoff;
    setMarket();
    mark(cutoff===end-1);
    if(next>=end)throw new Stop();
  }

  function recv(name){ counts[name]=(counts[name]||0)+1;advance(at+200_000); }
  function account(){
    return {Balance:freeUSDT,FrozenBalance:lockedUSDT,Stocks:heldBTC/BTC,FrozenStocks:lockedBTC/BTC};
  }

  function submitted(buy,wanted,q){
    recv(buy?'Buy':'Sell');
    assert.ok(wanted>0&&Number.isFinite(q));
    const price=roundEven(wanted*CENTS);
    const quantity=roundEven(q*BTC/LOT)*LOT;
    const value=price*quantity/CURRENCY_DENOMINATOR;
    const maximumCost=value*(1+style.fee);
    if(quantity<=0||value<5||(buy?freeUSDT+1e-9<maximumCost:heldBTC<quantity)){
      trace.push(['reject',at,Number(buy),price,quantity,wanted,q]);
      return null;
    }
    const id=orders.size+1;
    const o={id,buy,price,quantity,left:quantity,posted:at,deal:0,value:0,volume:0,reserve:0,state:0,witness:[]};
    orders.set(id,o);
    trace.push(['order',at,id,Number(buy),price,quantity,wanted,q]);
    maxQuoteAge=Math.max(maxQuoteAge,at-quote[1]);
    assert.ok(at-quote[1]<=10*US,['stale',at,quote[1],at-quote[1]]);
    const k=buy?0:2;
    const level=quote[4];
    for(let j=k;j<level.length&&o.left;j+=4){
      const px=level[j], capacity=level[j+1];
      if(!px||(buy?px>price:px<price))break;
      const key=Number(buy)+':'+px;
      const prior=priceLevelBook.get(key)||0;
      const available=Math.max(0,capacity-prior);
      const take=Math.floor(Math.min(available,o.left)/LOT)*LOT;
      if(take){
        priceLevelBook.set(key,prior+take);
        settle(o,take,px,'taker',at,[quote[1],quote[2],quote[3],prior]);
      }
    }
    if(o.left){
      if(buy){
        o.reserve=o.left*price/CURRENCY_DENOMINATOR*(1+style.fee);
        assert.ok(freeUSDT+1e-7>=o.reserve);
        freeUSDT-=o.reserve;
        lockedUSDT+=o.reserve;
      }else{
        assert.ok(heldBTC>=o.left);
        heldBTC-=o.left;
        lockedBTC+=o.left;
      }
      pool.set(id,o);
    }
    mark();
    return id;
  }

  function orderRecord(o){
    return {Id:o.id,Status:o.state,Price:o.price/CENTS,Amount:o.quantity/BTC,DealAmount:o.deal/BTC,
      AvgPrice:o.deal?o.value*BTC/o.deal:0,Type:Number(!o.buy),Time:o.posted/1000};
  }

  const exchange={
    GetTrades(){
      recv('GetTrades');
      const fresh=job.tape.slice(readTradePosition,i);
      readTradePosition=i;
      return fresh.sort((a,b)=>a[3]-b[3]).map(r=>({Id:r[3],Time:Math.floor(r[1]/1000),Price:r[5]/CENTS,Amount:r[6]/BTC,Type:1-r[4]}));
    },
    GetDepth(){
      recv('GetDepth');
      let sides=[[],[]];
      const level=quote[4];
      for(let j=0;j<level.length;j+=4){
        for(const k of [0,1]){
          const px=level[j+2*k],qty=level[j+2*k+1];
          if(px&&qty)sides[k].push({Price:px/CENTS,Amount:qty/BTC});
        }
      }
      return {Asks:sides[0],Bids:sides[1]};
    },
    GetAccount(){recv('GetAccount');return account();},
    GetOrders(){recv('GetOrders');return Array.from(pool.values(),orderRecord);},
    GetOrder(id){recv('GetOrder');const o=orders.get(id);return o?orderRecord(o):null;},
    CancelOrder(id){
      recv('CancelOrder');
      const o=pool.get(id);
      if(!o)return false;
      if(o.buy){freeUSDT+=o.reserve;lockedUSDT-=o.reserve;o.reserve=0;}
      else{lockedBTC-=o.left;heldBTC+=o.left;}
      o.state=2;pool.delete(id);trace.push(['cancel',at,id]);return true;
    },
    Buy(p,q){return submitted(true,p,q);},
    Sell(p,q){return submitted(false,p,q);},
  };

  class DateAt extends Date{
    constructor(...a){ if(a.length)super(...a);else super(Math.floor(at/1000)); }
    static now(){ return Math.floor(at/1000); }
  }

  const ctx=vm.createContext({
    exchange,Date:DateAt,Sleep(ms){assert.ok(Number.isFinite(ms)&&ms>0);advance(at+ms*1000);},
    _N:format, _C:(fn,...a)=>fn(...a), ORDER_STATE_PENDING:0, ORDER_STATE_CANCELED:2,
    _:{reduce:(a,fn,initialValue)=>a.reduce(fn,initialValue),
       max:a=>Math.max(...a),min:a=>Math.min(...a)},
    Log(){},LogProfit(){},LogStatus(){},...job.args,
  });

  advance(Math.max(job.book[0][0]*US,job.tape[0][0]));
  try{vm.runInContext(job.source+'\nmain();',ctx,{timeout:80_000,filename:'FMZ-5094.js'});}
  catch(e){if(!(e instanceof Stop))throw e;}
  assert.equal(at,end-1);
  assert.equal(i,job.tape.length);
  const endingBid=quote[4][2];
  return {style,start,end,first_book_us:job.book[0][1],initial,startMark,trace,counts,samples,markChanges,maxQuoteAge,
    bidCents:endingBid,lastTradeCents:last,marked:nav(endingBid),markedDrawdownRatio:dd,cash:freeUSDT,lockedCash:lockedUSDT,
    inventory:heldBTC,lockedBTC,pending:[...pool.keys()]};
}

(async()=>{
  await new Promise(r=>setTimeout(r,400));
  const input=read('round45-5094-input.json.gz');
  const job=JSON.parse(gunzipSync(input));
  assert.equal(sha(job.source),job.source_sha256);
  const proof=read('round45-5094-abi.json');
  const abi=JSON.parse(proof);
  const engine=sha(read('fmz-wasm-engine.cjs'));
  assert.equal(abi.engine_sha256,engine);
  assert.deepEqual([abi.deposit.Balance,abi.deposit.Stocks],[10000,3]);
  let unexpected=0;
  global.__offlineProbe=()=>{unexpected++;throw Error('Market inputs must be offline');};
  const native=fmz.VCtx({start:'2019-09-01 00:00:00',end:'2019-09-01 00:01:00',period:'1h',basePeriod:'1m',
    exchanges:[{eid:'Binance',currency:'BTC_USDT',fee:[0,0]}]}).scope;
  const results=[];
  for(const style of [{name:'archived zero fee',fee:0,volume:1},{name:'strict double volume',fee:0,volume:2},{name:'0.1% per-side fee sensitivity',fee:.001,volume:1}])
    results.push(run(job,style,native._N));
  assert.equal(unexpected,0);
  write(receipt,gzipSync(JSON.stringify({input_sha256:sha(input),worker_sha256:sha(read('fmz_native_round45_5094_worker.cjs')),
      native_abi_sha256:sha(proof),engine_sha256:engine,results})));
})().catch(e=>{write('round45-5094-runtime-error.txt',String(e.stack||e));nativeProcess.exit(1);});
