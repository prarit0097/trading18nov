"""Run FMZ #2708 with real same-frame and synthetic HA requests."""

import json
import re
import sys
from pathlib import Path

ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from probe_1216 import objects
from replay_2864 import engine_options,pine_compat,sha256
from replay_2994 import heikin_ashi

PROBES={
    "size":"strategy.position_size",
    "long":"longCondition ? 1 : 0",
    "short":"shortCondition ? 1 : 0",
    "close":"cross(close,tempx) or MarketClose ? 1 : 0",
    "session_close":"MarketClose ? 1 : 0",
    "trend":"Trend",
    "tsi":"Tsl",
    "tempx":"tempx",
    "htfx":"htfx",
    "ha_open":"heikinashi_open",
    "ha_close":"heikinashi_close",
    "ha_low":"heikinashi_low",
    "ha_high":"heikinashi_high",
    "ha_close30":"heikinashi_close30",
    "longstate":"rg",
    "shortstate":"nm",
}
OBS="\n"+"\n".join(f'plot({value},title="scope::{name}")' for name,value in PROBES.items())

def main():
    raw=(ROOT/"source-2708.md").read_bytes()
    assert sha256(raw)=="d7706e4a0a541a448681803705cbc6c10f385ba4f44bdd8c574ccc0f3fef82f3"
    fence=chr(96)*3
    (src,)=re.findall(r"(?ms)^"+fence+r"[^\n]*\n(.*?)^"+fence,raw.decode())
    src,n=re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*","",src)
    assert n==1
    code=re.sub(r'(?m)//[^\n]*|"[^"\n]*"','',src)
    assert len(re.findall(r"\bST\b",code))==1
    assert 'plot(Tsl,"ST"' in src
    clean,n=re.subn(r"(?m)^ST= supertrend\(Factor, Pd\)\n","",src)
    assert n==1
    out=[]
    for d in json.loads((ROOT/"2708-inputs.json").read_bytes())["cases"]:
        c,h=map(objects,(d["chart"],d["half"]))
        opts={**engine_options(d["market"]),"chart_timeframe":"240"}
        symbol=opts["chart_symbol"]
        synthetic=json.dumps({"chart":"heikinashi","symbol":symbol},separators=(",",":"))
        opts["request_bars"].update({f"{symbol}:240":c,f"{synthetic}:240":heikin_ashi(c),f"{synthetic}:30":heikin_ashi(h)})
        row={"market":d["market"]}
        for label,code in (("literal",src),("portable",clean)):
            try:
                result=pine_compat.run_script(code+OBS,c,**opts)
                row[label]={"diagnostics":result["diagnostics"],"broker":result["strategy"],
                            "plots":{p["title"].removeprefix("scope::"):p["values"] for p in result["plots"] if p.get("title","").startswith("scope::")}}
            except ValueError as e:
                row[label]={"errors":str(e).splitlines()}
        out.append(row)
    (ROOT/"2708-probe.json").write_bytes(json.dumps(out,separators=(",",":"),allow_nan=False).encode())

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        (ROOT/"2708-probe-error.txt").write_text(traceback.format_exc(),encoding="utf-8")
        raise
