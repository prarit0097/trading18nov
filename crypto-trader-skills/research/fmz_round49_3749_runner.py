"""Strict source and scoped identifier controls for #3749."""
import json
import re
import sys
from pathlib import Path
ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from replay_2864 import engine_options,pine_compat,sha256
from probe_1216 import objects

DIGEST="2000addd24625b8458d38032aaa70dc32a5b6996dd630897ef0990ae33031d07"
OBS="""
plot(vwap(hlc3),"scope VWAP")
plot(vwaprsi,"scope VWAP RSI")
plot(rsiv,"scope RSIv")
plot(long?1:0,"scope long")
plot(short?1:0,"scope short")
plot(close_long?1:0,"scope exit long")
plot(close_short?1:0,"scope exit short")
"""
def main():
    raw=(ROOT/"source-3749.md").read_bytes()
    assert sha256(raw)==DIGEST
    fence=chr(96)*3
    (block,)=re.findall(r"(?ms)^"+fence+r" pinescript[^\n]*\n(.*?)^"+fence,raw.decode())
    source,n=re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*","",block)
    assert n==1
    once=source.replace("//@version=4","",2)
    assert source.count("//@version=4")==2
    once="//@version=4\n"+once
    normalized=once.replace('security = input(""','aux_symbol = input(""').replace('security(security,','security(aux_symbol,')
    normalized,n=re.subn(r"(?m)^rsi (.*)$",r"price_rsi \1",normalized)
    assert n==1
    normalized,n=re.subn(r'(?m)^long = [^\n]+',lambda m: re.sub(r'\brsi\b','price_rsi',m[0]),normalized)
    assert n==1
    normalized = re.sub(r"\brsi\b(?!\s*\()", "price_rsi",normalized)
    yes=normalized.replace('strategy.close("Long", strategy.long,','strategy.close("Long", when=true,').replace(
                              'strategy.close("Short", strategy.short,','strategy.close("Short", when=true,')
    direction_bool=yes.replace('strategy.close("Short", when=true,','strategy.close("Short", when=false,')
    named,n=re.subn(r'strategy\.exit\(id="(Long|Short)",\s*qty_percent=',lambda m: f'strategy.exit(id="{m[1]}",from_entry="{m[1]}",qty_percent=',normalized)
    assert n==2
    data=json.loads((ROOT/"3749-feed.json").read_bytes())
    report={}
    scored={}
    for market,record in data["markets"].items():
        opts=engine_options(market)
        chart=objects(record["chart"])
        results={}
        for k,v in (("literal",source),("dedup_version",once),("compatibility",normalized),("all_true_control",yes),("direction_bool_control",direction_bool)):
            try:
                r=pine_compat.run_script(v+OBS,chart,**opts)
                results[k]={"diagnostics":r["diagnostics"],"broker":r["strategy"],
                            "plots":{p["title"]:p["values"] for p in r["plots"] if p.get("title","").startswith("scope ")}}
            except ValueError as error:
                results[k]={"errors":str(error).splitlines()}
        whole=engine_options(market)
        whole["request_bars"]["$chart"].update(quantityStep="1",minContract="1",pointValue=.001)
        for k,d in (("whole_monthly",record["chart"]),("whole_daily_control",record.get("daily_comparison",record["chart"]))):
            r=pine_compat.run_script(normalized+OBS,objects(d),**whole)
            results[k]={"diagnostics":r["diagnostics"],"broker":r["strategy"],"plots":{p["title"]:p["values"] for p in r["plots"] if p.get("title","").startswith("scope ")}}
        report[market]=results
        chosen=record.get("daily_comparison",record["chart"])
        r=pine_compat.run_script(named+OBS,objects(chosen),**whole)
        scored[market]={"diagnostics":r["diagnostics"],"broker":r["strategy"],"plots":{p["title"]:p["values"] for p in r["plots"] if p.get("title","").startswith("scope ")}}
    (ROOT/"3749-scored.json").write_bytes(json.dumps(scored,separators=(",",":"),allow_nan=False).encode())
    (ROOT/"3749-native.json").write_bytes(json.dumps(report,separators=(",",":"),allow_nan=False).encode())

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        (ROOT/"3749-error.txt").write_text(traceback.format_exc(),encoding="utf-8")
        raise
