import json,re,sys
from pathlib import Path
w=Path(__file__).parent
sys.path.insert(0,str(w/"priced-runtime"))
import pine_compat
feeds=json.loads((w/"r25-dma-feeds.json").read_bytes())
code=(w/"r25-dma-source.pine").read_text(encoding="utf-8")
code,n=re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*","",code)
assert n==1
plot='''
plot(bad_vol?1:0,title="Low volume mode")
plot(longCondition?1:0,title="Long gate")
plot(shortCondition?1:0,title="Short gate")
plot(strategy.position_size,title="Position")
plot(strategy.equity,title="Equity")
'''
fee_source=code.replace('default_qty_value=100)',"default_qty_value=100, commission_type=strategy.commission.percent, commission_value=0.059)")
assert fee_source!=code
def candles(src):
    return [dict(zip(("time","open","high","low","close","volume"),row,strict=True)) for row in src]
out=[]
selection=sys.argv[1:]
for period,markets in feeds.items():
    for market,scenario in markets.items():
        key=("native" if period=="FMZ native window" else "next")+"-"+market
        if selection and key not in selection:
            continue
        chart=candles(scenario["chart"])
        lower=candles([r for r in scenario["reference"] if r[0]>=chart[0]["time"]])
        symbol="BINANCE:"+market
        opts=dict(chart_symbol=symbol,chart_timeframe="60",request_bars={symbol+":1":lower,"$chart":{"minMove":1,"priceScale":100,"pointValue":1,"quantityStep":"0.001","minContract":"0.001","currency":"USDT"}})
        results={}
        for mode,script in (("with comparison fee",fee_source),):
            read=pine_compat.run_script(script+plot,chart,**opts)
            assert read["diagnostics"]==[] and read["strategy"]["diagnostics"]==[]
            results[mode]={"strategy":read["strategy"],"plots":{p["title"]:p["values"] for p in read["plots"]}}
        out.append({"period":period,"market":market,"results":results})
(w/("r25-dma-causal-"+("-".join(selection) or "all")+".json")).write_text(json.dumps(out,separators=(",",":")),encoding="utf-8",newline="\n")

