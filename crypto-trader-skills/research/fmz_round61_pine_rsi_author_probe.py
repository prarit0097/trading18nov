import json
import sys
from hashlib import sha256
from pathlib import Path

w = Path(__file__).parent
sys.path.insert(0, str(w))
from replay_1404 import OBS, engine_options, objects, pine_compat, scripts

_, v4, v5, base, explicit = scripts()
assert v4.count("buy==1") == v4.count("sell==1") == 1
exact = v4.replace("buy==1", "buy").replace("sell==1", "sell")
inputs = json.loads((w / "r51-1404-authored-inputs.json").read_bytes())
all_rows = {}
for coin, named in inputs.items():
    chart, minute = objects(named["chart"]), objects(named["minute"])
    opt = {**engine_options(coin + "USDT"), "chart_timeframe": "3"}
    opt["magnifier_bars"] = {
        "schemaVersion": 1,
        "chartBars": [
            {"chartBarIndex": index, "bars": minute[3 * index : 3 * index + 3]}
            for index in range(len(chart))
        ],
    }
    rows = {}
    for title, variant in [
        ("literal-v4", v4),
        ("boolean-v4", exact),
        ("boolean-v5-magnifier", explicit),
        ("literal-v5-magnifier", base),
    ]:
        settings = (
            opt
            if title.endswith("magnifier")
            else {k: v for k, v in opt.items() if k != "magnifier_bars"}
        )
        data = pine_compat.run_script(variant + OBS, chart, **settings)
        rows[title] = {
            "diagnostics": data["diagnostics"],
            "plots": [p["values"] for p in data["plots"][-7:]],
            "strategy": data["strategy"],
            "code_sha256": sha256((variant + OBS).encode()).hexdigest(),
        }
    all_rows[coin] = rows
(w / "r51-1404-authored-native.json").write_text(
    json.dumps(all_rows, separators=(",", ":")), encoding="utf8"
)
