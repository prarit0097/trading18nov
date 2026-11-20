
"""Run exact #5211 archived source with official 5m terminal samples."""

import json
import re
import sys
from pathlib import Path

ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from probe_1216 import objects
from replay_2864 import engine_options,pine_compat,sha256

OBS='''
plot(htfClose,title="scope close")
plot(srcHTF,title="scope source")
plot(sourceHTF,title="scope typical")
plot(volumeHTF,title="scope volume")
plot(macd,title="scope macd")
plot(signal,title="scope signal")
plot(mf,title="scope mf")
plot(UT ? 1 : 0,title="scope up")
plot(rsi,title="scope rsi")
plot(testPeriod() and UT and entry_long ? 1 : 0,title="scope buy")
plot(testPeriod() and exit_long ? 1 : 0,title="scope stop")
plot(long_take_level_1,title="scope absolute target")
plot(entry_price_long * long_trailing / syminfo.mintick,title="scope trail ticks")
plot(strategy.position_size,title="scope quantity")
'''
def main():
    r=(ROOT/"source-5211.md").read_bytes()
    assert sha256(r)=="87d1baaa9640ed7295e3f287e91ecd6f8e2ef5d478016dea22f7411285f37f6d"
    fence=chr(96)*3
    src,=re.findall(r"(?ms)^"+fence+r"[^\n]*\n(.*?)^"+fence,r.decode())
    src,n=re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*","",src)
    assert n==1
    normalized,n=re.subn(r"(?m)^mf = rsi\(upper_s, lower_s\)$",
                         "mf = 100.0 - (100.0 / (1.0 + upper_s / lower_s))",src)
    assert n==1
    tp1_only,n=re.subn(r'(?m)^ *strategy.exit\("Trail stop".*\n','',normalized)
    assert n==1
    data=json.loads((ROOT/"5211-inputs.json").read_bytes())
    output=[]
    for c in data["cases"]:
        m=c["market"]
        opts={**engine_options(m),"chart_timeframe":"D"}
        opts["request_bars"]["$currencyRates"]=data["fx"]
        symbol=opts["chart_symbol"]
        projected={**opts,"request_bars":{**opts["request_bars"],f"{symbol}:5":objects(c["last"])}}
        project_head={**opts,"request_bars":{**opts["request_bars"],f"{symbol}:5":objects(c["last"][:7])}}
        full_head={**opts,"request_bars":{**opts["request_bars"],f"{symbol}:5":objects(c["sample"])}}
        report={"market":m}
        for name,code,bars,kw in (("literal",src,c["chart"],projected),
                                  ("normalized",normalized,c["chart"],projected),
                                  ("tp1_only_control",tp1_only,c["chart"],projected),
                                  ("head_last",normalized,c["chart"][:7],project_head),
                                  ("head_full",normalized,c["chart"][:7],full_head)):
            try:
                result=pine_compat.run_script(code+OBS,objects(bars),**kw)
                report[name]={"diagnostics":result["diagnostics"],"broker":result["strategy"],
                             "plots":{p["title"]:p["values"] for p in result["plots"] if p.get("title","").startswith("scope ")}}
            except ValueError as e:
                report[name]={"errors":str(e).splitlines()}
        output.append(report)
    (ROOT/"5211-probe.json").write_bytes(json.dumps(output,separators=(",",":"),allow_nan=False).encode())

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        (ROOT/"5211-probe-error.txt").write_text(traceback.format_exc(),encoding="utf-8")
        raise
