import json
import re
import sys
import traceback
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

w = Path(__file__).parent
sys.path.insert(0, str(w / "priced-runtime"))
pine_compat = import_module("pine_compat")
try:
    raw = (w / "round31-masu-source.pine").read_text(encoding="utf8")
    code = re.sub(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", raw)
    code += "\n[yHigh,yLow]=[0.0,0.0]\n" if False else ""
    labels = {
        "Smooth close": "oClose",
        "Smooth high": "oHigh",
        "Smooth low": "oLow",
        "Direction": "dir",
        "Lower": "longStop",
        "Upper": "shortStop",
        "Yearly high gate": "yearlyHighCondition?1:0",
        "Yearly low gate": "yearlyLowCondition?1:0",
        "Long gate": "longCondition?1:0",
        "Short gate": "shortCondition?1:0",
        "Position": "strategy.position_size",
    }
    code += "".join(f'\nplot({exp},"{name}")' for name, exp in labels.items())
    data = json.loads((w / "round31-masu-feeds.json").read_bytes())
    years = json.loads((w / "round28-bb-years.json").read_bytes())
    tape = []
    for period, markets in data.items():
        for m, rows in markets.items():
            names = ("time", "open", "high", "low", "close", "volume")
            chart = [dict(zip(names, bar, strict=True)) for bar in rows]
            symbol = f"BINANCE:{m}"
            annual = [
                dict(zip(names, r, strict=True))
                for r in years[m]
                if datetime.fromtimestamp(r[0] / 1000, UTC).year <= 2023
            ]
            standard = {
                "minMove": 1,
                "priceScale": 10 if m == "BTCUSDT" else 100,
                "pointValue": 1,
                "quantityStep": "0.001",
                "minContract": "0.001",
                "currency": "USDT",
            }
            outcome = pine_compat.run_script(
                code,
                chart,
                chart_symbol=symbol,
                chart_timeframe="1D",
                request_bars={symbol + ":12M": annual, "$chart": standard},
            )
            tape.append(
                {
                    "period": period,
                    "market": m,
                    "orders": outcome["strategy"]["orders"],
                    "trades": outcome["strategy"]["trades"],
                    "equity": outcome["strategy"]["equity"],
                    "diagnostics": outcome["diagnostics"],
                    "broker_diagnostics": outcome["strategy"]["diagnostics"],
                    "observations": {
                        p["title"]: p["values"]
                        for p in outcome["plots"]
                        if p.get("title") in labels
                    },
                }
            )
    (w / "round31-masu-receipt.json").write_text(
        json.dumps(tape, separators=(",", ":")), encoding="utf8", newline="\n"
    )
except Exception:
    (w / "round31-masu-error.txt").write_text(traceback.format_exc(), encoding="utf8")
    raise
