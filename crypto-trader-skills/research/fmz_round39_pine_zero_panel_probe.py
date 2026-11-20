import json
import re
import sys
import traceback
from hashlib import sha256
from importlib import import_module
from itertools import batched
from pathlib import Path

w = Path(__file__).parent
sys.path.insert(0, str(w / "priced-runtime"))
pine = import_module("pine_compat")
mode = sys.argv[1]
try:
    src = (w / "r39-panel-source.pine").read_text(encoding="utf8")
    src = re.sub(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", src)
    if mode != "literal":
        src = src.replace("//@version=4", "//@version=5")
        for name, replacement in (
            ("sma", "ta.sma"),
            ("round", "math.round"),
            ("change", "ta.change"),
            ("tostring", "str.tostring"),
        ):
            src = re.sub(rf"\b{name}(?=\()", replacement, src)
        src = src.replace("input(size.large,", "input.string(size.large,")
        assert src.count("pyramiding = 0)") == 1
        if mode in ("magnified", "bracket"):
            src = src.replace(
                "pyramiding = 0)", "pyramiding = 0, use_bar_magnifier=true)"
            )
        if mode == "bracket":
            line1 = '    strategy.entry("Take", strategy.short, 0, limit = avg + ((avg / 100) * tp))'
            line2 = '    strategy.entry("Stop", strategy.short, 0, stop = avg - ((avg / 100) * sl))'
            assert src.count(line1) == src.count(line2) == 1
            src = src.replace(
                line1,
                '    strategy.exit("Bracket", "Long", limit = avg + ((avg / 100) * tp), stop = avg - ((avg / 100) * sl))',
            ).replace(line2, "")
    watch = {
        "MA": "ma",
        "Entry ref": "long",
        "Avg": "avg",
        "Take ref": "take",
        "Stop ref": "stop",
        "Pos": "strategy.position_size",
        "Equity": "strategy.equity",
    }
    src += "".join(f'\nplot({v},"{k}")' for k, v in watch.items())
    data = json.loads((w / "r39-panel-feeds.json").read_bytes())
    keys = ("time", "open", "high", "low", "close", "volume")

    def rows(src):
        return [dict(zip(keys, b, strict=True)) for b in src]

    out = []
    for period, assets in data.items():
        for market, tape in assets.items():
            props = {
                "minMove": 1,
                "priceScale": 10 if market == "BTCUSDT" else 100,
                "pointValue": 1,
                "currency": "USDT",
                "quantityStep": "0.001",
                "minContract": "0.001",
            }
            many = None
            if mode in ("magnified", "bracket"):
                assert not tape["ambiguous"]
                many = {
                    "schemaVersion": 1,
                    "chartBars": [
                        {"chartBarIndex": i, "bars": rows(b)}
                        for i, b in enumerate(batched(tape["base"], 24, strict=True))
                    ],
                }
            r = pine.run_script(
                src,
                rows(tape["chart"]),
                chart_symbol="BINANCE:" + market,
                chart_timeframe="1D",
                request_bars={"$chart": props},
                magnifier_bars=many,
                execution_times=[1732147200000] * len(tape["chart"]),
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
    (w / f"r39-panel-{mode}.json").write_text(
        json.dumps(out, separators=(",", ":")), encoding="utf8", newline="\n"
    )
except Exception:
    (w / f"r39-panel-{mode}-error.txt").write_text(
        traceback.format_exc(), encoding="utf8"
    )
    raise
