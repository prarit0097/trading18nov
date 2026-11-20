"""Assemble the #2547 report from a pinned, isolated 1h/15m replay."""

import math
import sys
from pathlib import Path

from research.fmz_round7_magnifier import iso_day, ledger_metrics, read, sha256, write

SOURCE = "ed71544916ea7904153d57868e4d51219b08448bebf55f2a4cab4696e9687bf7"
ENGINE = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
CAPITAL = 50_000
FEE = 0.00075


def finalize(work, output):
    receipt = work / "2547-verified.json"
    checked = read(receipt)
    data = read(work / "2547-inputs.json")
    assert sha256(work / "2547-replay.json") == checked["raw_sha256"]
    assert sha256(work / "source-2547.md") == SOURCE
    assert sha256(work / "priced-runtime/pine_compat/pine_compat.pyd") == ENGINE
    assert checked["missing_base_warning"] == "W_MAGNIFIER_FALLBACK"
    assert checked["session_exit_fixture"]["closed_lot"]["profit"] == 2
    isolation = read(work / "round3-isolation-python.json")
    assert set(isolation) == {"file_error", "network_error"}
    assert all(error[0] == "PermissionError" for error in isolation.values())
    cases = checked["results"]
    assert [r["market"] for r in cases] == ["BTCUSDT", "ETHUSDT"]
    attrs = {
        "id": 2547,
        "group": "FMZ · Pine Compat SMMA/EMA · Binance printed-candle replay",
        "exit": "300-tick target/stop; weekday session market close",
        "period": f"Binance USD-M · {iso_day(cases[0]['start'])} to {iso_day(cases[0]['end'])} UTC exclusive",
        "archive_interval": "1h",
        "interval": "1h",
        "currency": "USDT",
    }
    results = []
    pooled = []
    for row, feed, expected, chart_changes in zip(
        cases, data["feeds"], (138, 130), (39, 27), strict=True
    ):
        assert row["market"] == feed["market"] and row["file"] == feed["file"]
        assert sha256(work / feed["file"]) == row["sha256"] == feed["sha256"]
        assert row["finished_flat"] and len(row["ledger"]) == expected
        assert row["chart_bars"] == 720 and row["base_bars"] == 2880
        assert row["chart_vs_full_base_changed_lots"] == chart_changes
        assert row["zero_print_timestamps"] == feed["zero_print_timestamps"]
        lots = []
        for trade in row["ledger"]:
            side = {"long": 1, "short": -1}[trade["id"]]
            assert trade["qty"] == side
            assert trade["entryTime"] == trade["exitTime"]
            assert trade["entryTime"] <= trade["effective_entry"] <= trade["effective_exit"]
            assert trade["effective_exit"] < trade["exitTime"] + 3_600_000
            assert row["start"] <= trade["entryTime"] < row["end"]
            entry, exit_price = trade["entryPrice"], trade["exitPrice"]
            gross = side * (exit_price - entry)
            fee = FEE * (entry + exit_price)
            assert math.isclose(trade["profit"], gross, abs_tol=1e-8)
            assert math.isclose(trade["modeled_fees"], fee, abs_tol=1e-8)
            assert math.isclose(trade["after_fee_pnl"], gross - fee, abs_tol=1e-8)
            lots.append(
                {
                    **trade,
                    "exitTime": trade["effective_exit"],
                    "dir": side,
                    "qty": 1,
                    "commission": fee,
                    "profit": gross - fee,
                }
            )
        metrics = ledger_metrics(lots, CAPITAL, 0)
        assert math.isclose(metrics["gross"], row["primary_gross"], abs_tol=1e-8)
        assert math.isclose(metrics["after_fees"], row["primary_after_fees"], abs_tol=1e-8)
        results.append({**attrs, "market": row["market"], **metrics})
        pooled.extend(lots)
    results.append(
        {
            **attrs,
            "market": "BTCUSDT + ETHUSDT",
            **ledger_metrics(pooled, CAPITAL * 2, 0),
        }
    )
    report = {
        "schema": "FMZ 2547 Pine v4 and verified printed 15m path",
        "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
        "source_sha256": SOURCE,
        "source_url": "https://www.fmz.com/strategy/433113",
        "engine_sha256": ENGINE,
        "verified_sha256": sha256(receipt),
        "input_data": data,
        "isolation": isolation,
        "model": {
            "venue": "Saved Binance USD-M BTCUSDT date window and 1h/15m periods, with a separate ETHUSDT replay. UTC date and venue session assumptions are explicit.",
            "instrument_metadata": {
                "BTCUSDT": {"tick_usdt": 0.1, "quantity_step": 0.001},
                "ETHUSDT": {"tick_usdt": 0.01, "quantity_step": 0.001},
            },
            "source": "The archived dotted capital assignment fails to compile and its only literal is relocated to the declaration. Legacy v4 and weekday-preserving v5 controls match all chart-only numeric observations and broker output. The v5 replay also takes the archived 15m base feed.",
            "signals": "Three hl2 SMMAs (3/6/9), one close SMMA (50) and one close EMA (200) must be strictly stacked with price. The archived time condition permits entries at any hour. The close-all rule checks weekday 03:00–10:45 UTC membership at the 1h bar open. Separate dead date gates and size calculation remain in the program.",
            "execution": "One-unit next-open market entry, 300-tick bracket, archived 15m child OHLC endpoint order. The primary BTC ledger omits five official zero-print children from broker traversal only, preserving all 720 archived signal bars. The affected market entry uses the first positive-activity 15m open. Binance candles do not establish historical executable quotes, depth, or guaranteed fills.",
            "costs": "Two independent 50,000-USDT starting books. The native zero commission result defines gross P&L. The independent 0.075% per-side fee overlay leaves fills unchanged. Funding, spread and slippage are outside this accounting model. Drawdown uses time-aligned closed-trade equity.",
        },
        "coverage": [
            [
                2547,
                "Tested · Pine v4 SMMA/EMA and printed 15m execution",
                "Saved BTC 1h/15m and cross-asset ETH, 268 independently verified closes. Five BTC zero-print base candles retained for signals but skipped for execution, with one disclosed lot difference.",
            ]
        ],
        "results": results,
        "cases": cases,
        "legacy_compile_error": checked["legacy_compile_error"],
        "missing_base_warning": checked["missing_base_warning"],
        "session_exit_fixture": checked["session_exit_fixture"],
        "raw_sha256": checked["raw_sha256"],
    }
    write(output, report)


if __name__ == "__main__":
    finalize(*map(Path, sys.argv[1:]))
