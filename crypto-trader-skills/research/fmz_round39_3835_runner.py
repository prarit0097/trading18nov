"""Run source, declaration relocation, and sizing observations under isolated Pine Compat."""
import json
import re
import sys
from pathlib import Path

ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from probe_1216 import objects
from replay_2864 import engine_options,pine_compat,sha256
from replay_2994 import heikin_ashi

DIGEST="bb8bcf3005a529e1150b0bfa4254e3697976d76597e42379153df1ed9e017062"
OBS="""
plot(strategy.initial_capital,title="scope capital")
plot(floor(strategy.initial_capital*.1/close),title="scope quantity")
plot(bullishCriteria,title="scope bull")
plot(maFilter,title="scope filter")
plot(maFast,title="scope fast")
plot(maSlow,title="scope slow")
plot(K,title="scope K")
plot(D,title="scope D")
plot(bearishCriteria,title="scope bear")
plot(ha_open,title="scope ha open")
plot(ha_close,title="scope ha close")
"""
def main():
    raw=(ROOT/"source-3835.md").read_bytes()
    assert sha256(raw)==DIGEST
    fence=chr(96)*3
    (block,)=re.findall(r"(?ms)^"+fence+r" pinescript[^\n]*\n(.*?)^"+fence,raw.decode())
    source,n=re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*","",block)
    assert n==1 and source.count("strategy.initial_capital = 50000")==1
    relocated,n=re.subn(r'(?m)^strategy\("2nd Grade Strategy",',
                        'strategy("2nd Grade Strategy", initial_capital=50000,',source)
    assert n==1
    relocated=relocated.replace("strategy.initial_capital = 50000\n","")
    constant=relocated.replace("floor(strategy.initial_capital*.1/close)","floor(5000/close)")
    no_stop=relocated.replace(", stop = strategy.position_avg_price * 1.25","")
    assert constant != relocated and no_stop != relocated
    data=json.loads((ROOT/"3835-feed.json").read_bytes())
    results={}
    for market, chart in data["markets"].items():
        opts={**engine_options(market),"chart_timeframe":"D"}
        symbol=opts["chart_symbol"]
        bars=objects(chart)
        ha=heikin_ashi(bars)
        synthetic=json.dumps({"chart":"heikinashi","symbol":symbol},separators=(",",":"))
        opts["request_bars"].update({f"{symbol}:D":bars, f"{synthetic}:D":ha})
        results[market]={}
        for key, code in (("literal",source),("relocated",relocated),("constant_quantity",constant),("no_stop_control",no_stop)):
            try:
                r=pine_compat.run_script(code+OBS,bars,**opts)
                results[market][key]={"strategy":r["strategy"],"diagnostics":r["diagnostics"],
                     "plots":{x["title"]:x["values"] for x in r["plots"] if x.get("title","").startswith("scope ")}}
            except ValueError as e:
                results[market][key]={"errors":str(e).splitlines()}
    (ROOT/"3835-native.json").write_bytes(json.dumps(results,separators=(",",":"),allow_nan=False).encode())

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        (ROOT/"3835-error.txt").write_text(traceback.format_exc(),encoding="utf-8")
        raise
