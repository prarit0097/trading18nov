"""Assemble verified dated #4703 trade and drawdown metrics."""

import math
import sys
from pathlib import Path

from research.fmz_round7_magnifier import iso_day, ledger_metrics, read, sha256, write

SOURCE_SHA = "ee96c4e55874f22138b783482d1c5213122014fd1f133fceea83403c6b5e6d27"
ENGINE_SHA = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
CAPITAL = 1_000_000
FEE_OVERLAY = 0.00075


def finalize(work, output):
    path = work / "4703-verified.json"
    evidence = read(path)
    assert sha256(work / "source-4703.md") == SOURCE_SHA
    assert sha256(work / "priced-runtime/pine_compat/pine_compat.pyd") == ENGINE_SHA
    assert sha256(work / "4703-probe.json") == evidence["native_sha256"]
    isolation = read(work / "round3-isolation-python.json")
    assert set(isolation) == {"file_error", "network_error"}
    assert all(error[0] == "PermissionError" for error in isolation.values())
    runs = evidence["runs"]
    assert [case["market"] for case in runs] == ["BTCUSDT", "ETHUSDT"]
    assert [case["trades"] for case in runs] == [1, 10]
    assert sum(case["orders"] for case in runs) == 24
    assert sum(len(case["hourly_quotes"]) for case in runs) == 14
    results = []
    pooled = []
    period = f"Binance USD-M · {iso_day(runs[0]['chart_start'])} to {iso_day(runs[0]['chart_stop'])} UTC exclusive"
    attrs = {
        "id": 4703,
        "group": "FMZ · Pine Compat original daily pivot",
        "exit": "Archived prior-close-relative tick stop",
        "period": period,
        "archive_interval": "1d",
        "interval": "1d",
        "currency": "USDT",
    }
    for row in runs:
        assert row["chart_bars"] == 371 and row["ending_position"]["size"] == 1
        assert sha256(work / f"5411-feed-{row['market']}.json") == row["daily_sha256"]
        assert len(row["execution_checks"]) == row["orders"]
        assert row["orders"] == row["trades"] * 2 + 1
        for record in row["hourly_quotes"]:
            assert sha256(work / record["file"]) == record["sha256"]
        for fill in row["execution_checks"]:
            assert math.isclose(
                fill["broker_price"], fill["base_price"], rel_tol=0, abs_tol=1e-8
            )
        lots = []
        for lot in row["ledger"]:
            assert lot["id"] == "buy" and lot["qty"] == 1
            assert (
                row["chart_start"]
                <= lot["entryTime"]
                <= lot["exitTime"]
                < row["chart_stop"]
            )
            gross = lot["exitPrice"] - lot["entryPrice"]
            fee = FEE_OVERLAY * (lot["exitPrice"] + lot["entryPrice"])
            assert math.isclose(gross, lot["profit"], abs_tol=1e-8)
            assert math.isclose(fee, lot["fee_sensitivity"], abs_tol=1e-8)
            assert math.isclose(gross - fee, lot["after_fee_sensitivity"], abs_tol=1e-8)
            lots.append({**lot, "dir": 1, "commission": fee, "profit": gross - fee})
        assert len(lots) == row["trades"]
        results.append(
            {**attrs, "market": row["market"], **ledger_metrics(lots, CAPITAL, 1)}
        )
        pooled.extend(lots)
    results.append(
        {
            **attrs,
            "market": "BTCUSDT + ETHUSDT",
            **ledger_metrics(pooled, CAPITAL * 2, 2),
        }
    )
    report = {
        "schema": "Pine Compat FMZ 4703 archived daily pivot replay",
        "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
        "source_sha256": SOURCE_SHA,
        "source_url": "https://www.fmz.com/strategy/434581",
        "engine_sha256": ENGINE_SHA,
        "verified_sha256": sha256(path),
        "isolation": isolation,
        "notes": {
            "venue": "The archived Binance BTCUSDT daily chart and independent ETHUSDT cross-asset replay use the saved 2022-11-30 through 2023-12-06 UTC window.",
            "time": "A fixed UTC clock at the saved end supplies the archived display-only timenow values. The daily chart opens at calendar hour zero UTC, which is within the entry rule and leaves the hour-15 close inactive.",
            "daily_request": "The exact v4 script requests the same daily chart's previous-day H/L/C and uses their mean as a pivot. The independent checks prove those values lag one full bar, accounting for the generic Pine lookahead warning. A guard-only control suppresses the two unavailable first-bar stop calls with identical broker outputs.",
            "orders": "One-unit market entry at the next daily open. The protective stop uses the prior close times 0.5 as a tick distance. Reconstructed every fill price using independently checked one-hour data for execution days.",
            "fees": "The archived model's zero commission defines gross P&L. The 0.075% per-side overlay leaves fills and quantities fixed. Drawdown uses realized equity; two positions remain open at the end.",
        },
        "coverage": [
            [
                4703,
                "Tested · exact Pine v4 daily pivot replay",
                "Source-aligned UTC dates and native v4. Verified one-day-lag pivot and dynamic stops, 24 fill prices reconciled to official hourly quotes and 11 closed lots.",
            ]
        ],
        "results": results,
        **evidence,
    }
    write(output, report)


if __name__ == "__main__":
    finalize(*map(Path, sys.argv[1:]))
