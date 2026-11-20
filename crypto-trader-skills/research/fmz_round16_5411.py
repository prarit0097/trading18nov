"""Publish the verified #5411 no-fill outcomes for BTC and ETH."""

import sys
from pathlib import Path

from research.fmz_round7_magnifier import iso_day, ledger_metrics, read, sha256, write

SOURCE_SHA = "2ad55037d1ca1b62514f9c577bd9bd00b9c6c0128c46da53e3e1639284792e9d"
ENGINE_SHA = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
CAPITAL = 1_000_000


def finalize(work, output):
    verified_path = work / "5411-verified.json"
    data = read(verified_path)
    data["input_data"]["timezone_convention"] = (
        "FMZ host header wall times interpreted as UTC"
    )
    assert sha256(work / "source-5411.md") == SOURCE_SHA
    assert sha256(work / "priced-runtime/pine_compat/pine_compat.pyd") == ENGINE_SHA
    assert sha256(work / "5411-probe.json") == data["chart_run_sha256"]
    assert data["input_data"]["clock"] == 1_733_731_200_000
    assert data["input_data"]["gate"] == 1_731_110_400_000
    assert all(
        row["bars"] == 1812 and row["eligible_archive_checks"] == 30
        for row in data["input_data"]["history"]
    )
    for row in data["input_data"]["history"]:
        assert sha256(work / row["file"]) == row["sha256"]
    assert [row["market"] for row in data["runs"]] == ["BTCUSDT", "ETHUSDT"]
    first, last = (iso_day(data["input_data"][key]) for key in ("gate", "clock"))
    results = []
    for run in data["runs"]:
        assert run["filled_orders"] == run["closed"] == 0
        assert run["submitted_limits"] == 30 and run["tested_next_day_limits"] == 29
        clearance = min(row[-1] for row in run["interactions"])
        assert clearance == run["minimum_untouched_clearance"] > 0
        results.append(
            {
                "id": 5411,
                "group": "FMZ · Pine Compat fixed archived UTC clock",
                "exit": "Archived EMA limit entry and bracket",
                "period": f"Binance USD-M · {first} to {last} UTC exclusive",
                "archive_interval": "1d",
                "interval": "1d",
                "currency": "USDT",
                "market": run["market"],
                "submitted_limits": run["submitted_limits"],
                "tested_next_day_limits": run["tested_next_day_limits"],
                "filled_orders": run["filled_orders"],
                **ledger_metrics([], CAPITAL, 0),
            }
        )
    assert set(data["positive_synthetic_controls"]) == {
        "touch_then_stop",
        "touch_then_target",
        "gap_then_stop",
    }
    isolation = read(work / "round3-isolation-python.json")
    assert set(isolation) == {"file_error", "network_error"}
    assert all(error[0] == "PermissionError" for error in isolation.values())
    report = {
        "schema": "Pine Compat FMZ 5411 archived fixed-clock coverage",
        "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
        "source_sha256": SOURCE_SHA,
        "source_url": "https://www.fmz.com/strategy/474633",
        "engine_sha256": ENGINE_SHA,
        "verified_run_sha256": sha256(verified_path),
        "isolation": isolation,
        "disposition": "Verified no fills and zero positions during the saved UTC-aligned replay.",
        "coverage": [
            [
                5411,
                "Tested · archived fixed clock, zero fills",
                "Exact source. Fixed UTC replay clock, 1,812 genuine daily candles per Binance USD-M BTC/ETH market, 30 eligible submissions, 29 untouched subsequent lows, and zero fills per market.",
            ]
        ],
        "results": results,
        **data,
    }
    write(output, report)


if __name__ == "__main__":
    finalize(*map(Path, sys.argv[1:]))
