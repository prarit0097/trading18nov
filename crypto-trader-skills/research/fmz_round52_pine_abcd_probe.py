"""Run archived ABCD broker traces with and without the unused timestamp assignment."""

import json
import re
import sys
from hashlib import sha256
from importlib import import_module
from pathlib import Path

w = Path(__file__).parent
sys.path.insert(0, str(w / "priced-runtime"))
pine = import_module("pine_compat")
data = json.loads((w / "round47-2575-feeds.json").read_bytes())["data"]
source = (w / "round47-2575.pine").read_text(encoding="utf-8")
code, count = re.subn(r"(?m)^// @version=4$", "//@version=4", source)
assert count == 1
assert len(re.findall(r"\blapos_x\b", code)) == 1
displays = '\nplot(isLong?1:0,"Long gate")\nplot(isShort?1:0,"Short gate")\nplot(close_long?1:0,"Long exit gate")\nplot(close_short?1:0,"Short exit gate")\nplot(strategy.equity,"Eq")\nplot(strategy.position_size,"Pos")'
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
        for label, body in [
            ("literal-clock", code),
            (
                "dead-clock-removed",
                re.sub(
                    r"(?m)^lapos_x = timenow \+ round\(change\(time\)\*12\)\n", "", code
                ),
            ),
        ]:
            keys = ("time", "open", "high", "low", "close", "volume")
            z = pine.run_script(
                body + displays,
                [dict(zip(keys, b, strict=True)) for b in bars],
                chart_symbol=sym,
                chart_timeframe="60",
                request_bars=opt,
                execution_times=[b[0] + 3599999 for b in bars],
            )
            rec.append(
                [
                    tag,
                    coin,
                    label,
                    z["diagnostics"],
                    z["strategy"],
                    {p["title"]: p["values"] for p in z["plots"]},
                    sha256((body + displays).encode()).hexdigest(),
                ]
            )

(w / "round47-2575-probe.json").write_text(
    json.dumps(rec, separators=(",", ":")), encoding="utf-8"
)
