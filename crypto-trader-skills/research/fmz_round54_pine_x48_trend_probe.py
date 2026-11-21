"""Run the archived X48 Trend variant and its disabled-exit guard control."""

import json
import re
import sys
from hashlib import sha256
from importlib import import_module
from pathlib import Path

w = Path(__file__).parent
sys.path.insert(0, str(w / "priced-runtime"))
pine = import_module("pine_compat")
data = json.loads((w / "round47-4310-feeds.json").read_bytes())["data"]
source = (w / "round47-4310.pine").read_text(encoding="utf8")
watch = {
    "LongGate": "longcondition?1:0",
    "ShortGate": "shortcondition?1:0",
    "K": "k",
    "D": "d",
    "SMA high": "high_line",
    "SMA low": "low_line",
    "Position": "strategy.position_size",
    "Equity": "strategy.equity",
}
source += "".join(f'\nplot({expr},"{name}")' for name, expr in watch.items())
guard, n = re.subn(
    r"(?m)^([ \t]+)(strategy\.exit\([^\n]*\bstop = stoploss[^\n]*)$",
    lambda m: (
        m[1]
        + (
            "if not na(stoploss) or not na(takeprofit)\n"
            if "profit = takeprofit" in m[2]
            else "if not na(stoploss)\n"
        )
        + m[1]
        + "    "
        + m[2]
    ),
    source,
)
assert n == 6, n
rec = []
for tag, for_feed in data.items():
    for coin, bars in for_feed.items():
        sym = "BINANCE:" + coin + "USDT"
        opt = {
            "$chart": {
                "minMove": 1,
                "priceScale": 10 if coin == "BTC" else 100,
                "pointValue": 1,
                "currency": "USDT",
                "quantityStep": "0.001",
                "minContract": "0.001",
            }
        }
        for label, body in [("literal-noop", source), ("guarded-noop", guard)]:
            keys = ("time", "open", "high", "low", "close", "volume")
            z = pine.run_script(
                body,
                [dict(zip(keys, b, strict=True)) for b in bars],
                chart_symbol=sym,
                chart_timeframe="60",
                request_bars=opt,
            )
            rec.append(
                [
                    tag,
                    coin,
                    label,
                    z["diagnostics"],
                    z["strategy"],
                    {
                        p["title"]: p["values"]
                        for p in z["plots"]
                        if p["title"] in watch
                    },
                    sha256(body.encode()).hexdigest(),
                ]
            )

(w / "round47-4310-probe.json").write_text(
    json.dumps(rec, separators=(",", ":")), encoding="utf-8"
)
