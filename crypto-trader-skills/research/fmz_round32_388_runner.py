import json
import re
import sys
from pathlib import Path

ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))

from probe_1216 import objects
from replay_2864 import engine_options,pine_compat,sha256

OBS = '''
plot(long and ACT_BT and testPeriod ? 1 : 0, title="observed L")
plot(short and ACT_BT and testPeriod ? 1 : 0, title="observed S")
plot(src4h, title="observed previous daily")
plot(last_open_longCondition, title="observed reference L")
plot(last_open_shortCondition, title="observed reference S")
plot(strategy.position_size, title="observed size")
'''

def combine(rows,n):
    return [[part[0][0],part[0][1],max(x[2] for x in part),min(x[3] for x in part),part[-1][4],sum(x[5] for x in part)]
            for i in range(0,len(rows),n) if len(part:=rows[i:i+n])==n]

def main():
    raw=(ROOT/"source-388.md").read_bytes()
    assert sha256(raw)=="daf13b100e92cbd1b8f1f1c13d6c96f932b153e3ca10c1f938c0835b49ecd007"
    fence=chr(96)*3
    (src,)=re.findall(r"(?ms)^"+fence+r"[^\n]*\n(.*?)^"+fence,raw.decode("utf-8"))
    src=src.replace("\r\n", "\n")
    assert "//@version" not in src
    trailing,n=re.subn(r"(?m)^(\s*\w+_\d_h\s*=\s*iff\([^\n]+\)),[ \t]*$",r"\1",src)
    assert n==2
    v4_names = re.sub(r"\b(?:ta|math|request)\.(\w+)\b",r"\1",trailing)
    v4_names = v4_names.replace("length_/2)","int(length_/2))")
    out=[]
    for market in ("BTCUSDT","ETHUSDT"):
        data=json.loads((ROOT/f"1070-{market}.json").read_bytes())
        hour=objects(combine(data["base"],4))
        daily=objects(combine(data["base"],96))
        opts={**engine_options(market),"chart_timeframe":"60"}
        symbol=opts["chart_symbol"]
        opts["request_bars"].update({f"{symbol}:60":hour,f"{symbol}:1440":daily,f"{symbol}:D":daily})
        result={"market":market}
        for k,code in {"archived":src,"v4": "//@version=4\n"+trailing,"v5":"//@version=5\n"+trailing,
                       "v4_names":"//@version=4\n"+v4_names+OBS,
                       "v4_lot_units":"//@version=4\n"+v4_names+OBS}.items():
            try:
                model = opts
                if k=="v4_lot_units":
                    metadata={**opts["request_bars"]["$chart"], "pointValue":.001, "quantityStep":"1", "minContract":"1"}
                    model={**opts,"request_bars":{**opts["request_bars"],"$chart":metadata}}
                r=pine_compat.run_script(code,hour,**model)
                result[k]={"broker":r["strategy"],"diagnostics":r["diagnostics"],
                           "plots":{p["title"]:p["values"] for p in r["plots"] if p.get("title","").startswith("observed ")}}
            except ValueError as e:
                result[k]={"error":str(e).splitlines()}
        out.append(result)
    (ROOT/"388-probe.json").write_bytes(json.dumps(out,separators=(",",":"),allow_nan=False).encode())

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        (ROOT/"388-probe-error.txt").write_text(traceback.format_exc(),encoding="utf-8")
        raise
