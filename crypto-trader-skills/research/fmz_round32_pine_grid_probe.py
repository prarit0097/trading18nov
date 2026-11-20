import json
import re
import sys
import traceback
from importlib import import_module
from pathlib import Path

w = Path(__file__).parent
sys.path.insert(0, str(w / "priced-runtime"))
pine = import_module("pine_compat")
try:
    raw = (w / "r32-grid-source.pine").read_text(encoding="utf8")
    source = re.sub(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", raw)
    plots = {
        "Upper": "upperBound",
        "Lower": "lowerBound",
        "Position": "strategy.position_size",
        "Live grid": "strategy.opentrades",
        "Top guard": "array.get(gridLineArr, 29)",
        "First guard": "array.get(gridLineArr, 0)",
    }
    source += "".join(f'\nplot({exp},"{name}")' for name, exp in plots.items())
    data = json.loads((w / "r32-grid-feeds.json").read_bytes())
    out = []
    columns = ("time", "open", "high", "low", "close", "volume")
    for label, markets in data.items():
        for market, rows in markets.items():
            symbol = f"BINANCE:{market}"
            chart = [dict(zip(columns, row, strict=True)) for row in rows]
            for precision in ("0.001", "0.000001"):
                instrument = {
                    "minMove": 1,
                    "priceScale": 10 if market == "BTCUSDT" else 100,
                    "pointValue": 1,
                    "quantityStep": precision,
                    "minContract": precision,
                    "currency": "USD",
                }
                result = pine.run_script(
                    source,
                    chart,
                    chart_symbol=symbol,
                    chart_timeframe="120",
                    request_bars={"$chart": instrument},
                    execution_times=[r[0] + 7199999 for r in rows],
                )
                out.append(
                    {
                        "period": label,
                        "market": market,
                        "quantity_grid": precision,
                        "diagnostics": result["diagnostics"],
                        "strategy": result["strategy"],
                        "observations": {
                            p["title"]: p["values"]
                            for p in result["plots"]
                            if p.get("title") in plots
                        },
                    }
                )
except Exception:
    (w / "r32-grid-error.txt").write_text(traceback.format_exc(), encoding="utf8")
    raise
(w / "r32-grid-results.json").write_text(
    json.dumps(out, separators=(",", ":")), encoding="utf8", newline="\n"
)
