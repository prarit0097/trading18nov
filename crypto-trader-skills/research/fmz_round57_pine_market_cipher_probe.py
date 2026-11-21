"""Isolated chart and executor probes of pending authored case #4432."""

import json
import sys
from hashlib import sha256
from importlib import import_module
from itertools import batched
from pathlib import Path

w = Path(__file__).parent
sys.path.insert(0, str(w / "priced-runtime"))
p = import_module("pine_compat")
pack = json.loads((w / "r48-4432-feeds.json").read_bytes())["data"]
a = (w / "r48-4432-archive.pine").read_text(encoding="utf8")
s = (w / "r48-4432-projection.pine").read_text(encoding="utf8")


def capital(s):
    return s.replace("strategy.initial_capital = 50000", "").replace(
        "overlay=true )", "overlay=true, initial_capital=50000 )", 1
    )


fix = capital(s)
inline = fix
for x, y in [
    ("request.security(syminfo.tickerid, tf, src)", "src"),
    ("request.security(syminfo.tickerid, tf, ta.ema(ci, avg))", "ta.ema(ci, avg)"),
    (
        "request.security(syminfo.tickerid, tf, ta.sma(wt1, malen))",
        "ta.sma(wt1, malen)",
    ),
]:
    assert inline.count(x) == 1
    inline = inline.replace(x, y)


def ema_reference(s):
    start = s.index("    wtVwap = wt1 - wt2")
    end = s.index("    [wt1, wt2,", start)
    derived = "\n".join(line[4:] for line in s[start:end].splitlines())
    old = next(
        line
        for line in s.splitlines()
        if "f_wavetrend(wtMASource, wtChannelLen, wtAverageLen, wtMALen, timeframe.period)"
        in line
    )
    rename = {
        "wtCrosslast": "wtCross_last",
        "wtCrossUplast": "wtCrossUp_last",
        "wtCrossDownlast": "wtCrossDown_last",
    }
    for original, replaced in rename.items():
        derived = derived.replace(original, replaced)
    assert s.count(old) == 1
    return s.replace(
        old,
        "chartBasis = 0.0\nchartRate = 2.0/(wtChannelLen + 1)\nchartBasis := na(chartBasis[1]) ? wtMASource : chartRate * wtMASource + (1 - chartRate) * chartBasis[1]\nchartDevInput = math.abs(wtMASource - chartBasis)\nchartDev = 0.0\nchartDev := na(chartDev[1]) ? chartDevInput : chartRate * chartDevInput + (1 - chartRate) * chartDev[1]\nchartIndex = chartDev == 0 ? na : (wtMASource - chartBasis) / (0.015 * chartDev)\nwt1 = 0.0\nwaveRate = 2.0 / (wtAverageLen + 1)\nwt1 := na(wt1[1]) ? chartIndex : waveRate * chartIndex + (1 - waveRate) * wt1[1]\nwt2 = ta.sma(wt1, wtMALen)\n"
        + derived,
    )


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


def summarize(r):
    return {k: r[k] for k in ("orders", "trades", "position", "equity", "diagnostics")}


names = (
    "WT1",
    "WT2",
    "LongCond",
    "ShortCond",
    "Trade flag",
    "Gate equity",
    "Broker equity",
    "SL long",
    "SL short",
    "TP long",
    "TP short",
)
rows = []
keys = ("time", "open", "high", "low", "close", "volume")
for coin, scopes in pack.items():
    for scope, chart in scopes.items():
        bars = [dict(zip(keys, b, strict=True)) for b in chart]
        symbol = "BINANCE:" + coin + "USDT"
        data = {
            symbol + ":60": bars,
            "$chart": {
                "minMove": 1,
                "priceScale": 10 if coin == "BTC" else 100,
                "pointValue": 1,
                "quantityStep": "0.001",
                "minContract": "0.001",
                "currency": "USDT",
            },
        }
        for count in (4, 12):
            n = str(count * 60)
            bars_n = [
                {
                    "time": chunk[0]["time"],
                    "open": chunk[0]["open"],
                    "high": max(x["high"] for x in chunk),
                    "low": min(x["low"] for x in chunk),
                    "close": chunk[-1]["close"],
                    "volume": sum(x["volume"] for x in chunk),
                }
                for chunk in batched(bars, count, strict=True)
            ]
            data[symbol + ":" + n] = bars_n
        sym = json.dumps(
            {"chart": "heikinashi", "symbol": symbol}, separators=(",", ":")
        )
        for tf in ("60", "240"):
            data[sym + ":" + tf] = heikin(data[symbol + ":" + tf])
        modes = (
            (
                ("reference-archive", ema_reference(capital(a))),
                ("reference-archive-display", ema_reference(capital(a))),
                ("reference-inline-50k", ema_reference(inline)),
                (
                    "reference-inline-1m",
                    ema_reference(inline).replace(
                        "initial_capital=50000", "initial_capital=1000000"
                    ),
                ),
            )
            if sys.argv[1] == "reference"
            else (
                ("archive", a),
                ("archive-capital-only", capital(a)),
                ("archive-perturbed-display", capital(a)),
                ("projection-same-chart", fix),
                ("inline-50k", inline),
                (
                    "inline-1m",
                    inline.replace("initial_capital=50000", "initial_capital=1000000"),
                ),
            )
        )
        for key, src in modes:
            try:
                opts = data
                if key in ("archive-perturbed-display", "reference-archive-display"):
                    opts = {
                        k: [
                            {
                                name: v * (1 + (i % 4) / 10)
                                if name in ("open", "high", "low", "close")
                                else v
                                for name, v in row.items()
                            }
                            for i, row in enumerate(r)
                        ]
                        if k not in (symbol + ":60", "$chart")
                        else r
                        for k, r in data.items()
                    }
                q = p.run_script(
                    src,
                    bars,
                    chart_symbol=symbol,
                    chart_timeframe="60",
                    request_bars=opts,
                )
                rows.append(
                    [
                        coin,
                        scope,
                        key,
                        q["diagnostics"],
                        summarize(q["strategy"]),
                        {
                            r["title"]: r["values"]
                            for r in q["plots"]
                            if r.get("title") in names
                        },
                        sha256(src.encode()).hexdigest(),
                    ]
                )
            except (ValueError, RuntimeError, TypeError) as e:
                rows.append([coin, scope, key, str(e).splitlines(), None])
(w / f"r48-4432-{sys.argv[1]}.json").write_text(
    json.dumps(rows, separators=(",", ":")), encoding="utf8"
)
