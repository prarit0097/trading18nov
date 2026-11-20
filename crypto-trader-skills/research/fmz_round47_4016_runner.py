"""Check exact FMZ #4016 one-day history and filter data readiness."""
import json
import re
import sys
from pathlib import Path
ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from replay_2864 import engine_options,pine_compat,sha256
from probe_1216 import objects

DIGEST="9a23e9d4ac3329e5f5e935a0122682d6850a0f34b525dbd802dca3c20b90edc2"
OBS="""
plot(HP,"scope hp")
plot(myvwap,"scope vwap")
plot(av,"scope av")
plot(newSession,"scope reset")
plot(start,"scope timestamp")
plot(validLong?1:0,"scope buy")
plot(ohlc4,"scope simple ohlc4")
plot(strategy.position_size,"scope size")
plot(t_stop,"scope stop")
plot(t_target,"scope target")
plot(atr,"scope ATR")
"""
def main():
    raw=(ROOT/"source-4016.md").read_bytes()
    assert sha256(raw)==DIGEST
    fence=chr(96)*3
    (block,)=re.findall(r"(?ms)^"+fence+r" pinescript[^\n]*\n(.*?)^"+fence,raw.decode())
    source,n=re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*","",block)
    assert n==1
    explicit=source.replace('long=strategy.long','direction=strategy.long')
    ready=explicit.replace("array.get(x,0)","bar_index >= leng-1 ? array.get(x,0) : na")
    assert explicit!=source and ready!=explicit
    data=json.loads((ROOT/"4016-feed.json").read_bytes())
    report={}
    for market,record in data["markets"].items():
        opts={**engine_options(market),"chart_timeframe":"60"}
        sym=opts["chart_symbol"]
        chart=objects(record["chart"])
        opts["request_bars"].update({f"{sym}:1":objects(record["minute"])})
        r={}
        for name,code in (("literal",source),("direction_alias",explicit),("readiness_control",ready)):
            try:
                x=pine_compat.run_script(code+OBS,chart,**opts)
                r[name]={"diagnostics":x["diagnostics"],"broker":x["strategy"],
                         "plots":{p["title"]:p["values"] for p in x["plots"] if p.get("title","").startswith("scope ")}}
            except ValueError as e:
                r[name]={"errors":str(e).splitlines()}
        warm_options={**opts,"request_bars":{**opts["request_bars"],f"{sym}:1":objects(record["warm_minute"])}}
        burn=pine_compat.run_script(source+OBS,objects(record["warm_chart"]),**warm_options)
        r["warmup_diagnostic"]={"diagnostics":burn["diagnostics"],"broker":burn["strategy"],"plots":{z["title"]:z["values"] for z in burn["plots"] if z.get("title","").startswith("scope ")}}
        gated=source.replace("inDateRange = true",f'inDateRange = time >= {record["chart"][0][0]}')
        assert gated!=source
        restricted=pine_compat.run_script(gated+OBS,objects(record["warm_chart"]),**warm_options)
        r["gated_warmup"]={"diagnostics":restricted["diagnostics"],"broker":restricted["strategy"],"plots":{z["title"]:z["values"] for z in restricted["plots"] if z.get("title","").startswith("scope ")}}
        report[market]=r
    (ROOT/"4016-native.json").write_bytes(json.dumps(report,separators=(",",":"),allow_nan=False).encode())

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        (ROOT/"4016-error.txt").write_text(traceback.format_exc(),encoding="utf-8")
        raise
