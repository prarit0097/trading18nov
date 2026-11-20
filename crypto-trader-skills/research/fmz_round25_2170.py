"""Verify archived FMZ #2170 with legacy ticker binding and causal ANN inputs."""

import math
import re
import sys
from pathlib import Path

from research.fmz_round7_magnifier import (
    aggregate,
    date_ms,
    ledger_metrics,
    sha256,
    verified_archives,
    write,
)
from research.fmz_round8_fx import csv_rows
from research.fmz_round18_5745 import DAY, ENGINE_SHA, FIELDS

HOUR = 3_600_000
QUARTER = HOUR // 4
START, END, WARMUP = map(date_ms, ("2023-08-14", "2023-09-13", "2023-08-11"))
CAPITAL = 1_000_000
FEE = 0.00075
THRESHOLD = 0.006
LAYERS = (15, 30, 9, 1)
OBS = """
plot(entryToday,title="Daily one")
plot(entryYesterday,title="Daily two")
plot(exitToday,title="Hourly one")
plot(exitYesterday,title="Hourly two")
plot(entryPrediction,title="Entry prediction")
plot(exitPrediction,title="Exit prediction")
plot(goLong?1:0,title="Long gate")
plot(goShort?1:0,title="Short gate")
plot(strategy.position_size,title="Position")
"""


def objects(rows):
    return [dict(zip(FIELDS, r, strict=True)) for r in rows]


def network(source):
    rule = r"(?m)^    l([123])_(\d+) = PineActivationFunctionTanh\((.*)\)[ \t]*$"
    layers = [[] for _ in range(3)]
    for layer, index, block in re.findall(rule, source):
        k = int(layer) - 1
        assert int(index) == len(layers[k])
        row = []
        for match in re.split(r"\s*\+\s*(?=l[012]_\d+\*)", block):
            m = re.fullmatch(
                r"\s*l([012])_(\d+)\*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*",
                match,
            )
            assert m is not None, match
            level, number, weight = m.groups()
            assert int(level) == k and int(number) == len(row)
            row.append(float(weight))
        assert len(row) == LAYERS[k]
        layers[k].append(row)
    assert tuple(map(len, layers)) == LAYERS[1:]
    return layers


def activation(value, layers):
    prev = [value] * LAYERS[0]
    for layer in layers:
        prev = [
            math.tanh(math.fsum(w * x for w, x in zip(row, prev, strict=True)))
            for row in layer
        ]
    (result,) = prev
    return result


def mean_ohlc(bar):
    return math.fsum(bar[x] for x in ("open", "high", "low", "close")) / 4


def inputs(bars, hour, daily, layers):
    hb = {x["time"]: mean_ohlc(x) for x in hour}
    db = {x["time"]: mean_ohlc(x) for x in daily}
    times = []
    signals = []
    for bar in bars:
        stamp = bar["time"]
        midnight = stamp // DAY * DAY
        d1, d2 = db[midnight - DAY], db[midnight - 2 * DAY]
        h1, h2 = hb[stamp - HOUR], hb[stamp - 2 * HOUR]
        e = activation((d1 - d2) / d2, layers)
        x = activation((h1 - h2) / h2, layers)
        buy = e < -THRESHOLD and x < -THRESHOLD
        sell = e > THRESHOLD and x > THRESHOLD
        times.append((d1, d2, h1, h2, e, x, int(buy), int(sell)))
        signals.append(
            (
                buy,
                sell,
                x >= THRESHOLD or e >= THRESHOLD,
                x <= -THRESHOLD or e <= THRESHOLD,
            )
        )
    return times, signals


def broker_model(bars, signals):
    pending = side = 0
    entry = None
    orders, trade_indices, states = [], [], []
    for i, (buy, sell, close_buy, close_sell) in enumerate(signals):
        if pending != side:
            if side:
                orders.append(
                    (
                        i,
                        "Close entry(s) order LONG"
                        if side > 0
                        else "Close entry(s) order SHORT",
                    )
                )
                trade_indices.append((entry, i, side))
            if pending:
                orders.append((i, "LONG" if pending > 0 else "SHORT"))
            entry = i if pending else None
            side = pending
        states.append(side)
        if buy:
            pending = 1
        elif sell:
            pending = -1
        elif (side > 0 and close_buy) or (side < 0 and close_sell):
            pending = 0
    return orders, trade_indices, states, entry


def near(a, b):
    return math.isclose(a, b, rel_tol=1e-11, abs_tol=1e-10)


def replay(engine, source, model, market, chart, hour, daily, base):
    symbol = f"BINANCE:{market}"
    opts = {
        "chart_symbol": symbol,
        "chart_timeframe": "180",
        "request_bars": {
            symbol + ":60": hour,
            symbol + ":D": daily,
            "$chart": {
                "minMove": 1,
                "priceScale": 100,
                "pointValue": 1,
                "quantityStep": "0.001",
                "minContract": "0.001",
                "currency": "USDT",
            },
        },
    }
    actual = engine.run_script(source, chart, **opts)["strategy"]
    observed = engine.run_script(source + OBS, chart, **opts)
    assert actual == observed["strategy"] and not actual["diagnostics"]
    assert len(observed["diagnostics"]) == 4 and all(
        d["code"] == "W_LEGACY_SECURITY_LOOKAHEAD" for d in observed["diagnostics"]
    )
    traces = {
        plot["title"]: plot["values"] for plot in observed["plots"] if plot.get("title")
    }
    expected, signals = inputs(chart, hour, daily, model)
    columns = (
        "Daily one",
        "Daily two",
        "Hourly one",
        "Hourly two",
        "Entry prediction",
        "Exit prediction",
        "Long gate",
        "Short gate",
    )
    for label, values in zip(columns, zip(*expected, strict=True), strict=True):
        actual_series = traces[label]
        for i, (actual_value, predicted) in enumerate(
            zip(actual_series, values, strict=True)
        ):
            assert near(actual_value, predicted), (
                market,
                label,
                i,
                actual_value,
                predicted,
            )
    order_flow, lot_indices, positions, holding = broker_model(chart, signals)
    assert traces["Position"] == positions
    for o, (i, name) in zip(actual["orders"], order_flow, strict=True):
        b = chart[i]
        observed = base[b["time"]]
        assert (o["id"], o["time"], o["barIndex"], o["qty"], o["price"]) == (
            name,
            b["time"],
            i,
            1,
            observed["open"],
        )
        assert observed["volume"] > 0
    trades = []
    for lot, (entry, exit, side) in zip(actual["trades"], lot_indices, strict=True):
        ep, xp = chart[entry]["open"], chart[exit]["open"]
        assert (
            lot["entryBarIndex"],
            lot["exitBarIndex"],
            lot["qty"],
            lot["entryPrice"],
            lot["exitPrice"],
        ) == (entry, exit, side, ep, xp)
        gross = side * (xp - ep)
        commission = FEE * (xp + ep)
        assert near(gross, lot["profit"])
        trades.append(
            {
                **lot,
                "dir": side,
                "qty": 1,
                "commission": commission,
                "profit": gross - commission,
            }
        )
    return {
        "market": market,
        "bars": len(chart),
        "results": trades,
        "orders": actual["orders"],
        "ending_position": positions[-1],
        "ending_entry_bar": holding,
    }


def run(source_path, august, september, runtime, output):
    from hashlib import sha256 as digest

    assert sha256(runtime / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(runtime))
    import pine_compat as engine

    raw_source = source_path.read_bytes()
    source_hash = digest(raw_source).hexdigest()
    assert (
        source_hash
        == "0f96f2fb5b8f472c6f615e169a3e2f9e8fca150e6127ac1a1f5835cb9f7256c5"
    )
    (src,) = re.findall(
        r"(?ms)^```[ \t]*pinescript[^\n]*\n(.*?)^```",
        raw_source.decode().replace("\r\n", "\n"),
    )
    src, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", src)
    assert n == 1 and src.count("syminfo.tickerid") == 4
    source = src.replace("syminfo.tickerid", "tickerid")
    assert "//@version=2" in source
    model = network(source)
    manifest = []
    cases = []
    for market in ("BTCUSDT", "ETHUSDT"):
        files = verified_archives(
            august, market, "15m", ("2023-08",), manifest
        ) + verified_archives(september, market, "15m", ("2023-09",), manifest)
        rows = [
            (int(r[0]), *map(float, r[1:6]))
            for f in files
            for r in csv_rows(f)
            if r[0].isdigit() and WARMUP <= int(r[0]) < END
        ]
        assert [row[0] for row in rows] == list(range(WARMUP, END, QUARTER))
        assert all(
            0 < l <= min(o, c) <= max(o, c) <= h and v > 0 for _, o, h, l, c, v in rows
        )
        chart = objects([r for r in aggregate(rows, 12) if r[0] >= START])
        assert [r["time"] for r in chart] == list(range(START, END, 3 * HOUR))
        base = {r["time"]: r for r in objects(rows)}
        cases.append(
            replay(
                engine,
                source,
                model,
                market,
                chart,
                objects(aggregate(rows, 4)),
                objects(aggregate(rows, 96)),
                base,
            )
        )
    context = {
        "id": 2170,
        "group": "FMZ · Pine v2 · Confirmed OHLC neural signals",
        "period": "Binance USD-M · 2023-08-14 to 2023-09-13 UTC exclusive",
        "archive_interval": "3h",
        "interval": "3h",
        "currency": "USDT",
        "exit": "Authored threshold exit or reversal",
    }
    results = [
        {
            **context,
            "market": c["market"],
            **ledger_metrics(c["results"], CAPITAL, int(bool(c["ending_position"]))),
        }
        for c in cases
    ]
    results.append(
        {
            **context,
            "market": "BTCUSDT + ETHUSDT",
            **ledger_metrics(
                [lot for c in cases for lot in c["results"]],
                2 * CAPITAL,
                sum(bool(c["ending_position"]) for c in cases),
            ),
        }
    )
    write(
        output,
        {
            "schema": "FMZ 2170 · Legacy ticker binding and independent neural order verifier",
            "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
            "source_sha256": source_hash,
            "engine_sha256": ENGINE_SHA,
            "candle_archives": manifest,
            "references": [
                "https://www.tradingview.com/pine-script-docs/v4/appendix/pine-version-3-migration-guide/",
                "https://www.tradingview.com/pine-script-docs/v5/migration-guides/to-pine-version-4/",
            ],
            "notes": {
                "scope": "The source's saved three-hour BTC perpetual dates and independent ETH comparison use complete official 15-minute bars. Three days of separate warmup supply prior daily and hourly observations. Historical calculations run on completed chart bars; live tick recalculation was outside the comparison.",
                "compatibility": "The archive declares v2 but spells the four ticker IDs with the v4 namespace. Replacing only the symbol spelling with legacy tickerid keeps the original version and default alignment. Daily inputs are the previous two completed UTC days. Hourly inputs are the two hours preceding the first intrabar of each three-hour group.",
                "verification": "Independent arithmetic decodes every archived coefficient, verifies three weighted tanh layers against the emitted predictions, then checks both exact authored thresholds, broker flags, state transitions and prices from the first 15-minute child of each market fill. The original lookahead warnings are documented, and the verified [1] and [2] inputs are already known.",
                "costs": "One base unit and default 1,000,000 USDT capital per market. Gross uses source zero commission. Net subtracts a separately applied 0.075% per-side fee overlay. Workbook drawdown uses settled events. No forced terminal close.",
            },
            "coverage": [
                [
                    2170,
                    "Tested · Legacy neural predictions and causal price inputs",
                    "Only fixed the documented same-symbol ticker spelling for Pine v2. Independently verified daily/hourly prior inputs, all neural scores, both exit conditions, market fill prices and fee arithmetic.",
                ]
            ],
            "results": results,
            "scopes": cases,
        },
    )


if __name__ == "__main__":
    run(*map(Path, sys.argv[1:]))
