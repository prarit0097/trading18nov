"""Probe saved-clock and price-grid variants of the archived #3038 source."""

import json
import re
import sys
from pathlib import Path

ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from probe_1216 import objects
from replay_2864 import engine_options,pine_compat,sha256

OBS='''
plot(timenow, title="scope::clock")
plot(afterStartDate and beforeEndDate ? 1 : 0, title="scope::time_gate")
plot(buyLimitPrice,title="scope::buy_limit")
plot(sellLimitPriceEntry,title="scope::initial_target")
plot(stopLimitPriceEntry,title="scope::initial_stop")
plot(sellLimitPrice,title="scope::target")
plot(stopLimitPrice,title="scope::stop")
plot(barsFromEntry,title="scope::bar_count")
plot(strategy.position_size,title="scope::open_quantity")
plot(strategy.position_avg_price,title="scope::open_basis")
'''
REPLACEMENTS=(
 ("limit = buyLimitPrice)", "limit = floor(buyLimitPrice / syminfo.mintick + 1e-9) * syminfo.mintick)"),
 ("limit = sellLimitPriceEntry, stop = stopLimitPriceEntry)", "limit = ceil(sellLimitPriceEntry / syminfo.mintick - 1e-9) * syminfo.mintick, stop = floor(stopLimitPriceEntry / syminfo.mintick + 1e-9) * syminfo.mintick)"),
 ("limit = sellLimitPrice, stop = stopLimitPrice)", "limit = ceil(sellLimitPrice / syminfo.mintick - 1e-9) * syminfo.mintick, stop = floor(stopLimitPrice / syminfo.mintick + 1e-9) * syminfo.mintick)"),
)
def main():
    source=(ROOT/"source-3038.md").read_bytes()
    assert sha256(source)=="89f83a19c5fc7e7666531b9a91169aee896ac070cff8d8356ad8b47cc299de8a"
    fence=chr(96)*3
    (block,)=re.findall(r"(?ms)^"+fence+r"[^\n]*\n(.*?)^"+fence,source.decode())
    raw,n=re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*","",block)
    assert n==1
    data=json.loads((ROOT/"3038-inputs.json").read_bytes())
    clock=str(data["end"])
    chart=raw.replace("timenow",clock)
    assert chart!=raw
    grid=chart
    for old,new in REPLACEMENTS:
        assert grid.count(old)==1
        grid=grid.replace(old,new)
    bound=grid.replace('strategy.exit("INSTANT",', 'strategy.exit("INSTANT", from_entry="BUY",')
    assert bound!=grid
    (ROOT/"3038-source-variants.json").write_bytes(json.dumps({"saved_clock":chart,"grid":grid,"bound":bound},separators=(",",":")).encode())
    out=[]
    for case in data["cases"]:
        m=case["market"]
        opts={**engine_options(m),"chart_timeframe":"D"}
        opts["request_bars"]["$currencyRates"]=data["fx"]
        result={"market":m}
        for name,code,obs,host in (("literal_clock",raw,OBS,False),
                                  ("native_clock",raw,OBS,True),
                                  ("saved_clock",chart,OBS.replace("timenow",clock),False),
                                  ("grid",grid,OBS.replace("timenow",clock),False),
                                  ("named_entry_control",bound,OBS.replace("timenow",clock),False)):
            try:
                kwargs={**opts,"execution_times":[data["end"]]*len(case["chart"])} if host else opts
                r=pine_compat.run_script(code+obs,objects(case["chart"]),**kwargs)
                result[name]={"broker":r["strategy"],"diagnostics":r["diagnostics"],
                              "plots":{p["title"].removeprefix("scope::"):p["values"] for p in r["plots"] if p.get("title","").startswith("scope::")}}
            except ValueError as e:
                result[name]={"errors":str(e).splitlines()}
        out.append(result)
    (ROOT/"3038-probe.json").write_bytes(json.dumps(out,separators=(",",":"),allow_nan=False).encode())

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        (ROOT/"3038-probe-error.txt").write_text(traceback.format_exc(),encoding="utf-8")
        raise
