import json
import re
import sys
import traceback
from importlib import import_module
from pathlib import Path

w = Path(__file__).parent
sys.path.insert(0, str(w / "priced-runtime"))
pine_compat = import_module("pine_compat")
id = str(sys.argv[1])
try:
    raw = (w / f"round31-iir-{id}-source.pine").read_text(encoding="utf8")
    code = re.sub(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", raw)
    labels = {
        "IIR": "iirmaOTF",
        "IIR small": "iirma2OTF",
        "ALMA": "smaOTF",
        "Signal long": "(crossoverFast and iirma2Up == true"
        + (
            " and infastsqueeze == false and intightsqueeze == false"
            if id == "4545"
            else ""
        )
        + ")?1:0",
        "Signal exit": "crossunderFast?1:0",
        "Position": "strategy.position_size",
    }
    code += "".join(f'\nplot({exp},"{name}")' for name, exp in labels.items())
    # Keep the source declaration and add the project comparison commission.
    linked = "linktoseries = true)"
    if id == "5166":
        assert code.count(linked) == 1
        code = code.replace(
            linked,
            "linktoseries = true, commission_type=strategy.commission.percent, commission_value=0.059)",
        )
    else:
        assert code.count("overlay = true )") == 1
        code = code.replace(
            "overlay = true )",
            "overlay = true, initial_capital=1000000, commission_type=strategy.commission.percent, commission_value=0.059)",
        )
    if id == "4545":
        # The longest 32,640-bar SMA is unavailable on every 25,920-bar window.
        for ix in range(1, 4):
            marker = f"ma{ix} = sma(close, multiplier(maRes, mal{ix}))"
            assert code.count(marker) == 1
            code = code.replace(marker, f"float ma{ix} = na")
    f = json.loads((w / f"round31-iir-{id}-feeds.json").read_bytes())
    tape = []
    for period, markets in f.items():
        for market, rows in markets.items():
            if sys.argv[2:] and market not in sys.argv[2:]:
                continue
            chart = [
                dict(
                    zip(
                        ("time", "open", "high", "low", "close", "volume"),
                        bar,
                        strict=True,
                    )
                )
                for bar in rows
            ]
            price_context = {
                "minMove": 1,
                "priceScale": 10 if market == "BTCUSDT" else 100,
                "pointValue": 1,
                "quantityStep": "0.001",
                "minContract": "0.001",
                "currency": "USD" if id == "5166" else "USDT",
            }
            d = pine_compat.run_script(
                code,
                chart,
                chart_symbol=f"BINANCE:{market}",
                chart_timeframe="1" if id == "4545" else "5",
                request_bars={"$chart": price_context},
                execution_times=[
                    b["time"] + (60_000 if id == "4545" else 300_000) - 1 for b in chart
                ],
            )
            tape.append(
                {
                    "period": period,
                    "market": market,
                    "diagnostics": d["diagnostics"],
                    "orders": d["strategy"]["orders"],
                    "trades": d["strategy"]["trades"],
                    "broker_diagnostics": d["strategy"]["diagnostics"],
                    "observations": {
                        p["title"]: p["values"]
                        for p in d["plots"]
                        if p.get("title") in labels
                    },
                }
            )
    (
        w / f"round31-iir-{id}-full-{sys.argv[2] if len(sys.argv) > 2 else 'all'}.json"
    ).write_text(json.dumps(tape, separators=(",", ":")), encoding="utf8", newline="\n")
except Exception:
    (w / f"round31-iir-{id}-error.txt").write_text(
        traceback.format_exc(), encoding="utf8"
    )
    raise
