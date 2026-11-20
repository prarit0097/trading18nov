"""Verify the HP solve with an independent banded Cholesky factorization."""
from math import isclose, sqrt
from pathlib import Path
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR
import sys
from research.fmz_round7_magnifier import ledger_metrics, read, sha256, write
from research.fmz_round40_4307 import recurrence

N=100
LAMBDA=1000

def factors():
    principal=[]
    lower1=[]
    lower2=[]
    for i in range(N):
        a=1+LAMBDA*(1 if i in (0,N-1) else 5 if i in (1,N-2) else 6)
        b=-LAMBDA*(2 if i in (1,N-1) else 4)
        l2=LAMBDA/principal[i-2] if i>=2 else 0
        l1=(b-l2*lower1[i-1])/principal[i-1] if i else 0
        principal.append(sqrt(a-l1*l1-l2*l2))
        lower1.append(l1)
        lower2.append(l2)
    return principal,lower1,lower2

def hp(values, matrix):
    if len(values)<N:
        return None
    d,l1,l2=matrix
    y=[0] * N
    z=[0] * N
    for i,val in enumerate(reversed(values)):
        y[i]=(val-(l1[i]*y[i-1] if i else 0)-(l2[i]*y[i-2] if i>=2 else 0))/d[i]
    for i in range(N-1,-1,-1):
        z[i]=(y[i]-(l1[i+1]*z[i+1] if i+1<N else 0)-(l2[i+2]*z[i+2] if i+2<N else 0))/d[i]
    return z[0]

def indicators(chart):
    source=[sum(row[1:5])/4 for row in chart]
    matrix=factors()
    fitted=[hp(source[max(i-N+1,0):i+1],matrix) for i in range(len(chart))]
    ranges=[max(r[2]-r[3],abs(r[2]-chart[i-1][4]),abs(r[3]-chart[i-1][4])) if i else r[2]-r[3]
            for i,r in enumerate(chart)]
    atr=recurrence(ranges,14,1/14)
    return source,fitted,atr


SOURCE="9a23e9d4ac3329e5f5e935a0122682d6850a0f34b525dbd802dca3c20b90edc2"
ENGINE="6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
CAPITAL=D(1_000_000)
STEP=D(".001")
FEE=D(".00075")


def bracket_hit(minutes, stop, limit):
    for bar in minutes:
        t, op, hi, lo, _, vol = bar
        if vol==0:
            continue
        o,h,l=map(lambda x:D(str(x)),(op,hi,lo))
        if o<=stop:
            return t,o,"stop gap"
        if o>=limit:
            return t,o,"target gap"
        assert not (l<=stop and h>=limit)
        if l<=stop:
            return t,stop,"stop"
        if h>=limit:
            return t,limit,"target"
    return None


def cold(case, observed):
    assert [len(case[k]) for k in ("chart","minute","quarter")]==[24,1440,96]
    run=observed["literal"]
    assert run==observed["direction_alias"]==observed["readiness_control"]
    p=run["plots"]
    assert p["scope hp"]==p["scope vwap"]==[None]*24
    assert p["scope timestamp"]==[case["minute"][60*i+59][0] for i in range(24)]
    assert p["scope reset"]==[0]+[1]*23
    assert p["scope buy"]==p["scope size"]==[0]*24
    assert not run["broker"]["orders"] and not run["broker"]["trades"]
    assert not run["diagnostics"] and not run["broker"]["diagnostics"]
    assert all(r["cash"]==r["equity"]==CAPITAL and r["netProfit"]==0
               for r in run["broker"]["equity"])


def funded_path(market, case, observed):
    chart,mins=case["warm_chart"],case["warm_minute"]
    assert [len(x) for x in (chart,mins)]==[144,8640]
    assert chart[-24:]==case["chart"]
    start=case["chart"][0][0]
    assert start==chart[120][0]
    raw=observed["gated_warmup"]
    pnl=raw["broker"]
    p=raw["plots"]
    assert not raw["diagnostics"] and not pnl["diagnostics"]
    ohlc,fitted,atr=indicators(chart)
    for key,series in (("hp",fitted),("vwap",fitted),("simple ohlc4",ohlc),("ATR",atr)):
        assert all(a==b or (None not in (a,b) and isclose(a,b,rel_tol=0,abs_tol=2e-8))
                   for a,b in zip(p["scope "+key],series,strict=True)),(market,key)
    assert fitted[:99]==[None]*99 and all(v is not None for v in fitted[99:])
    assert p["scope hp"]==observed["warmup_diagnostic"]["plots"]["scope hp"]
    tick=D(".1") if market=="BTCUSDT" else D(".01")
    cash=CAPITAL
    orders,trades=[],[]
    holding=None
    next_levels=None
    for i,(bar,mark) in enumerate(zip(chart,pnl["equity"],strict=True)):
        stamp,op,_,lo,c,_=bar
        assert mins[60*i][:2]==bar[:2]
        if next_levels is not None:
            entry=D(str(op))
            units=cash/entry//STEP*STEP
            cash-=entry*units
            stop,target=next_levels
            holding=(i,stamp,entry,units,stop,target)
            orders.append(("strategy.long",i,stamp,op,float(units)))
            next_levels=None
        if holding is not None and i>holding[0]:
            entry_index, entry_time, entry, units, stop, target=holding
            touched=bracket_hit(mins[i*60:(i+1)*60],stop,target)
            if touched is not None:
                t,price,kind=touched
                cash+=price*units
                gross=(price-entry)*units
                fee=(price+entry)*units*FEE
                trades.append({"dir":1,"qty":float(units),"entryPrice":float(entry),"entryTime":entry_time,
                               "entry_index":entry_index,"exit_index":i,"exitPrice":float(price),
                               "exitTime":t,"stop_level":float(stop),"target_level":float(target),
                               "reason":kind,"gross":float(gross),"commission":float(fee),"profit":float(gross-fee)})
                orders.append(("strategy.exit",i,stamp,float(price),float(units)))
                holding=None
        av=fitted[i]
        cross=(i>0 and av is not None and fitted[i-1] is not None
               and fitted[i-1]<=ohlc[i-1] and av>ohlc[i])
        decide=bool(stamp>=start and holding is None and cross)
        assert decide==bool(p["scope buy"][i])
        if decide:
            stop=min(lo,chart[i-1][3])-atr[i]
            limit=2*c-stop
            assert isclose(stop,p["scope stop"][i],abs_tol=1e-8,rel_tol=0)
            assert isclose(limit,p["scope target"][i],abs_tol=1e-8,rel_tol=0)
            floor=(D(str(stop))/tick).to_integral_value(rounding=ROUND_FLOOR)*tick
            ceil=(D(str(limit))/tick).to_integral_value(rounding=ROUND_CEILING)*tick
            next_levels=floor,ceil
        value=D(str(c))*holding[3] if holding else D(0)
        assert isclose(float(cash),mark["cash"],rel_tol=0,abs_tol=1e-7)
        assert isclose(float(cash+value),mark["equity"],rel_tol=0,abs_tol=1e-7)
    assert next_levels is None and holding is None
    assert orders==[(o["direction"],o["barIndex"],o["time"],o["price"],o["qty"]) for o in pnl["orders"]]
    for a,b in zip(trades,pnl["trades"],strict=True):
        assert (a["entry_index"],a["exit_index"],a["entryPrice"],a["exitPrice"],a["qty"])==(
            b["entryBarIndex"],b["exitBarIndex"],b["entryPrice"],b["exitPrice"],b["qty"])
        assert isclose(a["gross"],b["profit"],abs_tol=1e-7,rel_tol=0)
    assert [t["entry_index"] for t in trades]==([122] if market=="BTCUSDT" else [130,134])
    return {"market":market,"cold_saved_day_orders":0,"warm_history_bars":120,
            "first_ready_hp_index":99,"verified_warmed_orders":orders,
            "earlier_control_trade_count":len(observed["warmup_diagnostic"]["broker"]["trades"]),
            "trades":trades}


def main(work,out):
    assert sha256(work/"source-4016.md")==SOURCE
    assert sha256(work/"priced-runtime/pine_compat/pine_compat.pyd")==ENGINE
    raw,feed=work/"4016-native.json",work/"4016-feed.json"
    native,data=read(raw),read(feed)
    assert len(data["receipts"])==4
    isolation=read(work/"round3-isolation-python.json")
    assert set(isolation)=={"file_error","network_error"}
    assert all(v[0]=="PermissionError" for v in isolation.values())
    cases=[]
    for market, case in data["markets"].items():
        cold(case,native[market])
        cases.append(funded_path(market,case,native[market]))
    attrs={"id":4016,"group":"FMZ Pine v4 · independently initialized HP",
           "exit":"Archived ATR bracket with minute touch proof",
           "period":"Binance USD-M · 2024-02-17 UTC, with 120 hours of prehistory only",
           "interval":"1h","archive_interval":"1h","currency":"USDT"}
    rows=[{**attrs,"market":r["market"],**ledger_metrics(r["trades"],float(CAPITAL),0)} for r in cases]
    rows.append({**attrs,"market":"BTCUSDT + ETHUSDT",**ledger_metrics(
        [t for c in cases for t in c["trades"]],float(2*CAPITAL),0)})
    cold_attrs={**attrs,"group":"FMZ Pine v4 · exact archived cold-start day",
                "period":"Binance USD-M · 2024-02-17 UTC, archived 24h without prehistory"}
    rows.extend({**cold_attrs,"market":market,**ledger_metrics([],float(CAPITAL)*count,0)}
                for market,count in (("BTCUSDT",1),("ETHUSDT",1),("BTCUSDT + ETHUSDT",2)))
    write(out,{"schema":"FMZ #4016 archived cold start and authenticated prehistory-only replay",
               "source_url":"https://www.fmz.com/strategy/442093",
               "source_revision":"7853bb2bf262c4567ac238d3552d97f0e50cb801",
               "source_sha256":SOURCE,"engine_sha256":ENGINE,"input_sha256":sha256(feed),
               "native_sha256":sha256(raw),"market_receipts":data["receipts"],"isolation":isolation,
               "fee_sensitivity_per_side":float(FEE),"cases":cases,
               "coverage":[[4016,"Tested · exact day cold and prehistory-initialized diagnostics",
                            "The exact saved day alone has zero orders with 24/100 HP inputs. 120 earlier, order-disabled chart bars initialize an independent verified HP solve, permitting three next-open trades and three grid-correct minute bracket touches during the same saved day."]],
               "results":rows})


if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
