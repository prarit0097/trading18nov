"""Independent minute VWAP, endpoint regressions, and RMA RSI for #3749."""
import math
from collections import Counter, defaultdict
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR
import sys
from pathlib import Path
from research.fmz_round7_magnifier import ledger_metrics, read, sha256, write
from research.fmz_round40_4307 import recurrence

DAY=86_400_000

def regression(data,n):
    mid=(n-1)/2
    denom=math.fsum((i-mid)**2 for i in range(n))
    weights=[1/n+mid*(i-mid)/denom for i in range(n)]
    return [None]*(n-1)+[math.fsum(v*w for v,w in zip(data[i-n+1:i+1],weights,strict=True))
                          for i in range(n-1,len(data))]

def wilder(values,n):
    difference=[b-a if None not in(a,b) else None for a,b in zip(values,values[1:])]
    gain=recurrence([None if d is None else max(0,d) for d in difference],n,1/n)
    loss=recurrence([None if d is None else max(0,-d) for d in difference],n,1/n)
    return [None,*[None if a is None else 100 if b==0 else 0 if a==0 else 100-100/(1+a/b)
                   for a,b in zip(gain,loss,strict=True)]]

def signals(tape):
    typical=[(r[2]+r[3]+r[4])/3 for r in tape]
    c=[r[4] for r in tape]
    volume=[r[-1] for r in tape]
    vwap=[]
    notional=total=0
    anchor=None
    for r,v,x in zip(tape,volume,typical,strict=True):
        if r[0]//DAY!=anchor:
            anchor=r[0]//DAY
            notional=total=0
        notional+=v*x
        total+=v
        vwap.append(notional/total if total>0 else None)
    idx=regression(c,23)
    vwma=[]
    for i,val in enumerate(idx):
        j=i-22
        vwma.append(None if j<0 or idx[j] is None or not math.fsum(volume[j:i+1]) else math.fsum(
            f*v for f,v in zip(idx[j:i+1],volume[j:i+1],strict=True))/math.fsum(volume[j:i+1]))
    rp=wilder(regression(typical,100),13)
    vv=wilder(vwap,13)
    rv=wilder(vwma,23)
    longs,shorts,exit_longs,exit_shorts=[],[],[],[]
    for i in range(len(tape)):
        a,b,c=rv[i],rv[i-1],rv[i-2]
        longs.append(i>0 and None not in (vv[i],vv[i-1],rp[i],rp[i-1])
                      and vv[i]>vv[i-1] and rp[i]>rp[i-1] and vv[i]<20)
        shorts.append(i>=2 and None not in(a,b,c) and a>95 and a<b and c<b)
        exit_shorts.append(i>=2 and None not in(a,b,c) and a>b and c>b)
        exit_longs.append(i>0 and None not in (vv[i],vv[i-1]) and vv[i]>99.8 and vv[i-1]<=99.8)
    return {"VWAP":vwap,"VWAP RSI":vv,"RSIv":rv,"long":longs,"short":shorts,
            "exit long":exit_longs,"exit short":exit_shorts}

STEP=D(".001")
BUDGET=D(10_000)
FEE=D(".00075")

def limitprice(price,side,tick):
    return (price*(D("1.003") if side>0 else D(".9905"))/tick).to_integral_value(
        rounding=ROUND_CEILING if side>0 else ROUND_FLOOR)*tick


def model(tape,sig,tick):
    positions=[]
    outcomes=[]

    side=0
    pending_entry=0
    pending_close=False
    held=None
    for i,(stamp,o,h,l,close,volume) in enumerate(tape):
        op,high,low=map(lambda x:D(str(x)),(o,h,l))
        previous=held
        if pending_close and held:
            outcomes.append((*held,i,op,"market close"))
            held=None
            side=0
        if pending_entry:
            if held:
                outcomes.append((*held,i,op,"reversal"))
            side=pending_entry
            qty=BUDGET/op//STEP*STEP
            held=(i,op,side,qty)
        if held and held==previous:
            _,entry,_,qty=held
            limit=limitprice(entry,side,tick)
            can_fill=(high>=limit if side>0 else low<=limit) and volume>0
            if can_fill:
                fill=max(op,limit) if side>0 else min(op,limit)
                outcomes.append((*held,i,fill,"limit"))
                held=None
                side=0
        positions.append(held)
        during_close=915 < (stamp%DAY)//60_000 < 960
        pending_close=held is not None and (during_close or (side>0 and sig["exit long"][i]))
        long_want=sig["long"][i] and side<=0
        short_want=sig["short"][i] and side>=0
        assert not (long_want and short_want)
        pending_entry=1 if long_want else -1 if short_want else 0
    return outcomes,positions


SOURCE="2000addd24625b8458d38032aaa70dc32a5b6996dd630897ef0990ae33031d07"
ENGINE="6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"


def same(a,b):
    return a==b or (None not in (a,b) and math.isclose(a,b,abs_tol=1e-7,rel_tol=0))


def validation(market, source, old, new):
    tape=source.get("daily_comparison",source["chart"])
    assert len(tape)==10080
    assert old["literal"]["errors"][0].startswith("E_LANGUAGE_VERSION_DUPLICATE")
    assert old["compatibility"]==old["direction_bool_control"]
    assert len(old["all_true_control"]["broker"]["trades"])==(54 if market=="BTCUSDT" else 63)
    before=old["whole_monthly"]["broker"]
    stale=[t["entryBarIndex"] for t in before["trades"] if t["entryBarIndex"]==t["exitBarIndex"]]
    assert stale==([5226] if market=="BTCUSDT" else [6016,8854])
    assert new["broker"]["diagnostics"]==new["diagnostics"]==[]
    assert sum(d["code"]=="E_STRATEGY_EXIT_QTY" for d in before["diagnostics"])==(0 if market=="BTCUSDT" else 252)
    expected=signals(tape)
    for key,values in expected.items():
        actual=new["plots"]["scope "+key]
        assert all(same(a,b) for a,b in zip(actual,values,strict=True)), (market,key)
    plan,positions=model(tape,expected,D(".1") if market=="BTCUSDT" else D(".01"))
    observed=new["broker"]["trades"]
    assert len(plan)==len(observed)==(22 if market=="BTCUSDT" else 35)
    executed=[]
    cash_postings=defaultdict(lambda:D(0))
    for offer,t in zip(plan,observed,strict=True):
        i0,entry,side,qty,i1,exit,reason=offer
        assert (t["entryBarIndex"],t["exitBarIndex"],t["entryPrice"],t["exitPrice"],t["qty"])==(
            i0,i1,float(entry),float(exit),int(qty*1000)*side),(market,offer,t)
        gross=(exit-entry)*side*qty
        fee=(entry+exit)*qty*FEE
        assert math.isclose(float(gross),t["profit"],abs_tol=1e-8)
        executed.append({"dir":side,"qty":float(qty),"entryPrice":float(entry),"exitPrice":float(exit),
                         "entryTime":tape[i0][0],"exitTime":tape[i1][0],"profit":float(gross-fee),
                         "commission":float(fee),"reason":reason})
        cash_postings[i1]+=gross
    realized=D(0)
    for i,(position,snapshot) in enumerate(zip(positions,new["broker"]["equity"],strict=True)):
        realized+=cash_postings[i]
        mark_quantity=D(0)
        cash=BUDGET+realized
        if position:
            _,entry,side,qty=position
            cash-=side*qty*entry
            mark_quantity=side*qty*D(str(tape[i][4]))
        for k,want in (("cash",cash),("marketValue",mark_quantity),("equity",cash+mark_quantity)):
            assert math.isclose(float(want),snapshot[k],abs_tol=1e-8,rel_tol=0),(market,i,k)
    last=positions[-1]
    terminal=None
    if last is not None:
        i0,entry,direction,qty=last
        close=D(str(tape[-1][4]))
        terminal={"opened":tape[i0][0],"entry":float(entry),"direction":direction,
                  "size":float(qty),"mark":float(close),
                  "unrealized_gross":float((close-entry)*qty*direction),
                  "unrealized_less_roundtrip_fees":float(((close-entry)*direction-(close+entry)*FEE)*qty)}
    return {"market":market,"native_compatibility_trades":len(old["compatibility"]["broker"]["trades"]),
            "false_positional_short_close_preserved":True,"stale_unnamed_exit_bar_indices":stale,
            "verified_named_exit_trade_reasons":dict(Counter(t["reason"] for t in executed)),
            "terminal":terminal,"trades":executed}


def main(work,out):
    assert sha256(work/"source-3749.md")==SOURCE
    assert sha256(work/"priced-runtime/pine_compat/pine_compat.pyd")==ENGINE
    feed,raw,scored=work/"3749-feed.json",work/"3749-native.json",work/"3749-scored.json"
    tape,fixture=work.parent/"3749-tape-comparison.json",work/"3749-lifecycle.json"
    d,n,s=read(feed),read(raw),read(scored)
    comparison=read(tape)
    assert len(comparison["resolution"])==100
    assert all(v["daily_ok"] and not v["monthly_ok"] for v in comparison["resolution"])
    chosen=next(x for x in comparison["resolution"] if x["t"]==1699629420000)
    assert chosen["first"][0:3]==[4279348766,1699629420092,37099.0] and chosen["ids_missing"]==0
    evidence=read(fixture)
    for case,results in evidence.items():
        if case=="separate_entry_after_close":
            orders=results["unbound"]["orders"]
            assert [(o["id"],o["barIndex"]) for o in orders][-2:]==[("Short",5),("LP",5)]
            assert results["named"]["orders"]==orders[:-1]
        else:
            assert results["unbound"]==results["named"]
    cases=[validation(m,case,n[m],s[m]) for m,case in d["markets"].items()]
    isolation=read(work/"round3-isolation-python.json")
    assert set(isolation)=={"file_error","network_error"}
    assert all(v[0]=="PermissionError" for v in isolation.values())
    attrs={"id":3749,"group":"FMZ Pine v4 · position-scoped take profit",
           "exit":"Source minute market closes and correctly scoped take-profit limits",
           "period":"Binance USD-M · 2023-11-08 to 2023-11-15 UTC exclusive",
           "interval":"1m","archive_interval":"1m","currency":"USDT"}
    rows=[{**attrs,"market":c["market"],**ledger_metrics(c["trades"],float(BUDGET),int(c["terminal"] is not None))}
          for c in cases]
    rows.append({**attrs,"market":"BTCUSDT + ETHUSDT",**ledger_metrics(
        [t for c in cases for t in c["trades"]],float(2*BUDGET),sum(c["terminal"] is not None for c in cases))})
    write(out,{"schema":"FMZ #3749 exact quote recovery and verified scoped exit benchmark",
               "source_url":"https://www.fmz.com/strategy/432312",
               "source_revision":"7853bb2bf262c4567ac238d3552d97f0e50cb801",
               "source_sha256":SOURCE,"engine_sha256":ENGINE,"input_sha256":sha256(feed),
               "native_sha256":sha256(raw),"scored_sha256":sha256(scored),
               "market_receipts":d["receipts"],"daily_market_receipt":d["btc_daily_receipt"],
               "raw_trade_receipt":comparison["receipt"],"source_data_comparison_sha256":sha256(tape),
               "all_100_monthly_conflicts_resolved_to_daily_edition":True,"critical_market_quote":chosen,
               "order_fixture":evidence,"isolation":isolation,"cases":cases,
               "fee_sensitivity_per_side":float(FEE),
               "coverage":[[3749,"Tested · scoped position limits and authenticated 1m quote correction",
                            "Typed v4 identifier aliases retain the available market context. The historical raw tape authenticates all 100 exceptional BTC daily candle values. A scoped limit benchmark removes proven invalid persistence after a market close. Every BTC/ETH entry, close and daily VWAP decision independently matches."]],
               "results":rows})


if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
