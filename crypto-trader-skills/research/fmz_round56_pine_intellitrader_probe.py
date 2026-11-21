"""Offline #4098 exact parser and order-gate language controls."""

import json
import sys
from importlib import import_module
from math import sin
from pathlib import Path

w = Path(__file__).parent
sys.path.insert(0, str(w / "priced-runtime"))
p = import_module("pine_compat")
r = (w / "r48-4098.pine").read_text(encoding="utf8")
out = {}
t = 1673395200000
D = 86_400_000
chart = [
    {
        "time": t + i * D,
        "open": 100 + sin(i) * 5,
        "high": 110 + sin(i) * 5,
        "low": 97 + sin(i) * 5,
        "close": 104 + sin(i) * 5,
        "volume": 80,
    }
    for i in range(45)
]
data = {
    "$chart": {
        "minMove": 1,
        "priceScale": 10,
        "pointValue": 1,
        "quantityStep": "0.001",
        "minContract": "0.001",
        "currency": "USDT",
    }
}
for n in ("1", "5", "15", "60", "240", "1440", "D"):
    m = (1440 if n == "D" else int(n)) * 60_000
    data["BINANCE:BTCUSDT:" + n] = [dict(k, time=k["time"] + D - m) for k in chart]
local = """//@version=3
strategy("lexical")
rsi7_Use_1d = input(false)
rsi7_1d_logic = true
if rsi7_Use_1d
    rsi7_1d_logic = false
bool_1d = false
bool_1d := rsi7_1d_logic
if not rsi7_Use_1d
    bool_1d = false
buy = bool_1d
plot(buy?1:0,"Buy")
tradeState = 0
tradeState := nz(tradeState[1])
tradeState := tradeState==0 ? buy==1 and (barstate.isconfirmed or barstate.ishistory) ? 1 : tradeState : tradeState
plot(tradeState,"State")
if tradeState==1
    strategy.entry("Long", strategy.long)
"""
run = {
    "archive": r,
    "legacy-security-name-only": r.replace("request.security", "security"),
    "lex-v3-exact-comparison": local,
    "lex-v5-exact-comparison": local.replace("version=3", "version=5"),
    "lex-v3-explicit-boolean": local.replace("buy==1", "buy"),
    "lex-v5-explicit-boolean": local.replace("version=3", "version=5").replace(
        "buy==1", "buy"
    ),
    "lex-v3-explicit-boolean-with-reassigned-reset": local.replace(
        "buy==1", "buy"
    ).replace("    bool_1d = false", "    bool_1d := false"),
}
for name, src in run.items():
    try:
        s = p.run_script(
            src,
            chart,
            chart_symbol="BINANCE:BTCUSDT",
            chart_timeframe="D",
            request_bars=data,
        )
        plots = {
            x["title"]: x["values"]
            for x in s["plots"]
            if x.get("title") in ("Buy", "State")
        }
        out[name] = {
            "diagnostics": s["diagnostics"],
            "broker_diagnostics": s["strategy"]["diagnostics"],
            "orders": s["strategy"]["orders"],
            "plots": plots,
        }
    except (ValueError, RuntimeError, TypeError) as e:
        out[name] = {"diagnostics": str(e).splitlines()}
(w / "r48-4098-typed.json").write_text(
    json.dumps(out, separators=(",", ":")), encoding="utf8"
)
