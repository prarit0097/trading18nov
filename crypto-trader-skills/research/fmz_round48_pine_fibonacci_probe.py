"""Replay literal, adapted EMA and documented comparison precision in Pine Compat."""

import json
import re
import sys
import traceback
from hashlib import sha256
from pathlib import Path

w = Path(__file__).parent
sys.path.insert(0, str(w / "priced-runtime"))
from importlib import import_module

pine = import_module("pine_compat")
feeds, rates = json.loads((w / "round47-probe-feeds.json").read_bytes())
source = (w / "round47-5230.pine").read_text(encoding="utf8")
rows = []
plot_defs = {
    **{
        x + y: f"{x}Band_{y}_Alert?1:0"
        for x in ("Strong", "Middle", "Sideways")
        for y in ("Buy", "Sell")
    },
    "Long low stop": "longSlLow",
    "Short high stop": "shortSlLow",
    "Long tp": "longTP1",
    "Short tp": "shortTP",
    "AggPos": "strategy.position_size",
    "AggBasis": "strategy.position_avg_price",
    "MarkedEquity": "strategy.equity",
}
lib = """
parity_ema(value, period) =>
    alpha = 2.0 / (period + 1)
    result = float(na)
    result := na(value) ? result[1] : na(result[1]) ? value : alpha * value + (1.0 - alpha) * result[1]
    result
"""
mode = sys.argv[1]
assert mode in ("sensitivity", "rounded")
for native in (True, False) if mode == "sensitivity" else (False,):
    for coin, bars in feeds.items():
        for period, candles in [("native", bars[:10080]), ("next", bars[10080:])]:
            try:
                src = source
                if not native:
                    src = re.sub(
                        r"(?m)(^strategy\([^\n]*\n)", r"\1" + lib, src, count=1
                    ).replace("ta.ema(", "parity_ema(")
                if mode == "rounded":
                    src, n = re.subn(
                        r"ta\.change\(((Strong|Middle|Sideways)Band_(Bull|Bear)_EMA)\)",
                        r"math.round(ta.change(\1),9)",
                        src,
                    )
                    assert n == 18, n
                src += "".join(
                    f'\nplot({expr}, "{title}")' for title, expr in plot_defs.items()
                )
                ticker = "BINANCE:" + coin + "USDT"
                keys = ("time", "open", "high", "low", "close", "volume")
                prop = {
                    "$chart": {
                        "minMove": 1,
                        "priceScale": 10 if coin == "BTC" else 100,
                        "pointValue": 1,
                        "currency": "USDT",
                        "minContract": "0.001",
                        "quantityStep": "0.001",
                    }
                }
                prop["$currencyRates"] = {
                    "schemaVersion": 1,
                    "pairs": [{"from": "USDT", "to": "USD", "rates": sorted(rates)}],
                }
                p = pine.run_script(
                    src,
                    [dict(zip(keys, b)) for b in candles],
                    chart_symbol=ticker,
                    chart_timeframe="1",
                    request_bars=prop,
                )
                rows.append(
                    [
                        native,
                        coin,
                        period,
                        p["diagnostics"],
                        p.get("strategy"),
                        {x["title"]: x["values"] for x in p["plots"]},
                        sha256(src.encode()).hexdigest(),
                    ]
                )
            except (AssertionError, RuntimeError, ValueError, TypeError):
                rows.append([native, coin, period, traceback.format_exc(), None])
(
    w
    / (
        "round47-5230-probe.json"
        if mode == "sensitivity"
        else "round47-5230-rounded.json"
    )
).write_text(json.dumps(rows, default=str, separators=(",", ":")), encoding="utf8")
