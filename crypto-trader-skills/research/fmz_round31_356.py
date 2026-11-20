"""Audit source-preserving Pine v4 decisions for FMZ #356."""

import collections
import math
import sys
from decimal import Decimal
from pathlib import Path

from research.fmz_round7_magnifier import aggregate, date_ms, ledger_metrics, raw_ohlcv, read, sha256, verified_archives, write
from research.fmz_round30_1070 import bar_bracket, offset

FEE = .0004
CAPITAL = 10_000
SOURCE = "29cd57977b69a28a1b96dbc0ce3e3d8d36b1d2ff7f7399853eea2a3eed1821e7"
ENGINE = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"


def thresholds(plot, side, i, entry, tick):
    direction = 1 if side == "L" else -1
    return (entry + direction * offset(plot["observed profit ticks"][i], tick),
            entry - direction * offset(plot["observed loss ticks"][i], tick))


def grid(price, tick):
    return math.isclose(price/tick, round(price/tick), abs_tol=1e-7, rel_tol=0)


def open_qty(capital, price):
    return int(Decimal(f"{capital:.9e}") / (Decimal(str(price)) * Decimal("1.0004")) * 1000) / 1000


def trade_audit(case, chart, minute, tick):
    assert case["v4_legacy"] == case["v4_explicit"]
    normalized = case["v4_legacy"]
    assert case["archived"]["exception"][0].startswith("E_LEGACY_VERSION_FEATURE:Error")
    assert [d["code"] for d in normalized["diagnostics"]] == ["W_LEGACY_SECURITY_LOOKAHEAD"]
    broker, plot = normalized["broker"], normalized["plots"]
    assert not broker["diagnostics"]
    assert plot["observed request"] == [None]+[c[4] for c in chart[:-1]]
    assert plot["observed timestamps"] == [None]+[0]*(len(chart)-1)
    assert all(not (u and d) for u,d in zip(plot["observed L"],plot["observed S"],strict=True))
    assert all(grid(order["price"], tick) for order in broker["orders"])
    assert all(math.isclose(close*tp/tick, actual, abs_tol=1e-8)
               for key,tp in (("observed profit ticks",.019),("observed loss ticks",.081))
               for (_,_,_,_,close,_),actual in zip(chart,plot[key],strict=True))
    order_bar = collections.defaultdict(list)
    for order in broker["orders"]:
        order_bar[order["barIndex"]].append(order)
    ledger, both, refined = [], [], []
    bracket_count = 0
    cash = CAPITAL
    prior = None
    for trade in broker["trades"]:
        side = trade["id"]
        opposite = "S" if side == "L" else "L"
        qty, e, x = trade["qty"],trade["entryBarIndex"],trade["exitBarIndex"]
        entry, closed = trade["entryPrice"],trade["exitPrice"]
        assert qty * (1 if side=="L" else -1) > 0
        assert chart[e][1] == minute[e*30][1] == entry
        assert chart[e][0] == trade["entryTime"] and chart[x][0] == trade["exitTime"]
        assert plot["observed "+side][e-1] == 1
        reversal = prior is not None and prior["exitBarIndex"] == e
        budget = cash + (FEE * abs(prior["qty"]) * entry if reversal else 0)
        assert open_qty(budget, entry) == abs(qty)
        placed, = [item for item in order_bar[e] if item["id"] == side]
        size = abs(qty) + (abs(prior["qty"]) if reversal else 0)
        assert math.isclose(size,placed["qty"],abs_tol=1e-10)
        for i in range(e,x):
            target, stop = thresholds(plot,side,i-1,entry,tick)
            assert bar_bracket(chart[i],side,target,stop)[0] is None, (e,x,i)
            assert i==e or not plot["observed "+opposite][i-1]
        exits = [item for item in order_bar[x] if item["direction"] == "strategy.exit"
                 and math.isclose(abs(qty),item["qty"],abs_tol=1e-10)
                 and math.isclose(closed,item["price"],abs_tol=1e-8)]
        if exits:
            bracket_count += 1
            order, = exits
            assert abs(qty) == order["qty"] and math.isclose(closed,order["price"],abs_tol=1e-8)
            target,stop = thresholds(plot,side,x-1,entry,tick)
            predicted,reason,contains_both = bar_bracket(chart[x],side,target,stop)
            assert math.isclose(closed,predicted,abs_tol=1e-8)
            for minbar in minute[x*30:x*30+30]:
                mp,mr,both_minute = bar_bracket(minbar,side,target,stop)
                if mp is not None:
                    break
            else:
                raise ValueError("No eligible bracket fill")
            record = {"source_bar":x,"source_time":chart[x][0],"source_ohlc":chart[x][1:5],
                      "side":side,"target":target,"stop":stop,"minute_time":minbar[0],"minute_ohlc":minbar[1:5],
                      "source_price":closed,"minute_price":mp,"source_reason":reason,"minute_reason":mr,
                      "both_minute":both_minute}
            if contains_both:
                both.append(record)
            if not math.isclose(closed,mp,abs_tol=1e-8):
                refined.append(record)
        else:
            assert plot["observed "+opposite][x-1] == 1
            assert chart[x][1] == minute[x*30][1] == closed
        fee = FEE * abs(qty) * (entry+closed)
        net = qty*(closed-entry)-fee
        assert math.isclose(net,trade["profit"],abs_tol=1e-8)
        cash += net
        ledger.append({**trade, "qty":abs(qty),"dir":1 if qty>0 else -1,"commission":fee})
        prior=trade
    final = broker["position"][-1]
    assert final["size"] < 0 and plot["observed S"][final["barIndex"]-1] == 1
    i = final["barIndex"]
    assert chart[i][1] == minute[i*30][1] == final["avgPrice"]
    assert open_qty(cash, final["avgPrice"]) == abs(final["size"])
    for bar in range(i, len(chart)):
        target, stop = thresholds(plot, "S", bar-1, final["avgPrice"], tick)
        assert bar_bracket(chart[bar], "S", target, stop)[0] is None
        assert not plot["observed L"][bar-1]
    return ({"market":case["market"],"closed":len(ledger),"both":both,"intrabar_changes":refined,
             "brackets":bracket_count,"reversals":len(ledger)-bracket_count,
             "original_compile_errors":case["archived"]["exception"][:4],
             "observed_same_frame_bars":len(chart), "open":final,
             "with_costs":ledger_metrics(ledger,CAPITAL,1)},ledger)


def main(work, public, output):
    replay_path=work/"356-probe.json"
    raw=read(replay_path)
    assert sha256(work/"source-356.md")==SOURCE
    assert sha256(work/"priced-runtime/pine_compat/pine_compat.pyd")==ENGINE
    isolation = read(work/"round3-isolation-python.json")
    assert set(isolation) == {"file_error", "network_error"}
    assert all(value[0] == "PermissionError" for value in isolation.values())
    manifest=read(work/"1070-inputs.json")
    archives=[]
    results=[]
    pooled=[]
    for case,ref,market in zip(raw,manifest["feeds"],("BTCUSDT","ETHUSDT"),strict=True):
        data_path=work/ref["file"]
        assert case["market"] == ref["market"] == market and sha256(data_path)==ref["sha256"]
        chart=read(data_path)["chart"]
        path, = verified_archives(public,market,"1m",("2024-01",),archives)
        minute=list(raw_ohlcv(path,60_000))
        assert [bar[0] for bar in minute] == list(range(date_ms("2024-01-01"),date_ms("2024-02-01"),60_000))
        assert [list(r[:5]) for r in aggregate(minute,30)]==[r[:5] for r in chart]
        row,ledger=trade_audit(case,chart,minute, .1 if market=="BTCUSDT" else .01)
        assert row["closed"] == 25 and not row["both"] and not row["intrabar_changes"]
        assert row["brackets"] == (14 if market == "BTCUSDT" else 19)
        results.append(row)
        pooled.extend(ledger)
    attrs = {"id":356,"group":"FMZ Pine v4 · ETH 30-minute trend filters",
             "exit":"1.9% target and 8.1% stop distances from decision close, opposite market reversals",
             "period":"Binance USD-M · 2024-01-01 to 2024-02-01 UTC exclusive",
             "interval":"30m", "archive_interval":"30m in title", "currency":"USDT"}
    rows = [{**attrs, "market": case["market"], **case["with_costs"]} for case in results]
    rows.append({**attrs,"market":"BTCUSDT + ETHUSDT",**ledger_metrics(pooled,2*CAPITAL,2)})
    write(output,{
        "schema":"FMZ #356 30m directional percent-of-equity replay",
        "source_url":"https://www.fmz.com/strategy/376259",
        "source_revision":"7853bb2bf262c4567ac238d3552d97f0e50cb801",
        "cases":results,"input_data":manifest,"minute_archives":archives,
        "source_sha256":SOURCE,"engine_sha256":ENGINE,"raw_sha256":sha256(replay_path),
        "isolation":isolation,
        "limitations":[
            "The archive has no version directive or saved market interval block. Pine v4 restores the authored legacy input and order syntax. BTC and ETH are compared at the source title's 30-minute interval over January 2024.",
            "Original 1/0 entry tokens and explicit direction constants agree on all orders, trades and observed series. The broker uses the archived numeric author's percent-of-equity, zero slippage, and .04% commission declaration. FMZ host settings are not saved.",
            "The original populated same-interval Jurik request equals the prior confirmed close at every noninitial candle. The timestamp request uses the chart timeframe at the saved input default and produces zero elapsed-bar weights after initialization.",
            "The 30-minute replay and every full minute group agree on the bracket or next-open fill. OHLC price and timing are modeled. Funding, spread, executable depth and further slippage are absent. One last position per symbol stays open.",
            "Each asset starts at 10,000 USDT. Gross P&L removes commissions from the same lots. Drawdown uses realized closes.",
        ],
        "coverage":[[356,"Tested · BTC and ETH 30m legacy Pine comparison",
                     "50 verified closes, 33 price brackets and 17 market reversals across two January 2024 scopes. Both markets match official minute chronology and prices. Version restoration only. FMZ host parity and ranking qualification remain outside this result."]],
        "results":rows,
    })


if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
