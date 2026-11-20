"""Independently account for every FMZ #2364 market fill and equity mark."""

import math
import sys
from decimal import Decimal
from pathlib import Path

from research.fmz_round7_magnifier import ledger_metrics, read, sha256, write

SOURCE = "f1e40082c8a965cd0229cb08dcdaf07266c286cab0872b55ed21c49c1cf792f0"
ENGINE = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
CAPITAL = 1_000_000
FEE = Decimal(".00075")
STEP = Decimal(".001")


def decimal(value):
    return Decimal(str(value))


def ledger(feed, baseline):
    chart = feed["chart"]
    plots = baseline["plots"]
    data = baseline["broker"]
    assert not baseline["diagnostics"] and not data["diagnostics"]
    known = []
    trades = []
    cash = Decimal(CAPITAL)
    position = None
    pending = None
    for i, (day, first_hour, mark) in enumerate(zip(chart, feed["first_hour"], data["equity"], strict=True)):
        assert first_hour[:2] == day[:2]
        stamp, first, _, _, close, _ = day
        price = decimal(first)
        if pending == "entry":
            assert position is None and i > 0
            qty = (Decimal(10_000) / decimal(chart[i - 1][4]) // STEP) * STEP
            position = i, stamp, price, qty
            cash -= price * qty
            known.append(("strategy.long", i, stamp, float(qty), first))
        elif pending == "close":
            ebar, etime, eprice, qty = position
            cash += price * qty
            known.append(("strategy.close", i, stamp, float(qty), first))
            gross = (price - eprice) * qty
            fee = (price + eprice) * qty * FEE
            trades.append({"dir":1,"qty":float(qty),"entryPrice":float(eprice),
                           "entryTime":etime,"entryBar":ebar,"exitPrice":first,"exitTime":stamp,"exitBar":i,
                           "commission":float(fee),"gross":float(gross),"profit":float(gross-fee)})
            position = None
        market_value = position[3] * decimal(close) if position else Decimal(0)
        for name, value in (("cash",cash),("marketValue",market_value),
                            ("equity",cash+market_value),("netProfit",cash+market_value-CAPITAL)):
            assert math.isclose(float(value), mark[name], rel_tol=0, abs_tol=1e-8), (i,name,value,mark)
        buys = [plots[k][i] for k in ("scope buy1","scope buy2","scope A")]
        if position:
            pending = "close" if plots["scope close"][i] else None
        else:
            pending = "entry" if any(buys) else None
    assert known == [(o["direction"],o["barIndex"],o["time"],o["qty"],o["price"]) for o in data["orders"]]
    for raw, matched in zip(data["trades"],trades,strict=True):
        assert (raw["entryBarIndex"],raw["exitBarIndex"],raw["entryPrice"],raw["exitPrice"],raw["qty"])==(
            matched["entryBar"], matched["exitBar"], matched["entryPrice"], matched["exitPrice"], matched["qty"])
        assert math.isclose(raw["profit"],matched["gross"],abs_tol=1e-8)
    return known, trades, position


def gates(a,b):
    return sum(x!=y for x,y in zip(a,b,strict=True))


def audit(market, feed, replay):
    assert len(feed["chart"]) == 371 and len(feed["six"]) == 1484
    assert replay["literal"]["errors"][0].startswith("E_LEGACY_VERSION_FEATURE")
    baseline = replay["vocabulary"]
    assert baseline == replay["modern_control"] == replay["numeric_if_control"]
    flat = replay["flat_context_control"]
    assert flat["broker"] == baseline["broker"]
    nested_delta_changes = gates(flat["plots"]["scope aMACDD"],baseline["plots"]["scope aMACDD"])
    buy_changes = gates(flat["plots"]["scope buy1"],baseline["plots"]["scope buy1"])
    assert (nested_delta_changes,buy_changes)==(363,0 if market=="BTCUSDT" else 1)
    for n in (90,220,365):
        prefix = replay[f"prefix_{n}"]
        assert prefix["plots"] == {k:v[:n] for k,v in baseline["plots"].items()}
        broker, result = baseline["broker"], prefix["broker"]
        for kind, index in (("orders","barIndex"),("position","barIndex"),
                            ("equity","barIndex"),("trades","exitBarIndex")):
            assert result[kind] == [row for row in broker[kind] if row[index]<n], kind
    orders,trades,position=ledger(feed,baseline)
    assert len(trades)==(8 if market=="BTCUSDT" else 12) and position
    _,entry_time,entry_price,quantity=position
    terminal=decimal(feed["chart"][-1][4])
    terminal_fee=(entry_price+terminal)*quantity*FEE
    mark={"opened":entry_time,"entry":float(entry_price),"quantity":float(quantity),
          "terminal_close":float(terminal),"gross_unrealized":float((terminal-entry_price)*quantity),
          "fee_if_closed_at_last_mark":float(terminal_fee)}
    return {"market":market,"orders":orders,"fills":trades,"mark":mark,
            "prefix_bars":[90,220,365],"flattened_signal_value_changes":nested_delta_changes,
            "flattened_buy_gate_changes":buy_changes}


def main(work,out):
    assert sha256(work/"source-2364.md") == SOURCE
    assert sha256(work/"priced-runtime/pine_compat/pine_compat.pyd") == ENGINE
    feed,raw=work/"2364-feed.json",work/"2364-native.json"
    data,native=read(feed),read(raw)
    assert len(data["receipts"]) == 26
    cases=[audit(m,d,native[m]) for m,d in data["markets"].items()]
    isolation=read(work/"round3-isolation-python.json")
    assert set(isolation)=={"file_error","network_error"}
    assert all(v[0]=="PermissionError" for v in isolation.values())
    attrs={"id":2364,"group":"FMZ Pine v3 · source vocabulary compatibility",
           "exit":"Archived MACD and stop-series market close rules",
           "period":"Binance USD-M · 2023-01-05 to 2024-01-11 UTC exclusive",
           "interval":"1d","archive_interval":"1d","currency":"USDT"}
    results=[{**attrs,"market":x["market"],**ledger_metrics(x["fills"],CAPITAL,1)} for x in cases]
    results.append({**attrs,"market":"BTCUSDT + ETHUSDT",
                    **ledger_metrics([t for x in cases for t in x["fills"]],2*CAPITAL,2)})
    write(out, {"schema":"FMZ #2364 exact v3 aliases and nested-context ledger verification",
                "source_url":"https://www.fmz.com/strategy/438502",
                "source_revision":"7853bb2bf262c4567ac238d3552d97f0e50cb801",
                "source_sha256":SOURCE,"engine_sha256":ENGINE,"native_sha256":sha256(raw),
                "input_sha256":sha256(feed),"market_receipts":data["receipts"],"isolation":isolation,
                "fee_sensitivity_per_side":float(FEE),"cases":cases,
                "coverage":[[2364,"Tested · v3 aliases, archived BTC/ETH next-open fills",
                             "Documented v3 aliases preserve the published strategy. Three prefix checks rule out later-data revisions in the saved run. The alternate nested-context calculation changes one ETH gate and the identical ledger still reconciles every position, fill, price and equity mark."]],
                "results":results})


if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
