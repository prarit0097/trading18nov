"""Verify FMZ #3301 default conditions and historical market-order equity."""

import math
import sys
from decimal import Decimal
from pathlib import Path

from research.fmz_round7_magnifier import ledger_metrics, read, sha256, write
from research.fmz_round32_trailing_offset import sma
from research.fmz_round40_4307 import recurrence

SOURCE = "4d777c6588633cd1977471f5253bc840d0a520a4d4529eb23501b4021c8767f8"
ENGINE = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
CAPITAL = Decimal(100)
FEE, STEP = Decimal(".00075"), Decimal(".001")


def local_rsi(close):
    changes = [a-b for b,a in zip(close,close[1:])]
    gains = recurrence([max(v,0) for v in changes],20,1/20)
    losses = recurrence([max(-v,0) for v in changes],20,1/20)
    return [None, *[None if a is None else 100 if b==0 else 100-100/(1+a/b)
                    for a,b in zip(gains,losses,strict=True)]]


def independent_series(data):
    close = [r[4] for r in data["chart"]]
    daily_rsi = local_rsi([r[4] for r in data["daily"]])
    local = local_rsi(close)
    higher = [None] + [daily_rsi[(i+1)//12 - 1] if i >= 11 else None for i in range(1,len(close))]
    # Each day's final 2h bar closes at the same time as that daily bar.
    fast, slow = sma(close,50),sma(close,100)
    available = [p is not None and q is not None and 0<p<=100 and 0<q<=100
                 for p,q in zip(local,higher,strict=True)]
    buy = [int(r and a>b) for r,a,b in zip(available,fast,slow,strict=True)]
    sell = [int(r and a<=b) for r,a,b in zip(available,fast,slow,strict=True)]
    return {"RSI":local,"daily RSI":higher,"short MA":fast,"long MA":slow,"buy":buy,"sell":sell}


def reconcile(data,run,signal):
    cash = CAPITAL
    cost_adjusted_cash = CAPITAL
    holding = None
    orders, trades = [], []
    broker = run["broker"]
    assert not run["diagnostics"] and not broker["diagnostics"]
    for i,(bar,mark) in enumerate(zip(data["chart"],broker["equity"],strict=True)):
        ts,op,_,_,close,_=bar
        assert bar[:2]==data["base"][i*8][:2]
        px = Decimal(str(op))
        if i>0 and signal["buy"][i-1] and holding is None:
            quantity = cash/px//STEP*STEP
            holding=ts,px,quantity
            assert quantity == cost_adjusted_cash/(px*(1+FEE))//STEP*STEP
            cash-=px*quantity
            cost_adjusted_cash-=px*quantity*(1+FEE)
            orders.append(("strategy.long",i,ts,op,float(quantity)))
        if i>0 and signal["sell"][i-1] and holding is not None:
            entry_time,entry_price,quantity=holding
            holding=None
            cash+=px*quantity
            cost_adjusted_cash+=px*quantity*(1-FEE)
            gross=(px-entry_price)*quantity
            fee=(px+entry_price)*quantity*FEE
            orders.append(("strategy.close",i,ts,op,float(quantity)))
            trades.append({"dir":1,"qty":float(quantity),"entryPrice":float(entry_price),
                           "entryTime":entry_time,"exitTime":ts,"exitPrice":op,
                           "gross":float(gross),"profit":float(gross-fee),"commission":float(fee)})
        value = holding[2]*Decimal(str(close)) if holding else Decimal(0)
        for k,want in (("cash",cash),("marketValue",value),("equity",cash+value),("netProfit",cash+value-CAPITAL)):
            assert math.isclose(float(want),mark[k],abs_tol=1e-9,rel_tol=0)
    assert orders==[(r["direction"],r["barIndex"],r["time"],r["price"],r["qty"]) for r in broker["orders"]]
    for actual,want in zip(broker["trades"],trades,strict=True):
        assert all(actual[k]==want[k] for k in ("entryTime","exitTime","entryPrice","exitPrice","qty"))
        assert math.isclose(actual["profit"],want["gross"],abs_tol=1e-9)
    assert holding is not None
    entry_time,entry_price,quantity=holding
    terminal=Decimal(str(data["chart"][-1][4]))
    gross=(terminal-entry_price)*quantity
    net=gross-(terminal+entry_price)*quantity*FEE
    return orders,trades,{"open_time":entry_time,"entry_price":float(entry_price),"quantity":float(quantity),
                          "final_close":float(terminal),"gross_unrealized":float(gross),
                          "after_fee_unrealized_at_last_close":float(net),
                          "cost_adjusted_equity_at_last_close":float(cost_adjusted_cash+terminal*quantity),
                          "cost_adjusted_equity_if_closed_at_last_close":float(cost_adjusted_cash+terminal*quantity*(1-FEE)),
                          "fee_aware_compounding_changes_quantity":False}


def market(name,data,observations):
    assert [len(data[k]) for k in ("base","chart","daily")]==[2880,360,30]
    literal=observations["literal"]["errors"]
    assert literal[0].startswith("E_UNKNOWN_FUNCTION") and "rsi" in literal[0]
    verified=observations["identifier_control"]
    assert verified==observations["inactive_bracket_control"]
    independent=independent_series(data)
    assert independent["daily RSI"][:251]==[None]*251
    assert independent["daily RSI"][251] is not None
    for key,series in independent.items():
        assert all(a==b or (None not in (a,b) and math.isclose(a,b,abs_tol=1e-9))
                   for a,b in zip(series,verified["plots"]["scope "+key],strict=True)),key
    orders,trades,mark=reconcile(data,verified,independent)
    assert len(trades)==(0 if name=="BTCUSDT" else 1)
    return {"market":name,"orders":orders,"trades":trades,"terminal_mark":mark,
            "first_ready_daily_rsi_chart_index":251,"literal_compile_error":literal[0]}


def main(work,out):
    assert sha256(work/"source-3301.md")==SOURCE
    assert sha256(work/"priced-runtime/pine_compat/pine_compat.pyd")==ENGINE
    feed,raw=work/"3301-feed.json",work/"3301-native.json"
    data,engine=read(feed),read(raw)
    assert len(data["receipts"])==4
    cases=[market(name,packet,engine[name]) for name,packet in data["markets"].items()]
    isolation=read(work/"round3-isolation-python.json")
    assert set(isolation)=={"file_error","network_error"}
    assert all(v[0]=="PermissionError" for v in isolation.values())
    attrs={"id":3301,"group":"FMZ Pine v4 · identifier compatibility",
           "exit":"Authored 50/100 SMA check with daily RSI gate",
           "period":"Binance USD-M · 2023-11-04 to 2023-12-04 UTC exclusive",
           "interval":"2h","archive_interval":"2h","currency":"USDT"}
    rows=[{**attrs,"market":s["market"],**ledger_metrics(s["trades"],float(CAPITAL),1)} for s in cases]
    rows.append({**attrs,"market":"BTCUSDT + ETHUSDT",**ledger_metrics(
        [t for s in cases for t in s["trades"]],float(2*CAPITAL),2)})
    write(out,{"schema":"FMZ #3301 verified point-in-time daily RSI and 2h market ledger",
               "source_url":"https://www.fmz.com/strategy/434288",
               "source_revision":"7853bb2bf262c4567ac238d3552d97f0e50cb801",
               "source_sha256":SOURCE,"engine_sha256":ENGINE,"input_sha256":sha256(feed),
               "native_sha256":sha256(raw),"market_receipts":data["receipts"],"isolation":isolation,
               "fee_sensitivity_per_side":float(FEE),"cases":cases,
               "coverage":[[3301,"Tested · daily RSI and 2h SMA market replay",
                            "The sole source identifier rename resolves shadowing. The first daily RSI and every price, size, exposure and cash mark independently reconcile. One ETH close and two ending open positions are disclosed."]],
               "results":rows})


if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
