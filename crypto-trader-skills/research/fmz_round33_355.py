"""Independent oscillator and trailing stop validation for FMZ #355."""

import math
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from research.fmz_round7_magnifier import aggregate,date_ms,ledger_metrics,read,sha256,verified_archives,write
from research.fmz_round26_977 import csv_rows

SOURCE="5708c3fec412b5669247dee901f24920afae76aa01ce1a61d133fa639a040bda"
ENGINE="6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
CAPITAL=100_000
FEE=.00075

def signals(chart, center):
    close=[bar[4] for bar in chart]
    cg=[]
    weights=range(1,109)
    for i in range(len(close)):
        if i<107:
            cg.append(0.0)
        else:
            recent=close[i-107:i+1][::-1]
            cg.append(-sum(price*w for price,w in zip(recent,weights,strict=True))/sum(recent)+center)
    norm=[]
    for i,v in enumerate(cg):
        seen=cg[i-108:i+1] if i>=108 else [v]
        lo,hi=min(seen),max(seen)
        norm.append((v-lo)/(hi-lo) if hi!=lo else 0.0)
    osc=[]
    for i in range(len(close)):
        val=sum(x*w for x,w in zip(norm[i-3:i+1],(1,2,3,4),strict=True))/10 if i>=3 else None
        osc.append(.5*math.log((1+1.98*(val-.5))/(1-1.98*(val-.5))) if val is not None else None)
    return osc

def step(ohlc, floor, activation, delta, peak, high_first):
    _,op,hi,lo,cl,_ = ohlc
    active_stop=max(floor,peak-delta) if peak is not None else floor
    if op<=active_stop:
        return op,peak
    if op>=activation:
        peak=max(op,peak) if peak is not None else op
    for price in (hi,lo,cl) if high_first else (lo,hi,cl):
        stop=max(floor,peak-delta) if peak is not None else floor
        if price<=stop:
            return stop,peak
        if price>=activation:
            peak=max(price,peak) if peak is not None else price
    return None,peak

def trade_tape(directory, market, date, minutes, receipts):
    name=f"{market}-trades-{date}.zip"
    path=directory/name
    digest=sha256(path)
    assert (directory/(name+".CHECKSUM")).read_text().split()[0]==digest
    receipts[(market,date)]={"name":name,"sha256":digest,"url":f"https://data.binance.vision/data/futures/um/daily/trades/{market}/{name}"}
    selected={}
    wanted={r[0] for r in minutes}
    for row in csv_rows(path):
        if not row[0].isdigit():
            continue
        i,price,qty,t=int(row[0]),float(row[1]),float(row[2]),int(row[4])
        start=t//60_000*60_000
        if start in wanted:
            selected.setdefault(start,[]).append((i,t,price,qty))
    return selected


def taped_step(rows, ohlc, floor, activation, delta, peak):
    assert all((a[0]+1==b[0] and a[1]<=b[1]) for a,b in zip(rows,rows[1:]))
    quoted=[row[2] for row in rows]
    assert (quoted[0],max(quoted),min(quoted),quoted[-1])==tuple(ohlc[1:5])
    assert math.isclose(math.fsum(row[3] for row in rows),ohlc[5],abs_tol=1e-7), (ohlc, math.fsum(row[3] for row in rows))
    for i,(trade_id,t,price,_) in enumerate(rows):
        stop=max(floor,peak-delta) if peak is not None else floor
        if price<=stop:
            return (price if i==0 else stop),peak,{"trade_id":trade_id,"event_time":t,"observed_trade_price":price}
        if price>=activation:
            peak=max(price,peak) if peak is not None else price
    return None,peak,None


def simulate(bars, entry, tick, compare, tape_for=None):
    fixed, activation, delta = entry-300*tick,entry+150*tick,50*tick
    peak=None
    ambiguous=[]
    for i,bar in enumerate(bars):
        _,op,hi,lo,_,_=bar
        if bar[5] == 0:
            continue
        first=hi-op<op-lo
        price,new_peak=step(bar,fixed,activation,delta,peak,first)
        other_price,other_peak=step(bar,fixed,activation,delta,peak,not first)
        if compare and (price!=other_price or (price is None and new_peak!=other_peak)):
            row={"bar":bar,"index":i,
                    "open_peak":peak,"high_first":first,
                    "native_price":price,"alternative_price":other_price,
                    "prior_stop":max(fixed,peak-delta) if peak is not None else fixed,
                    "fixed":fixed,"activation":activation}
            rows=tape_for(bar[0]) if tape_for is not None else None
            if not rows:
                return {"ambiguous":True,**row}
            price,new_peak,fired=taped_step(rows,bar,fixed,activation,delta,peak)
            ambiguous.append({**row,"tape_trigger_price":price,"tape_events":len(rows),"first_trigger":fired})
        if price is not None:
            return {"ambiguous":False,"bar":bar,"index":i,"peak":new_peak,
                    "trigger_price":price,"fill_price":price-5*tick,"tape_evidence":ambiguous}
        peak=new_peak
    return None


def open_size(capital,entry):
    return int(Decimal(f"{capital:.9e}")/Decimal(str(entry))*1000)/1000


def osc_gates(values, buy=-2.41,sell=2.43):
    output=[]
    for i, now in enumerate(values):
        if i<2 or any(x is None for x in values[i-2:i+1]):
            output.append((0,0))
            continue
        oldest,prior=values[i-2:i]
        output.append((int(prior<now<buy and oldest>=prior),int(prior>now>sell and oldest<=prior)))
    return output


def main(work,public,daily,output):
    feed=work/"355-inputs.json"
    replay=work/"355-probe.json"
    assert sha256(work/"source-355.md")==SOURCE
    assert sha256(work/"priced-runtime/pine_compat/pine_compat.pyd")==ENGINE
    isolation=read(work/"round3-isolation-python.json")
    assert set(isolation)=={"file_error","network_error"}
    assert all(v[0]=="PermissionError" for v in isolation.values())
    staged=read(feed)
    result=read(replay)
    receipts=[]
    tapes={}
    combined,rows,pooled=[],[],[]
    attributes={"id":355,"group":"FMZ Pine v3 · Fish Net combined fixed and trailing exit",
                "exit":"300-tick stop, 150-tick trailing activation, 50-tick distance",
                "period":"Binance USD-M · 2023-09-04 to 2023-09-11 UTC exclusive",
                "interval":"30m","archive_interval":"30m","currency":"USDT"}
    for data,r,trades_expected,events_expected,price_count in zip(staged["cases"],result,(2,4),(4,1),(1,0),strict=True):
        market=data["market"]
        c=data["chart"]
        assert len(c)==336 and r["market"]==market
        assert all(r["tested"]==r[v] for v in ("index_alias_control","inactive_alt","no_price_alt"))
        assert "exception" in r["raw"] and not r["tested"]["diagnostics"]
        plotted=r["tested"]["plots"]
        assert plotted["scoped length"]==[108]*len(c)
        observed=plotted["scoped oscillator"]
        diagnostics=[]
        for v in (54,54.5):
            expected=signals(c,v)
            diffs=[(i,a,b) for i,(a,b) in enumerate(zip(observed,expected,strict=True))
                   if (a is None)!=(b is None) or a is not None and not math.isclose(a,b,abs_tol=1e-8)]
            assert len(diffs)==(0 if v==54 else 110)
            diagnostics.append({"center":v,"different_bars":len(diffs),"first_difference":diffs[0] if diffs else None})
        expected=signals(c,54)
        gates=osc_gates(expected)
        assert list(zip(plotted["scoped buy"],plotted["scoped sell"],strict=True))==gates
        path,=verified_archives(public,market,"1m",("2023-09",),receipts)
        start,end=map(date_ms,("2023-09-04","2023-09-11"))
        minute=[]
        for row in csv_rows(path):
            if not row[0].isdigit() or not start<=int(row[0])<end:
                continue
            t=int(row[0])
            o,h,l,c1,v=map(float,row[1:6])
            assert int(row[6])==t+59_999 and 0<l<=min(o,c1)<=max(o,c1)<=h and v>=0
            assert v>0 or o==h==l==c1
            minute.append((t,o,h,l,c1,v))
        assert [x[0] for x in minute]==list(range(start,end,60_000))
        assert [list(x[:5]) for x in aggregate(minute,30)]==[x[:5] for x in c]
        model,ledger=[],[]
        tick=.1 if market=="BTCUSDT" else .01
        tape_data={}
        needed={i for t in r["tested"]["broker"]["trades"]
                for i in range(t["entryBarIndex"]*30,(t["exitBarIndex"]+2)*30)}
        scoped_minutes=[bar for i,bar in enumerate(minute) if i in needed]
        def tape_rows(stamp):
            date=datetime.fromtimestamp(stamp/1000,UTC).strftime("%Y-%m-%d")
            if date not in tape_data:
                path=daily/f"{market}-trades-{date}.zip"
                if not path.exists():
                    return None
                tape_data[date]=trade_tape(daily,market,date,scoped_minutes,tapes)
            return tape_data[date][stamp]
        simulation=r["tested"]["broker"]
        raw_trades=simulation["trades"]
        assert [t["entryBarIndex"] for t in raw_trades]==[i+1 for i,(buy,_) in enumerate(gates) if buy]
        assert all(not sell for _,sell in gates)
        assert len(raw_trades)==trades_expected and simulation["position"][-1]["size"]==0
        chart_equity=refined_equity=CAPITAL
        for i,t in enumerate(raw_trades):
            e=t["entryBarIndex"]
            entry=t["entryPrice"]
            assert t["id"]=="Long" and t["entryTime"]==c[e][0]==minute[e*30][0]
            assert c[e][1]==minute[e*30][1] and minute[e*30][5]>0
            assert math.isclose(entry,c[e][1]+5*tick,abs_tol=1e-9)
            assert open_size(chart_equity,entry)==t["qty"]
            chart_model=simulate(c[e:],entry,tick,False)
            minute_model=simulate(minute[e*30:],entry,tick,True,tape_rows)
            assert not chart_model["ambiguous"] and not minute_model["ambiguous"]
            assert e+chart_model["index"]==t["exitBarIndex"]
            assert math.isclose(chart_model["fill_price"],t["exitPrice"],abs_tol=1e-9)
            chart_profit=t["qty"]*(t["exitPrice"]-entry)
            assert math.isclose(chart_profit,t["profit"],abs_tol=1e-8)
            assert minute_model["bar"][0]//1_800_000*1_800_000==t["exitTime"]
            qty=open_size(refined_equity,entry)
            exit_price=minute_model["fill_price"]
            assert all(math.isclose(price/tick,round(price/tick),abs_tol=1e-7,rel_tol=0)
                       for price in (entry,exit_price))
            fee=FEE*qty*(entry+exit_price)
            realized=qty*(exit_price-entry)
            evidence=minute_model["tape_evidence"]
            exact=next((p["first_trigger"]["event_time"] for p in evidence if p["first_trigger"]),None)
            effective_time=minute_model["bar"][0] if exact is None else exact
            ledger.append({"entryTime":t["entryTime"],"exitTime":effective_time,"entryPrice":entry,
                           "exitPrice":exit_price,"qty":qty,"dir":1,"profit":realized-fee,"commission":fee})
            chart_equity+=chart_profit
            refined_equity+=realized
            model.append({"native_trade":t,"chart_rebuilt":chart_model,"minute_rebuilt":minute_model,
                          "refined_trade":ledger[-1]})
            assert i==len(raw_trades)-1 or effective_time<raw_trades[i+1]["entryTime"]
        assert sum(len(v["minute_rebuilt"]["tape_evidence"]) for v in model)==events_expected
        assert sum(not math.isclose(v["native_trade"]["exitPrice"],v["refined_trade"]["exitPrice"],abs_tol=1e-8) for v in model)==price_count
        assert math.isclose(CAPITAL+sum(t["profit"] for t in raw_trades),simulation["equity"][-1]["equity"],abs_tol=1e-8)
        combined.append({"market":market,"models":model,"oscillator_controls":diagnostics,
                         "empty_one_minute_groups":sum(r[5]==0 for r in minute)})
        rows.append({**attributes,"market":market,**ledger_metrics(ledger,CAPITAL,0)})
        pooled.extend(ledger)
    assert len(tapes)==3
    rows.append({**attributes,"market":"BTCUSDT + ETHUSDT",**ledger_metrics(pooled,2*CAPITAL,0)})
    write(output,{"schema":"FMZ #355 Fish Net · archived conditional exits verified on Binance tape",
                  "source_url":"https://www.fmz.com/strategy/426455",
                  "source_revision":"7853bb2bf262c4567ac238d3552d97f0e50cb801",
                  "source_sha256":SOURCE,"engine_sha256":ENGINE,"input_sha256":sha256(feed),
                  "replay_sha256":sha256(replay),"isolation":isolation,
                  "market_receipts":staged["market_receipts"],"minute_receipts":receipts,
                  "tape_receipts":list(tapes.values()),"cases":combined,
                  "cost_model":{"entry_slippage_ticks":5,"exit_slippage_ticks":5,
                                "archive_commission":0,"overlay_fee_per_side":FEE,"capital_per_market":CAPITAL},
                  "coverage":[[355,"Tested · native v3 Fish Net with tape-audited trailing stops",
                               "Archived −2.41/+2.43 thresholds. Six closes, with all five one-minute ambiguities resolved using official trade tapes. One BTC price change changes later sizing. The fee overlay is applied to the same refined closed lots."]],
                  "results":rows})

if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
