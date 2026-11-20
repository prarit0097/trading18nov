"""Independent OBV, PVT, HP, Bollinger and historical candle gate control."""
import math
from decimal import Decimal as D
from math import sqrt, fsum
from pathlib import Path
import sys
from research.fmz_round7_magnifier import ledger_metrics, read, sha256, write
from research.fmz_round32_trailing_offset import sma
from research.fmz_round40_4307 import recurrence
from research.fmz_round47_4016 import factors, hp

def stdev(src,n):
    out=[]
    for i,v in enumerate(src):
        block=[x for x in src[:i+1] if x is not None][-n:]
        avg=fsum(block)/n if len(block)==n else None
        out.append(sqrt(fsum((x-avg)**2 for x in block)/n) if avg is not None else None)
    return out

def norm(data):
    low,high=1e11,-1e11
    out=[]
    for d in data:
        if d is None:
            out.append(None)
            continue
        low,high=min(low,d),max(high,d)
        out.append(-1+2*(d-low)/max(high-low,1e-9))
    return out

def band(src, mid, std):
    return [(v-b+2*d)/(4*d) if None not in (v,b,d) and d>0 else None
            for v,b,d in zip(src,mid,std,strict=True)]

def above(v,a):
    return v is not None and v>a
def below(v,a):
    return v is not None and v<a

def curves(chart, seed):
    closes=[c[4] for c in chart]
    v=[c[-1] for c in chart]
    obv,pvt=[0.0],[0.0]
    for i in range(1,len(closes)):
        change=closes[i]-closes[i-1]
        obv.append(obv[-1]+v[i]*(int(change>0)-int(change<0)))
        pvt.append(pvt[-1]+v[i]*change/closes[i-1])
    result=[None,None]+[(obv[i]-pvt[i])-(obv[i-1]-pvt[i-1]) for i in range(2,len(closes))]
    pvt[0]=None
    nresult=recurrence(norm(result),seed,2/21)
    bbr=band(nresult,recurrence(nresult,seed,2/21),stdev(nresult,20))
    bbr1=band(closes,sma(closes,20),stdev(closes,20))
    delta=[a-b if None not in (a,b) else None for a,b in zip(bbr1,bbr,strict=True)]
    data=factors()
    filt=[hp(closes[max(i-99,0):i+1],data) for i in range(len(closes))]
    out={k:[] for k in ("buy long","buy short","close long","close short")}
    for i,(_,o,h,l,c,_) in enumerate(chart):
        _,o0,h0,l0,c0,_=chart[i-1] if i else chart[0]
        atrange=i>=16
        mid=[(r[2]+r[3])/2 for r in chart[i-16:i]] if atrange else []
        up=atrange and h>max(mid)
        dn=atrange and l<min(mid)
        inner=i>0 and h<h0 and l>l0
        bbh=i>=10 and l==o and o<min(r[3] for r in chart[i-10:i]) and o<c and c>(h0+l0)/2
        b,z,d,hp0=bbr[i],bbr1[i],delta[i],filt[i]
        l20=i>0 and above(d,0) and delta[i-1] is not None and delta[i-1]<=0
        l40=i>0 and above(hp0,0) and filt[i-1] is not None and filt[i-1]<=0
        long5=i>0 and hp0 is not None and filt[i-1] is not None and c<hp0 and hp0>filt[i-1]
        sell5=hp0 is not None and c>hp0
        z1,z2,z4,z5=above(z,1-1e-15),below(z,1) and above(z,.7-1e-15),below(z,.3) and above(z,-1e-15),below(z,0)
        a1,a5=above(b,1-1e-15),below(b,0)
        c1,b1=above(hp0,1-1e-15),above(d,1-1e-15)
        buy_long=(long5 or z5 or a5) and (inner or bbh or up)
        sell_long=((z1 or a1) or (l40 and l20)) and (inner or dn) and (c1 or b1)
        cancel=False  # The conditional declaration only shadows the outer Pine variable.
        buy_short=((z1 or z2 or a1 or sell5) and (l40 or l20)) and inner
        sell_short=(z5 or z4 or a5 or long5) and (inner or dn)
        for key,val in zip(out,(buy_long,buy_short,sell_long or cancel,sell_short),strict=True):
            out[key].append(int(val))
    return {"hp":filt,"obv":obv,"pvt":pvt,"transformed flow":nresult,"flow bb":bbr,"price bb":bbr1,**out}

CAPITAL=D(1_000_000)
STEP=D(".001")
FEE=D(".00075")

def model(feed, engine, signal):
    c=feed["chart"]
    p=engine["broker"]
    cash=CAPITAL
    held=None
    desired=0
    close_out=False
    trades,orders=[],[]
    for i,(bar,mark) in enumerate(zip(c,p["equity"],strict=True)):
        stamp,op,_,_,cl,_=bar
        px=D(str(op))
        prior_qty=D(0)
        if held is not None and (close_out or desired and held[3]!=desired):
            j,t,entry,direction,qty=held
            prior_qty=qty if not close_out else D(0)
            gross=(px-entry)*qty*direction
            fee=(px+entry)*qty*FEE
            cash+=px*qty*direction
            held=None
            trades.append({"dir":direction,"qty":float(qty),"entryPrice":float(entry),
                           "entryTime":t,"entryBar":j,"exitBar":i,"exitTime":stamp,
                           "exitPrice":op,"gross":float(gross),"profit":float(gross-fee),
                           "commission":float(fee)})
        if desired:
            assert held is None
            qty=(cash/px//STEP)*STEP
            cash-=px*qty*desired
            held=i,stamp,px,desired,qty
            orders.append(("strategy.long" if desired>0 else "strategy.short",i,stamp,float(prior_qty+qty),op))
        pos=held[3]*held[4] if held else D(0)
        value=pos*D(str(cl))
        for name,want in (("cash",cash),("marketValue",value),("equity",cash+value)):
            assert math.isclose(mark[name],float(want),abs_tol=1e-7,rel_tol=0),(i,name,mark,want)
        long_ok=signal["buy long"][i] and pos<=0
        short_ok=signal["buy short"][i] and pos>=0
        assert not (short_ok and long_ok)
        desired=1 if long_ok else -1 if short_ok else 0
        close_out=signal["close long"][i] and pos>0 or signal["close short"][i] and pos<0
    expected=[(a["direction"],a["barIndex"],a["time"],a["qty"],a["price"]) for a in p["orders"]]
    assert len(orders)==len(expected)
    for native,want in zip(expected,orders,strict=True):
        assert native[:3]+native[4:]==want[:3]+want[4:] and math.isclose(native[3],want[3],abs_tol=1e-9)
    for a,b in zip(trades,p["trades"],strict=True):
        pair=(b["entryBarIndex"],b["exitBarIndex"],b["entryPrice"],b["exitPrice"],b["qty"])
        assert pair==(a["entryBar"],a["exitBar"],a["entryPrice"],a["exitPrice"],a["qty"]*a["dir"]), (a,b)
        assert math.isclose(a["gross"],b["profit"],abs_tol=1e-7)
        for idx in (a["entryBar"], a["exitBar"]):
            assert c[idx][:2]==feed["quarter"][4*idx][:2]==feed["minute"][60*idx][:2]
    assert held
    _,t,entry,direction,qty=held
    last=D(str(c[-1][4]))
    return {"orders":orders,"trades":trades,"terminal":{"entry":float(entry),"opened":t,"direction":direction,"qty":float(qty),"mark":float(last),
            "gross_unrealized":float((last-entry)*direction*qty),
            "after_fees_if_closed_at_mark":float((last-entry)*direction*qty-(last+entry)*qty*FEE)}}


SOURCE="4c67ae7da368259d3dee368b00620b90f0d41217fba881b92ccab0716dac367f"
ENGINE="6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"


def audit(market, feed, variants, fixtures):
    assert [len(feed[k]) for k in ("chart","quarter","minute")]==[720,2880,43200]
    assert len(feed["price_discrepancies"])==(2 if market=="BTCUSDT" else 0)
    assert variants["literal"]==variants["direction_alias"]==variants["exact_comparison"]
    for record in fixtures:
        sample=record["plots"]
        assert sample["literal"]==sample["disjunction"]==sample["direct"]
        assert sample["difference"][1]==(record["candles"][1]["open"]-record["candles"][0]["high"])
        if sample["difference"][1]==0:
            assert sample["literal"][1]==sample["equality"][1]==1
    result={}
    for key,seed in (("literal",20),("documented_ema",1)):
        run=variants[key]
        p=run["plots"]
        assert not run["diagnostics"] and not run["broker"]["diagnostics"]
        assert p["scope time"]==[row[0] for row in feed["minute"][59::60]]
        assert sum(p["scope cancel"])==0
        independent=curves(feed["chart"],seed)
        for label,expect in independent.items():
            assert all(a==b or (None not in (a,b) and math.isclose(a,b,rel_tol=1e-7,abs_tol=1e-7))
                       for a,b in zip(expect,p["scope "+label],strict=True)), (market,key,label)
        result[key]=model(feed,run,independent)
        result[key]["entry_signals"]={label:sum(independent[label]) for label in ("buy long","buy short")}
    assert len(result["literal"]["trades"])==(15 if market=="BTCUSDT" else 16)
    assert len(result["documented_ema"]["trades"])==16
    return {"market":market,"original_source_prices":"Binance USD-M 15m",
            "minute_price_discrepancies_timestamp_only":feed["price_discrepancies"],
            "scopes":result}


def main(work,out):
    assert sha256(work/"source-3458.md")==SOURCE
    assert sha256(work/"priced-runtime/pine_compat/pine_compat.pyd")==ENGINE
    raw,feed=work/"3458-native.json",work/"3458-feed.json"
    fixtures=work/"3458-equality-fixtures.json"
    native,data,fixture=read(raw),read(feed),read(fixtures)
    assert len(data["receipts"])==8
    isolation=read(work/"round3-isolation-python.json")
    assert set(isolation)=={"file_error","network_error"}
    assert all(v[0]=="PermissionError" for v in isolation.values())
    cases=[audit(m,x,native[m],fixture[m]) for m,x in data["markets"].items()]
    attrs={"id":3458,"group":"FMZ Pine v4 · documented first-value EMA",
           "exit":"Authored market reversal and close-all conditions",
           "period":"Binance USD-M · 2023-10-24 to 2023-11-23 UTC exclusive",
           "interval":"1h","archive_interval":"1h","currency":"USDT"}
    rows=[{**attrs,"market":s["market"],**ledger_metrics(s["scopes"]["documented_ema"]["trades"],float(CAPITAL),1)}
          for s in cases]
    rows.append({**attrs,"market":"BTCUSDT + ETHUSDT",**ledger_metrics(
        [t for s in cases for t in s["scopes"]["documented_ema"]["trades"]],float(2*CAPITAL),2)})
    write(out,{"schema":"FMZ #3458 verified documented EMA, HP solver and market exercise",
               "source_url":"https://www.fmz.com/strategy/433080",
               "source_revision":"7853bb2bf262c4567ac238d3552d97f0e50cb801",
               "source_sha256":SOURCE,"native_engine_sha256":ENGINE,"input_sha256":sha256(feed),
               "native_sha256":sha256(raw),"equality_fixtures_sha256":sha256(fixtures),"market_receipts":data["receipts"],
               "fee_sensitivity_per_side":float(FEE),"isolation":isolation,"cases":cases,
               "coverage":[[3458,"Tested · source HP, documented EMA and verified reversal ledger",
                            "Pine v4 source and terminal timestamp projection agree. Independent HP, volume/Bollinger, sizing and position ledger tests verify both EMA seeds. Active scoped cancel remains false as authored. All documented-seed market closes match both public first-open feeds."]],
               "results":rows})


if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
