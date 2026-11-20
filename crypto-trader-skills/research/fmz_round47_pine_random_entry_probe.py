"""Replay archived Random Entry and Exit on the isolated Pine v4 runtime."""

import json
import sys
from hashlib import sha256
from importlib import import_module
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "priced-runtime"))
pine = import_module("pine_compat")
FIELDS = ("time", "open", "high", "low", "close", "volume")


def scenario(source, trial):
    assert source.count('defval="Long Only"') == 1
    assert source.count("random(0,100)") == 2
    code = source.replace('defval="Long Only"', 'defval="Random"')
    for seed in (trial * 65537, trial * 65537 + 8191):
        code = code.replace("random(0,100)", f"random(0,100,{seed})", 1)
    return (
        code
        + '\nplot(r, "R")\nplot(direction ? 1 : 0, "Direction")\nplot(strategy.position_size, "Pos")\nplot(strategy.equity, "Equity")'
    )


def replay():
    data = json.loads((HERE / "round47-5629-feeds.json").read_bytes())
    source = (HERE / "round47-5629.pine").read_text(encoding="utf-8")
    results = []
    for window, markets in data["tapes"].items():
        for market, bars in markets.items():
            chart = [dict(zip(FIELDS, bar, strict=True)) for bar in bars]
            options = {
                "$chart": {
                    "minMove": 1,
                    "priceScale": 10 if market == "BTCUSDT" else 100,
                    "pointValue": 1,
                    "currency": "USDT",
                    "minContract": "0.001",
                    "quantityStep": "0.001",
                },
                "$currencyRates": {
                    "schemaVersion": 1,
                    "pairs": [{"from": "USDT", "to": "USD", "rates": data["rates"]}],
                },
            }
            for trial in range(1, 33):
                code = scenario(source, trial)
                result = pine.run_script(
                    code,
                    chart,
                    chart_symbol="BINANCE:" + market,
                    chart_timeframe="1D",
                    request_bars=options,
                )
                broker = result["strategy"]
                assert not result["diagnostics"] and not broker["diagnostics"]
                results.append(
                    {
                        "window": window,
                        "market": market,
                        "trial": trial,
                        "sha256": sha256(code.encode()).hexdigest(),
                        "orders": broker["orders"],
                        "trades": broker["trades"],
                        "equity": broker["equity"],
                        "plot": {p["title"]: p["values"] for p in result["plots"]},
                    }
                )
    (HERE / "round47-5629-verified.json").write_text(
        json.dumps(results, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    try:
        replay()
    except Exception:
        import traceback

        (HERE / "round47-5629-probe-error.txt").write_text(
            traceback.format_exc(), encoding="utf-8"
        )
        raise
