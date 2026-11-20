"""Aggregate #1214 legacy-effective archived reversal results."""

import math
import sys
from collections import defaultdict
from pathlib import Path

from research.fmz_round7_magnifier import iso_day, ledger_metrics, read, sha256, write

SOURCE_SHA = "a6c50779e6b2fb7e3bd76b921268e96c436e6cb131ded08263f1c25c3e01e1c9"
FEE = 0.00004
CAPITAL = 50_000


def finalize(work, output):
    raw_path = work / "1214-replay.json"
    raw = read(raw_path)
    source = work / "source-1214.md"
    assert sha256(source) == SOURCE_SHA
    runtime_sha = sha256(work / "priced-runtime/pine_compat/pine_compat.pyd")
    assert (
        runtime_sha
        == "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
    )
    assert (
        len(raw["runs"]) == 4 and sum(r["tested_bars"] for r in raw["runs"]) == 264_960
    )
    assert all(run["legacy_v4_matches"] for run in raw["runs"])
    control = read(work / "1214-legacy-control.json")
    assert (
        control["match"] and len(control["v4_errors"]) == len(control["v5_errors"]) == 4
    )
    assert control["v4_errors"] == control["v5_errors"]
    isolation = read(work / "round3-isolation-python.json")
    assert set(isolation) == {"file_error", "network_error"}
    assert all(error[0] == "PermissionError" for error in isolation.values())

    cases = defaultdict(list)
    for run in raw["runs"]:
        assert sha256(work / run["file"]) == run["sha256"]
        unsettled = int(run["ending_position"] is not None)
        assert run["orders"] == run["closed"] + unsettled
        closed = []
        for trade in run["ledger"]:
            side = {"Long": 1, "Short": -1}[trade["id"]]
            assert run["start"] <= trade["entryTime"] < trade["exitTime"] < run["stop"]
            assert trade["qty"] == side
            start, stop = trade["entryPrice"], trade["exitPrice"]
            gross = side * (stop - start)
            fee = FEE * (start + stop)
            assert math.isclose(trade["gross"], gross, abs_tol=1e-8)
            assert math.isclose(trade["fees"], fee, abs_tol=1e-8)
            assert math.isclose(trade["profit"], gross - fee, abs_tol=1e-8)
            closed.append({**trade, "dir": side, "qty": 1, "commission": fee})
        assert len(closed) == run["closed"]
        cases[run["start"], run["stop"]].append((run["market"], closed, unsettled))

    results = []
    for (start, stop), markets in sorted(cases.items()):
        assert [market for market, _, _ in markets] == ["BTCUSDT", "ETHUSDT"]
        attrs = {
            "id": 1214,
            "group": "FMZ · Pine Compat · effective v4 EMA reversals",
            "exit": "Opposite EMA signal reversal, archived legacy no-op exits",
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
        "schema": "Pine Compat FMZ 1214 effective legacy archived-source replay",
        "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
        "source_sha256": SOURCE_SHA,
        "source_url": "https://www.fmz.com/strategy/429478",
        "engine_sha256": runtime_sha,
        "legacy_semantics_documentation": "https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/#strategyexit-now-must-do-something",
        "raw_ledger_sha256": sha256(raw_path),
        "isolation": isolation,
        "compiler_controls": control,
        "model": {
            "venue": "Archived Binance USD-M BTCUSDT plus independent ETHUSDT cross-asset replay",
            "defaults": "1m candles, 50,000 capital each, fixed 1 base-asset unit, authored per-side 0.004% commission, next opening price, archived legacy margins",
            "sizing": "The initial quantity declaration is overridden by the archived explicit quantity in both entry calls.",
            "effective_exit": "The StopLoss variable is assigned but isn't passed to any exit. Four parameter-free legacy no-op calls were omitted under TradingView's documented migration. The executable exit is reversal on the opposite archived entry signal.",
            "scope": "Standalone historical broker replay. Open positions tracked separately. Realized drawdown and no funding or slippage.",
        },
        "coverage": [
            [
                1214,
                "Tested · Pine Compat effective legacy reversals",
                "The four documented parameter-free no-ops were removed. Normalized v4 and migrated v5 match complete signal and broker outputs, checked independently on 264,960 actual 1m bars.",
            ]
        ],
        "results": results,
        **raw,
    }
    write(output, report)


if __name__ == "__main__":
    finalize(*map(Path, sys.argv[1:]))
