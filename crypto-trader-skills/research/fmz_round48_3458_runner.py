"""Check source and archival lower-timestamp mapping for the BB/HP strategy."""
import json
import re
import sys
from pathlib import Path
ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from replay_2864 import engine_options,pine_compat,sha256
from probe_1216 import objects

DIGEST="4c67ae7da368259d3dee368b00620b90f0d41217fba881b92ccab0716dac367f"
OBS="""
plot(start,"scope time")
plot(myvwap,"scope hp")
plot(i_obv,"scope obv")
plot(i_pvt,"scope pvt")
plot(nresult,"scope transformed flow")
plot(bbr,"scope flow bb")
plot(bbr1,"scope price bb")
plot(long ? 1:0,"scope buy long")
plot(short ? 1:0,"scope buy short")
plot(sell or cancel ? 1:0,"scope close long")
plot(buy?1:0,"scope close short")
plot(strategy.position_size,"scope size")
plot(sell ? 1:0,"scope raw sell")
plot(cancel ? 1:0,"scope cancel")
plot(icreturn ? 1:0,"scope inside candle")
"""
def main():
    raw=(ROOT/"source-3458.md").read_bytes()
    assert sha256(raw)==DIGEST
    fence=chr(96)*3
    (block,)=re.findall(r"(?ms)^"+fence+r" pinescript[^\n]*\n(.*?)^"+fence,raw.decode())
    source,n=re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*","",block)
    assert n==1
    precise=source.replace('strategy.entry("long", true,', 'strategy.entry("long", strategy.long,').replace(
                               'strategy.entry("short", false,','strategy.entry("short", strategy.short,')
    comparison=precise.replace("open >= high[1]","(open > high[1]) or (open == high[1])")
    assert comparison!=precise
    first_seed="""
fmz_ema(value, length) =>
    float prior = na
    alpha = 2.0 / (length + 1)
    prior := na(prior[1]) ? value : alpha * value + (1 - alpha) * prior[1]
float nresult = fmz_ema(normalize(result, -1, 1), 20)
"""
    documented=comparison.replace("float nresult = ema(normalize(result, -1, 1), 20)",first_seed).replace("basis = ema(nresult, length)","basis = fmz_ema(nresult, length)")
    data=json.loads((ROOT/"3458-feed.json").read_bytes())
    report={}
    for market,record in data["markets"].items():
        opts={**engine_options(market),"chart_timeframe":"60"}
        sym=opts["chart_symbol"]
        chart=objects(record["chart"])
        r={}
        for name,code,sample in (("literal",source,record["minute"]),("direction_alias",precise,record["minute"][59::60]),("exact_comparison",comparison,record["minute"][59::60]),("documented_ema",documented,record["minute"][59::60])):
            opts["request_bars"][f"{sym}:1"]=objects(sample)
            try:
                x=pine_compat.run_script(code+OBS,chart,**opts)
                r[name]={"diagnostics":x["diagnostics"],"broker":x["strategy"],
                         "plots":{p["title"]:p["values"] for p in x["plots"] if p.get("title","").startswith("scope ")}}
            except ValueError as e:
                r[name]={"errors":str(e).splitlines()}
        report[market]=r
    (ROOT/"3458-native.json").write_bytes(json.dumps(report,separators=(",",":"),allow_nan=False).encode())

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        (ROOT/"3458-error.txt").write_text(traceback.format_exc(),encoding="utf-8")
        raise
