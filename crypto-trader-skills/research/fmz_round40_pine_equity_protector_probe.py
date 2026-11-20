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
    src = (w / "r40-eur-source.pine").read_text(encoding="utf8")
    src = re.sub(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", src)
    if mode != "literal":
        invalid = "strategy.initial_capital = 50000"
        assert src.count(invalid) == 1
        src = src.replace(invalid, "")
    if mode == "separate":
        src, n = re.subn(r"\bstrategy\.initial_capital\b", "50000.0", src)
        assert n == 1
    if mode == "capital":
        assert src.count("initial_capital = 1000)") == 1
        src = src.replace("initial_capital = 1000)", "initial_capital = 50000)")
    if mode == "firstseed":
        for kind, side in (("short", "under"), ("long", "over")):
            s = f"cross{side}(ema(src_ema, len_ema),sma(src_bb, length_bb))"
            assert src.count(s) == 1
            src = src.replace(s, f"cross{side}(out_ema, basis_bb)")
        line = "out_ema = ema(src_ema, len_ema)"
        assert src.count(line) == 1
        src = src.replace(
            line,
            "out_ema = 0.0\nemaAlpha = 2.0/(len_ema+1)\nout_ema := na(out_ema[1]) ? src_ema : emaAlpha*src_ema+(1.0-emaAlpha)*out_ema[1]",
        )
    watch = {
        "Long": "longCondition?1:0",
        "Short": "shortCondition?1:0",
        "Close all": "equity_stopout?1:0",
        "MA": "out_ema",
        "BB": "basis_bb",
        "RSI": "vrsi",
        "SAR trend": "uptrend?1:0",
        "SAR": "SAR",
        "Hist": "hist",
        "SL": "stop",
        "TP": "target",
        "Balance": "balance",
        "Position": "strategy.position_size",
    }
    src += "".join(f'\nplot({value},"{label}")' for label, value in watch.items())
    data = json.loads((w / "r40-eur-feeds.json").read_bytes())
    keys = ("time", "open", "high", "low", "close", "volume")
    out = []
    for period, assets in data.items():
        for market, tape in assets.items():
            candles = [dict(zip(keys, b, strict=True)) for b in tape["chart"]]
            props = {
                "minMove": 1,
                "priceScale": 10 if market == "BTCUSDT" else 100,
                "pointValue": 1,
                "currency": "USDT",
                "quantityStep": "0.001",
                "minContract": "0.001",
            }
            r = pine.run_script(
                src,
                candles,
                chart_symbol="BINANCE:" + market,
                chart_timeframe="10",
                request_bars={"$chart": props},
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
    (w / f"r40-eur-{mode}.json").write_text(
        json.dumps(out, separators=(",", ":")), encoding="utf8", newline="\n"
    )
except Exception:
    (w / f"r40-eur-{mode}-error.txt").write_text(
        traceback.format_exc(), encoding="utf8"
    )
    raise
