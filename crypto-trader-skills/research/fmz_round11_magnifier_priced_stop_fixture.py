"""Proof of priced stop sizing only. Uses no market data."""

import json
import math
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
variant = sys.argv[1]
assert variant in {"market", "priced"}
sys.path.insert(
    0, str(root / ("market-runtime" if variant == "market" else "priced-runtime"))
)
import pine_compat


def run(gap, fixed):
    use_qty = ", qty=2" if fixed else ""
    source = f"""//@version=5
strategy("priced stop percent sizing", initial_capital=10000, default_qty_type=strategy.percent_of_equity, default_qty_value=10, commission_value=0.1, slippage=1, margin_long=0, margin_short=0, use_bar_magnifier=true)
if bar_index == 0
    strategy.entry("L",strategy.long,stop=150{use_qty})
if bar_index == 1
    strategy.close("L")
"""
    t = 1767225600000
    step = 1800000
    candles = [
        (100, 100, 100, 100),
        (200, 205, 199, 201) if gap else (120, 160, 119, 151),
        (210, 211, 208, 209),
    ]

    def bar(ts, row):
        return dict(
            zip(
                ("time", "open", "high", "low", "close", "volume"),
                [ts, *row, 1],
                strict=True,
            )
        )

    chart = [bar(t + i * step, row) for i, row in enumerate(candles)]
    intrabar = {
        "schemaVersion": 1,
        "chartBars": [
            {
                "chartBarIndex": i,
                "bars": [bar(t + i * step + j * 300000, row) for j in range(6)],
            }
            for i, row in enumerate(candles)
        ],
    }
    result = pine_compat.run_script(
        source,
        chart,
        chart_symbol="TEST:FIXTURE",
        chart_timeframe="30",
        request_bars={
            "$chart": {
                "minMove": 1,
                "priceScale": 10,
                "quantityStep": "0.1",
                "minContract": "0.1",
                "currency": "USD",
            }
        },
        magnifier_bars=intrabar,
    )
    assert not result["diagnostics"] and not result["strategy"]["diagnostics"]
    lot = result["strategy"]["trades"][0]
    assert math.isclose(lot["entryPrice"], 200.1 if gap else 150.1, abs_tol=1e-9)
    assert math.isclose(lot["exitPrice"], 209.9, abs_tol=1e-9)
    return lot


actual = {
    "stop_gap": run(True, False),
    "stop_traversed": run(False, False),
    "fixed_unchanged": run(True, True),
}
expected = {"stop_gap": 4.9, "stop_traversed": 6.6, "fixed_unchanged": 2}
checks = {}
for label, lot in actual.items():
    e, x, qty = lot["entryPrice"], lot["exitPrice"], lot["qty"]
    checks[label + "_qty"] = math.isclose(qty, expected[label], abs_tol=1e-9)
    checks[label + "_settle"] = math.isclose(
        lot["profit"], qty * ((x - e) - 0.001 * (e + x)), abs_tol=1e-8
    )
(root / f"priced-stop-control-{variant}.json").write_text(
    json.dumps({"checks": checks, "actual": actual}, indent=2) + "\n", encoding="utf-8"
)
if variant == "market":
    assert {key for key, passed in checks.items() if not passed} == {
        "stop_gap_qty",
        "stop_traversed_qty",
    }, checks
else:
    assert all(checks.values()), checks
