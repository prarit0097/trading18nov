"""Run FMZ #3301 exact default parameters and inactive bracket controls."""
import json
import re
import sys
from pathlib import Path
ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from replay_2864 import engine_options,pine_compat,sha256
from probe_1216 import objects

DIGEST="4d777c6588633cd1977471f5253bc840d0a520a4d4529eb23501b4021c8767f8"
OBS="""
plot(BUY ? 1:0,"scope buy")
plot(SELL ? 1:0,"scope sell")
plot(rsi_,"scope RSI")
plot(rsi_HTF,"scope daily RSI")
plot(_1,"scope short MA")
plot(_2,"scope long MA")
plot(strategy.position_size,"scope size")
"""
def main():
    raw=(ROOT/"source-3301.md").read_bytes()
    assert sha256(raw)==DIGEST
    fence=chr(96)*3
    (block,)=re.findall(r"(?ms)^"+fence+r" pinescript[^\n]*\n(.*?)^"+fence,raw.decode())
    source,n=re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*","",block)
    assert n==1
    compatible,n=re.subn(r"(?m)^rsi(\s*=.*)$",r"rsi_opt\1",source)
    assert n==1
    compatible=compatible.replace("co, cla, rsi,","co, cla, rsi_opt,").replace("cu, clu, rsi,","cu, clu, rsi_opt,").replace("== rsi   ","== rsi_opt ")
    no_exit,n=re.subn(r'(?m)^strategy.exit\("\[SL/TP\]".*\n',"",compatible)
    assert n==1
    data=json.loads((ROOT/"3301-feed.json").read_bytes())
    report={}
    for market,record in data["markets"].items():
        opts={**engine_options(market),"chart_timeframe":"120"}
        symbol=opts["chart_symbol"]
        chart=objects(record["chart"])
        opts["request_bars"][f"{symbol}:D"]=objects(record["daily"])
        r={}
        for name,code in (("literal",source),("identifier_control",compatible),("inactive_bracket_control",no_exit)):
            try:
                x=pine_compat.run_script(code+OBS,chart,**opts)
                r[name]={"diagnostics":x["diagnostics"],"broker":x["strategy"],
                         "plots":{p["title"]:p["values"] for p in x["plots"] if p.get("title","").startswith("scope ")}}
            except ValueError as e:
                r[name]={"errors":str(e).splitlines()}
        report[market]=r
    (ROOT/"3301-native.json").write_bytes(json.dumps(report,separators=(",",":"),allow_nan=False).encode())

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        (ROOT/"3301-error.txt").write_text(traceback.format_exc(),encoding="utf-8")
        raise
