"""Verify FMZ #3946 historical entry attempts and authored collateral limits."""

import math
import re
import sys
from pathlib import Path
from statistics import fmean, pstdev

from research.fmz_round7_magnifier import (
    date_ms,
    ledger_metrics,
    raw_ohlcv,
    read,
    sha256,
    verified_archives,
    write,
)
from research.fmz_round18_5745 import DAY, ENGINE_SHA, FEEDS, FIELDS
from research.fmz_round21_1988 import rsi14

SOURCE_SHA = "de62f324df008cf77d3bfb36c929a57251c9141e39bcd2cd1fd324a342e56e9e"
START, SWITCH, END = map(date_ms, ("2024-04-11", "2024-12-01", "2025-04-10"))
MONTHS = ("2024-12", "2025-01", "2025-02", "2025-03", "2025-04")
CAPITAL = 1_000_000
OBSERVE = """
plot(initialSize, title="Initial units")
plot(longCondition ? 1:0, title="Pivot long")
plot(shortCondition ? 1:0, title="Pivot short")
plot(longBBCondition ? 1:0, title="Band long")
plot(shortBBCondition ? 1:0, title="Band short")
plot(htf_is_pivot_low ? 1:0, title="Daily low pivot")
plot(htf_is_pivot_high ? 1:0, title="Daily high pivot")
plot(strategy.position_size, title="Position")
"""


def sources(work, feeds, market, receipts):
    raw = feeds / f"5411-feed-{market}.json"
    assert sha256(raw) == FEEDS[market]
    rows = [r for r in read(raw) if START <= r[0] < SWITCH]
    for file in verified_archives(work, market, "1d", MONTHS, receipts):
        rows.extend(r for r in raw_ohlcv(file, DAY) if SWITCH <= r[0] < END)
    assert [r[0] for r in rows] == list(range(START, END, DAY))
    assert all(r[5] > 0 for r in rows)
    return [dict(zip(FIELDS, r, strict=True)) for r in rows]


def bands(chart):
    values = [b["close"] for b in chart]
    rsi = rsi14(values)
    limits = [None] * 19
    for i in range(19, len(values)):
        scope = values[i - 19 : i + 1]
        mean = fmean(scope)
        half = 2 * pstdev(scope, mu=mean)
        limits.append((mean - half, mean + half))
    long = [0] * 20
    short = [0] * 20
    for i in range(20, len(values)):
        bottom, top = limits[i]
        prior_bottom, prior_top = limits[i - 1]
        long.append(
            int(rsi[i] < 30 and values[i] < bottom and values[i - 1] >= prior_bottom)
        )
        short.append(
            int(rsi[i] > 70 and values[i] > top and values[i - 1] <= prior_top)
        )
    return long, short


def native(engine, source, chart, market):
    options = {
        "chart_symbol": f"BINANCE:{market}",
        "chart_timeframe": "D",
        "request_bars": {
            "$chart": {
                "minMove": 1,
                "priceScale": 100,
                "pointValue": 1,
                "quantityStep": "0.001",
                "minContract": "0.001",
                "currency": "USDT",
            }
        },
    }
    exact = engine.run_script(source, chart, **options)
    observed = engine.run_script(source + OBSERVE, chart, **options)
    report = exact["strategy"]
    assert report == observed["strategy"] and not observed["diagnostics"]
    assert not report["orders"] and not report["trades"] and not report["position"]
    plots = {x["title"]: x["values"] for x in observed["plots"]}
    expected = CAPITAL * 0.01 / 9
    assert plots["Position"] == [0] * len(chart)
    assert all(math.isclose(q, expected, abs_tol=1e-10) for q in plots["Initial units"])
    assert all(row["equity"] == CAPITAL for row in report["equity"])
    assert not any(plots["Pivot long"]) and not any(plots["Pivot short"])
    long, short = bands(chart)
    assert plots["Band long"] == long and plots["Band short"] == short
    low_curve = [b["low"] for b in chart]
    high_curve = [b["high"] for b in chart]
    daily_lows = [0] * 4
    daily_highs = [0] * 4
    for i in range(4, len(chart)):
        daily_lows.append(
            int(
                low_curve[i - 2]
                < min(
                    low_curve[i - 4], low_curve[i - 3], low_curve[i - 1], low_curve[i]
                )
            )
        )
        daily_highs.append(
            int(
                high_curve[i - 2]
                > max(
                    high_curve[i - 4],
                    high_curve[i - 3],
                    high_curve[i - 1],
                    high_curve[i],
                )
            )
        )
    assert (
        daily_lows == plots["Daily low pivot"]
        and daily_highs == plots["Daily high pivot"]
    )
    assert all(expected * b["low"] > CAPITAL for b in chart)
    attempted = [
        {
            "signal_time": chart[i]["time"],
            "fill_eligible_time": chart[i + 1]["time"],
            "side": "long" if long[i] else "short",
            "units": expected,
            "required_collateral_USDT": expected * chart[i + 1]["open"],
        }
        for i in range(len(chart) - 1)
        if long[i] or short[i]
    ]
    assert len(attempted) == len(report["diagnostics"])
    assert all(x["code"] == "E_STRATEGY_MARGIN" for x in report["diagnostics"])
    assert attempted
    return {
        "market": market,
        "bars": len(chart),
        "margin_rejections": attempted,
        "minimum_theoretical_notional_USDT": expected * min(b["low"] for b in chart),
        "starting_and_ending_equity_USDT": CAPITAL,
    }


def run(source_path, feeds, monthly, engine_root, output):
    assert sha256(source_path) == SOURCE_SHA
    assert sha256(engine_root / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(engine_root))
    import pine_compat as engine

    (src,) = re.findall(
        r"(?ms)^```[^\n]*\n(.*?)^```", source_path.read_text(encoding="utf-8")
    )
    src, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", src)
    assert n == 1
    assert "margin_long=100, margin_short=100" in src
    receipts = []
    cases = [
        native(engine, src, sources(monthly, feeds, m, receipts), m) for m in FEEDS
    ]
    meta = {
        "id": 3946,
        "group": "FMZ · Pine v6 · Original 100% margin test",
        "period": "Binance USD-M · 2024-04-11 to 2025-04-10 UTC exclusive",
        "exit": "No entry passed the source margin requirement",
        "interval": "1d",
        "archive_interval": "1d",
        "currency": "USDT",
    }
    results = [
        {**meta, "market": c["market"], **ledger_metrics([], CAPITAL, 0)} for c in cases
    ]
    results.append(
        {**meta, "market": "BTCUSDT + ETHUSDT", **ledger_metrics([], 2 * CAPITAL, 0)}
    )
    write(
        output,
        {
            "schema": "FMZ 3946 · Source collateral test",
            "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
            "source_sha256": SOURCE_SHA,
            "engine_sha256": ENGINE_SHA,
            "daily_archives_sha256": FEEDS,
            "monthly_archives": receipts,
            "notes": {
                "scope": "Exact Pine v6 on the archived 364-day Binance daily window and same-window ETH comparison. The configured higher timeframe is also daily. Pinned native and later monthly archive inputs provide all required chart bars.",
                "configured_size": "Source 100% long and short collateral, 1% initial risk setting and literal equity division by 9. With the broker's 1,000,000 USDT default equity, this requests over 1,111 base units per opening order. Minimum observed prices make the initial order exceed 100% collateral at every chart price.",
                "order_evidence": "The exact archived broker trace and instrumented trace agree. Separate 20-bar population-deviation bands and 14-period RSI reproduce the recorded order conditions. Every submitted order is rejected for insufficient margin. No position, fee, liquidation, close or win percentage is observed. DCA and partial exits therefore remain inactive in this run.",
            },
            "coverage": [
                [
                    3946,
                    "Tested · Authored 100% margin and zero fills",
                    "Exact Pine v6 on the archived daily dates. Independent Bollinger/RSI check and source sizing proof agree with nine explicit initial-order margin rejections, zero fills and undefined win rate.",
                ]
            ],
            "results": results,
            "scopes": cases,
        },
    )


if __name__ == "__main__":
    run(*map(Path, sys.argv[1:]))
