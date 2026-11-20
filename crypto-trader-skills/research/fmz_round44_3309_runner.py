"""Probe exact FMZ #3309 v4 polynomial arrays, scope, and inactive brackets."""
import json
import re
import sys
from pathlib import Path
ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from replay_2864 import engine_options,pine_compat,sha256
from probe_1216 import objects

DIGEST="69e8340f3130ee9e6563864f2a4f800e2ce8dc99fb1bc0177d23b2d3f72f1824"
OBS="""
plot(src,"scope RSI")
plot(drsi,"scope DRSI")
plot(nrmse,"scope NRMSE")
plot(signalline,"scope signal")
plot(golong ? 1:0,"scope buy")
plot(goshort ? 1:0,"scope sell")
plot(endlong ? 1:0,"scope end long")
plot(endshort ? 1:0,"scope end short")
plot(strategy.position_size,"scope size")
"""
def main():
    raw=(ROOT/"source-3309.md").read_bytes()
    assert sha256(raw)==DIGEST
    fence=chr(96)*3
    (block,)=re.findall(r"(?ms)^"+fence+r" pinescript[^\n]*\n(.*?)^"+fence,raw.decode())
    source,n=re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*","",block)
    assert n==1
    bare_bracket,n=re.subn(r'(?m)^strategy.exit\(id="sl/tp.*\n *limit=.*\n',"",source)
    assert n==2
    eager,n=re.subn(r"(?m)^rsifilter = usersi\?\(rsi\(close,14\) > rsitrhs1 and rsi\(close,14\) < rsitrhs2\):true$",
                    r'filtered_rsi=rsi(close,14)\nrsifilter = usersi?(filtered_rsi > rsitrhs1 and filtered_rsi < rsitrhs2):true',source)
    assert n==1
    typed=source.replace("_nrmse := na", "_nrmse := float(na)")
    typed_init=source.replace("float _nrmse = 0.0", "float _nrmse = na")
    assert typed!=source and typed_init!=source
    first_ema="""
fmz_ema(value, length) =>
    float prior = na
    alpha = 2.0 / (length + 1)
    prior := na(prior[1]) ? value : alpha * value + (1 - alpha) * prior[1]
signalline = fmz_ema(drsi, signalLength)
"""
    authored_scope=typed.replace("signalline = ema(drsi, signalLength)",first_ema)
    exact_bracket,n=re.subn(r'(?m)^strategy.exit\(id="sl/tp.*\n *limit=.*\n',"",authored_scope)
    assert n==2
    data=json.loads((ROOT/"3309-feed.json").read_bytes())
    report={}
    for market,record in data["markets"].items():
        opts={**engine_options(market),"chart_timeframe":"60"}
        chart=objects(record["chart"])
        r={}
        for name,code in (("literal",source),("typed_fallback",typed),("typed_init",typed_init),("documented_first_ema",authored_scope),("documented_ema_no_brackets",exact_bracket)):
            try:
                x=pine_compat.run_script(code+OBS,chart,**opts)
                r[name]={"diagnostics":x["diagnostics"],"broker":x["strategy"],
                         "plots":{p["title"]:p["values"] for p in x["plots"] if p.get("title","").startswith("scope ")}}
            except ValueError as e:
                r[name]={"errors":str(e).splitlines()}
        report[market]=r
    (ROOT/"3309-native.json").write_bytes(json.dumps(report,separators=(",",":"),allow_nan=False).encode())

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        (ROOT/"3309-error.txt").write_text(traceback.format_exc(),encoding="utf-8")
        raise
