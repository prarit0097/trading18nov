import json
import re
import sys
from pathlib import Path

ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from probe_1216 import objects
from replay_2864 import engine_options,pine_compat,sha256

OBS='''
plot(ma_short, title="scoped short")
plot(ma_long, title="scoped long")
plot(longCond ? 1 : 0, title="scoped entryL")
plot(shortCond ? 1 : 0, title="scoped entryS")
plot(round(n/2), title="scoped HMA length")
'''
def main():
    raw=(ROOT/"source-5252.md").read_bytes()
    assert sha256(raw)=="99679cb4be389e97d4420eee05e5a04e1c0eaf43ba672bd1afe2aa64459f6097"
    fence=chr(96)*3
    (block,)=re.findall(r"(?ms)^"+fence+r"[^\n]*\n(.*?)^"+fence,raw.decode("utf-8"))
    src,n=re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*","",block)
    assert n==1
    legacy=src.replace("syminfo.tickerid","tickerid").replace("timeframe.period","period").replace("request.security(","security(")
    projected=legacy
    for state,kind in (("v5","float"),("cruce","bool"),("trendState","bool")):
        expr=r"(?m)^(\s*)"+state+r"\s*=([^\n]*\b"+state+r"\[1\][^\n]*)$"
        projected,n=re.subn(expr,r"\1"+kind+" "+state+r" = na\n\1"+state+r" :=\2",projected)
        assert n==1,state
    visual_fixed,n=re.subn(r"(barcolor\(barcol), transp=0|, circles = 0",r"\1",projected)
    assert n == 3
    scripts={"raw":src,"legacy":legacy,"explicit_state":projected,
             "trade_projection":visual_fixed,
             "observation":re.sub(r"(?m)^strategy.exit\([^\n]+\)\s*$","",visual_fixed)}
    out=[]
    for case in json.loads((ROOT/"5252-inputs.json").read_bytes())["cases"]:
        opts={**engine_options(case["market"]),"chart_timeframe":"240"}
        chart=objects(case["chart"])
        opts["request_bars"][opts["chart_symbol"]+":W"]=objects(case["week"])
        result={"market":case["market"]}
        for mode,script in scripts.items():
            try:
                run=pine_compat.run_script(script+OBS,chart,**opts)
                result[mode]={"diagnostics":run["diagnostics"],"broker":run["strategy"],
                              "plots":{p["title"]:p["values"] for p in run["plots"] if p.get("title","").startswith("scoped ")}}
            except ValueError as e:
                result[mode]={"exception":str(e).splitlines()}
        out.append(result)
    (ROOT/"5252-probe.json").write_bytes(json.dumps(out,separators=(",",":"),allow_nan=False).encode())

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        (ROOT/"5252-probe-error.txt").write_text(traceback.format_exc(),encoding="utf-8")
        raise
