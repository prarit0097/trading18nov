"""Run the original threshold-selection and exit controls for FMZ #355."""

import json
import re
import sys
from pathlib import Path

ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))

from probe_1216 import objects
from replay_2864 import engine_options,pine_compat,sha256

OBS='''
plot(Length, title="scoped length")
plot(Value3, title="scoped oscillator")
plot(buy and window() ? 1 : 0, title="scoped buy")
plot(sell and window() ? 1 : 0, title="scoped sell")
plot(strategy.position_size, title="scoped size")
'''

def variants(raw):
    assert sha256(raw)=="5708c3fec412b5669247dee901f24920afae76aa01ce1a61d133fa639a040bda"
    assert "|v_input_4|-2.41|BuyTreshold(-)|" in raw.decode().replace(" ","")
    assert "|v_input_5|2.43|SellTreshold(+)|" in raw.decode().replace(" ","")
    fence=chr(96)*3
    (block,)=re.findall(r"(?ms)^"+fence+r"[^\n]*\n(.*?)^"+fence,raw.decode())
    raw,n=re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*","",block)
    assert n==1
    selected,n=re.subn(r"type = float, defval= ?(?:-2\.0|2\.0)","type = float",raw)
    assert n==2
    legacy=selected.replace('input.source(close, "Source")','input(close,"Source")')
    tested=legacy.replace('hline.style_solid','solid')
    assert legacy.count('hline.style_solid')==2
    control=tested.replace('if(n > 5)','if(bar_index > 5)')
    assert tested!=control
    try_local=tested.replace('if(n > 5)','if(false)')
    no_price,n=re.subn(r'(?m)^strategy\.exit\("Exit", when= \w+\)\s*$','',control)
    assert n==2
    return {"raw":raw,"selected":selected,"legacy":legacy,"tested":tested,
            "index_alias_control":control,"inactive_alt":try_local,"no_price_alt":no_price}

def main():
    src=variants((ROOT/"source-355.md").read_bytes())
    data=json.loads((ROOT/"355-inputs.json").read_bytes())["cases"]
    result=[]
    for case in data:
        opts={**engine_options(case["market"]),"chart_timeframe":"30"}
        r={"market":case["market"]}
        for key,script in src.items():
            try:
                run=pine_compat.run_script(script+OBS,objects(case["chart"]),**opts)
                r[key]={"broker":run["strategy"],"diagnostics":run["diagnostics"],
                        "plots":{v["title"]:v["values"] for v in run["plots"] if v.get("title","").startswith("scoped ")}}
            except ValueError as e:
                r[key]={"exception":str(e).splitlines()}
        result.append(r)
    (ROOT/"355-probe.json").write_bytes(json.dumps(result,separators=(",",":"),allow_nan=False).encode())

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        (ROOT/"355-probe-error.txt").write_text(traceback.format_exc(),encoding="utf-8")
        raise
