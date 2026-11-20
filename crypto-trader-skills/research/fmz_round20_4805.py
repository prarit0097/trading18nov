"""Verify #4805 with its original BTC price input and a labelled Bitfinex variant."""

import json
import math
import re
import sys
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

from research.fmz_round7_magnifier import (
    aggregate,
    date_ms,
    ledger_metrics,
    raw_ohlcv,
    read,
    sha256,
    verified_archives,
    write,
)
from research.fmz_round18_5745 import ENGINE_SHA, FIELDS

SOURCE_SHA = "984687369d89e497dfe0d7c3df9fb9bcb3d6ea0f32a3d7146658d655503cea58"
HOUR = 3_600_000
MINUTE = 60_000
START, END = map(date_ms, ("2023-12-26", "2024-01-25"))
CAPITAL = 1000
FEE = Decimal("0.0005")
STEP = Decimal("0.001")
ORIGINAL = "BTC_USDT:swap"
BITFINEX = "BITFINEX:BTCUSDSHORTS"
OBSERVE = """
plot(Shorts,title="Request")
plot(vrsi,title="RSI")
plot(RSIover?1:0,title="Long gate")
plot(RSIunder?1:0,title="Short gate")
plot(strategy.position_size,title="Position")
"""


def stats(work):
    manifest = read(work / "4805-bitfinex-manifest.json")
    assert len(manifest) == 5
    positions = {}
    for record in manifest:
        path = work / record["file"]
        assert sha256(path) == record["sha256"]
        data = json.loads(path.read_bytes(), parse_float=Decimal)
        assert len(data) == record["n"]
        for stamp, qty in data:
            assert stamp not in positions and qty > 0
            positions[stamp] = qty
    assert list(positions) == list(range(START - MINUTE, END, MINUTE))
    series = []
    for stamp in range(START, END, HOUR):
        prior = float(positions[stamp - MINUTE])
        series.append(
            dict(zip(FIELDS, (stamp, prior, prior, prior, prior, 0), strict=True))
        )
    return series, manifest


def signal(values):
    changes = [b - a for a, b in pairwise(values)]
    up = math.fsum(max(x, 0) for x in changes[:7]) / 7
    down = math.fsum(max(-x, 0) for x in changes[:7]) / 7
    readings = [None] * 7
    for i in range(7, len(values)):
        if i > 7:
            up = (6 * up + max(changes[i - 1], 0)) / 7
            down = (6 * down + max(-changes[i - 1], 0)) / 7
        readings.append(100 - 100 / (1 + up / down) if down else 100)
    edge = [0] * 8
    for a, b in pairwise(readings[7:]):
        edge.append(1 if b < 30 <= a else -1 if b > 75 >= a else 0)
    return readings, edge


def oracle(bars, lower, edges):
    orders, trades, curve = [], [], []
    pending = side = 0
    open_lots = []
    cash = Decimal(CAPITAL)
    close_calls = 0
    for i, bar in enumerate(bars):
        opening, closing = (Decimal(str(x)) for x in (bar["open"], bar["close"]))
        old_quantity = sum(q for _, _, q in open_lots)
        if open_lots:
            old_avg = sum(price * q for _, price, q in open_lots) / old_quantity
            old_bound = old_avg * (1 - Decimal("0.25") * side)
            for row in lower[i * 4 : i * 4 + 4]:
                if side > 0:
                    assert Decimal(str(row["low"])) > old_bound
                else:
                    assert Decimal(str(row["high"])) < old_bound
                close_calls += 1
        if pending:
            size = (
                (cash + side * old_quantity * opening) / 10 / opening // STEP
            ) * STEP
            assert size > 0
            reversed_qty = old_quantity if side and pending != side else Decimal(0)
            if reversed_qty:
                for j, price, quantity in open_lots:
                    pnl = side * quantity * (opening - price)
                    fee = FEE * quantity * (opening + price)
                    trades.append((side, j, i, quantity, pnl, fee))
                open_lots.clear()
            moved = size + reversed_qty
            cash -= (pending + FEE) * moved * opening
            side = pending
            open_lots.append((i, opening, size))
            orders.append((side, i, opening, moved))
        current_qty = sum(q for _, _, q in open_lots)
        if open_lots:
            held_avg = sum(price * q for _, price, q in open_lots) / current_qty
            bound = held_avg * (1 - Decimal("0.25") * side)
            for row in lower[i * 4 : i * 4 + 4]:
                if side > 0:
                    assert Decimal(str(row["low"])) > bound
                else:
                    assert Decimal(str(row["high"])) < bound
                close_calls += 1
        pending = edges[i] if edges[i] != side or len(open_lots) < 2 else 0
        curve.append((side * current_qty, cash + side * current_qty * closing))
    return orders, trades, curve, close_calls


def near(a, b):
    return math.isclose(a, float(b), rel_tol=1e-12, abs_tol=1e-8)


def replay(engine, source, symbol, market, chart, lower, reference):
    options = {
        "chart_symbol": f"BINANCE:{market}",
        "chart_timeframe": "60",
        "request_bars": {
            symbol + ":60": reference,
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
    actual = engine.run_script(source, chart, **options)["strategy"]
    observed = engine.run_script(source + OBSERVE, chart, **options)
    assert not observed["diagnostics"] and actual == observed["strategy"]
    plots = {p["title"]: p["values"] for p in observed["plots"]}
    values = [bar["open"] for bar in reference]
    assert plots["Request"] == values
    rsi, edges = signal(values)
    for expected, got in zip(rsi, plots["RSI"], strict=True):
        assert got is None if expected is None else near(got, expected)
    assert plots["Long gate"] == [int(x == 1) for x in edges]
    assert plots["Short gate"] == [int(x == -1) for x in edges]
    orders, trades, balances, bounds = oracle(chart, lower, edges)
    for o, (side, i, px, moved) in zip(actual["orders"], orders, strict=True):
        assert (
            o["id"] == ("LONG" if side > 0 else "SHORT")
            and o["barIndex"] == i
            and o["time"] == chart[i]["time"]
        )
        assert near(o["price"], px) and near(o["qty"], moved), (
            market,
            symbol,
            i,
            o["qty"],
            moved,
        )
    for i, (size, equity) in enumerate(balances):
        assert near(plots["Position"][i], size) and near(
            actual["equity"][i]["equity"], equity
        )
    verified = []
    for lot, (side, entry, exit, qty, gross, cost) in zip(
        actual["trades"], trades, strict=True
    ):
        assert (lot["entryBarIndex"], lot["exitBarIndex"]) == (entry, exit)
        assert near(lot["qty"], side * qty) and near(lot["profit"], gross - cost)
        verified.append(
            {**lot, "dir": side, "qty": float(qty), "commission": float(cost)}
        )
    open_count = len(orders) - len(trades)
    assert 0 < open_count <= 2 and balances[-1][0]
    return {
        "market": market,
        "symbol": symbol,
        "orders": actual["orders"],
        "settled_lots": verified,
        "open_lots": open_count,
        "bracket_interval_checks": bounds,
        "ending_position": actual["position"][-1],
        "ending_equity": float(balances[-1][1]),
    }


def run(work, archives, engine_root, output):
    assert sha256(engine_root / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(engine_root))
    import pine_compat as engine

    path = work / "source-4805.md"
    assert sha256(path) == SOURCE_SHA
    (source,) = re.findall(
        r"(?ms)^```[^\n]*\n(.*?)^```", path.read_text(encoding="utf-8")
    )
    source, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", source)
    assert n == 1 and source.count(ORIGINAL) == 1
    references, position_manifest = stats(work)
    charts, bases, candle_manifest = {}, {}, []
    for market in ("BTCUSDT", "ETHUSDT"):
        files = verified_archives(
            archives, market, "15m", ("2023-12", "2024-01"), candle_manifest
        )
        rows = [
            row
            for f in files
            for row in raw_ohlcv(f, HOUR // 4)
            if START <= row[0] < END
        ]
        assert [r[0] for r in rows] == list(range(START, END, HOUR // 4))
        assert all(row[5] > 0 for row in rows)
        charts[market] = [
            dict(zip(FIELDS, row, strict=True)) for row in aggregate(rows, 4)
        ]
        bases[market] = [dict(zip(FIELDS, row, strict=True)) for row in rows]
    outcomes = []
    evidence = []
    for symbol, ref in ((ORIGINAL, charts["BTCUSDT"]), (BITFINEX, references)):
        variant = source if symbol == ORIGINAL else source.replace(ORIGINAL, BITFINEX)
        cases = [
            replay(engine, variant, symbol, m, chart, bases[m], ref)
            for m, chart in charts.items()
        ]
        evidence.extend(cases)
        label = (
            "Archived BTC perpetual open"
            if symbol == ORIGINAL
            else "Official Bitfinex BTC shorts variant"
        )
        common = {
            "id": 4805,
            "group": f"FMZ · Pine v5 · {label}",
            "period": "Binance USD-M · 2023-12-26 to 2024-01-25 UTC exclusive",
            "exit": "Source RSI reversals and 25% stops",
            "interval": "1h",
            "archive_interval": "1h",
            "currency": "USDT",
        }
        outcomes.extend(
            {
                **common,
                "market": c["market"],
                **ledger_metrics(c["settled_lots"], CAPITAL, c["open_lots"]),
            }
            for c in cases
        )
        outcomes.append(
            {
                **common,
                "market": "BTCUSDT + ETHUSDT",
                **ledger_metrics(
                    [lot for c in cases for lot in c["settled_lots"]],
                    CAPITAL * 2,
                    sum(c["open_lots"] for c in cases),
                ),
            }
        )
    write(
        output,
        {
            "schema": "FMZ 4805 · Archived BTC input and explicit Bitfinex input variant",
            "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
            "source_sha256": SOURCE_SHA,
            "engine_sha256": ENGINE_SHA,
            "candles": candle_manifest,
            "positions": position_manifest,
            "notes": {
                "original": "The published input defaults to BTC_USDT:swap. In the listed Binance context it is bound to the same BTC perpetual hourly opening prices, also on the ETH comparison. The strategy title refers to Bitfinex while the saved initial input names a BTC perpetual.",
                "variant": "The source's explicit symbol input is changed for a separate experiment. Official Bitfinex tBTCUSD short size is sampled from the completed minute immediately before each hour to prevent future input. It measures aggregate BTC spot margin shorts.",
                "validation": "The Pine output and an independent RSI, pyramiding, cash and fee ledger agree. Every received position and opening price was checked; 15-minute price extremes independently verified that the original 25% stops remained inactive. No forced ending settlement.",
                "cost": "Archived 1000 USDT capital, 10% of marked equity size, 0.001 quantity step, pyramiding up to two and 0.05% default percent commission. Realized statistics use closed lots. Open marks appear separately. Funding and slippage are outside this run.",
            },
            "coverage": [
                [
                    4805,
                    "Tested · Archived BTC reference and historical Bitfinex variant",
                    "Verified saved hourly BTC and ETH comparison with fixed BTC perpetual opens. Also tested an explicitly bound historical aggregate shorts variant using official minute snapshots. Causal RSI, pyramiding, orders, fees and stop non-touches reconcile.",
                ]
            ],
            "results": outcomes,
            "scopes": evidence,
        },
    )


if __name__ == "__main__":
    run(*map(Path, sys.argv[1:]))
