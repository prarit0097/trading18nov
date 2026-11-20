import json
import re
import sys
import traceback
from hashlib import sha256
from importlib import import_module
from itertools import batched
from pathlib import Path

root = Path(__file__).parent
sys.path.insert(0, str(root / "priced-runtime"))
pine = import_module("pine_compat")
try:
    source = (root / "r34-koala-source.pine").read_text(encoding="utf8")
    source = re.sub(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", source)
    assert source.count("strategy.initial_capital = 50000") == 1
    source = source.replace("strategy.initial_capital = 50000", "")
    if "firstseed" in sys.argv[1:]:
        mark = "out5 = ema(src5, len5)"
        assert source.count(mark) == 1
        source = source.replace(
            mark,
            "out5 = 0.0\nemaK = 2.0 / (len5+1)\nout5 := na(out5[1]) ? src5 : emaK*src5+(1-emaK)*out5[1]",
        )
    use_mag = "magnified" in sys.argv[1:]
    decl = "slippage=3)"
    assert source.count(decl) == 1
    if use_mag:
        source = (root / "r34-koala-v5.pine").read_text(encoding="utf8")
    watch = {
        "Session": "london?1:0",
        "Entry hours": "londonEntry?1:0",
        "SMMA 3": "smma",
        "SMMA 6": "smma2",
        "SMMA 9": "smma3",
        "SMMA 50": "smma4",
        "EMA 200": "out5",
        "Long gate": "longCond?1:0",
        "Short gate": "shortCond?1:0",
        "Position": "strategy.position_size",
    }
    source += "".join(f'\nplot({v}, "{k}")' for k, v in watch.items())
    data = json.loads((root / "r34-koala-feeds.json").read_bytes())
    fields = ("time", "open", "high", "low", "close", "volume")

    def as_objects(rows):
        return [dict(zip(fields, row, strict=True)) for row in rows]

    cases = []
    for period, markets in data.items():
        for market, tape in markets.items():
            if "BTCUSDT" in sys.argv[1:] and market != "BTCUSDT":
                continue
            if "ETHUSDT" in sys.argv[1:] and market != "ETHUSDT":
                continue
            scale = 10 if market == "BTCUSDT" else 100
            sym = f"BINANCE:{market}"
            candles = as_objects(tape["chart"])
            chart_context = {
                "minMove": 1,
                "priceScale": scale,
                "pointValue": 1,
                "currency": "USDT",
                "minContract": "0.001",
                "quantityStep": "0.001",
            }
            many = None
            if use_mag:
                groups = []
                for i, rows in enumerate(batched(tape["base"], 60, strict=True)):
                    if (
                        rows[0][0] in (1699628400000, 1699632000000)
                        and market == "BTCUSDT"
                    ):
                        continue
                    groups.append({"chartBarIndex": i, "bars": as_objects(rows)})
                many = {"schemaVersion": 1, "chartBars": groups}
            o = pine.run_script(
                source,
                candles,
                chart_symbol=sym,
                chart_timeframe="60",
                request_bars={"$chart": chart_context},
                magnifier_bars=many,
            )
            cases.append(
                {
                    "period": period,
                    "market": market,
                    "diagnostics": o["diagnostics"],
                    "strategy": o["strategy"],
                    "executed_source_sha256": sha256(source.encode()).hexdigest(),
                    "witnesses": {
                        p["title"]: p["values"]
                        for p in o["plots"]
                        if p.get("title") in watch
                    },
                }
            )
    tag = "-".join(sys.argv[1:]) or "base"
    (root / f"r34-koala-{tag}-receipt.json").write_text(
        json.dumps(cases, separators=(",", ":")), encoding="utf8", newline="\n"
    )
except Exception:
    (root / "r34-koala-error.txt").write_text(traceback.format_exc(), encoding="utf8")
    raise
