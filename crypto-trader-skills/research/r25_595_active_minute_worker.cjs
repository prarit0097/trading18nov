const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const {gunzipSync}=require("node:zlib");
const {createHash}=require("node:crypto");

const sha=buffer=>createHash("sha256").update(buffer).digest("hex");
const stop=Symbol("complete sampled hour");
const BALANCE=1000000;
const pinned="7a7471ae23a3f881ddfa5a23286dd8cdb78409b8301aac7c960957f19b0fe7ba";

function run(code,tape,filter){
  assert.equal(tape.samples.length,3600);
  assert.equal(tape.end-tape.start,3600);
  assert.ok(filter.apply_min_to_market&&filter.markets_allowed);
  const min=Number(filter.min_notional);
  assert.equal(min,5);
  let i=0, reads=0, balanceReads=0;
  let cash=BALANCE;
  const intents=[];
  function getRecords(){
    reads++;
    const [second,arrival,exchange,minute,open,close]=tape.samples[i];
    assert.equal(second,tape.start+i);
    assert.ok(arrival<=second*1000000&&minute<=second);
    assert.ok(Math.floor(exchange/60000000)*60===minute);
    return [{Time:minute*1000,Open:open,Close:close}];
  }
  function getAccount(){
    balanceReads++;
    return {Balance:cash,Stocks:0,FrozenBalance:0,FrozenStocks:0};
  }
  function market(side,price,size){
    assert.equal(price,-1);
    assert.ok(size>0&&Number.isFinite(size));
    const order={side,second:tape.start+i,quantity:size};
    intents.push(order);
    if(side==="buy"){
      order.valued_notional_bound=size*tape.proof.max_price_ratio;
      if(order.valued_notional_bound>=min) {
        order.condition="Eligible or ambiguous buy needs actual execution tape";
        throw new Error(order.condition);
      }
      order.condition="Below captured Binance size minimum";
    }else{
      order.condition="Zero base inventory, sale rejected";
    }
    return null;
  }
  const exchange={GetRecords:getRecords,GetAccount:getAccount,
    Buy:(p,s)=>market("buy",p,s),Sell:(p,s)=>market("sell",p,s)};
  function sleep(ms){
    assert.equal(ms,1000);
    i++;
    if(i===tape.samples.length)throw stop;
  }
  let result="source returned";
  let issue;
  try{
    vm.runInNewContext(code+"\nmain();",{exchange,Sleep:sleep,Log(){}},
      {filename:"archived-fmz-595.js",timeout:20000,contextCodeGeneration:{strings:false,wasm:false}});
  }catch(e){
    if(e===stop)result="fixed market boundary";
    else{result="incomplete"; issue=String(e);}
  }
  return {coin:tape.coin,day:tape.day,start:tape.start,end:tape.end,
    last_second:tape.start+i,reason:result,issue,record_reads:reads,account_reads:balanceReads,
    intents,cash,start_cash:BALANCE,stock:0,fills:0,fees:0};
}

function main(){
 const data=fs.readFileSync(path.join(__dirname,"r25-595-binance-active-minute-job.json.gz"));
 const job=JSON.parse(gunzipSync(data));
 assert.equal(sha(Buffer.from(job.source)),pinned);
 assert.equal(job.source_sha256,pinned);
 const [source,alt]=job.filters;
 assert.deepEqual(source.filter,alt.filter);
 const scopes=job.scopes.map(t=>run(job.source,t,source.filter[t.coin+"USDT"]));
 const report={job_sha256:sha(data),worker_sha256:sha(fs.readFileSync(__filename)),source_sha256:pinned,scopes};
 fs.writeFileSync(path.join(__dirname,"r25-595-active-minute-receipt.json"),JSON.stringify(report)+"\n");
}
try{main();}catch(e){
 fs.writeFileSync(path.join(__dirname,"r25-595-active-minute-error.txt"),String(e.stack||e)+"\n");
 process.exitCode=1;
}
