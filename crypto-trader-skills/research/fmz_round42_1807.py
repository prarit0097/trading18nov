"""Audit the #1807 saved default signals and market order ledger."""

import math
import sys
from decimal import Decimal
from pathlib import Path

from research.fmz_round7_magnifier import ledger_metrics, read, sha256, write
from research.fmz_round40_4307 import recurrence

SOURCE = "e213ba7b0ec9370a3ec19e3aa7cb33a6c7af76f7b1be2782eecd7bbce4de4075"
ENGINE = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
CAPITAL = 1_000_000
FEE = Decimal(".00075")


def gates(candles, immediate_ema=False):
    close = [r[4] for r in candles]
    changes = [x - y for y,x in zip(close,close[1:])]
    gain = [None, *recurrence([max(x, 0) for x in changes], 2, .5)]
    loss = [None, *recurrence([max(-x, 0) for x in changes], 2, .5)]
    oversold_rsi = [n is not None and d and 100 - 100 / (1 + n / d) < 12
                    for n,d in zip(gain,loss,strict=True)]
    stoch = []
    for i,price in enumerate(close):
        lookback = candles[max(0,i-11):i+1]
        high, low = max(r[2] for r in lookback), min(r[3] for r in lookback)
        stoch.append(len(lookback)==12 and high>low and 100*(price-low)/(high-low)<10)
    average_short = recurrence(close, 1 if immediate_ema else 10, 2 / 11)
    average_long = recurrence(close, 1 if immediate_ema else 20, 2 / 21)
    sell = [False] * len(close)
    for i in range(1,len(close)):
        a,b,p,q=average_short[i],average_long[i],average_short[i-1],average_long[i-1]
        sell[i]=None not in (a,b,p,q) and a<b and p>=q
    buy = [bool(a and b) for a,b in zip(oversold_rsi,stoch,strict=True)]
    return {"rsi":[bool(v) for v in oversold_rsi],"stoch":stoch,"raw buy":buy,"raw sell":sell,"sellma":sell}


def state(candles,buy,sell):
    active=False
    closed=False
    peak=0
    basis=0
    out={name:[] for name in ("entry","close","target","stop","opposite")}
    for i,((_,_,h,lo,c,_),a,b) in enumerate(zip(candles,buy,sell,strict=True)):
        enter=bool(a and not active and not closed)
        if enter:
            active=True
            basis=c
        if active:
            peak=max(peak,h)
        target=active and peak>=basis*1.01 and lo<=peak
        stop=active and lo<=basis*.98
        opposite=bool(i>0 and active and b and not sell[i-1])
        closed=bool((target or stop or opposite) and not enter)
        if closed:
            active=False
            peak=0
        for key,value in zip(out,(enter,closed,target,stop,opposite),strict=True):
            out[key].append(value)
    return out


def orders_and_pnl(feed, run, intent):
    candles = feed["chart"]
    actual = run["broker"]
    assert not run["diagnostics"] and not actual["diagnostics"]
    cash = Decimal(CAPITAL)
    holding = None
    orders = []
    trades = []
    for i,(bar,mark) in enumerate(zip(candles,actual["equity"],strict=True)):
        stamp,op,_,_,close,_=bar
        base=feed["base"][i*4]
        assert base[:2]==bar[:2]
        price=Decimal(str(op))
        if i>0 and intent["entry"][i-1]:
            assert holding is None and not intent["close"][i-1]
            holding=(stamp,i,price)
            cash-=price
            orders.append(("strategy.long",i,stamp,op,1))
        if i>0 and intent["close"][i-1]:
            etime,ebar,eprice=holding
            holding=None
            cash+=price
            gross=price-eprice
            fee=(price+eprice)*FEE
            orders.append(("strategy.close",i,stamp,op,1))
            trades.append({"dir":1,"qty":1,"entryPrice":float(eprice),"entryTime":etime,"entryBar":ebar,
                           "exitPrice":op,"exitTime":stamp,"exitBar":i,"gross":float(gross),
                           "profit":float(gross-fee),"commission":float(fee)})
        value=Decimal(str(close)) if holding is not None else Decimal(0)
        for name,want in (("cash",cash),("marketValue",value),("netProfit",cash+value-CAPITAL),("equity",cash+value)):
            assert math.isclose(float(want),mark[name],abs_tol=1e-8,rel_tol=0)
    assert holding is None
    assert orders==[(v["direction"],v["barIndex"],v["time"],v["price"],v["qty"]) for v in actual["orders"]]
    assert len(trades)==2
    for seen,cue in zip(actual["trades"],trades,strict=True):
        assert (seen["entryBarIndex"],seen["exitBarIndex"],seen["qty"])==(cue["entryBar"],cue["exitBar"],1)
        assert math.isclose(seen["profit"],cue["gross"],abs_tol=1e-8)
    return orders,trades


def audit(market,feed,replays):
    assert {k:len(v) for k,v in feed.items()}=={"chart":120,"base":480,"3":2400,"5":1440}
    reject=replays["literal"]["errors"][0]
    assert reject.startswith("E_LEGACY_VERSION_FEATURE")
    result=replays["v3_repaired"]
    assert result==replays["v3_repaired_core"]==replays["v3_checked_numeric"]
    plot=result["plots"]
    assert plot["scope gate"]==plot["scope bands"]==[1]*120
    independent=gates(feed["chart"])
    assert all(plot["scope "+k]==v for k,v in independent.items())
    state_vars=state(feed["chart"],independent["raw buy"],independent["raw sell"])
    assert all(plot["scope "+k]==v for k,v in state_vars.items())
    data_first_seed=gates(feed["chart"],True)
    first_seed=state(feed["chart"],data_first_seed["raw buy"],data_first_seed["raw sell"])
    assert first_seed["entry"]==state_vars["entry"] and first_seed["close"]==state_vars["close"]
    orders,trades=orders_and_pnl(feed,result,state_vars)
    return {"market":market,"original_compiler_error":reject,
            "signal_counts":{k:sum(v) for k,v in {**independent,**state_vars}.items()},
            "orders":orders,"trades":trades}


def main(work,out):
    assert sha256(work/"source-1807.md")==SOURCE
    assert sha256(work/"priced-runtime/pine_compat/pine_compat.pyd")==ENGINE
    feed, raw=work/"1807-feed.json",work/"1807-native.json"
    data, replay=read(feed),read(raw)
    assert len(data["receipts"])==4
    cases=[audit(m,x,replay[m]) for m,x in data["markets"].items()]
    isolation=read(work/"round3-isolation-python.json")
    assert set(isolation)=={"file_error","network_error"}
    assert all(v[0]=="PermissionError" for v in isolation.values())
    attrs={"id":1807,"group":"FMZ Pine v3 · eager source compatibility",
           "exit":"Authored TP/SL and opposite signals, next-open market close",
           "period":"Binance USD-M · 2023-11-18 to 2023-11-23 UTC exclusive",
           "interval":"1h","archive_interval":"1h","currency":"USDT"}
    results=[{**attrs,"market":x["market"],**ledger_metrics(x["trades"],CAPITAL,0)} for x in cases]
    results.append({**attrs,"market":"BTCUSDT + ETHUSDT",
                    **ledger_metrics([t for x in cases for t in x["trades"]],2*CAPITAL,0)})
    write(out,{"schema":"FMZ #1807 audited default momentum and historical market execution",
               "source_url":"https://www.fmz.com/strategy/435880",
               "source_revision":"7853bb2bf262c4567ac238d3552d97f0e50cb801",
               "source_sha256":SOURCE,"engine_sha256":ENGINE,"native_sha256":sha256(raw),
               "input_sha256":sha256(feed),"market_receipts":data["receipts"],"isolation":isolation,
               "fee_sensitivity_per_side":float(FEE),"cases":cases,
               "coverage":[[1807,"Tested · preserved v3 eager defaults and market ledger",
                            "A narrow syntax/type compatibility variant keeps eager iff and the source default decision path. Complete original chart and auxiliary inputs, target/state controls and every fill reconcile. One closed win and loss on each market."]],
               "results":results})


if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
