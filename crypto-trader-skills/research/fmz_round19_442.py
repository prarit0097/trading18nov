"""Assemble the #442 source-matched USD-account performance report."""

import math
import sys
from collections import Counter
from pathlib import Path

from research.fmz_round7_magnifier import iso_day, ledger_metrics, read, sha256, write

SOURCE = "8f4d081f51bef7d668f0177dec6bea86c430c9a015dce1d5fc6657aa316b6a2f"
ENGINE = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
DAY = 86_400_000
CAPITAL = 100_000
FEE = 0.00075
FX_URL = "https://api.exchange.coinbase.com/products/USDT-USD/candles?granularity=86400&start=2023-12-12T00%3A00%3A00Z&end=2023-12-20T00%3A00%3A00Z"


def finalize(work, output):
    receipt = work / "442-verified.json"
    checked = read(receipt)
    data = read(work / "442-inputs.json")
    assert sha256(work / "442-replay.json") == checked["raw_sha256"]
    assert sha256(work / "source-442.md") == SOURCE
    assert sha256(work / "priced-runtime/pine_compat/pine_compat.pyd") == ENGINE
    fx_path = work / data["fx"]["file"]
    assert sha256(fx_path) == data["fx"]["sha256"]
    fx = {
        row["effectiveTime"]: row["rate"] for row in read(fx_path)["pairs"][0]["rates"]
    }
    assert len(fx) == 7
    assert checked["missing_base_warning"] == "W_MAGNIFIER_FALLBACK"
    assert checked["fixture"]["first_position_stays_open_through_entry_bar"]
    isolation = read(work / "round3-isolation-python.json")
    assert set(isolation) == {"file_error", "network_error"}
    assert all(error[0] == "PermissionError" for error in isolation.values())
    cases = checked["cases"]
    assert [r["market"] for r in cases] == ["BTCUSDT", "ETHUSDT"]
    assert [r["signals"] for r in cases] == [20, 21]
    attrs = {
        "id": 442,
        "group": "FMZ · Pine Compat Ichimoku/DMI · Coinbase prior-day USD FX",
        "exit": "Reserved 150/200-tick brackets or opposite order",
        "period": f"Binance USD-M · {iso_day(cases[0]['start'])} to {iso_day(cases[0]['end'])} UTC exclusive",
        "archive_interval": "30m",
        "interval": "30m",
        "currency": "USD",
    }
    results = []
    pooled = []
    reasons = Counter()
    for row in cases:
        assert row["closed"] == len(row["ledger"]) == 20
        assert (
            row["orders"] == 40 and row["chart_bars"] == 336 and row["base_bars"] == 672
        )
        assert sha256(work / row["file"]) == row["sha256"]
        lots = []
        for trade in row["ledger"]:
            side = {"buy": 1, "sel": -1}[trade["id"]]
            assert trade["qty"] == side
            assert row["start"] <= trade["entryTime"] < trade["exitTime"] < row["end"]
            assert trade["entryBarIndex"] + 1 == trade["exitBarIndex"]
            fx_open = fx[trade["entryTime"] // DAY * DAY]
            fx_close = fx[trade["exitTime"] // DAY * DAY]
            assert trade["fx_entry"] == fx_open and trade["fx_exit"] == fx_close
            entry, exit_price = trade["entryPrice"], trade["exitPrice"]
            gross = side * (exit_price - entry) * fx_close
            fee = FEE * (entry * fx_open + exit_price * fx_close)
            assert math.isclose(trade["profit"], gross, abs_tol=1e-8)
            assert math.isclose(trade["fee_sensitivity"], fee, abs_tol=1e-8)
            assert math.isclose(
                trade["after_fee_sensitivity"], gross - fee, abs_tol=1e-8
            )
            reasons[trade["reason"]] += 1
            lots.append(
                {
                    **trade,
                    "dir": side,
                    "qty": 1,
                    "entryPrice": entry * fx_close,
                    "exitPrice": exit_price * fx_close,
                    "commission": fee,
                    "profit": gross - fee,
                }
            )
        results.append(
            {**attrs, "market": row["market"], **ledger_metrics(lots, CAPITAL, 0)}
        )
        pooled.extend(lots)
    assert reasons["opposite raw order"] == 1
    assert (
        sum(
            row["reserved"].get("same_direction_add_before_reserved_exit", 0)
            for row in cases
        )
        == 4
    )
    results.append(
        {
            **attrs,
            "market": "BTCUSDT + ETHUSDT",
            **ledger_metrics(pooled, CAPITAL * 2, 0),
        }
    )
    report = {
        "schema": "FMZ 442 exact archived v2 and verified 15m USD execution",
        "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
        "source_sha256": SOURCE,
        "source_url": "https://www.fmz.com/strategy/436096",
        "engine_sha256": ENGINE,
        "verified_sha256": sha256(receipt),
        "input_data": data,
        "fx_source_url": FX_URL,
        "isolation": isolation,
        "exit_reasons": dict(reasons),
        "model": {
            "venue": "Saved Binance USD-M BTCUSDT, with a separately funded ETHUSDT cross-asset replay. Saved wall-clock dates interpreted as UTC.",
            "instrument_metadata": {
                "BTCUSDT": {"tick_usdt": 0.1, "quantity_step": 0.001},
                "ETHUSDT": {"tick_usdt": 0.01, "quantity_step": 0.001},
            },
            "source": "Original Pine v2 strategy, and a weekday-preserving v5 control with explicit legacy recurrences. Full chart-only v2/v5 and complete 15m Bar Magnifier outputs are identical.",
            "signals": "Weekdays 04:00 to 15:00 UTC, with a seven-bar Donchian midpoint crossing and a directional movement index above 20. Verified independently including initial recursive states.",
            "orders": "One-unit raw order. Its 150-tick stop and 200-tick target are reserved on the following evaluation, with exact subsequent gap or trigger prices. Four same-direction additions retain the newly opened unit after the previous lot exits. One opposite raw order settles the previous short without opening a new long.",
            "funding": "The source sets USD starting equity to 100,000. Coinbase's prior UTC closing rate translates each venue USDT cash effect. The archived zero commission defines gross results. An independent 0.075% per-side fee overlay leaves prices and quantities unchanged.",
        },
        "coverage": [
            [
                442,
                "Tested · exact Pine v2 Ichimoku/DMI with USD FX",
                "Saved Binance 30m and 15m charts on both markets. Exact v2 and matched v5 controls, forty verified closed positions and UTC prior-day USD conversion.",
            ]
        ],
        "results": results,
        **checked,
    }
    write(output, report)


if __name__ == "__main__":
    finalize(*map(Path, sys.argv[1:]))
