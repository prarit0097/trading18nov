import json
import re
import sys
from hashlib import sha256
from importlib import import_module
from pathlib import Path

w = Path(__file__).parent
sys.path.insert(0, str(w / "priced-runtime"))
pine = import_module("pine_compat")
outputs = []
for ident in (3190, 2828):
    raw = (w / f"r38-capital-{ident}-source.pine").read_text(encoding="utf8")
    src = re.sub(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", raw)
    illegal = "strategy.initial_capital = 50000"
    assert src.count(illegal) == 1
    if ident == 3190:
        plots = {
            "Cash order": "cashOrder",
            "Capital ref": "capital_ref",
            "ROC": "roc",
            "Equity": "strategy.equity",
            "Position": "strategy.position_size",
        }
    else:
        plots = {
            "Cash order": "cashOrder",
            "Capital ref": "capital_ref",
            "ATR": "atr",
            "Equity": "strategy.equity",
            "Position": "strategy.position_size",
        }
    src += "".join(f'\nplot({value},"{label}")' for label, value in plots.items())
    keys = ("time", "open", "high", "low", "close", "volume")
    data = json.loads((w / f"r38-capital-{ident}-feeds.json").read_bytes())
    for period, assets in data.items():
        for market, tape in assets.items():
            props = {
                "minMove": 1,
                "priceScale": 10 if market == "BTCUSDT" else 100,
                "pointValue": 1,
                "currency": "USDT",
                "minContract": "0.001",
                "quantityStep": "0.001",
            }
            for case in ("literal", "declared", "separate", "property"):
                x = src
                if case != "literal":
                    x = x.replace(illegal, "")
                    if ident == 2828:
                        x, n = re.subn(r"(?m)^plotchar\((?:rsi|roc_ma),.*$", "", x)
                        assert n == 2
                if case == "separate":
                    x, n = re.subn(r"strategy\.initial_capital", "50000.0", x)
                    assert n == 2
                if case == "property":
                    x, n = re.subn(
                        r"initial_capital=1000,", "initial_capital=50000,", x
                    )
                    assert n == 1
                for context in ("chart", "with_prefix"):
                    active = x
                    if context == "with_prefix":
                        active = x.replace(
                            "inRange := true",
                            f"inRange := time >= {tape['trading_start']}",
                        )
                        assert active != x
                    rows = [dict(zip(keys, r, strict=True)) for r in tape[context]]
                    rec = {
                        "id": ident,
                        "period": period,
                        "market": market,
                        "case": case,
                        "context": context,
                        "source_sha256": sha256(active.encode()).hexdigest(),
                    }
                    try:
                        r = pine.run_script(
                            active,
                            rows,
                            chart_symbol="BINANCE:" + market,
                            chart_timeframe="1D",
                            request_bars={"$chart": props},
                        )
                        rec.update(
                            {
                                "diagnostics": r["diagnostics"],
                                "strategy": r["strategy"],
                                "plots": {
                                    p["title"]: p["values"]
                                    for p in r["plots"]
                                    if p.get("title") in plots
                                },
                            }
                        )
                    except ValueError as exc:
                        rec["error"] = f"{type(exc).__name__}: {exc}"
                    outputs.append(rec)
(w / "r38-capital.json").write_text(
    json.dumps(outputs, separators=(",", ":")), encoding="utf8", newline="\n"
)
