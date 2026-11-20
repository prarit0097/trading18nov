"""Audit #3038's pre-entry bracket and the archived-clock sensitivity."""

import math
import sys
from datetime import UTC,datetime
from decimal import Decimal
from pathlib import Path

from research.fmz_round7_magnifier import aggregate,read,sha256,verified_archives,write
from research.fmz_round26_977 import csv_rows
from research.fmz_round33_355 import trade_tape

SOURCE="89f83a19c5fc7e7666531b9a91169aee896ac070cff8d8356ad8b47cc299de8a"
ENGINE="6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
ALT="9a4699655d9f5d0ad105b14cf68b60d6fa1cc8a608ed85b11deebaccbaccbdea"
DAY=86400_000
FEE=Decimal(".00075")

def min_candles(path,start,end):
    rows=[]
    for r in csv_rows(path):
        if r[0].isdigit() and start<=int(r[0])<end:
            t=int(r[0])
            o,h,l,c,v=map(float,r[1:6])
            assert int(r[6])==t+59_999 and 0<l<=min(o,c)<=max(o,c)<=h and v>=0
            assert v or o==h==l==c
            rows.append((t,o,h,l,c,v))
    assert [r[0] for r in rows]==list(range(start,end,60_000))
    return rows

def directed_prices(close,tick):
    true_buy=Decimal(str(close))*Decimal(".97")
    buy=true_buy//tick*tick
    stop=true_buy*Decimal(".99")//tick*tick
    target=(true_buy*Decimal("1.01")/tick).to_integral_value(rounding="ROUND_CEILING")*tick
    return tuple(map(float,(buy,stop,target)))

def next_touch(bars,buy,stop,target,minute_tape):
    opened=None
    for b in bars:
        t,o,h,l,c,v=b
        if not v:
            continue
        if opened is None:
            if l>buy:
                continue
            opened=(t,min(buy,o),b)
            if l<=stop or h>=target:
                events=minute_tape(b)
                assert all(a[0]<z[0] and a[1]<=z[1] for a,z in zip(events,events[1:]))
                price=[event[2] for event in events]
                assert (price[0],max(price),min(price),price[-1])==(o,h,l,c)
                assert math.isclose(math.fsum(e[3] for e in events),v,abs_tol=1e-7)
                first=next(i for i,event in enumerate(events) if event[2]<=buy)
                entry_note=events[first][:3]
                opened=(*opened,{"first_trade_at_limit":entry_note,"eligible_trade_events":len(events),
                                 "skipped_trade_ids":sum(z[0]-a[0]-1 for a,z in zip(events,events[1:]))})
                for event in events[first:]:
                    if event[2]<=stop or event[2]>=target:
                        return opened,(t,stop if event[2]<=stop else target,b,
                                       "stop" if event[2]<=stop else "target",event[:3])
            continue
        if l<=stop or h>=target:
            assert not (l<=stop and h>=target)
            return opened,(t,min(o,stop) if l<=stop else max(o,target),b,"stop" if l<=stop else "target")
    return opened,None

def main(work,node,minute_source,daily,out):
    assert sha256(work/"source-3038.md")==SOURCE
    assert sha256(work/"priced-runtime/pine_compat/pine_compat.pyd")==ENGINE
    assert sha256(node/"package/dist/index.js")==ALT
    isolation=read(work/"round3-isolation-python.json")
    assert set(isolation)=={"file_error","network_error"}
    assert all(v[0]=="PermissionError" for v in isolation.values())
    node_isolation=read(node/"isolation-probe.json")
    assert node_isolation=={"privateDenied":True,"networkDenied":True}
    feed=work/"3038-inputs.json"
    raw=work/"3038-probe.json"
    alt=node/"3038-piner.json"
    staged=read(feed)
    alternate=read(alt)
    assert alternate["engine"]==ALT
    main_cases=[]
    receipts=[]
    raw_tape={}
    rate={r["effectiveTime"]:Decimal(str(r["rate"])) for r in staged["fx"]["pairs"][0]["rates"]}
    end=staged["end"]
    for data,native,other,expected in zip(staged["cases"],read(raw),alternate["cases"],
                                        [(36338.6,35975.2,35737.0,.002,.002),(1961.73,1942.12,1933.44,.049,.05)],strict=True):
        m=data["market"]
        assert m==native["market"]==other["market"]
        chart=data["chart"]
        assert len(chart)==371
        assert native["literal_clock"]["errors"]==["timenow requires an explicit execution timestamp for this script execution"]
        baseline=native["native_clock"]
        assert baseline["broker"]==native["saved_clock"]["broker"] and baseline["plots"]["time_gate"]==native["saved_clock"]["plots"]["time_gate"]
        assert baseline["plots"]["clock"]==[end]*371
        assert baseline["plots"]["time_gate"]==[0]*364+[1]*7
        norm=native["grid"]["broker"]
        named=native["named_entry_control"]["broker"]
        assert len(norm["orders"])==len(named["orders"])==2
        assert norm["orders"][0]==named["orders"][0]
        assert [t["id"] for t in norm["orders"]]==["BUY","SELL"]
        assert [t["id"] for t in named["orders"]]==["BUY","INSTANT"]
        a0,a1=norm["orders"]
        b0,b1=named["orders"]
        target_day=a0["time"]
        assert target_day==chart[365][0]
        incoming, stop, daily_close, native_qty,piner_qty=expected
        assert math.isclose(incoming,a0["price"],abs_tol=1e-8)
        assert math.isclose(stop,b1["price"],abs_tol=1e-8) and a1["price"]==daily_close
        assert a0["qty"]==a1["qty"]==native_qty
        for mode in ("grid","bound"):
            alt_trade,=other[mode]["closed"]
            assert (alt_trade["entryTime"],alt_trade["exitTime"],alt_trade["exitPrice"],alt_trade["qty"])==(
                target_day,target_day,daily_close,piner_qty)
        px=(Decimal(".1") if m=="BTCUSDT" else Decimal(".01"))
        _,tar_stop,tar_level=directed_prices(chart[364][4],px)
        assert tar_stop==stop
        minute_file,=verified_archives(minute_source,m,"1m",("2023-11",),receipts)
        minute=min_candles(minute_file,end-7*DAY,end)
        assert [list(r[:5]) for r in aggregate(minute,1440)]==[r[:5] for r in chart[-7:]]
        market_fills=[]
        def subminute(bar):
            date=datetime.fromtimestamp(bar[0]/1000,UTC).strftime("%Y-%m-%d")
            return trade_tape(daily,m,date,[bar],raw_tape)[bar[0]]
        for i in range(365,371):
            buy,stop,target=directed_prices(chart[i-1][4],px)
            child=minute[(i-364)*1440:(i-363)*1440]
            e,x=next_touch(child,buy,stop,target,subminute)
            if e is not None:
                market_fills.append((i,e,x))
        (ix,opened,closed),=market_fills
        assert ix==365 and closed[3]=="target" and closed[1]==tar_level
        assert (opened[0],closed[0])==(1700578980000,1700581560000 if m=="BTCUSDT" else 1700579040000)
        assert math.isclose(opened[1],incoming,abs_tol=1e-8)
        fx=rate[target_day]
        prior=chart[ix-1]
        qty=Decimal(100)/(rate[prior[0]]*Decimal(str(prior[4]))*(1+FEE))//Decimal(".001")*Decimal(".001")
        alt_qty=Decimal(100)/(fx*Decimal(str(incoming))*(1+FEE))//Decimal(".001")*Decimal(".001")
        assert float(qty)==native_qty
        assert float(alt_qty)==piner_qty
        native_trade,=named["trades"]
        native_net=qty*(Decimal(str(b1["price"]-opened[1]))-FEE*Decimal(str(b1["price"]+opened[1])))*fx
        assert math.isclose(float(native_net),native_trade["profit"],abs_tol=1e-8)
        main_cases.append({"market":m,"signal_close_native_quantity":native_qty,"price_basis_piner_quantity":piner_qty,
                           "prior_day_exchange_rate":float(fx),"grid_open":opened,"first_minute_bracket_touch":closed,
                           "original_grid_unbound_exit":a1,"same_day_attached_control_exit":b1,
                           "piner_unnamed_and_named_exit_price":daily_close,
                           "prepared_grid_levels":{"limit":incoming,"stop":tar_stop,"target":tar_level}})
    write(out,{"schema":"FMZ #3038 original dynamic clock and pre-entry bracket evidence",
               "source_url":"https://www.fmz.com/strategy/433542",
               "source_revision":"7853bb2bf262c4567ac238d3552d97f0e50cb801",
               "source_sha256":SOURCE,"engine_sha256":ENGINE,"alternate_engine_sha256":ALT,
               "input_sha256":sha256(feed),"native_sha256":sha256(raw),"alternate_sha256":sha256(alt),
               "market_receipts":staged["market_receipts"],"fx_receipts":staged["fx_receipts"],
               "isolation":{"python":isolation,"node":node_isolation},
               "minute_receipts":receipts,"trade_tape_receipts":list(raw_tape.values()),"replay_clock":end,"cases":main_cases,
               "coverage":[[3038,"Pending · archived pre-entry bracket semantics",
                            "The literal code runs with the saved endpoint clock. Both engines fill the later daily close under the unnamed pre-entry bracket. The named Pine Compat daily control fills both stops; the observed Binance minute path reaches an earlier BTC target. Piner's bound control still uses the daily close. Exact host attachment remains unresolved."]],
               "results":[]})

if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
