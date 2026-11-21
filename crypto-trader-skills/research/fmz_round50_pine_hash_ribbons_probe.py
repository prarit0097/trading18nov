"""Replay the archived Hash Ribbons against two named public provider inputs."""

import json
import sys
from hashlib import sha256
from importlib import import_module
from pathlib import Path

w = Path(__file__).parent
sys.path.insert(0, str(w / "priced-runtime"))
pine = import_module("pine_compat")
src = (w / "round47-4802.pine").read_text(encoding="utf8")
p = json.loads((w / "round47-4802-feeds.json").read_bytes())
results = []
stream_ids = {
    "Blockchain.com": "BLOCKCHAIN:BTC_HASHRATE",
    "Coin Metrics": "COINMETRICS:BTC_HASHRATE",
}
keys = ("time", "open", "high", "low", "close", "volume")
for p_name, series in p["series"]["values"].items():
    name = stream_ids[p_name]
    code = src.replace("INTOTHEBLOCK:BTC_HASHRATE", name)
    code += '\nplot(HashRate,"Raw")\nplot(LongCondition?1:0,"Long")\nplot(ShortCondition?1:0,"Short")'
    assert code.count(name) == 1
    for window, charts in p["chart"].items():
        for coin, bars in charts.items():
            t0 = bars[0][0]
            t1 = bars[-1][0]
            reference = [
                dict(zip(keys, [t, v, v, v, v, 1], strict=True))
                for t, v in series
                if t0 <= t <= t1
            ]
            options = {
                name + ":D": reference,
                "$chart": {
                    "minMove": 1,
                    "priceScale": 10 if coin == "BTC" else 100,
                    "pointValue": 1,
                    "currency": "USDT",
                    "quantityStep": "0.001",
                    "minContract": "0.001",
                },
            }
            r = pine.run_script(
                code,
                [dict(zip(keys, b, strict=True)) for b in bars],
                chart_symbol="BINANCE:" + coin + "USDT",
                chart_timeframe="1D",
                request_bars=options,
            )
            results.append(
                [
                    p_name,
                    coin,
                    window,
                    r["diagnostics"],
                    r["strategy"],
                    {z["title"]: z["values"] for z in r["plots"]},
                    sha256(code.encode()).hexdigest(),
                ]
            )
(w / "round47-4802-receipt.json").write_text(
    json.dumps(results, separators=(",", ":")), encoding="utf8"
)
