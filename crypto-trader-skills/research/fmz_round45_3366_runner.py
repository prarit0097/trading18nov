"""Probe the #3366 archived fixed, trailing, and opposite market-close paths."""
import json
import re
import sys
from pathlib import Path
ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from replay_2864 import engine_options,pine_compat,sha256
from probe_1216 import objects

DIGEST="5a83ddb08f370b1a1571419c1885d9e18031846d58706f01235ed3a24a32efb7"
OBS="""
plot(entryLongCondition?1:0,"scope buy")
plot(entryShortCondition?1:0,"scope sell")
plot(exitLongCondition?1:0,"scope close long")
plot(exitShortCondition?1:0,"scope close short")
plot(strategy.position_size,"scope size")
plot(xl_sl_price,"scope long stop")
plot(xl_tp_price,"scope long target")
plot(xs_sl_price,"scope short stop")
plot(xs_tp_price,"scope short target")
plot(xl_ts_tick,"scope trail activation")
plot(xl_to_tick,"scope trail offset")
plot(volatilityCondition?1:0,"scope vol")
"""
def main():
    raw=(ROOT/"source-3366.md").read_bytes()
    assert sha256(raw)==DIGEST
    fence=chr(96)*3
    (block,)=re.findall(r"(?ms)^"+fence+r" pinescript[^\n]*\n(.*?)^"+fence,raw.decode())
    source,n=re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*","",block)
    assert n==1
    reduced=source.split("monthly_table(int",1)[0]
    data=json.loads((ROOT/"3366-feed.json").read_bytes())
    report={}
    for market,record in data["markets"].items():
        opts={**engine_options(market),"chart_timeframe":"D"}
        sym=opts["chart_symbol"]
        chart=objects(record["chart"])
        opts["request_bars"].update({f"{sym}:D":chart,f"{sym}:1D":chart})
        r={}
        for name,code in (("literal",source),("no_table",reduced)):
            try:
                x=pine_compat.run_script(code+OBS,chart,**opts)
                r[name]={"diagnostics":x["diagnostics"],"broker":x["strategy"],
                         "plots":{p["title"]:p["values"] for p in x["plots"] if p.get("title","").startswith("scope ")}}
            except ValueError as e:
                r[name]={"errors":str(e).splitlines()}
        report[market]=r
    (ROOT/"3366-native.json").write_bytes(json.dumps(report,separators=(",",":"),allow_nan=False).encode())

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        (ROOT/"3366-error.txt").write_text(traceback.format_exc(),encoding="utf-8")
        raise
