"""Verify archived #1951 ALMA orders against a separate causal broker ledger."""

import math
import re
import sys
from decimal import Decimal
from pathlib import Path

from research.fmz_round7_magnifier import (
    aggregate,
    date_ms,
    ledger_metrics,
    read,
    sha256,
    verified_archives,
    write,
)
from research.fmz_round8_fx import csv_rows
from research.fmz_round18_5745 import DAY, ENGINE_SHA, FEEDS, FIELDS

HOUR = 3_600_000
START, END = map(date_ms, ("2022-11-22", "2023-11-22"))
MONTHS = ("2022-11", "2022-12", *(f"2023-{month:02d}" for month in range(1, 12)))
FEE = Decimal(".002")
STEP = Decimal(".001")
CAPITAL = 1000
OBSERVE = """
plot(entry_long?1:0,title="Active long entry")
plot(exit_long?1:0,title="Active long close")
plot(entry_short?1:0,title="Active short entry")
plot(exit_short?1:0,title="Active short close")
plot(strategy.position_size,title="Position")
"""


def objects(rows):
    return [dict(zip(FIELDS, r, strict=True)) for r in rows]


def alma(values, length=18):
    mid = 0.88 * (length - 1)
    scale = length
    weights = [math.exp(-((i - mid) ** 2) / (2 * scale * scale)) for i in range(length)]
    total = math.fsum(weights)
    return [None] * (length - 1) + [
        math.fsum(
            w * x for w, x in zip(weights, values[j - length + 1 : j + 1], strict=True)
        )
        / total
        for j in range(length - 1, len(values))
    ]


def positions(chart):
    opens = alma([x["open"] for x in chart])
    closes = alma([x["close"] for x in chart])
    trend = False
    target = False
    long = False
    entry = None
    completed = []
    events = []
    flags = []
    equity = []
    cash = Decimal(CAPITAL)
    held = Decimal(0)
    first = None
    for i, bar in enumerate(chart):
        open_px, close_px = (Decimal(str(bar[k])) for k in ("open", "close"))
        if long != target:
            if target:
                held = (cash / open_px / (1 + FEE) // STEP) * STEP
                entry = i
                first = open_px
                cash -= held * open_px * (1 + FEE)
            else:
                gross = held * (open_px - first)
                cost = held * FEE * (open_px + first)
                cash += held * open_px * (1 - FEE)
                completed.append((entry, i, held, gross, cost))
            events.append((i, target, held, open_px))
            long = target
            if not long:
                held = Decimal(0)
        remembered = (
            i > 0 and opens[i - 1] is not None and closes[i - 1] >= opens[i - 1]
        )
        new_buy = bool(remembered and not trend)
        new_sell = bool(trend and not remembered)
        flags.append((int(new_buy), int(new_sell)))
        if new_buy or new_sell:
            target = new_buy
        trend = remembered
        equity.append((held, cash + held * close_px))
    return opens, closes, flags, events, completed, equity


def near(a, b):
    return math.isclose(a, float(b), rel_tol=1e-12, abs_tol=1e-8)


def replay(engine, source, market, chart, hour, two_hours):
    ticker = f"BINANCE:{market}"
    requests = {
        ticker + ":60": hour,
        ticker + ":120": two_hours,
        ticker + ":1D": chart,
        "$chart": {
            "minMove": 1,
            "priceScale": 100,
            "pointValue": 1,
            "quantityStep": "0.001",
            "minContract": "0.001",
            "currency": "USDT",
        },
    }
    opts = {"chart_symbol": ticker, "chart_timeframe": "D", "request_bars": requests}
    actual = engine.run_script(source, chart, **opts)["strategy"]
    sample = engine.run_script(source + OBSERVE, chart, **opts)
    assert actual == sample["strategy"] and not actual["diagnostics"]
    assert all(
        x["code"] == "W_LEGACY_SECURITY_LOOKAHEAD" for x in sample["diagnostics"]
    )
    # The lower feeds support displayed trends. They do not drive the active order paths.
    shifted = {**requests}
    for suffix, chosen in (("60", hour), ("120", two_hours)):
        shifted[ticker + ":" + suffix] = [
            {**r, **{k: r[k] * 1.4 for k in ("open", "high", "low", "close")}}
            for r in chosen
        ]
    assert (
        engine.run_script(source, chart, **{**opts, "request_bars": shifted})[
            "strategy"
        ]
        == actual
    )
    opens, closes, flags, events, lots, equity = positions(chart)
    plots = {p["title"]: p["values"] for p in sample["plots"] if p.get("title")}
    for label, independent in (("Open Line", opens), ("Close Line", closes)):
        for i, (observed, model) in enumerate(
            zip(plots[label], independent, strict=True)
        ):
            assert observed is None if model is None else near(observed, model), (
                market,
                label,
                i,
                observed,
                model,
            )
    assert (
        list(zip(plots["Active long entry"], plots["Active long close"], strict=True))
        == flags
    )
    assert not any(plots["Active short entry"]) and not any(plots["Active short close"])
    quarter = {b["time"]: b for b in hour}
    for native, (i, is_enter, size, px) in zip(actual["orders"], events, strict=True):
        stamp = chart[i]["time"]
        quote = quarter[stamp]
        assert native["id"] == (
            "ENTRY_LONG" if is_enter else "Close entry(s) order ENTRY_LONG"
        )
        assert (native["barIndex"], native["time"]) == (i, stamp)
        assert (
            near(native["qty"], size)
            and near(native["price"], px)
            and quote["open"] == float(px)
            and quote["volume"] > 0
        )
    for i, (size, e) in enumerate(equity):
        assert near(plots["Position"][i], size) and near(
            actual["equity"][i]["equity"], e
        ), (market, i, size, e)
    verified = []
    for native, (entry, exit, size, gross, commission) in zip(
        actual["trades"], lots, strict=True
    ):
        assert (native["entryBarIndex"], native["exitBarIndex"]) == (entry, exit)
        assert near(native["qty"], size) and near(native["profit"], gross - commission)
        verified.append({**native, "dir": 1, "commission": float(commission)})
    return {
        "market": market,
        "trades": verified,
        "fills": actual["orders"],
        "ending_size": float(equity[-1][0]),
        "ending_marked_equity": float(equity[-1][1]),
        "chart_bars": len(chart),
    }


def run(source_path, daily, hourly, runtime, output):
    assert (
        sha256(source_path)
        == "8f1950543062574cd8b31a7b057273c5b9d74cd48d8322142b980e38015db8b4"
        and sha256(runtime / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    )
    sys.path.insert(0, str(runtime))
    import pine_compat as engine

    (src,) = re.findall(
        r"(?ms)^```[^\n]*\n(.*?)^```", source_path.read_text(encoding="utf-8")
    )
    source, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", src)
    assert n == 1
    receipts = []
    cases = []
    for market, digest in FEEDS.items():
        path = daily / f"5411-feed-{market}.json"
        assert sha256(path) == digest
        chart = [r for r in read(path) if START <= r[0] < END]
        files = verified_archives(hourly, market, "1h", MONTHS, receipts)
        rows = [
            (int(r[0]), *map(float, r[1:6]))
            for p in files
            for r in csv_rows(p)
            if r[0].isdigit() and START <= int(r[0]) < END
        ]
        assert [r[0] for r in rows] == list(range(START, END, HOUR))
        assert [r[0] for r in chart] == list(range(START, END, DAY))
        for h, d in zip(aggregate(rows, 24), chart, strict=True):
            assert h[:5] == tuple(d[:5])
        cases.append(
            replay(
                engine,
                source,
                market,
                objects(chart),
                objects(rows),
                objects(aggregate(rows, 2)),
            )
        )
    common = {
        "id": 1951,
        "group": "FMZ · Pine v4 · Prior-day ALMA order crossover",
        "period": "Binance USD-M · 2022-11-22 to 2023-11-22 UTC exclusive",
        "archive_interval": "1d",
        "interval": "1d",
        "currency": "USDT",
        "exit": "Opposite completed daily ALMA trend",
    }
    results = [
        {
            **common,
            "market": case["market"],
            **ledger_metrics(case["trades"], CAPITAL, int(bool(case["ending_size"]))),
        }
        for case in cases
    ]
    results.append(
        {
            **common,
            "market": "BTCUSDT + ETHUSDT",
            **ledger_metrics(
                [lot for case in cases for lot in case["trades"]],
                2 * CAPITAL,
                sum(bool(c["ending_size"]) for c in cases),
            ),
        }
    )
    write(
        output,
        {
            "schema": "FMZ 1951 · Daily ALMA and open-price cash reconciliation",
            "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
            "source_sha256": sha256(source_path),
            "engine_sha256": ENGINE_SHA,
            "hourly_archives": receipts,
            "daily_feeds_sha256": FEEDS,
            "notes": {
                "scope": "The original daily Binance BTC replay uses its 2022–2023 saved dates. ETH is a same-venue comparison. All same-day candles are verified against official hourly market prices. The original defaults enable long trades and disable short trades.",
                "timing": "The Pine v4 source requests 1D series on a daily chart. The active ALMA comparison reads both values from the preceding daily bar and generates long-only flips. The separately supplied 1h and 2h inputs are from known completed candles; perturbing them left the complete simulated strategy output identical.",
                "accounting": "The archived 1,000 USDT, 100% equity allocation and 0.2% fee are preserved. An independent next-open cash witness reserves the entry fee and rounds down to a 0.001 step. All positions, fills, settled P&L and daily marked equity values reconcile. Funding and extra slippage are outside this test.",
            },
            "coverage": [
                [
                    1951,
                    "Tested · Prior-day daily ALMA orders and fees",
                    "Exact Pine v4 and saved BTC dates with an ETH comparison. Same-context ALMA, original long-only default, causal next-open sizing and source fee reconcile. Aux data perturbation leaves the broker unchanged.",
                ]
            ],
            "results": results,
            "scopes": cases,
        },
    )


if __name__ == "__main__":
    run(*map(Path, sys.argv[1:]))
