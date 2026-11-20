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
    src = (w / "r37-andy-source.pine").read_text(encoding="utf8")
    src = re.sub(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", src)
    if mode == "display-off":
        witness = "show_performance = input.bool(true,"
        assert src.count(witness) == 1
        src = src.replace(witness, "show_performance = input.bool(false,")
    elif mode != "literal":
        head, tail = src.split(
            "// MONTHLY TABLE PERFORMANCE - Developed by @QuantNomad", 1
        )
        assert "strategy.entry" not in tail and "strategy.close" not in tail
        src = head
    if mode in ("first", "magnified"):
        for label, n in (("short", 5), ("middle", 20), ("long", 40)):
            name = f"ema_{label}"
            old = f"{name} = ta.ema(close,{n})"
            assert src.count(old) == 1
            src = src.replace(
                old,
                f"{name} = 0.0\n{name} := na({name}[1]) ? close : (2.0/{n + 1})*close + (1-2.0/{n + 1})*{name}[1]",
            )
    if mode == "magnified":
        assert src.count("default_qty_value = 10000)") == 1
        src = src.replace(
            "default_qty_value = 10000)",
            "default_qty_value = 10000, use_bar_magnifier=true)",
        )
    watch = {
        "Slow EMA": "ema_long",
        "Medium EMA": "ema_middle",
        "Fast EMA": "ema_short",
        "ATR stop": "xATRTrailingStop",
        "ATR RSI": "atr_rsi",
        "Long": "long_condition?1:0",
        "Short": "short_condition?1:0",
        "Position": "strategy.position_size",
    }
    src += "".join(f'\nplot({value},"{label}")' for label, value in watch.items())
    keys = ("time", "open", "high", "low", "close", "volume")

    def candles(rows):
        return [dict(zip(keys, r, strict=True)) for r in rows]

    data = json.loads((w / "r37-andy-feeds.json").read_bytes())
    out = []
    for period, assets in data.items():
        for market, tape in assets.items():
            chart = candles(tape["chart"])
            symbol = "BINANCE:" + market
            props = {
                "minMove": 1,
                "priceScale": 10 if market == "BTCUSDT" else 100,
                "pointValue": 1,
                "currency": "USDT",
                "minContract": "0.001",
                "quantityStep": "0.001",
            }
            magnifier = None
            if mode == "magnified":
                groups = []
                for i, rows in enumerate(batched(tape["base"], 4, strict=True)):
                    if market == "BTCUSDT" and rows[0][0] in (
                        1699628400000,
                        1699632000000,
                    ):
                        continue
                    groups.append({"chartBarIndex": i, "bars": candles(rows)})
                magnifier = {"schemaVersion": 1, "chartBars": groups}
            result = pine.run_script(
                src,
                chart,
                chart_symbol=symbol,
                chart_timeframe="60",
                request_bars={"$chart": props},
                magnifier_bars=magnifier,
            )
            out.append(
                {
                    "executed_source_sha256": sha256(src.encode()).hexdigest(),
                    "period": period,
                    "market": market,
                    "diagnostics": result["diagnostics"],
                    "strategy": result["strategy"],
                    "plots": {
                        p["title"]: p["values"]
                        for p in result["plots"]
                        if p.get("title") in watch
                    },
                }
            )
    (w / f"r37-andy-{mode}.json").write_text(
        json.dumps(out, separators=(",", ":")), encoding="utf8", newline="\n"
    )
except Exception:
    (w / f"r37-andy-{mode}-error.txt").write_text(
        traceback.format_exc(), encoding="utf8"
    )
    raise
