"""Probe the literal bool operand and two explicitly diagnostic short controls."""
import json
import re
import sys
from hashlib import sha256
from pathlib import Path

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from probe_1216 import objects
from replay_2864 import engine_options,pine_compat

DIGEST="5c125dea008e6af98abbb053d77d3da81f93e9ba5ff5a6492a7816e2455d522a"
OBS='''\nplot(v,"scope value")
plot(golong ? 1 : 0,"scope buy")
plot(goshort ? 1 : 0,"scope sell")
'''
def main():
    source=(ROOT/"source-5530.md").read_bytes()
    assert sha256(source).hexdigest()==DIGEST
    fence=chr(96)*3
    block,=re.findall(r"(?ms)^"+fence+r" pinescript[^\n]*\n(.*?)^"+fence,source.decode())
    native,n=re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*","",block)
    assert n==1 and native.count("crossunder(v,b)")==2
    variants={"literal":native,"boolean_numeric_control":native.replace("crossunder(v,b)", "crossunder(v,b ? 1.0 : 0.0)"),
              "minus_point_eight_control":native.replace("crossunder(v,b)", "crossunder(v,-0.8)")}
    alias={key:case.replace('resCustom = input(title="Timeframe", defval="1440" )','resCustom = input(title="Timeframe", defval="D" )')
           for key,case in variants.items()}
    variants.update({key+"_daily_alias":case for key,case in alias.items()})
    compatible={key+"_version_vocabulary":code.replace("request.security(", "security(").replace("color=red", "color=color.red").replace("color=green", "color=color.green") for key,code in variants.items()}
    variants.update(compatible)
    data=json.loads((ROOT/"5530-feed.json").read_bytes())
    output={}
    for market,candles in data["markets"].items():
        opts={**engine_options(market),"chart_timeframe":"D"}
        symbol=opts["chart_symbol"]
        bars=objects(candles)
        opts["request_bars"][f"{symbol}:1440"]=bars
        opts["request_bars"][f"{symbol}:D"]=bars
        report={}
        for name,code in variants.items():
            try:
                res=pine_compat.run_script(code+OBS,bars,**opts)
                report[name]={"diagnostics":res["diagnostics"],
                    "orders":res["strategy"]["orders"],"position":res["strategy"]["position"],
                    "plots":{p["title"]:p["values"] for p in res["plots"] if p.get("title","").startswith("scope ")}}
            except ValueError as error:
                report[name]={"errors":str(error).splitlines()}
        output[market]=report
    (ROOT/"5530-native.json").write_bytes(json.dumps(output,separators=(",",":"),allow_nan=False).encode())
    (ROOT/"5530-piner-input.json").write_bytes(json.dumps({"sources":{"literal":native+OBS,"vocabulary":compatible["literal_version_vocabulary"]+OBS},"bars":objects(data["markets"]["BTCUSDT"])},
                                                        separators=(",",":"),allow_nan=False).encode())

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        (ROOT/"5530-error.txt").write_text(traceback.format_exc(),encoding="utf-8")
        raise
