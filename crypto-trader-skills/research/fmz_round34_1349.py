"""Audit the missing #1349 strategy declaration and its diagnostic control."""

import math
import sys
from pathlib import Path

from research.fmz_round7_magnifier import ledger_metrics,read,sha256,write

SOURCE="5531bfff3605c47f4e9112dddfd20a04c578bef4689f11cf33cea55b2326ec41"
ENGINE="6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"

def wma(series,n):
    output=[]
    for i in range(len(series)):
        tail=series[i-n+1:i+1] if i>=n-1 else []
        output.append(sum((j+1)*p for j,p in enumerate(tail))/(n*(n+1)/2)
                      if tail and all(v is not None for v in tail) else None)
    return output

def linreg(series,n):
    mid=(n-1)/2
    var=sum((p-mid)**2 for p in range(n))
    out=[]
    for i in range(len(series)):
        y=series[i-n+1:i+1] if i>=n-1 else []
        out.append(None if not y else sum(y)/n+sum((j-mid)*p for j,p in enumerate(y))*mid/var)
    return out

def compare_market(d,case):
    market=case["market"]
    arch=case["archived"]
    assert len(arch["errors"])==1 and arch["errors"][0].startswith("E_LEGACY_INDICATOR_DECLARATION:Error:")
    result=case["header_control"]
    broker=result["strategy"]
    assert not broker["orders"] and not broker["trades"] and not result["diagnostics"]
    exit_codes=[item["code"] for item in broker["diagnostics"]]
    assert exit_codes==["E_STRATEGY_EXIT_TICKS"]*480
    neutral=case["inert_exit_control"]
    assert not neutral["diagnostics"] and not neutral["strategy"]["diagnostics"]
    assert neutral["plots"]==result["plots"]
    assert neutral["strategy"]=={**broker,"diagnostics":[]}
    c,q=d["chart"],d["week"]
    assert len(c)==480 and len(q)==43
    p=result["plots"]
    assert p["scope entry"]==p["scope weekly transition"]==[0]*len(c)
    assert p["scope scan"]==[None]*len(c)
    closes=[bar[4] for bar in q]
    hma3=wma([3*a-b-c if c is not None else None
              for a,b,c in zip(wma(closes,4),wma(closes,6),wma(closes,12),strict=True)],12)
    visual=wma([2*a-b if b is not None else None for a,b in zip(wma(closes,12),wma(closes,24),strict=True)],5)
    for key,prior in (("scope previous weekly",hma3[-3]),("scope weekly visual",visual[-2])):
        assert all(math.isclose(value,prior,abs_tol=1e-7,rel_tol=0) for value in p[key])
    regression=linreg([bar[4] for bar in c],25)
    assert regression[:24]==p["scope regression"][:24]==[None]*24
    assert all(math.isclose(p["scope regression"][i],regression[i],abs_tol=1e-7,rel_tol=0) and regression[i]>hma3[-3]
               for i in range(24,480))
    assert all(v["cash"]==v["equity"]==1000 and v["marketValue"]==v["netProfit"]==0 for v in broker["equity"])
    return {"market":market,"native_archived_compile_failure":arch["errors"][0],
            "diagnostic_chart_bars":len(c),"diagnostic_aux_week_bars":len(q),
            "diagnostic_zero_orders":True,"diagnostic_zero_closes":True,
            "prior_weekly_hull":hma3[-3],"minimum_ready_regression":min(regression[24:]),
            "weekly_transitions":0,"inert_flat_exit_diagnostics":len(exit_codes)}

def main(work,out):
    assert sha256(work/"priced-runtime/pine_compat/pine_compat.pyd")==ENGINE
    assert sha256(work/"source-1349.md")==SOURCE
    feed=work/"1349-inputs.json"
    raw=work/"1349-probe.json"
    data=read(feed)
    report=read(raw)
    assert report["declarations"]==0
    cases=[compare_market(data[c["market"]],c) for c in report["cases"]]
    assert [c["market"] for c in cases]==["BTCUSDT","ETHUSDT"]
    isolation=read(work/"round3-isolation-python.json")
    assert set(isolation)=={"file_error","network_error"}
    assert all(v[0]=="PermissionError" for v in isolation.values())
    attrs={"id":1349,"group":"FMZ Pine v4 · Source-header restoration",
           "exit":"Four archived take-profit brackets and shared stop",
           "period":"Binance USD-M · 2023-10-24 to 2023-10-25 UTC exclusive",
           "interval":"3m", "archive_interval":"3m", "currency":"USDT"}
    rows=[{**attrs,"market":m,**ledger_metrics([],2_000 if m=="BTCUSDT + ETHUSDT" else 1_000,0)}
          for m in ("BTCUSDT","ETHUSDT","BTCUSDT + ETHUSDT")]
    write(out,{"schema":"FMZ #1349 source declaration and weekly zero-signal control",
               "source_url":"https://www.fmz.com/strategy/430758",
               "source_revision":"7853bb2bf262c4567ac238d3552d97f0e50cb801",
               "source_sha256":SOURCE,"engine_sha256":ENGINE,"raw_sha256":sha256(raw),
               "input_sha256":sha256(feed),"input_data":data["receipts"],"cases":cases,"isolation":isolation,
               "coverage":[[1349,"Tested · source-header restoration, zero orders",
                            "Original published v4 compilation fails on the commented header. Restoring the single authored line gives zero orders over the saved 3m day on real BTC and ETH inputs, with a populated weekly context and independent no-crossover proof. Flat exit diagnostics have no ledger effect."]],
               "results":rows})

if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
