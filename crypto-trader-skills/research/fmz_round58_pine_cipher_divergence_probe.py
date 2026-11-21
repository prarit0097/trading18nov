"""Replay archived #3184 in the offline Pine Compat AppContainer."""

import json
import sys
from importlib import import_module
from itertools import batched
from pathlib import Path

w = Path(__file__).parent
sys.path.insert(0, str(w / "priced-runtime"))
p = import_module("pine_compat")


def month():
    s = (w / "r49-3184.pine").read_text(encoding="utf8")
    b = json.loads((w / "r49-3184-feeds.json").read_bytes())["1h"]
    keys = ("time", "open", "high", "low", "close", "volume")
    bars = [dict(zip(keys, x)) for x in b[:744]]
    q5 = json.loads((w / "r49-3184-sample-q5.json").read_bytes())["data"]
    symbols = {}
    symbol = "BINANCE:BTCUSDT"
    sym = json.dumps({"chart": "heikinashi", "symbol": symbol}, separators=(",", ":"))
    symbols.update(
        {
            symbol + ":60": bars,
            "BTC_USDT:swap:5": [
                dict(
                    zip(
                        keys,
                        (t, op / 10, hi / 10, lo / 10, close / 10, v * 0.001),
                        strict=True,
                    )
                )
                for t, op, hi, lo, close, v, *_ in q5
            ],
        }
    )

    def rolled(n):
        return [
            {
                "time": g[0]["time"],
                "open": g[0]["open"],
                "high": max(i["high"] for i in g),
                "low": min(i["low"] for i in g),
                "close": g[-1]["close"],
                "volume": sum(i["volume"] for i in g),
            }
            for g in batched(bars, n)
            if len(g) == n
        ]

    def heikin(rows):
        out = []
        y = None
        for row in rows:
            o, h, l, c = (row[k] for k in ("open", "high", "low", "close"))
            newo = (o + c) / 2 if y is None else sum(y) / 2
            newc = (o + h + l + c) / 4
            out.append(
                {
                    **row,
                    "open": newo,
                    "high": max(h, newo, newc),
                    "low": min(l, newo, newc),
                    "close": newc,
                }
            )
            y = (newo, newc)
        return out

    for n in (4, 12):
        symbols[symbol + ":" + str(n * 60)] = rolled(n)
    for k in ("60", "240"):
        symbols[sym + ":" + k] = heikin(symbols[symbol + ":" + k])
    symbols["$chart"] = {
        "minMove": 1,
        "priceScale": 10,
        "pointValue": 1,
        "quantityStep": "0.001",
        "minContract": "0.001",
        "currency": "USDT",
    }
    projection = (w / "r49-3184-projected.pine").read_text(encoding="utf8")
    all = {}
    for name, src in (
        ("archived", s),
        ("cross-feed-shift", s),
        ("projection", projection),
    ):
        try:
            opts = (
                symbols
                if name != "cross-feed-shift"
                else {
                    k: [
                        {
                            name: v * 1.2
                            if name in ("open", "high", "low", "close")
                            else v
                            for name, v in u.items()
                        }
                        for u in rows
                    ]
                    if k not in ("$chart", symbol + ":60")
                    else rows
                    for k, rows in symbols.items()
                }
            )
            r = p.run_script(
                src,
                bars,
                chart_symbol="BINANCE:BTCUSDT",
                chart_timeframe="60",
                request_bars=opts,
            )
            all[name] = {
                "diag": r["diagnostics"],
                "plots": {
                    x.get("title"): x["values"]
                    for x in r["plots"]
                    if x.get("title")
                    in (
                        "LongGate",
                        "ShortGate",
                        "WT1",
                        "WT2",
                        "LocalBasis",
                        "Entry-limit",
                        "Target",
                        "Stop",
                    )
                },
                "orders": r["strategy"]["orders"],
            }
        except (ValueError, RuntimeError, TypeError) as e:
            all[name] = {"diag": str(e).splitlines()}
    (w / "r49-3184-month.json").write_text(json.dumps(all), encoding="utf8")


def cohort(mode):
    source = "documented-explicit" if mode == "event" else mode
    s = (w / f"r49-3184-{source}.pine").read_text(encoding="utf8")
    h = json.loads((w / "r49-3184-fulltape.json").read_bytes())["data"]
    keys = ("time", "open", "high", "low", "close", "volume")
    r = {}
    for sym, windows in h.items():
        for scope, (hours, quarter) in windows.items():
            nm = f"{sym}:{scope}"
            bars = [dict(zip(keys, row, strict=True)) for row in hours]
            opts = {
                "$chart": {
                    "minMove": 1,
                    "priceScale": 10 if sym == "BTC" else 100,
                    "pointValue": 1,
                    "quantityStep": "0.001",
                    "minContract": "0.001",
                    "currency": "USDT",
                }
            }
            try:
                q = p.run_script(
                    s,
                    bars,
                    chart_symbol="BINANCE:" + sym + "USDT",
                    chart_timeframe="60",
                    request_bars=opts,
                )
                r[nm] = {
                    "diag": q["diagnostics"],
                    "strategy": q["strategy"],
                    "plots": {
                        x.get("title"): x["values"]
                        for x in q["plots"]
                        if x.get("title")
                        in (
                            "LongGate",
                            "ShortGate",
                            "WT1",
                            "WT2",
                            "LocalBasis",
                            "Entry-limit",
                            "Target",
                            "Stop",
                        )
                    },
                }
            except (ValueError, RuntimeError, TypeError) as e:
                r[nm] = {"diag": str(e).splitlines()}
            (w / f"r49-3184-{mode}-full.json").write_text(
                json.dumps(r, separators=(",", ":")), encoding="utf8"
            )


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "month":
        month()
    else:
        assert mode in ("projected", "documented", "event")
        cohort(mode)
