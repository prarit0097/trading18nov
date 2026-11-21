import json
import sys
import traceback
from hashlib import sha256
from importlib import import_module
from pathlib import Path

w = Path(__file__).parent
sys.path.insert(0, str(w / "priced-runtime"))
pine = import_module("pine_compat")
feeds = json.loads((w / "round47-3697-feeds.json").read_bytes())["chart"]
src = (w / "round47-3697.pine").read_text(encoding="utf8")
runs = []
plots = {
    "Flip": "flip?1:0",
    "Coin": "coinLabel",
    "Wait": "barsBetweenflips",
    "Long": "long?1:0",
    "Short": "short?1:0",
    "Stopped": "stoppedOut?1:0",
    "Take": "takeProfit?1:0",
    "InTrade": "posLive?1:0",
    "Target": "p1",
    "Basis": "p2",
    "Stop": "p3",
    "BoxPos": "posType",
    "Position": "strategy.position_size",
    "Equity": "strategy.equity",
}
for trial in range(1, 33):
    code = src
    for site, (a, b) in enumerate(((1, 255), (1, 10), (3, "round(maxBars)"))):
        loc = f"random({a},{b})"
        assert code.count(loc) == 1, loc
        code = code.replace(loc, f"random({a},{b},{trial * 65537 + site * 8191})")
    code += "".join(f'\nplot({value},"{name}")' for name, value in plots.items())
    for t, m in feeds.items():
        for coin, tape in m.items():
            try:
                opts = {
                    "$chart": {
                        "minMove": 1,
                        "priceScale": 10 if coin == "BTC" else 100,
                        "pointValue": 1,
                        "currency": "USDT",
                        "quantityStep": "0.001",
                        "minContract": "0.001",
                    }
                }
                keys = ("time", "open", "high", "low", "close", "volume")
                r = pine.run_script(
                    code,
                    [dict(zip(keys, b, strict=True)) for b in tape],
                    chart_symbol="BINANCE:" + coin + "USDT",
                    chart_timeframe="1D",
                    request_bars=opts,
                )
                runs.append(
                    [
                        trial,
                        t,
                        coin,
                        r["diagnostics"],
                        r["strategy"],
                        {
                            p["title"]: p["values"]
                            for p in r["plots"]
                            if p.get("title") in plots
                        },
                        sha256(code.encode()).hexdigest(),
                    ]
                )
            except (TypeError, ValueError, RuntimeError):
                runs.append([trial, t, coin, traceback.format_exc(), None])
(w / "round47-3697-probe.json").write_text(
    json.dumps(runs, separators=(",", ":")), encoding="utf8"
)
