"""Finalize verified #3604 metrics under its declarative capital migration."""

import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

from research.fmz_round7_magnifier import iso_day, ledger_metrics, read, sha256, write

SOURCE_SHA = "901f3dcc56cbaccc1a604972e410972b92da4ac87be57818f829e33c90f35e36"
ENGINE_SHA = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
CAPITAL = 50_000
FEE_OVERLAY = 0.00075


def finalize(work, output):
    raw_path = work / "3604-replay.json"
    raw = read(raw_path)
    lower_path = work / "3604-base-control.json"
    base = read(lower_path)
    assert sha256(work / "wallet-3604.md") == SOURCE_SHA
    assert sha256(work / "priced-runtime/pine_compat/pine_compat.pyd") == ENGINE_SHA
    assert len(raw["runs"]) == len(base["receipts"]) == 4
    assert sum(run["chart_bars"] for run in raw["runs"]) == 4416
    assert [run["closed"] for run in raw["runs"]] == [17, 36, 9, 22]
    assert sum(row["bars"] for row in base["receipts"]) == 17_664
    assert sum(row["verified_execution_prices"] for row in base["receipts"]) == 135
    assert raw["archive_error"] == ["E_PARSE_EXPR:Error:219:26: expected expression"]
    isolation = read(work / "round3-isolation-python.json")
    assert set(isolation) == {"file_error", "network_error"}
    assert all(error[0] == "PermissionError" for error in isolation.values())
    cases = defaultdict(list)
    reasons = Counter()
    for run, check in zip(raw["runs"], base["receipts"], strict=True):
        assert sha256(work / run["feed"]) == run["feed_sha256"]
        assert sha256(work / check["name"]) == check["sha256"]
        assert run["orders"] == check["verified_execution_prices"]
        unsettled = int(run["ending_position"]["size"] != 0)
        closed = []
        for trade in run["ledger"]:
            side = {"Long Entry": 1, "Short Entry": -1}[trade["id"]]
            assert run["start"] <= trade["entryTime"] < trade["exitTime"] < run["stop"]
            assert trade["qty"] == side
            entry, exit_price = trade["entryPrice"], trade["exitPrice"]
            gross = side * (exit_price - entry)
            fee = FEE_OVERLAY * (entry + exit_price)
            assert math.isclose(trade["profit"], gross, abs_tol=1e-8)
            assert math.isclose(trade["fee_sensitivity"], fee, abs_tol=1e-8)
            assert math.isclose(
                trade["after_fee_sensitivity"], gross - fee, abs_tol=1e-8
            )
            reasons[trade["reason"]] += 1
            closed.append(
                {
                    **trade,
                    "dir": side,
                    "qty": 1,
                    "commission": fee,
                    "profit": gross - fee,
                }
            )
        assert len(closed) == run["closed"]
        cases[run["start"], run["stop"]].append((run["market"], closed, unsettled))

    results = []
    for (start, stop), markets in sorted(cases.items()):
        assert [name for name, _, _ in markets] == ["BTCUSDT", "ETHUSDT"]
        attrs = {
            "id": 3604,
            "group": "FMZ · Pine Compat declared capital migration",
            "exit": "Archived account-relative threshold close or opposite entry",
            "period": f"Binance USD-M · {iso_day(start)} to {iso_day(stop)} UTC exclusive",
            "archive_interval": "1h",
            "interval": "1h",
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
        "schema": "Pine Compat FMZ 3604 declared capital migration evidence",
        "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
        "source_sha256": SOURCE_SHA,
        "source_url": "https://www.fmz.com/strategy/442822",
        "engine_sha256": ENGINE_SHA,
        "raw_ledger_sha256": sha256(raw_path),
        "lower_price_control_sha256": sha256(lower_path),
        "lower_price_control": base,
        "isolation": isolation,
        "close_reasons": dict(reasons),
        "model": {
            "venue": "Archived Binance USD-M BTCUSDT with independent ETHUSDT cross-asset replay",
            "initial_capital": "The archived dotted assignment causes a compile error. Its sole, non-conflicting 50,000 literal is moved to the strategy declaration, and all archived profit-denominator reads are retained.",
            "orders": "Hourly decisions and market fills on the next candle opening. Simultaneous explicit close and opposite entry follow the checked offline broker order sequence.",
            "fee_overlay": "Archived broker declares no commission. The after-fee sensitivity applies 0.075 percent per side to the identical settled fills. Ending exposure is tracked separately.",
            "base_data": "Official Binance 15-minute aggregation reproduced the hour and priced every fill. This is a quote reconciliation with the FMZ host base period under the original Pine v4 source mode.",
        },
        "coverage": [
            [
                3604,
                "Tested · Pine Compat declared capital migration",
                "Archived sole 50,000-USDT literal relocated to declaration. Verified original order and market-close logic on both Binance USD-M contracts, and priced all fills with official 15m base data.",
            ]
        ],
        "results": results,
        **raw,
    }
    write(output, report)


if __name__ == "__main__":
    finalize(*map(Path, sys.argv[1:]))
