"""Compare the first trail touch in verified one-hour source paths."""
import math
import sys
from datetime import UTC,datetime
from decimal import Decimal as D,ROUND_CEILING,ROUND_FLOOR
from pathlib import Path
from research.fmz_round7_magnifier import read, sha256, write
from research.fmz_round32_trailing_offset import sma

DAY=86400000
HOUR=3600000

def iso(x):
    return datetime.fromtimestamp(x/1000,UTC).isoformat()

def grid(value,q,mode):
    return (value/q).to_integral_value(rounding=mode)*q

def scan(market, chart, source, trade, high_first):
    positive=trade["qty"]>0
    tick=D(".1") if market=="BTCUSDT" else D(".01")
    entry=D(str(trade["entryPrice"]))
    first=trade["entryTime"]
    end=trade["exitTime"]+DAY
    chart_by_start={row[0]:row for row in chart}
    swing=None
    offset=None
    for t,o,h,l,c,v in source:
        if not first<=t<end:
            continue
        origin=t//DAY*DAY
        close1=D(str(chart_by_start[origin-DAY][4]))
        off=close1*D(".005")
        activate=entry+close1*D(".02") if positive else entry-close1*D(".02")
        live_stop = entry*(D(".98") if positive else D("1.02")) if origin>first else None
        live_limit = entry*(D("1.09") if positive else D(".91")) if origin>first else None
        if live_stop is not None:
            live_stop=grid(live_stop,tick,ROUND_FLOOR if positive else ROUND_CEILING)
            live_limit=grid(live_limit,tick,ROUND_CEILING if positive else ROUND_FLOOR)
        op,hi,lo,cl=map(lambda x:D(str(x)),(o,h,l,c))
        for idx,px in enumerate((op,hi,lo,cl) if high_first else(op,lo,hi,cl)):
            if swing is not None:
                trail=swing-off if positive else swing+off
                trail=grid(trail,tick,ROUND_FLOOR if positive else ROUND_CEILING)
            else:
                trail=None
            exits=[]
            for kind,touch in (("trail",trail),("stop",live_stop),("limit",live_limit)):
                if touch is None:
                    continue
                direction=positive if kind!="limit" else not positive
                if (px<=touch if direction else px>=touch):
                    exits.append((kind,touch))
            if exits:
                k,px0=max(exits,key=lambda r:r[1] if positive else -r[1])
                return iso(t),k,float(px if idx==0 else px0),v
            if (px>=activate if positive else px<=activate) and (swing is None or (px>swing if positive else px<swing)):
                swing=px
    return None


SOURCE = "5a83ddb08f370b1a1571419c1885d9e18031846d58706f01235ed3a24a32efb7"
ENGINE = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"


def entry_signals(chart):
    prices=[row[4] for row in chart]
    mean=sma(prices,15)
    stdev=[math.sqrt(math.fsum((c-m)**2 for c in prices[i-14:i+1])/15)
           if m is not None else None for i,m in enumerate(mean)]
    prior=sma(stdev,15)
    high=[m+2*v if m is not None else None for m,v in zip(mean,stdev,strict=True)]
    low=[m-2*v if m is not None else None for m,v in zip(mean,stdev,strict=True)]
    output={name:[] for name in ("buy","sell","close long","close short","vol")}
    for i,c in enumerate(prices):
        vol=prior[i] is not None and stdev[i]>prior[i]
        up=i>0 and high[i-1] is not None and prices[i-1]<=high[i-1] and c>high[i]
        down=i>0 and low[i-1] is not None and prices[i-1]>=low[i-1] and c<low[i]
        for key,value in zip(output,(up and vol,down and vol,down,up,vol),strict=True):
            output[key].append(int(value))
    return output


def audit(market,case,result,minutes):
    assert len(case["chart"])==347 and len(case["hour"])==347*24
    baseline=result["literal"]
    assert baseline==result["no_table"]
    assert not baseline["diagnostics"] and not baseline["broker"]["diagnostics"]
    signals=entry_signals(case["chart"])
    assert all(baseline["plots"]["scope "+key]==value for key,value in signals.items())
    trades=baseline["broker"]["trades"]
    assert len(trades)==(13 if market=="BTCUSDT" else 9)
    grid = D(".1") if market=="BTCUSDT" else D(".01")
    witness=[]
    for trade in trades:
        day=iso(trade["entryTime"])[:10]
        if day not in ("2023-10-02","2023-10-24","2023-06-21","2023-03-10"):
            continue
        record=minutes if day.startswith("2023-10") else case["hour"]
        history=[scan(market,case["chart"],record,trade,b) for b in (False,True)]
        assert all(x is not None for x in history)
        witness.append({"entry_day":day,"entry":trade["entryPrice"],"native_exit":trade["exitPrice"],
                        "native_exit_on_tick_grid":D(str(round(trade["exitPrice"],8)))%grid==0,
                        "resampled_interval":"1m" if record is minutes else "1h",
                        "low_first_trace":history[0],"high_first_trace":history[1]})
    return {"market":market,"source_chart_days":347,"diagnostic_native_closed_trade_count":len(trades),
            "independently_verified_daily_entry_flags":{k:sum(v) for k,v in signals.items()},
            "venue_tick_path_witnesses":witness}


def main(work,out):
    assert sha256(work/"source-3366.md")==SOURCE
    assert sha256(work/"priced-runtime/pine_compat/pine_compat.pyd")==ENGINE
    feed,raw,lower=work/"3366-feed.json",work/"3366-native.json",work/"3366-minute-witnesses.json"
    source,native,minutes=read(feed),read(raw),read(lower)
    assert len(source["receipts"])==26 and len(minutes["receipts"])==2
    isolation=read(work/"round3-isolation-python.json")
    assert set(isolation)=={"file_error","network_error"}
    assert all(v[0]=="PermissionError" for v in isolation.values())
    cases=[audit(m,case,native[m],minutes["market"][m]) for m,case in source["markets"].items()]
    oct24,=[w for w in cases[0]["venue_tick_path_witnesses"] if w["entry_day"]=="2023-10-24"]
    assert oct24["native_exit"]==35134.6
    assert oct24["low_first_trace"]==oct24["high_first_trace"]
    assert oct24["low_first_trace"][:3]==("2023-10-24T00:59:00+00:00","trail",33584.6)
    june21,=[w for w in cases[0]["venue_tick_path_witnesses"] if w["entry_day"]=="2023-06-21"]
    assert june21["native_exit"]==30680.5 and june21["low_first_trace"]==june21["high_first_trace"]
    assert june21["low_first_trace"][:3]==("2023-06-21T01:00:00+00:00","trail",28945.1)
    january=next(t for t in native["BTCUSDT"]["literal"]["broker"]["trades"] if iso(t["entryTime"])[:10]=="2023-01-11")
    assert january["exitPrice"]==18997.392 and D(str(january["exitPrice"]))%D(".1")!=0
    write(out,{"schema":"FMZ #3366 verified entry signals and adverse combined-bracket evidence",
               "source_url":"https://www.fmz.com/strategy/433024",
               "source_revision":"7853bb2bf262c4567ac238d3552d97f0e50cb801","source_sha256":SOURCE,
               "native_engine_sha256":ENGINE,"input_sha256":sha256(feed),"native_probe_sha256":sha256(raw),
               "minute_input_sha256":sha256(lower),"hourly_receipts":source["receipts"],
               "minute_receipts":minutes["receipts"],"isolation":isolation,"cases":cases,
               "example_native_off_grid_exit":january,
               "coverage":[[3366,"Pending · daily trail and combined bracket chronology",
                            "The exact Pine builds and all chart entry flags independently match. A verified October BTC minute path reaches the source trail at 33584.60, 1550.00 below its daily engine exit, and a native January target is off tick grid. Full original hourly-plus-tick order chronology remains uncertified."]],
               "results":[]})


if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
