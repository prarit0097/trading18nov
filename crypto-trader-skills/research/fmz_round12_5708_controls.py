"""Independent research probe for FMZ archive #5708."""

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "priced-runtime"))
import pine_compat


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def migrate():
    raw = (ROOT / "source-5708.md").read_bytes()
    assert (
        digest(raw)
        == "5ba5718671a7c169e75e826206af348f7b201c57903f1b392d7bb073e8966cdf"
    )
    (code,) = re.findall(
        r"(?m)^``` pinescript\n.*?^\*/\n\n(.*?)^```", raw.decode(), re.DOTALL
    )
    substitutions = (
        ("//@version=1", "//@version=5", 1),
        ("input(hlc3)", "input.source(hlc3)", 1),
        ("input(22)", "input.int(22)", 1),
        ("input(14)", "input.int(14)", 1),
        ("input(2)", "input.int(2)", 1),
        ("highest(", "ta.highest(high, ", 2),
        ("lowest(", "ta.lowest(low, ", 2),
        (" == 1 and", " and", 2),
        (
            "long and long[1], color=green, style=line",
            "long and long[1] ? 1 : 0, color=color.green, style=plot.style_line",
            1,
        ),
        (
            "short and short[1], color=red, style=line",
            "short and short[1] ? 1 : 0, color=color.red, style=plot.style_line",
            1,
        ),
    )
    for previous, updated, count in substitutions:
        assert code.count(previous) == count, (previous, count)
        code = code.replace(previous, updated)
    assert "use_bar_magnifier" not in code
    return code


OBSERVER = """
plot(long1 ? 1 : 0, title="Long signal")
plot(short1 ? 1 : 0, title="Short signal")
"""


def as_objects(rows):
    keys = ("time", "open", "high", "low", "close", "volume")
    return [dict(zip(keys, row, strict=True)) for row in rows]


def controls():
    source = migrate()
    options = {
        "chart_symbol": "BINANCE:BTCUSDT",
        "chart_timeframe": "60",
        "request_bars": {
            "$chart": {
                "minMove": 1,
                "priceScale": 10,
                "pointValue": 1,
                "quantityStep": "0.001",
                "minContract": "0.001",
                "currency": "USDT",
            },
            "$currencyRates": {
                "schemaVersion": 1,
                "pairs": [
                    {
                        "from": "USDT",
                        "to": "USD",
                        "rates": [
                            {"effectiveTime": 0, "rate": 0.98},
                            {"effectiveTime": 86400000, "rate": 0.95},
                        ],
                    }
                ],
            },
        },
    }
    candles = [[100, 101, 99, 100]] * 24 + [
        [100, 110, 90, 100],
        [116, 150, 80, 146],
        [130, 132, 20, 50],
        [45, 52, 42, 50],
    ]
    chart = as_objects([[j * 3600000, *bar, 2.0] for j, bar in enumerate(candles)])
    observed = pine_compat.run_script(source + OBSERVER, chart, **options)
    complete = pine_compat.run_script(source, chart, **options)
    altered = pine_compat.run_script(
        source.replace("calc_on_order_fills=true", "calc_on_order_fills=false"),
        chart,
        **options,
    )
    assert observed["strategy"] == complete["strategy"]
    emit = {
        "source": source,
        "chart": chart,
        "observer": observed["plots"][-2:],
        "complete": complete,
        "no_on_fill": altered,
    }
    (ROOT / "synthetic-observed.json").write_text(
        json.dumps(emit, indent=2), encoding="utf8"
    )


if __name__ == "__main__":
    controls()
