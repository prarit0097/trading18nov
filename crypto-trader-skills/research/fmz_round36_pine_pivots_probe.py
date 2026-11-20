import json
import re
import sys
import traceback
from datetime import UTC, datetime
from hashlib import sha256
from importlib import import_module
from pathlib import Path

w = Path(__file__).parent
sys.path.insert(0, str(w / "priced-runtime"))
pine = import_module("pine_compat")
try:
    raw = (w / "r36-pivots-source.pine").read_text(encoding="utf8")
    src = re.sub(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", raw)
    qty = ("time", "open", "high", "low", "close", "volume")

    def bars(r):
        return [dict(zip(qty, b, strict=True)) for b in r]

    plots = {
        "R1": "R1",
        "S2": "S2",
        "Date gate": "inDateRange?1:0",
        "Buy": "longCondition?1:0",
        "Sell": "shortCondition?1:0",
        "Position": "strategy.position_size",
    }
    src += "".join(f'\nplot({val},"{label}")' for label, val in plots.items())
    data = json.loads((w / "r36-pivots-feeds.json").read_bytes())
    outputs = []
    for period, markets in data.items():
        for market, tape in markets.items():
            symbol = f"BINANCE:{market}"
            chart = bars(tape["chart"])
            anchors = (
                ("2026-11-21",)
                if not sys.argv[1:]
                else ("2023-12-29", "2024-02-29", "2026-11-21")
            )
            ids = ("0",) if not sys.argv[1:] else ("0", "1", "2", "3")
            props = {
                "minMove": 1,
                "priceScale": 10 if market == "BTCUSDT" else 100,
                "pointValue": 1,
                "quantityStep": "0.001",
                "minContract": "0.001",
                "currency": "USDT",
            }
            for phase in ids:
                ref = bars(tape["contexts"][phase])
                for date in anchors:
                    stamp = int(
                        datetime.fromisoformat(date).replace(tzinfo=UTC).timestamp()
                        * 1000
                    )
                    one = pine.run_script(
                        src,
                        chart,
                        chart_symbol=symbol,
                        chart_timeframe="1D",
                        request_bars={symbol + ":4D": ref, "$chart": props},
                        execution_times=[stamp] * len(chart),
                    )
                    outputs.append(
                        {
                            "executed_source_sha256": sha256(src.encode()).hexdigest(),
                            "period": period,
                            "market": market,
                            "phase": phase,
                            "anchor": date,
                            "strategy": one["strategy"],
                            "diagnostics": one["diagnostics"],
                            "plots": {
                                p["title"]: p["values"]
                                for p in one["plots"]
                                if p.get("title") in plots
                            },
                        }
                    )
    (
        w / ("r36-pivots-full.json" if sys.argv[1:] else "r36-pivots-probe.json")
    ).write_text(
        json.dumps(outputs, separators=(",", ":")), encoding="utf8", newline="\n"
    )
except Exception:
    (w / "r36-pivots-error.txt").write_text(traceback.format_exc(), encoding="utf8")
    raise
