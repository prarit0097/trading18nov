"""Run the isolated Pine Compat source and timestamp controls."""

import json
import sys
import traceback
from hashlib import sha256
from importlib import import_module
from pathlib import Path

w = Path(__file__).parent
sys.path.insert(0, str(w / "priced-runtime"))
pine = import_module("pine_compat")
code = (w / "r47-3664.pine").read_text(encoding="utf8")
all_data = json.loads((w / "r47-3664-exact-feeds.json").read_bytes())["data"]
keys = ("time", "open", "high", "low", "close", "volume")
plots = {
    "Buy": "buy_signal?1:0",
    "Volume gates": "Condition?1:0",
    "DAILY": "getVolume(syminfo.tickerid,0)",
    "39m": "getVolume2(syminfo.tickerid,0)",
    "F1": "firstCandleColor1",
    "F2": "firstCandleColor2",
    "F3": "firstCandleColor3",
    "ATR1": "atr1?1:0",
    "Difference": "prevCloseChange",
}
plots.update(
    {
        "ATR3": "atr_value3",
        "RSI": "rsi",
        "Original above SMA": "numCandles",
        "Oversold": "was_over_sold?1:0",
        "Original equity": "strategy.equity",
        "Original pos": "strategy.position_size",
    }
)
code += "".join(f'\nplot({v},"{k}")' for k, v in plots.items())
rows = []
for scope, markets in all_data.items():
    for coin, market in markets.items():
        symbol = "BINANCE:" + coin + "USDT"
        for variant in ("39-fmz-native", "39-fmz-causal", "39-binance-sensitivity"):
            tape = market["chart"]
            options = {
                "$chart": {
                    "minMove": 1,
                    "priceScale": 10 if coin == "BTC" else 100,
                    "pointValue": 1,
                    "currency": "USDT",
                    "quantityStep": "0.001",
                    "minContract": "0.001",
                }
            }
            for ref in ("1", "30", "39", "D", "W"):
                options[symbol + ":" + ref] = [
                    dict(zip(keys, b, strict=True))
                    for b in market[variant if ref == "39" else ref]
                ]
            try:
                r = pine.run_script(
                    code,
                    [dict(zip(keys, b, strict=True)) for b in tape],
                    chart_symbol=symbol,
                    chart_timeframe="60",
                    request_bars=options,
                )
                rows.append(
                    [
                        scope,
                        coin,
                        variant,
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
            except (ValueError, RuntimeError, TypeError):
                rows.append([scope, coin, variant, traceback.format_exc(), None])
(w / "r47-3664-final.json").write_text(
    json.dumps(rows, separators=(",", ":")), encoding="utf8"
)
