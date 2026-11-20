"""Measure first one-minute touches for the source fixed tick brackets."""
import math
import sys
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path
from research.fmz_round7_magnifier import ledger_metrics, read, sha256, write
from research.fmz_round40_4307 import recurrence

FRAME=10_800_000

def utc(stamp):
    return datetime.fromtimestamp(stamp/1000,UTC).isoformat()

def touches(minute, start, end, entry, side, tick):
    price=D(str(entry))
    minimum=D(100)*tick
    maximum=D(1500)*tick
    stop=price-side*minimum
    target=price+side*maximum
    for bar in minute:
        t,o,h,l,_,v=bar
        if not start<=t<end or not v:
            continue
        p, high, low=map(lambda x:D(str(x)),(o,h,l))
        if side*(p-stop)<=0:
            return t,"stop_open",float(p),bar
        if side*(p-target)>=0:
            return t,"target_open",float(p),bar
        s=low<=stop if side>0 else high>=stop
        q=high>=target if side>0 else low<=target
        if s and q:
            return t,"ambiguous",[float(stop),float(target)],bar
        if s:
            return t,"stop",float(stop),bar
        if q:
            return t,"target",float(target),bar
    return None

def rsi(prices):
    diff=[b-a for a,b in zip(prices,prices[1:])]
    up=recurrence([max(v,0) for v in diff],14,1/14)
    down=recurrence([max(-v,0) for v in diff],14,1/14)
    return [None,*[None if a is None else 100 if b==0 else 0 if a==0 else 100-100/(1+a/b)
                   for a,b in zip(up,down,strict=True)]]

def gates(values):
    buy,sell=[],[]
    for i,(p,x) in enumerate(zip(values,values[1:]),1):
        if p is None or x is None:
            continue
        if p<35<x:
            buy.append(i)
        if p>65>x:
            sell.append(i)
    return buy,sell


SOURCE = "16fa099c9b2ff273356c2060984e2a3755d64ef5f04123c02d44c7d69e185bc9"
ENGINE = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
CAPITAL = 1_000_000
FEE = D(".00075")


def audit(market, feed, observed):
    chart,minute,quarter = [feed[k] for k in ("chart","minute","quarter")]
    assert [len(r) for r in (chart,minute,quarter)]==[248,44640,2976]
    source=observed["v2_alias"]
    assert source==observed["v2_direction"]==observed["v2_no_alert_appendix"]
    assert observed["literal"]["errors"][0].startswith("E_LEGACY_VERSION_FEATURE")
    assert [d["code"] for d in source["diagnostics"]]==["W_LEGACY_SECURITY_LOOKAHEAD"]*7
    broker,plot=source["broker"],source["plots"]
    assert not broker["diagnostics"] and broker["position"][-1]["size"]==0
    one_rsi=rsi([r[4] for r in minute])
    fifteen_rsi=rsi([r[4] for r in quarter])
    for name,values in (("1m RSI",one_rsi[::180]),("15m RSI",fifteen_rsi[::12])):
        assert all(a==b or (None not in (a,b) and math.isclose(a,b,abs_tol=1e-9))
                   for a,b in zip(plot["scope "+name],values,strict=True)), name
    longs,shorts=gates(one_rsi[::180])
    last_longs,last_shorts=gates(one_rsi[179::180])
    assert (longs,shorts)!= (last_longs,last_shorts)
    assert [i for i,b in enumerate(plot["scope buy"]) if b]==longs
    assert [i for i,b in enumerate(plot["scope sell"]) if b]==shorts
    tick = D(".1") if market=="BTCUSDT" else D(".01")
    entry_signals=sorted([(i,1) for i in longs]+[(i,-1) for i in shorts])
    trades=[]
    changes=[]
    for i,((signal,side), tr) in enumerate(zip(entry_signals,broker["trades"],strict=True)):
        i0=signal+1
        assert tr["entryBarIndex"]==tr["exitBarIndex"]==i0 and tr["qty"]==side
        record=chart[i0]
        assert tr["entryTime"]==tr["exitTime"]==record[0]
        assert tr["entryPrice"]==record[1]==quarter[12*i0][1]==minute[180*i0][1]
        entry,venue_exit=broker["orders"][2*i:2*i+2]
        assert entry["price"]==tr["entryPrice"] and venue_exit["price"]==tr["exitPrice"]
        assert venue_exit["id"]==("Exit Long" if side>0 else "Exit Short")
        touched=touches(minute[180*i0:180*(i0+1)],record[0],record[0]+FRAME,record[1],side,tick)
        assert touched is not None and touched[1]!="ambiguous"
        stamp,kind,price,evidence=touched
        initial=D(str(record[1]))
        final=D(str(price))
        assert initial%tick==final%tick==0
        if not math.isclose(price,tr["exitPrice"],abs_tol=1e-9):
            changes.append({"entry":record[1],"source_chart_open":record[0],
                            "native_coarse_exit":tr["exitPrice"],"minute_exit":price,
                            "exit_touch_bar":evidence,"reason":kind})
        gross=(final-initial)*side
        fee=(final+initial)*FEE
        trades.append({"dir":side,"qty":1,"entryTime":record[0],"entryPrice":record[1],
                       "exitTime":stamp,"exitPrice":price,"commission":float(fee),
                       "profit":float(gross-fee),"exit_touch":kind})
    if market=="BTCUSDT":
        assert (len(longs),len(shorts),len(last_longs),len(last_shorts))==(15,16,26,14)
        assert [(utc(r["source_chart_open"]),r["native_coarse_exit"],r["minute_exit"],r["reason"])
                for r in changes]==[("2023-12-11T03:00:00+00:00",41812.3,41972.3,"stop"),
                                    ("2023-12-26T12:00:00+00:00",42870.0,42710.0,"stop")]
    else:
        assert (len(longs),len(shorts),len(last_longs),len(last_shorts))==(9,17,14,18)
        assert not changes
    return {"market":market,"verified_chart_bars":248,"verified_minute_bars":44640,
            "first_child_signal_counts":[len(longs),len(shorts)],
            "last_child_diagnostic_counts":[len(last_longs),len(last_shorts)],
            "dual_trigger_minutes":0,"native_ohlc_disagreements":changes,"trades":trades}


def main(work,out):
    assert sha256(work/"source-4026.md")==SOURCE
    assert sha256(work/"priced-runtime/pine_compat/pine_compat.pyd")==ENGINE
    probe,feed=work/"4026-native.json",work/"4026-feed.json"
    native,data=read(probe),read(feed)
    assert len(data["receipts"])==4
    isolation=read(work/"round3-isolation-python.json")
    assert set(isolation)=={"file_error","network_error"}
    assert all(v[0]=="PermissionError" for v in isolation.values())
    cases=[audit(m,r,native[m]) for m,r in data["markets"].items()]
    attrs={"id":4026,"group":"FMZ Pine v2 · first intrabar RSI, minute brackets",
           "exit":"Authored 100-tick stop and 1500-tick price target",
           "period":"Binance USD-M · December 2023 UTC",
           "interval":"3h","archive_interval":"3h","currency":"USDT"}
    rows=[{**attrs,"market":s["market"],**ledger_metrics(s["trades"],CAPITAL,0)} for s in cases]
    rows.append({**attrs,"market":"BTCUSDT + ETHUSDT",
                 **ledger_metrics([t for s in cases for t in s["trades"]],2*CAPITAL,0)})
    write(out,{"schema":"FMZ #4026 authenticated 1m/15m first-child RSI and fixed bracket replay",
               "source_url":"https://www.fmz.com/strategy/438929",
               "source_revision":"7853bb2bf262c4567ac238d3552d97f0e50cb801",
               "source_sha256":SOURCE,"engine_sha256":ENGINE,"native_sha256":sha256(probe),
               "input_sha256":sha256(feed),"market_receipts":data["receipts"],"isolation":isolation,
               "fee_sensitivity_per_side":float(FEE),"cases":cases,
               "coverage":[[4026,"Tested · Pine v2 first intrabar and exact minute stop ordering",
                            "Real complete 1m/15m exchange feeds verify both legacy RSI projections and all 57 entries and exits. Two misleading BTC chart-level profit targets become earlier verified stop triggers. Both controls agree with the legacy aliases."]],
               "results":rows})


if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
