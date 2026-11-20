"""Aggregate settled replay evidence for FMZ #2864."""

import math
import sys
from collections import defaultdict
from pathlib import Path

from research.fmz_round7_magnifier import iso_day, ledger_metrics, read, sha256, write

SOURCE_SHA = "bf53b40fbca165ea4ddc50c9a3c254e59e8ae8cc997a3df4776e3e730e534d08"
FEE_OVERLAY = 0.00075
CAPITAL = 1000


def finalize(work, output):
    raw_path = work / "2864-replay.json"
    raw = read(raw_path)
    assert sha256(work / "source-2864.md") == SOURCE_SHA
    assert len(raw["runs"]) == 4 and sum(r["bars"] for r in raw["runs"]) == 264_960
    isolation = read(work / "round3-isolation-python.json")
    assert set(isolation) == {"file_error", "network_error"}
    assert all(error[0] == "PermissionError" for error in isolation.values())
    cases = defaultdict(list)
    for run in raw["runs"]:
        assert sha256(work / run["file"]) == run["sha256"]
        closed = []
        unsettled = int(run["ending_position"] is not None)
        assert run["closed"] == len(run["ledger"])
        assert run["fills"] == 2 * run["closed"] + unsettled
        for trade in run["ledger"]:
            assert run["start"] <= trade["entryTime"] < trade["exitTime"] < run["stop"]
            assert trade["qty"] < 0 and trade["id"] == "Short"
            qty = abs(trade["qty"])
            gross = qty * (trade["entryPrice"] - trade["exitPrice"])
            overlay = FEE_OVERLAY * qty * (trade["entryPrice"] + trade["exitPrice"])
            assert math.isclose(gross, trade["profit"], abs_tol=1e-8)
            assert math.isclose(overlay, trade["fee_sensitivity"], abs_tol=1e-8)
            assert math.isclose(
                gross - overlay, trade["after_fee_sensitivity"], abs_tol=1e-8
            )
            closed.append(
                {
                    **trade,
                    "dir": -1,
                    "qty": qty,
                    "commission": overlay,
                    "profit": gross - overlay,
                }
            )
        cases[run["start"], run["stop"]].append((run["market"], closed, unsettled))

    results = []
    for (start, stop), markets in sorted(cases.items()):
        assert [market for market, _, _ in markets] == ["BTCUSDT", "ETHUSDT"]
        attrs = {
            "id": 2864,
            "group": "FMZ · Pine Compat same-context session VWAP",
            "exit": "Archived RSI threshold or delayed crossunder",
            "period": f"Binance USD-M · {iso_day(start)} to {iso_day(stop)} UTC exclusive",
            "archive_interval": "1m",
            "interval": "1m",
            "currency": "USDT",
        }
        for market, trades, unsettled in markets:
            results.append(
                {
                    **attrs,
                    "market": market,
                    **ledger_metrics(trades, CAPITAL, unsettled),
                }
            )
        pooled = [lot for _, trades, _ in markets for lot in trades]
        open_count = sum(unsettled for _, _, unsettled in markets)
        results.append(
            {
                **attrs,
                "market": "BTCUSDT + ETHUSDT",
                **ledger_metrics(pooled, CAPITAL * 2, open_count),
            }
        )

    report = {
        "schema": "Pine Compat FMZ 2864 archived-source replay",
        "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
        "source_sha256": SOURCE_SHA,
        "source_url": "https://www.fmz.com/strategy/437003",
        "raw_ledger_sha256": sha256(raw_path),
        "isolation": isolation,
        "model": {
            "venue": "Binance USD-M perpetuals, BTCUSDT archive and ETHUSDT cross-asset replay",
            "calendar": "UTC midnight session VWAP anchor, calculated from one-minute close and volume",
            "original": "USD-M account denominated in USDT, capital 1,000, 50 percent position sizing, no commission or slippage declared, next opening price",
            "fee_overlay": "0.075 percent per side applied to archived settled fills with quantity held fixed",
            "scope": "Original chart resolution setting is empty and Laguerre is disabled. Other user-input settings are outside this study.",
        },
        "coverage": [
            [
                2864,
                "Tested · Pine Compat VWAP source migration",
                "Verified migrated original short-only rules, authored minute chart and default same-context request, 264,960 actual Binance USD-M chart bars and a settled-ledger oracle.",
            ]
        ],
        "results": results,
        **raw,
    }
    write(output, report)


if __name__ == "__main__":
    finalize(*map(Path, sys.argv[1:]))
