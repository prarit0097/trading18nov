const assert = require("node:assert/strict");
const {createHash} = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {gunzipSync} = require("node:zlib");
const Library = require("./fmz-wasm-engine.cjs");

const ROOT = __dirname;
const DAY = 86400;
const CASH = 2;
const QTY = 10000;
const TAKER = 0.00075;
const POSITION_LONG = 0;
const POSITION_SHORT = 1;
const TP = Symbol("fixed clock cutoff");
const sha = raw => createHash("sha256").update(raw).digest("hex");
const read = name => fs.readFileSync(path.join(ROOT,name));
const same = (a,b) => a.length === b.length && a.every((value,i) => value === b[i]);

function replay(day,spec,source,coreTalib) {
  assert.equal(spec.samples.length,5761);
  const history = new Map(spec.fmz_history_rows.map(r => [r[0],r]));
  for (const row of spec.daily_fmz_near) {
    if (row[0] <= spec.today) history.set(row[0],row);
    if (row[0] === spec.today + DAY) {
      assert.deepEqual(row.slice(1,5),spec.daily_exchange);
    }
  }
  const bars = [...history.values()].sort((a,b) => a[0]-b[0]).map((r,i,a) => {
    if (i) assert.equal(r[0]-a[i-1][0],DAY);
    return {Time:(r[0]-DAY)*1000,Open:r[1],High:r[2],Low:r[3],Close:r[4],Volume:r[5]};
  });
  assert.equal(bars.at(-1).Time,(spec.today-DAY)*1000);
  const nCompleted = bars.length;
  assert.ok(nCompleted >= 500); // Causal history is long enough to cross-check alternate warmup lengths.
  bars.push(null);

  const fundingAt = spec.today+4*3600;
  const candidates = spec.funding_near_settlement.filter(r => r[5] === fundingAt*1000000 && r[1] <= fundingAt*1000000);
  assert.ok(candidates.length > 0,day);
  const rates = [...new Set(candidates.map(r => r[6]))];
  assert.equal(rates.length,1);
  const rate = Number(rates[0]);
  const lastPreFunding = candidates.at(-1);
  const firstRolledFunding = spec.funding_near_settlement.find(r => r[5] > fundingAt*1000000);
  assert.ok(firstRolledFunding);
  const markAtFunding = lastPreFunding[2];
  const rolledMark = firstRolledFunding[2];

  let i=0, cash=CASH, position=0, entry=0, direction, barAt=-1, lastSar=0;
  let maxWarmError=0, maxNumberRecords=0, funded=false;
  const orders=[], funding=[], path=[], counts={ticker:0,records:0,indicator:0,account:0};
  const quote = () => spec.samples[i];
  const timestamp = () => quote()[0]*1000;

  function getRecords(interval) {
    assert.equal(interval,DAY);
    counts.records++;
    if (barAt !== i) {
      const data=quote();
      bars[nCompleted] = {
        Time:spec.today*1000,Open:data[3],High:data[4],Low:data[5],Close:data[6],Volume:0,
      };
      barAt=i;
    }
    return bars;
  }

  function sar(records,accel,max) {
    assert.equal(records,bars);
    assert.equal(accel,0.02);
    assert.equal(max,0.2);
    counts.indicator++;
    const full=coreTalib.SAR(records,accel,max);
    assert.equal(full.length,bars.length);
    lastSar=full.at(-1);
    assert.ok(Number.isFinite(lastSar));
    for (const width of [101,251,501]) {
      const partial=coreTalib.SAR(records.slice(-width),accel,max).at(-1);
      maxWarmError=Math.max(maxWarmError,Math.abs(lastSar-partial));
      assert.equal(lastSar,partial,"Causal SAR differs across warmup lengths");
    }
    maxNumberRecords=Math.max(maxNumberRecords,records.length);
    return full;
  }

  function getTicker() {
    const data=quote();
    counts.ticker++;
    return {Last:data[6],Buy:data[9],Sell:data[10],Time:data[7]/1000};
  }

  function account() {
    counts.account++;
    return {Stocks:cash};
  }

  function order(side,limit,size) {
    const data=quote();
    const isBuy=side===1;
    const px=data[isBuy?10:9];
    const depth=data[isBuy?12:11];
    const time=data[0]*1000000;
    assert.equal(size,QTY);
    assert.equal(px,limit);
    assert.ok(data[7] <= time && data[8] <= time && time-data[7] <= 5000000,"No sufficiently fresh observed execution quote");
    assert.ok(depth>=size,"The limit may only partially fill at the observed best quote");
    const f=(size/px)*TAKER;
    const mark=data[15];
    let gross=0;
    if (direction==="buy" || direction==="sell") {
      assert.equal(position,0);
      assert.equal(direction,isBuy?"buy":"sell");
      assert.ok(cash>size/px+2*f,"Insufficient 1x inverse collateral");
      position=side*size;
      entry=px;
    } else {
      assert.equal(direction,isBuy?"closesell":"closebuy");
      assert.equal(position,-side*size);
      gross=position*(1/entry-1/px);
      position=0;
      entry=0;
    }
    cash+=gross-f;
    orders.push({at:data[0],side,direction,qty:size,price:px,fee:f,gross,cash,mark,
                 observed_top_size:depth,quote_local_us:data[7],quote_exchange_us:data[8],
                 last:data[6],sar:lastSar});
    return orders.length;
  }

  function pathPoint() {
    const row=quote();
    const mark=row[15];
    const price=row[6];
    const delta=position?position*(1/entry-1/mark):0;
    if (position) {
      assert.ok(cash+delta > Math.abs(position)/mark*0.005+Math.abs(position)/mark*TAKER,
        "Potential funding or maintenance constraint");
    }
    path.push([row[0],position,entry,cash,delta,mark,price,lastSar]);
  }

  function sleep(ms) {
    assert.equal(ms,5000);
    pathPoint();
    i++;
    if (quote()[0]===fundingAt) {
      assert.equal(funded,false);
      const amount=-(position/markAtFunding)*rate;
      const alternative=-(position/rolledMark)*rate;
      cash+=amount;
      funding.push({at:fundingAt,qty:position,mark:markAtFunding,rate,amount,alternative_mark:rolledMark,
                    alternative_amount:alternative,before:lastPreFunding,first_rolled:firstRolledFunding});
      funded=true;
    }
    if(quote()[0]===spec.end) throw TP;
  }

  const plotting={PlotRecords(){},PlotLine(){},PlotFlag(){}};
  const SimDate=class extends Date {
    constructor(...args) {super(...(args.length?args:[timestamp()]));}
    static now(){return timestamp();}
  };
  const exchange={
    SetContractType(type){assert.equal(type,"XBTUSD");},
    SetMarginLevel(level){assert.equal(level,1);},
    SetDirection(value){direction=value;},
    GetRecords:getRecords,GetTicker:getTicker,GetAccount:account,
    Buy:(price,amount)=>order(1,price,amount),Sell:(price,amount)=>order(-1,price,amount),
    GetCurrency:()=>"XBT_USD",
  };
  const scope={
    exchange,IsVirtual:true,Date:SimDate,PD_LONG:POSITION_LONG,PD_SHORT:POSITION_SHORT,
    talib:{SAR:sar},Amount:QTY,time_interval:DAY,Sleep:sleep,$:plotting,LogProfit(){},
  };
  try {
    vm.runInNewContext(source+"\nmain();",scope,{
      timeout:30000,filename:"pinned-fmz-880.js",
      contextCodeGeneration:{strings:false,wasm:false}
    });
    throw new Error("Source loop returned unexpectedly");
  } catch(e) {
    if (e!==TP) throw e;
  }

  assert.equal(timestamp(),spec.end*1000);
  assert.equal(i,5760);
  assert.equal(funded,true);
  pathPoint();
  assert.equal(path.length,5761);
  assert.equal(counts.indicator,5760);
  const mark=quote()[15];
  return {day,counts,settlement:"BTC",start:spec.begin,end:spec.end,cash,currency:"BTC",
          position,entry,ending_mark:mark,ending_unrealized:position?position*(1/entry-1/mark):0,
          final_sar:lastSar,orders,funding,path,max_warm_error:maxWarmError,
          available_completed_bars:nCompleted,max_number_records:maxNumberRecords};
}

async function main(){
  await new Promise(resolve=>setTimeout(resolve,300));
  const raw=read("round20-xbtusd-sar-tape.json.gz");
  const job=JSON.parse(gunzipSync(raw));
  assert.equal(sha(Buffer.from(job.source)),job.source_sha256);
  assert.equal(job.source_sha256,"d0a6b32e1c702ecb536ac9cb60416161186c8db7231c5829523c437355b9d6e5");
  assert.equal(job.author.archive_scope.args,'[["Amount",10000],["time_interval",86400]]');
  let unexpectedMarketRequests=0;
  global.__offlineProbe = () => {unexpectedMarketRequests++;throw Error("Native math helper cannot request network");};
  const ctx=Library.VCtx({start:"2020-08-01 02:00:00",end:"2020-08-01 10:00:00",
    period:"1d",basePeriod:"1h",exchanges:[{eid:"Futures_BitMEX",currency:"XBT_USD",balance:0,stocks:CASH}]});
  const result={source_sha256:job.source_sha256,job_sha256:sha(raw),native_engine_sha256:sha(read("fmz-wasm-engine.cjs")),scopes:[]};
  try {
    for (const [day,spec] of Object.entries(job.scenarios)) {
      try { result.scopes.push(replay(day,spec,job.source,ctx.scope.talib)); }
      catch(e) { result.scopes.push({day,error:String(e),stack:e.stack}); }
    }
    assert.equal(unexpectedMarketRequests,0);
    result.math_only_market_requests=unexpectedMarketRequests;
    fs.writeFileSync(path.join(ROOT,"round20-xbtusd-sar-run.json"),JSON.stringify(result)+"\n");
    assert.ok(result.scopes.every(s => !s.error),"One or more source scopes terminated");
  } finally {ctx.Join();}
}

main().catch(error=>{
  fs.writeFileSync(path.join(ROOT,"round20-xbtusd-sar-worker-error.txt"),String(error.stack||error)+"\n");
  process.exitCode=1;
});
