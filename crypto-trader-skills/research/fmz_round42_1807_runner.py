"""Check original Pine v3 eager state and plotting appendix independently."""
import json
import re
import sys
from pathlib import Path
ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from replay_2864 import engine_options,pine_compat,sha256
from probe_1216 import objects

DIGEST="e213ba7b0ec9370a3ec19e3aa7cb33a6c7af76f7b1be2782eecd7bbce4de4075"
OBS="""
plot(testPeriod() and isLong ? 1:0,"scope gate")
plot(rsiBuy ? 1:0,"scope rsi")
plot(bbBuy ? 1:0,"scope bands")
plot(stochBuy ? 1:0,"scope stoch")
plot(sell_maBuy ? 1:0,"scope sellma")
plot(buy ? 1:0,"scope raw buy")
plot(sell ? 1:0,"scope raw sell")
plot(longCondition ? 1:0,"scope entry")
plot(longClose ? 1:0,"scope close")
plot(floor(last_open_longCondition * 100)/100,"scope basis")
plot(long_tp ? 1:0,"scope target")
plot(long_sl ? 1:0,"scope stop")
plot(long_sos ? 1:0,"scope opposite")
"""
def main():
    raw=(ROOT/"source-1807.md").read_bytes()
    assert sha256(raw)==DIGEST
    fence=chr(96)*3
    (block,)=re.findall(r"(?ms)^"+fence+r" pinescript[^\n]*\n(.*?)^"+fence,raw.decode())
    src,n=re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*","",block)
    assert n==1
    v3=src.replace("request.security(","security(").replace("syminfo.tickerid","tickerid").replace("timeframe.period","period")
    core=v3.split("// EOF",1)[0]
    repaired,n=re.subn(r'(?m)^rsi(\s*=.*)$',r'pulseRSI\1',v3)
    assert n==1
    repaired,n=re.subn(r'(?m)^per_rsi.*$',lambda m: re.sub(r"\brsi\b", "pulseRSI",m[0]),repaired)
    assert n==1
    repaired=repaired.replace("buy==1 and","buy and").replace("sell==1  and","sell  and").replace("shortExitC = 0","shortExitC = 0 * close")
    numeric=repaired.replace("buy and (barstate", "(buy ? 1 : 0) == 1 and (barstate").replace("sell  and (barstate", "(sell ? 1 : 0) == 1 and (barstate")
    assert numeric!=repaired
    v4=src.replace("//@version=3","//@version=4").replace("request.security(","security(")
    data=json.loads((ROOT/"1807-feed.json").read_bytes())
    output={}
    for market,d in data["markets"].items():
        opts={**engine_options(market),"chart_timeframe":"60"}
        symbol=opts["chart_symbol"]
        bars=objects(d["chart"])
        opts["request_bars"].update({f"{symbol}:60":bars,f"{symbol}:15":objects(d["base"]),f"{symbol}:3":objects(d["3"]),f"{symbol}:5":objects(d["5"])})
        reports={}
        for case,code in (("literal",src),("v3_aliases",v3),("v3_core",core),("v3_repaired",repaired),("v3_checked_numeric",numeric),("v3_repaired_core",repaired.split("// EOF",1)[0]),("v4_control",v4)):
            try:
                r=pine_compat.run_script(code+OBS,bars,**opts)
                reports[case]={"diagnostics":r["diagnostics"],"broker":r["strategy"],
                               "plots":{p["title"]:p["values"] for p in r["plots"] if p.get("title","").startswith("scope ")}}
            except ValueError as e:
                reports[case]={"errors":str(e).splitlines()}
        output[market]=reports
    (ROOT/"1807-native.json").write_bytes(json.dumps(output,separators=(",",":"),allow_nan=False).encode())

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        (ROOT/"1807-error.txt").write_text(traceback.format_exc(),encoding="utf-8")
        raise
