"""Run exact source with all lower feeds and isolate conditional call-state diagnostics."""
import json
import re
import sys
from pathlib import Path
ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from replay_2864 import engine_options,pine_compat,sha256
from probe_1216 import objects

DIGEST="29ff9d35d78c1959dd227e7f77bfebde4e38582dcfdc0a333b48f922f423fcc2"
OBS="""
plot(longEntryCondition?1:0,"scope long")
plot(shortEntryCondition?1:0,"scope short")
plot(smoothAvgTotal,"scope total")
plot(swingLength1,"scope len1")
plot(swingLength2,"scope len5")
plot(swingLength3,"scope len15")
plot(smoothAvgK,"scope k")
plot(smoothAvgD,"scope d")
plot(smoothAvgJ,"scope j")
"""
def main():
    raw=(ROOT/"source-4307.md").read_bytes()
    assert sha256(raw)==DIGEST
    fence=chr(96)*3
    (block,)=re.findall(r"(?ms)^"+fence+r" pinescript[^\n]*\n(.*?)^"+fence,raw.decode())
    source,n=re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*","",block)
    assert n==1
    forced,noff=re.subn(r"(?m)^buySignal = (.*) and ta.crossover\((.*)\)$",r'upCross=ta.crossover(\2)\nbuySignal = \1 and upCross',source)
    forced,ndn=re.subn(r"(?m)^sellSignal = (.*) and ta.crossunder\((.*)\)$",r'downCross=ta.crossunder(\2)\nsellSignal = \1 and downCross',forced)
    assert noff==ndn==1
    stop_only,n=re.subn(r", trail_points=atrValueTSL / syminfo.mintick","",forced)
    assert n==2
    data=json.loads((ROOT/"4307-feed.json").read_bytes())
    records={}
    for market,frames in data["market_data"].items():
        opts={**engine_options(market),"chart_timeframe":"D"}
        symbol=opts["chart_symbol"]
        opts["request_bars"].update({f"{symbol}:{key}":objects(rows) for key,rows in frames.items()})
        records[market]={}
        for name,script in (("original",source),("cross_diagnostics_control",forced),("stop_only_diagnostic",stop_only)):
            try:
                r=pine_compat.run_script(script+OBS,objects(frames["D"]),**opts)
                records[market][name]={"diagnostics":r["diagnostics"], "broker":r["strategy"],
                    "plots":{p["title"]:p["values"] for p in r["plots"] if p.get("title","").startswith("scope ")}}
            except ValueError as e:
                records[market][name]={"errors":str(e).splitlines()}
    (ROOT/"4307-native.json").write_bytes(json.dumps(records,separators=(",",":"),allow_nan=False).encode())

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        (ROOT/"4307-error.txt").write_text(traceback.format_exc(),encoding="utf-8")
        raise
