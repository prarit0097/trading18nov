import assert from "node:assert/strict";
import fs from "node:fs";
import {createHash} from "node:crypto";

const pinnedEngine = "9a4699655d9f5d0ad105b14cf68b60d6fa1cc8a608ed85b11deebaccbaccbdea";
const pinnedArchive = "wyZp7irvRiBBoSkLINDqufqRsc6rZH7uoIwk1dZHlKIkLBz+fpeBi7mbgumRxiyBNZf2dN6YmiE6swRhWE9wNw==";
const path = new URL("./package/dist/index.js",import.meta.url);
const archive = fs.readFileSync(new URL("./piner-0.13.0.tgz",import.meta.url));
assert.equal(createHash("sha512").update(archive).digest("base64"),pinnedArchive);
assert.equal(createHash("sha256").update(fs.readFileSync(path)).digest("hex"),pinnedEngine);
const {compile, Engine, ArrayFeed, barMagnifierTimeframe} = await import(path);

async function fixture(){
    const start = 1767225600000;
    const step=300000;
    const base=1800000;
    const tuples = [
      [100,101,99,100],[100,100,99,100],[100,100,99,100],[100,100,99,100],[100,100,99,100],[100,100,99,100],
      [100,100,99,100],[94,95,92,93],[93,100,90,99],[99,106,99,104],[104,106,103,105],[105,105,102,104],
      [104,105,102,104],[104,104,102,103],[103,106,102,104],[104,105,103,104],[104,106,103,104],[104,104,103,104],
    ];
    const intrabars = tuples.map(([open,high,low,close],i)=>({time:start+i*step, open,high,low,close,volume:1}));
    const chart = Array.from({length:3},(_,i)=>{
      const b=intrabars.slice(i*6,(i+1)*6);
      return {time:b[0].time, open:b[0].open, high:Math.max(...b.map(x=>x.high)), low:Math.min(...b.map(x=>x.low)), close:b.at(-1).close, volume:6};
    });
    const injection = {
      targetTimeframe:barMagnifierTimeframe("30"),
      bars:intrabars,
      chartIntervals:{closeTimes:chart.map(x=>x.time+base),source:"utc-fixed"},
      coverage:{requested:{from:start,to:start+3*base},covered:[{from:start,to:start+3*base}],gaps:[],complete:true},
    };
    assert.equal(injection.targetTimeframe,"5");
    async function run(use,coof,data,backend="js") {
      const program=compile(`//@version=6
strategy("separated intrabar checks", initial_capital=10000, margin_long=0, margin_short=0, use_bar_magnifier=${use}, calc_on_order_fills=${coof})
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
    strategy.exit("Bracket", from_entry="L", stop=95, limit=105)
`);
      const engine=new Engine(program,new ArrayFeed(chart),{backend});
      if(data) engine.ctx.magnifierData=data;
      await engine.run({symbol:"SYNTHETIC_CONTROL",timeframe:"30",mintick:0.01});
      return engine.strategy;
    }
    const results={mapping:Object.fromEntries(["1","5","15","30","60","120","240","D"].map(x=>[x,barMagnifierTimeframe(x)]))};
    try {
      results.control=await run(false,false,null);
      results.intrabar=await run(true,false,injection);
      results.interpreter=await run(true,false,injection,"interp");
      results.absent=await run(true,false,null);
      results.coof=await run(true,true,injection);
      try {
        await run(true,false,{...injection,targetTimeframe:"3"});
        throw Error("Invalid target was accepted");
      } catch(e) {results.invalidTarget=String(e)}
      try {
        await run(true,false,{...injection,coverage:{...injection.coverage,complete:false,
          gaps:[{from:start,to:start+step,reason:"provider-missing"}]}});
        throw Error("Incomplete coverage was accepted");
      } catch(e) {results.incomplete=String(e)}
      assert.equal(results.control.closedTrades.length,1);
      assert.equal(results.intrabar.closedTrades.length,1);
      assert.equal(results.control.closedTrades[0].exitPrice,105);
      assert.equal(results.intrabar.closedTrades[0].exitPrice,94);
      const b=results.intrabar.barMagnifier;
      assert.equal(b.active,true);
      assert.equal(b.magnifiedBars,3);
      assert.equal(b.intrabarsUsed,18);
      assert.equal(b.fallbackBars,0);
      assert.equal(b.capFallbackBars,0);
      assert.equal(b.dataFallbackBars,0);
      assert.equal(b.coverage,"complete");
      assert.deepEqual(results.intrabar,results.interpreter);
      assert.equal(results.absent.barMagnifier.active,false);
      assert.equal(results.coof.barMagnifier.active,false);
      assert(!results.invalidTarget.includes("was accepted"));
      assert(!results.incomplete.includes("was accepted"));
      results.verified=true;
    } catch(e) {
      results.error=e.stack??String(e);
      process.exitCode=1;
    }
    fs.writeFileSync(new URL("./fixture.json",import.meta.url),JSON.stringify(results,null,2));
}

async function settings(){
    const t=1767225600000, chartMs=1800000, ltfMs=300000;
    const intrabars=Array.from({length:18},(_,i)=>({time:t+i*ltfMs,open:101,high:102,low:i===7?100:101,close:101,volume:1}));
    const chart=Array.from({length:3},(_,i)=>({time:t+i*chartMs,open:101,high:102,low:i===1?100:101,close:101,volume:6}));
    async function play(properties, orders,version=6){
      const source=`//@version=${version}
strategy("Archived setting check", use_bar_magnifier=true, ${properties})
${orders}
`;
      const c=compile(source);
      const e=new Engine(c,new ArrayFeed(chart));
      e.ctx.magnifierData={targetTimeframe:"5",bars:intrabars,
        chartIntervals:{source:"utc-fixed",closeTimes:chart.map(x=>x.time+chartMs)},
        coverage:{complete:true,requested:{from:t,to:t+3*chartMs},covered:[{from:t,to:t+3*chartMs}],gaps:[]}};
      await e.run({symbol:"BINANCE:BTCUSDT",timeframe:"30",mintick:1});
      assert.equal(e.strategy.barMagnifier.fallbackBars,0);
      return {settings:c.metadata.strategy,size:e.ctx.strategyBroker.size,
              accountCurrency:e.ctx.strategy.account_currency,closed:e.strategy.closedTrades.length};
    }
    const order='if bar_index == 0\n    strategy.entry("L", strategy.long, limit=100, qty=1)';
    const control=await play("backtest_fill_limits_assumption=0",order);
    const requiresOneTick=await play("backtest_fill_limits_assumption=1",order);
    const baseUsd=await play('currency="USD"',order,5);
    const baseEur=await play('currency="EUR"',order,5);
    const whenOrders='if bar_index == 0\n    strategy.entry("L",strategy.long,qty=1)\nif bar_index == 1\n    strategy.close("L", when=false)';
    const when=await play("initial_capital=10000",whenOrders,5);
    assert.equal(control.size,1);
    assert.deepStrictEqual(control,requiresOneTick);
    assert.deepStrictEqual(baseUsd,baseEur);
    fs.writeFileSync(new URL("settings-fixture.json",import.meta.url),JSON.stringify({control,requiresOneTick,baseUsd,baseEur,when},null,2));
}

async function compileArchive(){
    const audit=JSON.parse(fs.readFileSync(new URL("./source-audit.json",import.meta.url),"utf8"));
    const output=[];
    for(const a of audit) {
      const src=fs.readFileSync(new URL(`./source-${a.id}.pine`,import.meta.url),"utf8");
      const opts={timeframe:a.period.endsWith("h")?String(Number(a.period.slice(0,-1))*60):a.period.endsWith("m")?a.period.slice(0,-1):"D"};
      let c;
      try {
        const code=src.replace(/^\/\*backtest\r?\n[\s\S]*?^\*\/\r?\n/m, "");
        c=compile(code);
        output.push({...a,target:barMagnifierTimeframe(opts.timeframe),diagnostics:c.diagnostics??[],kind:c.metadata?.isStrategy,settingsParsed:c.metadata?.strategy,inputs:c.metadata?.inputs,requests:c.metadata?.securityDependencies});
      } catch(e) {
        output.push({...a,target:barMagnifierTimeframe(opts.timeframe),compileError:String(e)});
      }
    }
    fs.writeFileSync(new URL("./compile-probe.json",import.meta.url),JSON.stringify(output,null,2));
}

async function replay(){
    const read=name=>fs.readFileSync(new URL(name,import.meta.url));
    const load=name=>JSON.parse(read(name));
    const digest=data=>createHash("sha256").update(data).digest("hex");
    const verified=load("./fixture.json");
    const iso=load("./isolation-probe.json");
    assert(verified.verified&&iso.privateDenied&&iso.networkDenied);
    const sourceList=load("./source-audit.json");

    function objects(data){
      return data.map(([time,open,high,low,close,volume])=>({time,open,high,low,close,volume}));
    }
    function checkTimes(p){
      assert.equal(p.chartTimeframe,p.chartTimeframe.toUpperCase());
      assert.equal(p.targetTimeframe,barMagnifierTimeframe(p.chartTimeframe));
      assert.equal(p.chart.length*p.chartMs,p.to-p.from);
      assert.equal(p.intrabar.length*p.ltfMs,p.to-p.from);
      assert(p.intrabar.length <= 200000);
      for(const [series,ms] of [[p.chart,p.chartMs],[p.intrabar,p.ltfMs]]){
        assert(series.every(([t,o,h,l,c,v],i)=>t===p.from+i*ms&&l>0&&l<=Math.min(o,c)&&Math.max(o,c)<=h&&v>0));
      }
    }
    async function runCase(edition, p, backend, model){
      const bars=objects(p.chart);
      const engine=new Engine(edition,new ArrayFeed(bars),{backend,strategy:model});
      engine.ctx.magnifierData = {targetTimeframe:p.targetTimeframe,bars:objects(p.intrabar),
        chartIntervals:{closeTimes:bars.map(b=>b.time+p.chartMs),source:"utc-fixed"},
        coverage:{requested:{from:p.from,to:p.to},covered:[{from:p.from,to:p.to}],gaps:[],complete:true}};
      await engine.run({symbol:`BINANCE:${p.symbol}`,timeframe:p.chartTimeframe,mintick:p.symbol==="BTCUSDT"?0.1:0.01});
      const r=engine.strategy;
      const b=r.barMagnifier;
      assert(b?.active && b.coverage==="complete");
      assert.equal(b.magnifiedBars,p.chart.length);
      assert.equal(b.intrabarsUsed,p.intrabar.length);
      assert.equal(b.fallbackBars,0);
      assert.equal(b.capFallbackBars,0);
      assert.equal(b.dataFallbackBars,0);
      assert.equal(r.wins+r.losses+r.evens,r.closedTrades.length);
      for(const t of r.closedTrades){
        const values=[t.entryPrice,t.exitPrice,t.qty,t.commission,t.profit];
        assert(values.every(Number.isFinite)&&t.qty>0&&t.commission>=0&&t.entryPrice>0&&t.exitPrice>0);
        assert([-1,1].includes(t.dir)&&t.exitTime>=t.entryTime&&t.entryTime>=p.from&&t.exitTime<p.to);
        const modelPnl=t.qty*t.dir*(t.exitPrice-t.entryPrice)-t.commission;
        assert(Math.abs(modelPnl-t.profit)<1e-8*Math.max(1,Math.abs(modelPnl)));
      }
      return {openSize:engine.ctx.strategyBroker.size,entries:engine.ctx.strategyBroker.openTradeCount,report:r};
    }

    const byFrame={"1d":"D-60","1h":"60-10","45m":"45-5","15m":"15-2","1m":"1-10S"};
    const ids=process.argv.slice(3).map(Number);
    const output=[];
    for(const id of ids) {
      const a=sourceList.find(x=>x.id===id);
      const source=read(`./source-${id}.pine`);
      assert.equal(digest(source),a.script_sha256);
      const code=source.toString("utf8").replace(/^\/\*backtest\r?\n[\s\S]*?^\*\/\r?\n/m,"");
      const entry={id,sourceSha256:a.source_sha256,scriptSha256:a.script_sha256,compiledSourceSha256:digest(code),period:a.period};
      try{
        assert(!/\bbacktest_fill_limits_assumption\s*=\s*[1-9]/.test(code),"Piner broker drops one-tick limit verification");
        const edition=compile(code);
        const meta=edition.metadata;
        assert(meta.isStrategy&&meta.strategy.useBarMagnifier&&!meta.strategy.calcOnOrderFills,"No active lower-timeframe broker with COOF");
        assert(!meta.securityDependencies.length,"Reference feed validation not completed");
        entry.header=meta.strategy;
        entry.warnings=edition.diagnostics;
        // Piner 0.13.0 defaults to v6's 100% margins for unqualified headers.
        // Pine v5 uses zero when omitted. Preserve each archived header value.
        const model={minQty:0.001};
        if(a.pine_header[0]==="5"){
          model.marginLong=meta.strategy.marginLong??0;
          model.marginShort=meta.strategy.marginShort??0;
        }
        entry.settings={...meta.strategy,...model};
        const f=byFrame[a.period];
        const files=fs.readdirSync(new URL(".",import.meta.url)).filter(n=>n.startsWith("feed-")&&n.includes(`-${f}-`)).sort();
        assert.equal(files.length,4,`Expected two dates for both BTC and ETH on ${f}`);
        entry.runs=[];
        for(const name of files) {
           const raw=read(name);
           const p=JSON.parse(raw);
           checkTimes(p);
           const js = await runCase(edition,p,"js",model);
           const interp = await runCase(edition,p,"interp",model);
           assert.deepStrictEqual(js,interp,`Backends disagree at ${name}`);
           entry.runs.push({symbol:p.symbol,from:p.from,to:p.to,sha256:digest(raw),chart:p.chartTimeframe,
                            target:p.targetTimeframe,bothBackendsEqual:true,...js});
        }
        entry.verified=true;
      } catch(e) {entry.error=e.stack??String(e)}
      output.push(entry);
      fs.writeFileSync(new URL(`./replay-${ids.join("-")}.json`,import.meta.url),JSON.stringify(output));
    }
}

const phase=process.argv[2];
if(phase==="fixture") await fixture();
else if(phase==="settings") await settings();
else if(phase==="compile") await compileArchive();
else if(phase==="replay") await replay();
else throw Error("Expected fixture, settings, compile, or replay");
