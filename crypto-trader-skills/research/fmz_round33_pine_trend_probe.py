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
try:
    code = (w / "r33-trend-source.pine").read_text(encoding="utf8")
    code = re.sub(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", code)
    old = "initial_capital=1000, pyramiding=0)"
    assert code.count(old) == 1
    code = code.replace(
        old,
        "initial_capital=1000, pyramiding=0, commission_type=strategy.commission.percent, commission_value=0.059)",
    )
    variant = "exact" if not sys.argv[1:] else "ema shim"
    if variant == "ema shim":
        mark = "ema = ta.ema(close, len)"
        assert code.count(mark) == 1
        # First-price source EMA, replacing the reference runner's SMA seed.
        code = code.replace(
            mark,
            "ema = 0.0\nalpha = 2.0 / (len+1)\nema := na(ema[1]) ? close : close*alpha + (1-alpha)*ema[1]",
        )
        delegated = "emaSmooth = request.security(syminfo.tickerid, HTF_TimeFrame, ema[barstate.isrealtime ? 1 : 0], gaps=barmerge.gaps_on)[barstate.isrealtime ? 0 : 1]"
        assert code.count(delegated) == 1
        code = code.replace(delegated, "emaSmooth = ema[1]")
    plots = {
        "EMA previous": "emaSmooth",
        "HTF trend": "HTF_trend",
        "LTF trend": "trend",
        "HTF upper": "HTF_up",
        "HTF lower": "HTF_dn",
        "Cloud A": "SSA",
        "Cloud B": "SSB",
        "Long gate": "longCondition?1:0",
        "Short gate": "shortCondition?1:0",
        "Exit long": "exitLong?1:0",
        "Exit short": "exitShort?1:0",
        "Position": "strategy.position_size",
    }
    code += "".join(f'\nplot({exp},"{name}")' for name, exp in plots.items())
    out = []
    cols = ("time", "open", "high", "low", "close", "volume")
    for p, markets in json.loads((w / "r33-trend-feeds.json").read_bytes()).items():
        for market, rows in markets.items():
            sym = f"BINANCE:{market}"
            chart = [dict(zip(cols, row, strict=True)) for row in rows]
            context = {
                "minMove": 1,
                "priceScale": 10 if market == "BTCUSDT" else 100,
                "pointValue": 1,
                "quantityStep": "0.001",
                "minContract": "0.001",
                "currency": "USDT",
            }
            result = pine.run_script(
                code,
                chart,
                chart_symbol=sym,
                chart_timeframe="60",
                request_bars={"$chart": context, sym + ":60": chart},
            )
            out.append(
                {
                    "period": p,
                    "market": market,
                    "executed_source_sha256": sha256(code.encode()).hexdigest(),
                    "source_diagnostics": result["diagnostics"],
                    "strategy": result["strategy"],
                    "observations": {
                        o["title"]: o["values"]
                        for o in result["plots"]
                        if o.get("title") in plots
                    },
                }
            )
    (w / f"r33-trend-{variant}-receipt.json").write_text(
        json.dumps(out, separators=(",", ":")), encoding="utf8", newline="\n"
    )
except Exception:
    (w / "r33-trend-error.txt").write_text(traceback.format_exc(), encoding="utf8")
    raise
