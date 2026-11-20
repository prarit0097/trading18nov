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
    raw = (w / "r43-mtf-source.pine").read_text(encoding="utf8")
    src = re.sub(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", raw)
    if mode != "literal":
        src = src.replace("request.security(", "security(").replace(
            "syminfo.tickerid", "tickerid"
        )
        src, n = re.subn(r"(?m)^plot\([^\n]+style=linestyle[^\n]*\n", "", src)
        assert n == 5
        src = src.replace("linestyle = line", "")
    if mode == "confirmed":
        for k in range(2, 5):
            for name in ("open", "close"):
                old = f"security(tickerid, TF_{k}_time, {name})"
                assert src.count(old) == 1
                src = src.replace(old, f"security(tickerid, TF_{k}_time, {name}[1])")
    watch = {
        **{f"TF {i}": f"TF_{i}?1:0" for i in range(1, 5)},
        "Long": "longCondition?1:0",
        "Short": "shortCondition?1:0",
        "Position": "strategy.position_size",
        "Keltner Hi": "kc_upper",
        "Keltner Lo": "kc_lower",
    }
    src += "".join(f'\nplot({value},"{label}")' for label, value in watch.items())
    packages = json.loads((w / "r43-mtf-feeds.json").read_bytes())
    keys = ("time", "open", "high", "low", "close", "volume")

    def items(rows):
        return [dict(zip(keys, r, strict=True)) for r in rows]

    out = []
    for period, assets in packages.items():
        for market, tape in assets.items():
            prop = {
                "minMove": 1,
                "priceScale": 10 if market == "BTCUSDT" else 100,
                "pointValue": 1,
                "currency": "USDT",
                "minContract": "0.001",
                "quantityStep": "0.001",
            }
            symbol = "BINANCE:" + market
            context = {
                symbol + ":" + ("D" if k == "1" else k + "D"): items(v)
                for k, v in tape["contexts"].items()
            }
            context["$chart"] = prop
            r = pine.run_script(
                src,
                items(tape["chart"]),
                chart_symbol=symbol,
                chart_timeframe="1D",
                request_bars=context,
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
    (w / f"r43-mtf-{mode}.json").write_text(
        json.dumps(out, separators=(",", ":")), encoding="utf8", newline="\n"
    )
except Exception:
    (w / f"r43-mtf-{mode}-error.txt").write_text(
        traceback.format_exc(), encoding="utf8"
    )
    raise
