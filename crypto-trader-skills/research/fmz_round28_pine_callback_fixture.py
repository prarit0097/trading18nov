import json
import re
import sys
import traceback
from importlib import import_module
from pathlib import Path

w = Path(__file__).parent
sys.path.insert(0, str(w / "priced-runtime"))
pine_compat = import_module("pine_compat")
source = re.sub(
    r"(?ms)^/\*backtest\n.*?^\*/\n*",
    "",
    (w / "round28-bb-source.pine").read_text(encoding="utf8"),
)
plots = {
    "New close": "newClose",
    "ATR": "atr",
    "Long stop": "longStop",
    "Short stop": "shortStop",
    "Direction": "dir",
    "Year high": "yearlyHighCondition?1:0",
    "Year low": "yearlyLowCondition?1:0",
    "Buy": "buyCondition?1:0",
    "Sell": "sellCondition?1:0",
    "Position": "strategy.position_size",
}
code = source + "\n".join(f'\nplot({v}, "{k}")' for k, v in plots.items())
cases = json.loads((w / "round28-bb-feeds.json").read_bytes())
years = json.loads((w / "round28-bb-years.json").read_bytes())
result = []
fixture = {
    ("native", "BTCUSDT"): 133,
    ("native", "ETHUSDT"): 153,
    ("next", "BTCUSDT"): 162,
    ("next", "ETHUSDT"): 181,
}
try:
    for period, markets in cases.items():
        for m, chart in markets.items():
            candles = [
                dict(
                    zip(
                        ("time", "open", "high", "low", "close", "volume"),
                        r,
                        strict=True,
                    )
                )
                for r in chart
            ]
            symbol = f"BINANCE:{m}"
            annual = [
                dict(
                    zip(
                        ("time", "open", "high", "low", "close", "volume"),
                        a,
                        strict=True,
                    )
                )
                for a in years[m]
            ]
            market = {
                "minMove": 1,
                "priceScale": 10 if m == "BTCUSDT" else 100,
                "pointValue": 1,
                "quantityStep": "0.001",
                "minContract": "0.001",
                "currency": "USDT",
            }
            chosen = fixture[(period, m)]
            prefix = candles[: chosen + 1]
            anchor = prefix[-1]
            flat = {k: anchor["open"] for k in ("high", "low", "close")}
            flat["volume"] = 0.0
            for label, feed in (
                ("full candle", prefix),
                ("opening snapshot", prefix[:-1] + [anchor | flat]),
            ):
                r = pine_compat.run_script(
                    code,
                    feed,
                    chart_symbol=symbol,
                    chart_timeframe="1D",
                    request_bars={"$chart": market, symbol + ":12M": annual},
                )
                result.append(
                    {
                        "period": period,
                        "market": m,
                        "mode": label,
                        "bar": chosen,
                        "diagnostics": r["diagnostics"],
                        "strategy": r["strategy"],
                        "observations": {
                            p["title"]: p["values"]
                            for p in r["plots"]
                            if p.get("title") in plots
                        },
                    }
                )
except Exception:
    (w / "round28-bb-error.txt").write_text(traceback.format_exc(), encoding="utf8")
    raise
(w / "round28-bb-snapshot-results.json").write_text(
    json.dumps(result, separators=(",", ":")), encoding="utf8", newline="\n"
)
