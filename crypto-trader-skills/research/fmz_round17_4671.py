"""Freeze the dated #4671 Pine v4 standalone variants and fee metrics."""

import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

from research.fmz_round7_magnifier import iso_day, ledger_metrics, read, sha256, write

SOURCE_SHA = "bc4aa004c953721da57d29dbfafe1f192606a50efae5ee70e4e890d5d84c3013"
ENGINE_SHA = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
CAPITAL = 50_000
FEE_OVERLAY = 0.00075


def finalize(work, output):
    raw_path = work / "4671-replay.json"
    raw = read(raw_path)
    assert sha256(work / "wallet-4671.md") == SOURCE_SHA
    assert sha256(work / "priced-runtime/pine_compat/pine_compat.pyd") == ENGINE_SHA
    author = read(work / "4671-author-data.json")
    isolation = read(work / "round3-isolation-python.json")
    assert set(isolation) == {"file_error", "network_error"}
    assert all(error[0] == "PermissionError" for error in isolation.values())
    assert len(raw["runs"]) == 6
    assert sum(row["chart_bars"] for row in raw["runs"]) == 5856
    assert sum(row["base_bars"] for row in raw["runs"]) == 23424
    assert [r["closed"] for r in raw["runs"]] == [4, 3, 4, 7, 2, 8]
    assert sum(row["native_orders"] for row in raw["runs"]) == 56
    cases = defaultdict(list)
    reasons = Counter()
    for row in raw["runs"]:
        file = work / row["file"]
        assert sha256(file) == row["sha256"]
        if row["sample"] != "FMZ archived dates":
            file = work / f"native-base-{row['market']}-{iso_day(row['start'])}.json"
        assert sha256(file) == row["base_sha"]
        assert row["ending_position"]["size"] == 0
        assert row["native_orders"] == row["closed"] * 2
        for control in row["base_stop_controls"]:
            assert math.isclose(
                control["native_price"],
                control["base_open_model_price"],
                rel_tol=0,
                abs_tol=1e-8,
            )
        closes = []
        for trade in row["ledger"]:
            side = {"long": 1, "short": -1}[trade["id"]]
            assert trade["qty"] == side
            assert row["start"] <= trade["entryTime"] <= trade["exitTime"] < row["stop"]
            gross = side * (trade["exitPrice"] - trade["entryPrice"])
            fee = FEE_OVERLAY * (trade["entryPrice"] + trade["exitPrice"])
            assert math.isclose(gross, trade["profit"], abs_tol=1e-8)
            assert math.isclose(fee, trade["fee_sensitivity"], abs_tol=1e-8)
            assert math.isclose(
                gross - fee, trade["after_fee_sensitivity"], abs_tol=1e-8
            )
            reasons[trade["reason"]] += 1
            closes.append(
                {
                    **trade,
                    "dir": side,
                    "qty": 1,
                    "commission": fee,
                    "profit": gross - fee,
                }
            )
        assert len(closes) == row["closed"]
        cases[row["start"], row["stop"]].append((row["market"], closes))
    assert reasons == {"stop": 27, "session_market": 1}
    results = []
    for (start, stop), markets in sorted(cases.items()):
        assert [name for name, _ in markets] == ["BTCUSDT", "ETHUSDT"]
        attrs = {
            "id": 4671,
            "group": "FMZ · Pine Compat standalone v4 · 50k capital variant",
            "exit": "Archived session market close or 66-tick stop",
            "period": f"Binance USD-M · {iso_day(start)} to {iso_day(stop)} UTC exclusive",
            "archive_interval": "1h",
            "interval": "1h",
            "currency": "USDT",
        }
        for market, closes in markets:
            results.append(
                {**attrs, "market": market, **ledger_metrics(closes, CAPITAL, 0)}
            )
        pooled = [lot for _, closes in markets for lot in closes]
        results.append(
            {
                **attrs,
                "market": "BTCUSDT + ETHUSDT",
                **ledger_metrics(pooled, CAPITAL * 2, 0),
            }
        )
    assert len(results) == 9
    report = {
        "schema": "Pine Compat FMZ 4671 standalone v4 evidence",
        "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
        "source_sha256": SOURCE_SHA,
        "source_url": "https://www.fmz.com/strategy/428812",
        "engine_sha256": ENGINE_SHA,
        "raw_sha256": sha256(raw_path),
        "authored_market_inputs": author,
        "isolation": isolation,
        "close_reasons": dict(reasons),
        "variant_assumptions": {
            "declaration": "Archive strategy declaration is commented, and the active dotted property assignment fails Pine compilation. Standalone results declare 50,000-USDT capital from the active literal and retain the authored order body.",
            "comparison": "A second run restores the commented 10,000-USDT declaration and 0.00008 per-contract fee. All orders, positions and trade prices match the 50,000-USDT version, and each closed trade differs by the verified two per-contract fees.",
            "calendar": "Saved UTC date range with v4 weekday session defaults, one-hour chart and validated 15m base candles. 03:00 UTC decisions fill at the next open, and the market exit condition evaluates outside 03:00–09:45.",
            "quantity": "The archive computes a size value for reference; the actual entry arguments use the broker's one-unit default. Loss is 66 ticks from each original fill.",
            "fees": "Main declaration applies zero commission. The sensitivity subtracts 0.075% per side from the same settled fills. The report uses realized drawdown.",
        },
        "coverage": [
            [
                4671,
                "Tested · Pine Compat standalone v4 variant",
                "Archive-effective order body, disclosed 50,000 capital assumption, and matching alternative commented-header fills. 28 settled BTC/ETH trades with 15m fill and stop reconciliation.",
            ]
        ],
        "results": results,
        **raw,
    }
    write(output, report)


if __name__ == "__main__":
    finalize(*map(Path, sys.argv[1:]))
