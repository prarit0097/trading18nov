"""Deterministic diagnostics only. These fixtures are not market backtests."""

import json
import math
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
backend = sys.argv[1]
assert backend in ("baseline", "patched")
sys.path.insert(
    0, str(root / ("baseline-runtime" if backend == "baseline" else "patched-runtime"))
)
import pine_compat

T = 1767225600000
STEP = 1800000
BASE = 300000


def candle(time, o, h=None, l=None, c=None):
    return {
        "time": time,
        "open": o,
        "high": o if h is None else h,
        "low": o if l is None else l,
        "close": o if c is None else c,
        "volume": 1,
    }


def chart(ohlc):
    return [candle(T + i * STEP, *row) for i, row in enumerate(ohlc)]


def magnify(chart_bars, overrides=None):
    groups = []
    overrides = overrides or {}
    for i, bar in enumerate(chart_bars):
        source = overrides.get(i)
        if source is None:
            item = tuple(bar[name] for name in ("open", "high", "low", "close"))
            source = [item] * 6
        groups.append(
            {
                "chartBarIndex": i,
                "bars": [
                    candle(bar["time"] + j * BASE, *args)
                    for j, args in enumerate(source)
                ],
            }
        )
    return {"schemaVersion": 1, "chartBars": groups}


def run(code, bars, step="0.1", mag=None):
    grid = {
        "minMove": 1,
        "priceScale": 10,
        "pointValue": 1,
        "quantityStep": step,
        "minContract": step,
        "currency": "USD",
    }
    result = pine_compat.run_script(
        code,
        bars,
        chart_symbol="TEST:FIXTURE",
        chart_timeframe="30",
        request_bars={"$chart": grid},
        magnifier_bars=mag,
    )
    return {
        "trades": result["strategy"]["trades"],
        "orders": result["strategy"]["orders"],
        "final_position": result["strategy"]["position"][-1],
        "end_equity": result["strategy"]["equity"][-1]["equity"],
        "warnings": result["diagnostics"],
        "broker": result["strategy"]["diagnostics"],
    }


def sizing_source(fee, ltf):
    return f"""//@version=5
strategy("Next-open equity sizing",initial_capital=10000,default_qty_type=strategy.percent_of_equity,default_qty_value=10,margin_long=0,margin_short=0,commission_value={fee},use_bar_magnifier={str(ltf).lower()})
if bar_index == 0
    strategy.entry("L",strategy.long)
if bar_index == 1
    strategy.close("L")
"""


def limit_source(assumption):
    return f"""//@version=5
strategy("Limit timing",initial_capital=10000,margin_long=0,margin_short=0,use_bar_magnifier=true,backtest_fill_limits_assumption={assumption})
if bar_index == 0
    strategy.entry("L",strategy.long,qty=1)
if bar_index == 1
    strategy.exit("TP","L",limit=105)
"""


reversal_source = """//@version=5
strategy("Next-open net target on reversal",initial_capital=10000,default_qty_type=strategy.percent_of_equity,default_qty_value=10,margin_long=0,margin_short=0)
if bar_index == 0
    strategy.entry("L",strategy.long)
if bar_index == 1
    strategy.entry("S",strategy.short)
"""
coof_source = """//@version=5
strategy("COOF magnifier history",initial_capital=10000,margin_long=0,margin_short=0,use_bar_magnifier=true,calc_on_order_fills=true)
if bar_index == 0 and strategy.position_size == 0
    strategy.entry("L",strategy.long,qty=1)
if strategy.position_size > 0
    strategy.exit("X","L",stop=95,limit=105)
"""
cfg = chart([(100,), (200,), (210,)])
coof_chart = chart([(100,), (100, 106, 90, 100), (100,)])
coof_intra = magnify(
    coof_chart,
    {
        1: [
            (100, 101, 99, 100),
            (94, 95, 92, 93),
            (93, 100, 90, 100),
            (100, 106, 100, 105),
            (105, 106, 103, 104),
            (104, 105, 100, 100),
        ]
    },
)
limits = chart([(100,), (100,), (100, 105, 99, 101), (100, 105.1, 99, 101)])
actual = {
    "open_gap": run(sizing_source(0, False), cfg),
    "open_gap_with_fees_and_lot": run(sizing_source(0.1, True), cfg, mag=magnify(cfg)),
    "reversal": run(reversal_source, chart([(100,), (200,), (250,)])),
    "limit0": run(limit_source(0), limits, mag=magnify(limits)),
    "limit1": run(limit_source(1), limits, mag=magnify(limits)),
    "coof_ohlc": run(coof_source, coof_chart),
    "coof_ltf": run(coof_source, coof_chart, mag=coof_intra),
}
checks = {
    "gap_qty": actual["open_gap"]["trades"][0]["qty"] == 5,
    "gap_value": actual["open_gap"]["trades"][0]["profit"] == 50,
    "fee_lot": actual["open_gap_with_fees_and_lot"]["trades"][0]["qty"] == 4.9,
    "fee_profit": math.isclose(
        actual["open_gap_with_fees_and_lot"]["trades"][0]["profit"],
        46.991,
        abs_tol=1e-8,
    ),
    "reversal_old_lot": actual["reversal"]["trades"][0]["qty"] == 5,
    "reversal_new_net": actual["reversal"]["final_position"]["size"] == -4.1,
    "touch_bar": actual["limit0"]["trades"][0]["exitBarIndex"] == 2,
    "through_bar": actual["limit1"]["trades"][0]["exitBarIndex"] == 3,
    "same_limit_price": actual["limit0"]["trades"][0]["exitPrice"]
    == actual["limit1"]["trades"][0]["exitPrice"]
    == 105,
    "coof_chart_target": actual["coof_ohlc"]["trades"][0]["exitPrice"] == 105,
    "coof_real_intra_first": actual["coof_ltf"]["trades"][0]["exitPrice"] == 94,
    "active_ltf": not any(
        actual[x]["warnings"]
        for x in ("open_gap_with_fees_and_lot", "limit0", "limit1", "coof_ltf")
    ),
}
(root / f"market-fixtures-{backend}.json").write_text(
    json.dumps({"checks": checks, "actual": actual}, indent=2) + "\n", encoding="utf-8"
)
if backend == "baseline":
    assert sum(not passed for passed in checks.values()) == 6, checks
else:
    assert all(checks.values()), checks
