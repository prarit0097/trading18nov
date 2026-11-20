"""Controls for priced-stop netting and authored exit precedence."""

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

header = """//@version=5
strategy("Stop control",initial_capital=10000,default_qty_type=strategy.percent_of_equity,default_qty_value=10,margin_long=0,margin_short=0,pyramiding=3,use_bar_magnifier=true)
"""
reverse = (
    header
    + """
if bar_index == 0
    strategy.entry("L", strategy.long)
if bar_index == 1
    strategy.entry("S", strategy.short, stop=170)
"""
)
oca = (
    header
    + """
if bar_index == 0
    strategy.entry("A",strategy.long,qty=2,stop=150,oca_name="group",oca_type=strategy.oca.cancel)
    strategy.entry("B",strategy.long,qty=3,stop=155,oca_name="group",oca_type=strategy.oca.cancel)
"""
)
v5 = (
    header
    + """
if bar_index == 0
    strategy.entry("L",strategy.long,qty=1)
if bar_index == 1
    strategy.exit("X","L",stop=95,loss=2,limit=110,trail_points=50,trail_offset=20)
"""
)


def replay(source, rows):
    start = 1767225600000
    fields = ("time", "open", "high", "low", "close", "volume")

    def bar(time, row):
        return dict(zip(fields, (time, *row, 1), strict=True))

    chart = [bar(start + i * 1800000, r) for i, r in enumerate(rows)]
    mag = {
        "schemaVersion": 1,
        "chartBars": [
            {
                "chartBarIndex": i,
                "bars": [bar(start + i * 1800000 + j * 300000, r) for j in range(6)],
            }
            for i, r in enumerate(rows)
        ],
    }
    result = pine_compat.run_script(
        source,
        chart,
        chart_symbol="SYNTHETIC:STOP",
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
        magnifier_bars=mag,
    )
    assert not result["diagnostics"], result["diagnostics"]
    return result["strategy"]


data = {
    "reversal": replay(
        reverse, [(100, 100, 100, 100), (200, 200, 200, 200), (150, 150, 150, 150)]
    ),
    "oca": replay(
        oca, [(100, 100, 100, 100), (100, 160, 99, 155), (160, 160, 159, 160)]
    ),
    "v5_pair": replay(
        v5,
        [
            (100, 100, 100, 100),
            (100, 100, 100, 100),
            (100, 101, 98, 100),
            (94, 96, 93, 95),
        ],
    ),
}
rev = data["reversal"]
other = data["oca"]
pair = data["v5_pair"]
checks = {
    "priced_reversal_closed_long_at_150": len(rev["trades"]) == 1
    and rev["trades"][0]["qty"] == 5
    and rev["trades"][0]["exitPrice"] == 150,
    "priced_reversal_open_short_size": math.isclose(
        rev["position"][-1]["size"], -6.5, abs_tol=1e-10
    ),
    "explicit_oca_cancelled_sibling": len(other["orders"]) == 1
    and other["orders"][0]["id"] == "A"
    and other["orders"][0]["qty"] == 2,
    "v5_absolute_stop_precedes_relative_loss": len(pair["trades"]) == 1
    and pair["trades"][0]["exitBarIndex"] == 3
    and pair["trades"][0]["exitPrice"] == 94,
}
(root / f"priced-controls-{variant}.json").write_text(
    json.dumps({"checks": checks, "ledger": data}, indent=2) + "\n", encoding="utf-8"
)
if variant == "market":
    assert {k for k, v in checks.items() if not v} == {
        "priced_reversal_open_short_size"
    }, checks
else:
    assert all(checks.values()), checks
