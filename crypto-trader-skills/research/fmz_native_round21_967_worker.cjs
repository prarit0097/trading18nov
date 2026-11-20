const assert = require("node:assert/strict");
const {createHash} = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {gunzipSync} = require("node:zlib");
const Library = require("./fmz-wasm-engine.cjs");

const ROOT=__dirname;
const CUT=Symbol("time cutoff");
const LONG=0, SHORT=1, WALLET=1, FACE=100, TAKER=0.0005, MAKER=0.0002;
const sha=raw=>createHash("sha256").update(raw).digest("hex");
const rawFile=name=>fs.readFileSync(path.join(ROOT,name));

function run(day,tape,job,talib,micro) {
  const {data,start,end}=tape;
  const stop=end-start;
  assert.equal(stop,72000);
  assert.equal(data.trades.length,data.quotes.length);
  assert.equal(data.quotes.length,data.derivative_ticker.length);
  assert.equal(data.trades.length,stop+1);
  assert.equal(tape.symbol,"BTC-USD-200327");
  assert.equal(tape.interval_ms,1000);
  assert.equal(tape.proof.derivative_ticker.funding_field_events,0);
  let at=0, cash=WALLET, pos=0, entry=0, marginLevel=1, direction;
  const rows=[], orders=[], recorded=[], counts={bars:0,sleeps:0,atr:0,empty:0,cancels:0};
  let curr=null, pending=null;

  function updateBars() {
    for (const [stamp,o,h,l,c] of data.trades[at]) {
      const offset=(stamp-start)/900;
      assert.equal(Math.floor(offset),offset);
      assert.ok(offset<=rows.length&&stamp<=start+at);
      rows[offset]={Time:stamp*1000,Open:o,High:h,Low:l,Close:c,Volume:0};
      if (curr===null||offset>=curr) curr=offset;
    }
  }

  function state() {
    const marker=data.derivative_ticker[at];
    const mark=marker?marker[2]:null;
    const unrealized=pos?pos*FACE*(1/entry-1/mark):0;
    if(pos) assert.ok(mark>0&&cash+unrealized>0.95*WALLET);
    recorded.push([start+at,cash,pos,entry,mark,unrealized]);
  }

  function sleep(ms) {
    assert.equal(ms%1000,0);
    assert.ok(ms>0);
    counts.sleeps++;
    for (let step=0;step<ms/1000;step++) {
      state();
      at++;
      updateBars();
      if(pending&&pending.fillSecond===start+at){
        const marker=data.derivative_ticker[at];
        assert.ok(marker);
        settle(pending.order,pending.order.limit,MAKER,marker[2]);
        pending=null;
      }
      if (at===stop) throw CUT;
    }
  }

  function getRecords() {
    counts.bars++;
    if (!rows.length) counts.empty++;
    return rows;
  }

  function exactPassiveEvidence(side,limit,first,last) {
    assert.ok(micro.start <= first && last <= micro.end);
    const opposite = -side;
    const tradeCandidates=[];
    const quoteCrossings=[];
    for(let sec=first;sec<last;sec++){
      for(const [offset,takerSide,p,q] of micro.tables.trades[sec]||[]){
        if(sec===first&&offset===0)continue;
        if(takerSide===opposite&&(side>0?p<=limit:p>=limit))
          tradeCandidates.push({t:sec*1000000+offset,p,q});
      }
      for(const [offset,bid,ask] of micro.tables.quotes[sec]||[]){
        if(sec===first&&offset===0)continue;
        if(side>0?ask<=limit:bid>=limit)
          quoteCrossings.push({t:sec*1000000+offset,bid,ask});
      }
    }
    if(!tradeCandidates.length&&!quoteCrossings.length)
      return {conclusion:"no observable match in exact cancellation window",from:first,to:last,tradeCandidates,quoteCrossings};
    const firstTrade=tradeCandidates.find(t=>t.q>=1&&(side>0?t.p<limit:t.p>limit));
    const priorQuotes=firstTrade?quoteCrossings.filter(q=>q.t<firstTrade.t):quoteCrossings;
    const priorTrades=firstTrade?tradeCandidates.filter(t=>t.t<firstTrade.t):tradeCandidates;
    const guaranteedBy=firstTrade?.t;
    const earliestPossible=first*1000000+1;
    const oneSecondBound=guaranteedBy&&(guaranteedBy<earliestPossible+999999);
    const noEarlierObservedInterest=!priorQuotes.length&&!priorTrades.length;
    const settled=guaranteedBy&&(oneSecondBound||noEarlierObservedInterest);
    return {
      conclusion:settled?"strict through price":"indeterminate passive fill",
      from:first,to:last,firstTrade,earliestPossible,guaranteedBy,oneSecondBound,
      tradeCandidates:tradeCandidates.slice(0,8),quoteCrossings:quoteCrossings.slice(0,8),
    };
  }

  function place(side,limit,qty,prevPos,tick,sourceType) {
    const quote=data.quotes[at];
    const mark=data.derivative_ticker[at];
    const time=(start+at)*1000000;
    assert.equal(qty,1);
    assert.equal(tick,0.5);
    assert.ok(limit>0&&Number.isFinite(limit));
    assert.ok(quote&&mark,"Missing time-matched depth or mark");
    const [seen,ex,bid,ask,bidQty,askQty]=quote;
    const price=side>0?ask:bid;
    const depth=side>0?askQty:bidQty;
    const context={timestamp:start+at,side,limit,qty,direction,prevPos,sourceType,quote,last:rows[curr].Close};
    orders.push(context);
    assert.ok(seen<=time&&ex<=time&&time-seen<=2000000&&bid<ask,"Stale or crossed best-quote state");
    if(side>0?limit<ask:limit>bid){
      assert.equal(pending,null);
      const next=Math.min(end,start+at+2);
      const evidence=exactPassiveEvidence(side,limit,start+at,next);
      context.passive=evidence;
      assert.notEqual(evidence.conclusion,"indeterminate passive fill","Passive queue/timing remained ambiguous");
      if(evidence.conclusion==="strict through price"){
        context.fill_local_us=evidence.firstTrade.t;
        pending={order:context,fillSecond:Math.ceil(evidence.firstTrade.t/1000000)};
      }
      return orders.length;
    }
    assert.ok(depth>=qty,"Limited visible depth for source order");
    context.fill_local_us=time;
    settle(context,price,TAKER,mark[2]);
    return orders.length;
  }

  function settle(context,price,feeRate,mark){
    const {qty,side}=context;
    if(context.direction!==direction)throw Error("Order direction changed before fill");
    let gross=0;
    const fee=qty*FACE/price*feeRate;
    if (direction==="buy"||direction==="sell") {
      assert.equal(pos,0);
      assert.equal(direction,side>0?"buy":"sell");
      assert.ok(cash>qty*FACE/price/marginLevel+2*fee);
      pos=side*qty;
      entry=price;
    } else {
      assert.equal(direction,side>0?"closesell":"closebuy");
      assert.equal(pos,-side*qty);
      gross=pos*FACE*(1/entry-1/price);
      pos=0;
      entry=0;
    }
    cash+=gross-fee;
    Object.assign(context,{price,fee,feeRate,gross,mark,cash,pos,entry});
  }

  const exchange = {
    SetContractType(symbol){assert.equal(symbol,"quarter");},
    GetRecords:getRecords,
    SetDirection(x){direction=x;},
    GetPosition(){return pos?[{ContractType:"quarter",Type:pos>0?LONG:SHORT,Amount:Math.abs(pos),Price:entry}]:[];},
    Buy:(...args)=>place(1,...args), Sell:(...args)=>place(-1,...args),
    GetOrders:()=>[],
    CancelOrder(id){
      const o=orders[id-1];
      assert.ok(o && pending===null);
      counts.cancels++;
      o.cancel_at=start+at;
      return !o.price;
    },
  };
  const scope = {
    exchange,$:{PlotRecords(){},PlotLine(){},PlotFlag(){}},
    LogStatus(){},Sleep:sleep,_D:()=>start+at,_C:f=>f(),
    PD_LONG:LONG,PD_SHORT:SHORT,
    talib:{ATR(bars,period){counts.atr++;assert.equal(period,45);return talib.ATR(bars,period);}},
    ...job.author.args,
  };
  updateBars();
  let issue;
  try {
    vm.runInNewContext(job.source+"\nmain();",scope,{
      filename:"pinned-fmz-967.js",timeout:40000,contextCodeGeneration:{strings:false,wasm:false}
    });
    throw new Error("Source loop returned unexpectedly");
  } catch(e) {
    if(e!==CUT) issue=String(e.stack||e);
  }
  state();
  return {day,begin:start,end,finished_at:start+at,issue,cash,pos,entry,counts,orders,path:recorded};
}

async function main(){
  await new Promise(resolve=>setTimeout(resolve,300));
  const raw=rawFile("round21-967-okx-cold-start.json.gz");
  const job=JSON.parse(gunzipSync(raw));
  const microRaw=rawFile("round21-967-micro-fill-tape.json.gz");
  const micro=JSON.parse(gunzipSync(microRaw));
  assert.equal(micro.base_sha256,sha(raw));
  assert.equal(sha(Buffer.from(job.source)),job.source_sha256);
  const expected={Amount:1,TradeInterval:2000,PriceTick:0.5,Symbol:"quarter",pd:45,factor:3};
  assert.deepEqual(job.author.args,expected);
  let mathMarketRequests=0;
  global.__offlineProbe = () => {mathMarketRequests++;throw Error("Math library input must be local");};
  const ctx=Library.VCtx({start:"2020-02-01 02:00:00",end:"2020-02-01 10:00:00",
    period:"15m",basePeriod:"5m",exchanges:[{eid:"Futures_OKX",currency:"BTC_USD",balance:0,stocks:WALLET}]});
  const result={source_sha256:job.source_sha256,job_sha256:sha(raw),micro_sha256:sha(microRaw),scopes:[]};
  try{
    for (const [day,tape] of Object.entries(job.scopes)) result.scopes.push(run(day,tape,job,ctx.scope.talib,micro.scopes[day]));
    assert.equal(mathMarketRequests,0);
    fs.writeFileSync(path.join(ROOT,"round21-967-okx-proven-receipt.json"),JSON.stringify(result)+"\n");
  }finally{ctx.Join();}
}
main().catch(error=>{
  fs.writeFileSync(path.join(ROOT,"round21-967-okx-proven-error.txt"),String(error.stack||error)+"\n");
  process.exitCode=1;
});
