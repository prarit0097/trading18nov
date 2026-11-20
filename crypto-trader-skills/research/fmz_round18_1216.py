"""Freeze the #1216 same-signal chart and five-minute bracket comparison."""

import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

from research.fmz_round7_magnifier import iso_day, ledger_metrics, read, sha256, write

SOURCE_SHA = "784b4554332fba13d142f8e0d58c17110190dfd8fa1b96b5b61f96160e219eee"
ENGINE_SHA = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
CAPITAL = 50_000
FEE = 0.00075


def finalize(work, output):
    path = work / "1216-verified.json"
    checked = read(path)
    raw = work / "1216-probe.json"
    data = read(work / "1216-inputs.json")
    assert sha256(work / "source-1216.md") == SOURCE_SHA
    assert sha256(work / "priced-runtime/pine_compat/pine_compat.pyd") == ENGINE_SHA
    assert sha256(raw) == checked["raw_probe_sha256"]
    assert read(raw)["archive_error"] == [
        "E_PARSE_EXPR:Error:6:26: expected expression"
    ]
    assert checked["synthetic_ordering"] == {
        "coarse_exit": 95,
        "five_minute_high_first": 110,
        "five_minute_low_first": 95,
    }
    assert checked["missing_group_warning"] == "W_MAGNIFIER_FALLBACK"
    isolation = read(work / "round3-isolation-python.json")
    assert set(isolation) == {"file_error", "network_error"}
    assert all(error[0] == "PermissionError" for error in isolation.values())
    runs = checked["cases"]
    assert len(runs) == len(data["samples"]) == 6
    assert sum(row["chart_bars"] for row in runs) == 19_008
    assert sum(row["base_bars"] for row in runs) == 57_024
    assert [row["closed"] for row in runs] == [0, 0, 5, 4, 5, 5]
    windows = defaultdict(list)
    flips = Counter()
    for row, ref in zip(runs, data["samples"], strict=True):
        assert sha256(work / row["file"]) == row["sha256"] == ref["sha256"]
        assert (
            row["closed"]
            == row["signal_count"]
            == len(row["base_ledger"])
            == len(row["chart_ledger"])
        )
        for item in row["chart_base_differences"]:
            flips[f"{item['chart_reason']} to {item['base_reason']}"] += 1
        lots = []
        for trade in row["base_ledger"]:
            side = {"long": 1, "short": -1}[trade["id"]]
            assert trade["qty"] == side
            assert row["start"] <= trade["entryTime"] == trade["exitTime"] < row["end"]
            assert (
                trade["entryTime"]
                <= trade["first_base_time"]
                < trade["entryTime"] + 15 * 60_000
            )
            gross = side * (trade["exitPrice"] - trade["entryPrice"])
            fee = FEE * (trade["entryPrice"] + trade["exitPrice"])
            assert math.isclose(gross, trade["profit"], abs_tol=1e-8)
            assert math.isclose(fee, trade["fee_sensitivity"], abs_tol=1e-8)
            assert math.isclose(
                gross - fee, trade["after_fee_sensitivity"], abs_tol=1e-8
            )
            lots.append(
                {
                    **trade,
                    "dir": side,
                    "qty": 1,
                    "commission": fee,
                    "profit": gross - fee,
                }
            )
        windows[row["start"], row["end"]].append((row["market"], lots))
    assert flips == {"target to stop": 5, "stop to target": 1}
    results = []
    for (start, stop), markets in sorted(windows.items()):
        assert [m for m, _ in markets] == ["BTCUSDT", "ETHUSDT"]
        attrs = {
            "id": 1216,
            "group": "FMZ · Pine Compat 15m chart and 5m execution",
            "exit": "Archived 50-tick target and 100-tick stop",
            "period": f"Binance USD-M · {iso_day(start)} to {iso_day(stop)} UTC exclusive",
            "archive_interval": "15m",
            "interval": "15m",
            "currency": "USDT",
        }
        for market, lots in markets:
            results.append(
                {**attrs, "market": market, **ledger_metrics(lots, CAPITAL, 0)}
            )
        pooled = [trade for _, lots in markets for trade in lots]
        results.append(
            {
                **attrs,
                "market": "BTCUSDT + ETHUSDT",
                **ledger_metrics(pooled, 2 * CAPITAL, 0),
            }
        )
    report = {
        "schema": "FMZ 1216 Pine Compat matched five-minute bracket evidence",
        "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
        "source_sha256": SOURCE_SHA,
        "source_url": "https://www.fmz.com/strategy/428000",
        "engine_sha256": ENGINE_SHA,
        "input_data": data,
        "verified_sha256": sha256(path),
        "isolation": isolation,
        "flip_counts": dict(flips),
        "notes": {
            "legacy": "The sole unsupported property assignment moves its 50,000-USDT literal to the strategy declaration. Relocated v4 and converted v5 have identical chart-only broker output with explicit v4-equivalent weekday calendars.",
            "signals": "Three DEMA curves, both weekday sessions and all four source crossover outputs match independent calculations. Duplicate overlapping-session signals settle as one entry. The actual source order quantity is one.",
            "broker": "The five-minute execution variant explicitly enables Pine Compat Bar Magnifier using the saved 5m base and original 15m chart. Every admitted entry and exit reference matches an independent five-minute first-contact model. The model uses the native OHLC path within each five-minute candle.",
            "prices": "Parent timestamps come from Pine Compat. The independent audit also records the first effective five-minute candle for every selected exit.",
            "fees": "The original strategy declares no commission. The report overlays 0.075% per side on the verified fills with realized drawdown.",
        },
        "coverage": [
            [
                1216,
                "Tested · Pine Compat DEMA and 5m brackets",
                "Weekday-preserving v4 and v5 source controls match. Saved BTC/ETH dates produce zero fills. Two comparison windows close 19 positions, six with changed bracket outcomes on the complete five-minute base.",
            ]
        ],
        "results": results,
        **checked,
    }
    write(output, report)


if __name__ == "__main__":
    finalize(*map(Path, sys.argv[1:]))
