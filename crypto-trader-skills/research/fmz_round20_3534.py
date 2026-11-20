"""Replay the archived #3534 order rules on explicitly bound 15-minute crypto charts."""

import itertools
import math
import re
import sys
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path

from research.fmz_round7_magnifier import ledger_metrics, read, sha256, write
from research.fmz_round18_5745 import ENGINE_SHA, FIELDS
from research.fmz_round19_3315 import FEEDS

SOURCE_SHA = "121e9ddbc3a07acf6f7f79c6190de117a06bd1b155d3e1e1fadbb3d50a436743"
CAPITAL = 10_000
FEE = Decimal("0.001")
CENT = Decimal("0.01")
MINUTE_15 = 900_000
OBSERVE = """
plot(price, title="Reference close")
plot(longCondition ? 1 : 0, title="Long crossover")
plot(shortCondition ? 1 : 0, title="Short crossover")
"""


def signals(chart):
    close = [Decimal(str(bar["close"])) for bar in chart]
    delta = [
        sum(close[i - 9 : i + 1]) / 10 - sum(close[i - 29 : i + 1]) / 30
        for i in range(29, len(chart))
    ]
    return [0] * 30 + [
        1 if current > 0 >= prev else -1 if current < 0 <= prev else 0
        for prev, current in itertools.pairwise(delta)
    ]


def witness(chart, events):
    inventory = None
    cash = Decimal(CAPITAL)
    pending = 0
    orders, lots, rejected = [], [], []
    confirmed_exits = []
    for index, price in enumerate(chart):
        opening = Decimal(str(price["open"]))
        if pending:
            if opening * (1 + FEE) > cash:
                rejected.append(index)
            else:
                inventory = pending, index, opening
                orders.append((index, opening))
            pending = 0
        if inventory:
            side, entry, execution = inventory
            # The first protective order is submitted at the close of the fill bar.
            if index > entry:
                o, h, l = (Decimal(str(price[k])) for k in ("open", "high", "low"))
                rounding = ROUND_FLOOR if side == 1 else ROUND_CEILING
                stop = (execution * (1 - Decimal("0.02") * side)).quantize(
                    CENT, rounding=rounding
                )
                target = (execution * (1 + Decimal("0.05") * side)).quantize(
                    CENT, rounding=ROUND_CEILING if side == 1 else ROUND_FLOOR
                )
                if side == 1:
                    stopped, targeted = l <= stop, h >= target
                    stop_fill, target_fill = min(o, stop), max(o, target)
                else:
                    stopped, targeted = h >= stop, l <= target
                    stop_fill, target_fill = max(o, stop), min(o, target)
                assert not (stopped and targeted), (index, entry)
                if stopped or targeted:
                    fill = stop_fill if stopped else target_fill
                    pnl = side * (fill - execution)
                    fee = FEE * (execution + fill)
                    cash += pnl - fee
                    lots.append((side, entry, index, pnl, fee))
                    orders.append((index, fill))
                    confirmed_exits.append(
                        {
                            "chart_index": index,
                            "stop": str(stop),
                            "target": str(target),
                            "reason": "stop" if stopped else "target",
                        }
                    )
                    inventory = None
        if inventory is None:
            pending = events[index]
    return orders, lots, inventory, rejected, confirmed_exits


def replay(engine, source, market, chart):
    opts = {
        "chart_symbol": f"BINANCE:{market}",
        "chart_timeframe": "15",
        "request_bars": {
            "swap:15": chart,
            "$chart": {
                "minMove": 1,
                "priceScale": 100,
                "pointValue": 1,
                "quantityStep": "0.001",
                "minContract": "0.001",
                "currency": "USDT",
            },
        },
    }
    original = engine.run_script(source, chart, **opts)["strategy"]
    observed = engine.run_script(source + OBSERVE, chart, **opts)
    assert original == observed["strategy"]
    series = {p["title"]: p["values"] for p in observed["plots"]}
    assert series["Reference close"] == [bar["close"] for bar in chart]
    cross = signals(chart)
    assert series["Long crossover"] == [int(x > 0) for x in cross]
    assert series["Short crossover"] == [int(x < 0) for x in cross]
    orders, lots, inventory, rejected, checks = witness(chart, cross)
    assert all(
        error["code"] == "E_STRATEGY_MARGIN" for error in original["diagnostics"]
    )
    assert len(original["diagnostics"]) == len(rejected)
    for order, (i, px) in zip(original["orders"], orders, strict=True):
        assert order["barIndex"] == i and order["time"] == chart[i]["time"]
        assert order["price"] == float(px) and order["qty"] == 1
    verified = []
    for lot, (side, entry, exit, gross, fee) in zip(
        original["trades"], lots, strict=True
    ):
        assert (
            lot["qty"] == side
            and lot["entryBarIndex"] == entry
            and lot["exitBarIndex"] == exit
        )
        assert math.isclose(lot["profit"], float(gross - fee), abs_tol=1e-10)
        verified.append({**lot, "dir": side, "qty": 1, "commission": float(fee)})
    ending = original["position"][-1] if inventory else None
    if inventory:
        side, entry, opening = inventory
        assert (
            ending["barIndex"] == entry
            and ending["size"] == side
            and ending["avgPrice"] == float(opening)
        )
    return {
        "market": market,
        "bars": len(chart),
        "rejected_for_margin": rejected,
        "exits": checks,
        "trades": verified,
        "ending_position": ending,
        "orders": original["orders"],
    }


def run(work, feeds, engine_root, output):
    assert sha256(engine_root / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(engine_root))
    import pine_compat as engine

    path = work / "source-3534.md"
    assert sha256(path) == SOURCE_SHA
    (source,) = re.findall(
        r"(?ms)^```[^\n]*\n(.*?)^```", path.read_text(encoding="utf-8")
    )
    source, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", source)
    assert n == 1
    cases = []
    for market, digest in FEEDS.items():
        path = feeds / f"4671-authored-{market}.json"
        assert sha256(path) == digest
        raw = read(path)
        chart = [dict(zip(FIELDS, row, strict=True)) for row in raw["intrabar"]]
        assert [bar["time"] for bar in chart] == list(
            range(raw["from"], raw["to"], MINUTE_15)
        )
        cases.append(replay(engine, source, market, chart))
    common = {
        "id": 3534,
        "group": "FMZ · Pine v5 · Explicit same-market 15m research",
        "archive_interval": "1d",
        "interval": "15m",
        "currency": "USDT",
        "period": "Binance USD-M · 2023-09-08 to 2023-10-08 UTC exclusive",
        "exit": "Original 2% stop and 5% target",
    }
    totals = [
        {
            **common,
            "market": c["market"],
            **ledger_metrics(c["trades"], CAPITAL, int(bool(c["ending_position"]))),
        }
        for c in cases
    ]
    totals.append(
        {
            **common,
            "market": "BTCUSDT + ETHUSDT",
            **ledger_metrics(
                [r for c in cases for r in c["trades"]],
                len(cases) * CAPITAL,
                sum(bool(c["ending_position"]) for c in cases),
            ),
        }
    )
    write(
        output,
        {
            "schema": "FMZ 3534 · Pinned 15-minute comparison and margin control",
            "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
            "source_sha256": SOURCE_SHA,
            "engine_sha256": ENGINE_SHA,
            "feeds_sha256": FEEDS,
            "notes": {
                "scope": "Comparison under the source title and input cadence of 15 minutes. The archived chart metadata separately describes a 1-day case and does not identify the bare swap alias. This replay binds it to each chart's own Binance USD-M perpetual. The order code and all default inputs stay literal.",
                "order_model": "Source 10,000 USDT starting capital, fixed one-unit default size, 100% margin, 0.1% commission. Market entry at next 15-minute open. The 2% stop and 5% target are first available after the entry bar closes. Each reported stop or target is independently checked with no dual-touch ambiguity.",
                "evidence": "Both moving-average crossings, market entries, price gaps, margin rejection counts and realized cash ledger reconcile. BTC uses the authored margin, which rejected all one-unit requests in this window. The ETH row has ending inventory. No funding or execution-fee overlay.",
            },
            "coverage": [
                [
                    3534,
                    "Tested · Explicit 15m data binding and margin check",
                    "Native Pine rules on an explicitly identified same-market BTC/ETH 15-minute input. Independent signal, margin, stop/target and fee checks all agree. The archived one-day profile and bare swap data provenance are open research questions.",
                ]
            ],
            "results": totals,
            "scopes": cases,
        },
    )


if __name__ == "__main__":
    run(*map(Path, sys.argv[1:]))
