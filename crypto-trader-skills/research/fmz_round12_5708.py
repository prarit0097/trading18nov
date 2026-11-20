"""Summarize the source-bound #5708 Binance USD-account experiments."""

import math
import sys
from collections import defaultdict
from pathlib import Path

from research.fmz_round7_magnifier import iso_day, ledger_metrics, read, sha256, write
from research.fmz_round8_fx import prior_close_rates

CAPITAL = 100_000
FEE_OVERLAY = 0.00075
DAY = 86_400_000
ARCHIVE = "https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E9%AB%98%E7%82%B9%E4%BD%8E%E7%82%B9%E7%AA%81%E7%A0%B4%E8%B6%8B%E5%8A%BF%E8%BF%BD%E8%B8%AA%E7%AD%96%E7%95%A5High-Low-Breakout-Trend-Following-Strategy.md"
FX_URL = "https://api.exchange.coinbase.com/products/USDT-USD/candles?granularity=86400&start=2026-07-31T00%3A00%3A00Z&end=2026-11-01T00%3A00%3A00Z"


def finalize(work, output):
    raw_path = work / "replay-5708.json"
    raw = read(raw_path)
    source = work / "source-5708.md"
    assert (
        sha256(source)
        == "5ba5718671a7c169e75e826206af348f7b201c57903f1b392d7bb073e8966cdf"
    )
    assert [case["closed"] for case in raw["cases"]] == [10, 15, 8, 17]
    assert sum(case["intrabar_reversals"] for case in raw["cases"]) == 0
    assert all(case["official_15m_sensitivity"]["match"] for case in raw["cases"])
    assert sum(case["chart_bars"] for case in raw["cases"]) == 4416
    assert sum(case["fills"] for case in raw["cases"]) == 54
    original_fx = work / "coinbase-usdt-usd-daily.json"
    assert sha256(original_fx) == raw["fx_sha256"]
    rates = {
        row["effectiveTime"]: row["rate"]
        for row in prior_close_rates(read(original_fx))["pairs"][0]["rates"]
    }
    isolation = read(work / "round3-isolation-python.json")
    assert set(isolation) == {"file_error", "network_error"}
    assert all(info[0] == "PermissionError" for info in isolation.values())

    cases = defaultdict(list)
    for case in raw["cases"]:
        assert sha256(work / case["feed"]) == case["feed_sha256"]
        lower = case["official_15m_sensitivity"]
        assert sha256(work / lower["name"]) == lower["sha256"]
        assert case["ending_position"]["size"] != 0
        close = []
        for trade in case["ledger"]:
            side = {"Long": 1, "Short": -1}[trade["id"]]
            ent_rate = rates[trade["entryTime"] // DAY * DAY]
            ext_rate = rates[trade["exitTime"] // DAY * DAY]
            qty = abs(trade["qty"])
            ent, ext = trade["entryPrice"], trade["exitPrice"]
            gross = side * (ext - ent) * qty * ext_rate
            fee = FEE_OVERLAY * qty * (ent * ent_rate + ext * ext_rate)
            assert math.isclose(gross, trade["profit"], rel_tol=1e-9, abs_tol=1e-7)
            assert math.isclose(
                fee, trade["fee_sensitivity"], rel_tol=1e-9, abs_tol=1e-7
            )
            assert math.isclose(
                gross - fee, trade["after_fee_sensitivity"], rel_tol=1e-9, abs_tol=1e-7
            )
            close.append(
                {
                    **trade,
                    "dir": side,
                    "qty": qty,
                    "entryPrice": ent * ext_rate,
                    "exitPrice": ext * ext_rate,
                    "commission": fee,
                    "profit": gross - fee,
                }
            )
        cases[case["start"], case["end"]].append((case["market"], close))

    results = []
    for (start, end), markets in sorted(cases.items()):
        assert [market for market, _ in markets] == ["BTCUSDT", "ETHUSDT"]
        attrs = {
            "id": 5708,
            "group": "FMZ · Pine Compat v1 migration · Coinbase prior-day FX",
            "exit": "Archived opposite-direction reversal",
            "period": f"Binance USD-M · {iso_day(start)} to {iso_day(end)} UTC exclusive",
            "archive_interval": "1h",
            "interval": "1h",
            "currency": "USD",
        }
        for market, close in markets:
            results.append(
                {**attrs, "market": market, **ledger_metrics(close, CAPITAL, 1)}
            )
        pooled = [lot for _, close in markets for lot in close]
        results.append(
            {
                **attrs,
                "market": "BTCUSDT + ETHUSDT",
                **ledger_metrics(pooled, CAPITAL * 2, 2),
            }
        )

    output_report = {
        "schema": "Pine Compat FMZ 5708 archived-source replay",
        "source_url": ARCHIVE,
        "source_archive_sha256": sha256(source),
        "runtime_engine_commit": "c0ecc3bde5eece9c4f2a63c6785aec9c5e571acc",
        "raw_ledger_sha256": sha256(raw_path),
        "fee_mode": "Archived Pine broker specifies zero fee. Report gross reproduces it. Report after_fees applies an explicit 0.075% per side sensitivity to the same verified fills without changing order sizing. Entry and exit fees use their respective prior-day FX.",
        "fx_url": FX_URL,
        "fx_policy": "Coinbase Exchange USDT-USD close from the last complete UTC day. Realized USD P&L uses the exit rate. Drawdown is based on settled trades, with open positions reported separately.",
        "instrument_note": "Archive specifies Binance USD-M BTCUSDT. ETHUSDT is an independent cross-asset research replay.",
        "historical_mode": "Source has Pine calc_on_order_fills=true, no use_bar_magnifier flag. The first 22 chart bars cannot signal without the complete lagged extrema window. All four real runs returned identical outcomes in the separately enabled, complete 15m base-data control. The synthetic callback test distinguishes 132 same-bar from 45 next-bar execution.",
        "isolation": isolation,
        "coverage": [
            [
                5708,
                "Tested · Pine Compat v1 source migration",
                "Both Binance USD-M contracts, two historical hourly windows and full no-fallback 15m base sensitivity. Source BTCUSDT, ETHUSDT cross-asset. USD prior-day Coinbase FX.",
            ]
        ],
        "results": results,
        **raw,
    }
    write(output, output_report)


if __name__ == "__main__":
    finalize(*map(Path, sys.argv[1:]))
