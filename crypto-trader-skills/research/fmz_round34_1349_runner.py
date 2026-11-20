"""Check whether the archived FMZ #1349 source declares a usable broker."""

import json
import re
import sys
from pathlib import Path

ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from probe_1216 import objects
from replay_2864 import engine_options,pine_compat,sha256

OBS='''
plot(l and testPeriod ? 1 : 0, "scope entry")
plot(b, "scope previous weekly")
plot(a, "scope weekly visual")
plot(zx, "scope scan")
plot(linear_reg, "scope regression")
plot(ti ? 1 : 0, "scope weekly transition")
'''

def main():
    raw=(ROOT/"source-1349.md").read_bytes()
    assert sha256(raw)=="5531bfff3605c47f4e9112dddfd20a04c578bef4689f11cf33cea55b2326ec41"
    fence=chr(96)*3
    (code,)=re.findall(r"(?ms)^"+fence+r"[^\n]*\n(.*?)^"+fence,raw.decode("utf-8"))
    code,n=re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*","",code)
    assert n==1
    count=len(re.findall(r"(?m)^\s*strategy\s*\(",code))
    uncommented,n=re.subn(r"(?m)^// (strategy\([^\n]+)",r"\1",code)
    assert count==0 and n==1
    flat_guard,n=re.subn(r'(?m)^(strategy\.exit\([^\n]+\)\n(?:strategy\.exit\([^\n]+\)\n){3})',
                        lambda g:"if strategy.position_size != 0\n"+"".join("    "+line for line in g[0].splitlines(keepends=True)),
                        uncommented)
    assert n==1
    cases=[]
    data=json.loads((ROOT/"1349-inputs.json").read_bytes())
    for market in ("BTCUSDT","ETHUSDT"):
        selected=data[market]
        opts={**engine_options(market),"chart_timeframe":"3"}
        symbol=opts["chart_symbol"]
        opts["request_bars"][f"{symbol}:W"]=objects(selected["week"])
        row={"market":market}
        for k,script in (("archived",code),("header_control",uncommented),("inert_exit_control",flat_guard)):
            try:
                r=pine_compat.run_script(script+OBS,objects(selected["chart"]),**opts)
                row[k]={"diagnostics":r["diagnostics"],"strategy":r["strategy"],
                        "plots":{p["title"]:p["values"] for p in r["plots"] if p.get("title","").startswith("scope ")}}
            except ValueError as e:
                row[k]={"errors":str(e).splitlines()}
        cases.append(row)
    (ROOT/"1349-probe.json").write_bytes(json.dumps({"declarations":count,"cases":cases},separators=(",",":")).encode())
if __name__=="__main__":
    main()
