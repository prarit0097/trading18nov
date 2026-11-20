"""Check the mixed-version authored lower-timeframe request and order chronology."""
import json
import re
import sys
from pathlib import Path
ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from replay_2864 import engine_options,pine_compat,sha256
from probe_1216 import objects

HASH="16fa099c9b2ff273356c2060984e2a3755d64ef5f04123c02d44c7d69e185bc9"
OBS="""
plot(res_outRSI_cur_close,"scope 1m RSI")
plot(ltf_outRSI_cur_close,"scope 15m RSI")
plot(enterLong?1:0,"scope buy")
plot(enterShort?1:0,"scope sell")
plot(exitLong?1:0,"scope close long")
plot(exitShort?1:0,"scope close short")
plot(strategy.position_size,"scope size")
"""
def main():
    raw=(ROOT/"source-4026.md").read_bytes()
    assert sha256(raw)==HASH
    fence=chr(96)*3
    (block,)=re.findall(r"(?ms)^"+fence+r" pinescript[^\n]*\n(.*?)^"+fence,raw.decode())
    source,n=re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*","",block)
    assert n==1
    aliases=source.replace("request.security(","security(").replace("syminfo.tickerid","tickerid")
    assert source.count("inputTime")==1
    aliases=aliases.replace(", size=size.tiny","").replace(",size=size.tiny","")
    aliases=re.sub(r"(?m)^inputTime .*\n","",aliases)
    explicit=aliases.replace("long = true","direction = strategy.long").replace("long = false","direction = strategy.short")
    core=explicit.split("// Transform strtegy to alert",1)[0]
    data=json.loads((ROOT/"4026-feed.json").read_bytes())
    result={}
    for market,record in data["markets"].items():
        opts={**engine_options(market),"chart_timeframe":"180"}
        symbol=opts["chart_symbol"]
        c=objects(record["chart"])
        opts["request_bars"].update({f"{symbol}:1":objects(record["minute"]), f"{symbol}:15":objects(record["quarter"])})
        report={}
        for label,pine in (("literal",source),("v2_alias",aliases),("v2_direction",explicit),("v2_no_alert_appendix",core)):
            try:
                x=pine_compat.run_script(pine+OBS,c,**opts)
                report[label]={"diagnostics":x["diagnostics"],"broker":x["strategy"],
                    "plots":{p["title"]:p["values"] for p in x["plots"] if p.get("title","").startswith("scope ")}}
            except ValueError as e:
                report[label]={"errors":str(e).splitlines()}
        result[market]=report
    (ROOT/"4026-native.json").write_bytes(json.dumps(result,separators=(",",":"),allow_nan=False).encode())

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        (ROOT/"4026-error.txt").write_text(traceback.format_exc(),encoding="utf-8")
        raise
