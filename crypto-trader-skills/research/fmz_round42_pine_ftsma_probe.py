import json
import re
import sys
import traceback
from hashlib import sha256
from importlib import import_module
from pathlib import Path

w = Path(__file__).parent
sys.path.insert(0, str(w / "priced-runtime"))
pine = import_module("pine_compat")
mode = sys.argv[1]
try:
    src = (w / "r42-ftsma-source.pine").read_text(encoding="utf8")
    src = re.sub(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", src)
    if mode in ("ema", "first"):
        for which, n in (("SLOW", 1), ("MED", 2), ("FAST", 3)):
            pattern = rf"(?m)^{which}MA = plotSMA\?calc_ma\(close\+sx\(0,sin{n}\),(\w+)\):close\+sx\(0,sin{n}\)$"
            r = re.search(pattern, src)
            assert r
            period = r[1]
            if mode == "ema":
                text = f"{which}MA = ema(close+sx(0,sin{n}),{period})"
            else:
                text = f"{which}src = close+sx(0,sin{n})\n{which}a = 2.0/({period}+1)\n{which}MA = 0.0\n{which}MA := na({which}MA[1]) ? {which}src : {which}a*{which}src+(1-{which}a)*{which}MA[1]"
            src = src.replace(r[0], text)
    watch = {
        "Pi": "pi",
        "Slow MA": "SLOWMA",
        "Medium MA": "MEDMA",
        "Fast MA": "FASTMA",
        "Long": "longCondition?1:0",
        "Short": "shortCondition?1:0",
        "Position": "strategy.position_size",
    }
    src += "".join(f'\nplot({value},"{label}")' for label, value in watch.items())
    data = json.loads((w / "r42-ftsma-feeds.json").read_bytes())
    keys = ("time", "open", "high", "low", "close", "volume")
    out = []
    for period, assets in data.items():
        for market, tape in assets.items():
            prop = {
                "minMove": 1,
                "priceScale": 10 if market == "BTCUSDT" else 100,
                "pointValue": 1,
                "currency": "USDT",
                "minContract": "0.001",
                "quantityStep": "0.001",
            }
            opts = {
                "$chart": prop,
                "$currencyRates": {
                    "schemaVersion": 1,
                    "pairs": [{"from": "USDT", "to": "EUR", "rates": tape["rates"]}],
                },
            }
            r = pine.run_script(
                src,
                [dict(zip(keys, b, strict=True)) for b in tape["chart"]],
                chart_symbol="BINANCE:" + market,
                chart_timeframe="10",
                request_bars=opts,
            )
            out.append(
                {
                    "period": period,
                    "market": market,
                    "executed_source_sha256": sha256(src.encode()).hexdigest(),
                    "diagnostics": r["diagnostics"],
                    "strategy": r["strategy"],
                    "plots": {
                        p["title"]: p["values"]
                        for p in r["plots"]
                        if p.get("title") in watch
                    },
                }
            )
    (w / f"r42-ftsma-{mode}.json").write_text(
        json.dumps(out, separators=(",", ":")), encoding="utf8", newline="\n"
    )
except Exception:
    (w / f"r42-ftsma-{mode}-error.txt").write_text(
        traceback.format_exc(), encoding="utf8"
    )
    raise
