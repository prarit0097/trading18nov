"""Run source-preserving v3 namespace repair and isolate same-context nested requests."""
import json
import re
import sys
from pathlib import Path
ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from replay_2864 import engine_options,pine_compat,sha256
from probe_1216 import objects

DIGEST="f1e40082c8a965cd0229cb08dcdaf07266c286cab0872b55ed21c49c1cf792f0"
OBS="""
plot(MACD,"scope MACD")
plot(aMACD,"scope signal")
plot(delta,"scope delta")
plot(MACDD,"scope MACDD")
plot(aMACDD,"scope aMACDD")
plot(deltad,"scope deltad")
plot(SL,"scope SL")
plot(A,"scope A")
plot((MACD>hmacd) and deltad>0 and delta>delta[1] ? 1 : 0, "scope buy1")
plot(crossover(low,SL) and SL-SL[1]<close*0.005 and SL-SL[1]>-close*0.005 ? 1 : 0, "scope buy2")
plot(crossunder(delta,0) or crossunder(close,SL) ? 1 : 0,"scope close")
"""
def main():
    raw=(ROOT/"source-2364.md").read_bytes()
    assert sha256(raw)==DIGEST
    fence=chr(96)*3
    (block,)=re.findall(r"(?ms)^"+fence+r" pinescript[^\n]*\n(.*?)^"+fence,raw.decode())
    source,n=re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*","",block)
    assert n==1 and source.count("request.security(")==5
    modern=source.replace("//@version=3","//@version=4").replace("request.security(","security(")
    vocabulary=source.replace("request.security(","security(").replace("syminfo.tickerid","tickerid")
    positive=vocabulary.replace("if A \n","if A != 0\n")
    assert positive != vocabulary
    flattened,n=re.subn(r"(?m)^aMACDD = .*", "aMACDD = security(tickerid,'360',ema(ema(close,fastLength)-ema(close,slowlength),MACDLength))",positive)
    assert n==1
    data=json.loads((ROOT/"2364-feed.json").read_bytes())
    records={}
    for market,d in data["markets"].items():
        opts={**engine_options(market),"chart_timeframe":"D"}
        sym=opts["chart_symbol"]
        opts["request_bars"].update({f"{sym}:D":objects(d["chart"]),f"{sym}:360":objects(d["six"])})
        out={}
        for name,script in (("literal",source),("vocabulary",vocabulary),("modern_control",modern),("numeric_if_control",positive),("flat_context_control",flattened)):
            try:
                r=pine_compat.run_script(script+OBS,objects(d["chart"]),**opts)
                out[name]={"diagnostics":r["diagnostics"], "broker":r["strategy"],
                            "plots":{p["title"]:p["values"] for p in r["plots"] if p.get("title","").startswith("scope ")}}
            except ValueError as err:
                out[name]={"errors":str(err).splitlines()}
        for cutoff in (90, 220, 365):
            prefix={**opts,"request_bars":{**opts["request_bars"], f"{sym}:D":objects(d["chart"][:cutoff]), f"{sym}:360":objects(d["six"][:4*cutoff])}}
            p=pine_compat.run_script(vocabulary+OBS,objects(d["chart"][:cutoff]),**prefix)
            out[f"prefix_{cutoff}"]={"broker":p["strategy"],"plots":{v["title"]:v["values"] for v in p["plots"] if v.get("title","").startswith("scope ")}}
        records[market]=out
    (ROOT/"2364-native.json").write_bytes(json.dumps(records,separators=(",",":"),allow_nan=False).encode())

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        (ROOT/"2364-error.txt").write_text(traceback.format_exc(),encoding="utf-8")
        raise
