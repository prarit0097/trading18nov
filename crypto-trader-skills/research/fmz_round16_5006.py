"""Settle the #5006 GBP-account metrics and reconcile official base quotes."""

import math
import sys
from collections import defaultdict
from pathlib import Path

from research.fmz_round7_magnifier import iso_day, ledger_metrics, read, sha256, write

DAY = 86_400_000
MINUTE = 60_000
CAPITAL = 1_000_000
FEE_OVERLAY = 0.00075
SOURCE_SHA = "75ccb16d13396df5b7fa13ad7279aa164c6f8451f4dbd27ee6ca78f19065d42a"
FX_API = (
    "https://api.kraken.com/0/public/OHLC?pair=USDTGBP&interval=1440&since=1785456000"
)


def verify_base(work, run, prior):
    record = prior[run["market"], run["start"]]
    base_file = work / record["file"]
    assert sha256(base_file) == record["sha256"]
    minute = read(base_file)
    assert [bar[0] for bar in minute] == list(range(run["start"], run["end"], MINUTE))
    prices = {bar[0]: bar[1] for bar in minute}
    group = read(work / run["feed"])["intrabar"]
    assert len(minute) == len(group) * 10
    for i, parent in enumerate(group):
        parts = minute[i * 10 : (i + 1) * 10]
        assert parts[0][:2] == parent[:2] and parts[-1][4] == parent[4]
        assert max(b[2] for b in parts) == parent[2]
        assert min(b[3] for b in parts) == parent[3]
        assert math.isclose(math.fsum(b[5] for b in parts), parent[5], rel_tol=1e-10)
    position = run["ending_position"]
    executions = [
        (run["start"] + position["barIndex"] * 10 * MINUTE, position["avgPrice"])
    ]
    for trade in run["ledger"]:
        executions.extend(
            [
                (trade["entryTime"], trade["entryPrice"]),
                (trade["exitTime"], trade["exitPrice"]),
            ]
        )
    assert len(executions) == run["orders"]
    assert all(
        math.isclose(prices[time], price, abs_tol=1e-8) for time, price in executions
    )
    return {
        "name": base_file.name,
        "sha256": record["sha256"],
        "minute_bars": len(minute),
        "verified_execution_prices": len(executions),
    }


def finalize(work, reference, output):
    raw_path = work / "5006-replay.json"
    raw = read(raw_path)
    assert sha256(work / "source-5006.md") == SOURCE_SHA
    assert (
        sha256(work / "priced-runtime/pine_compat/pine_compat.pyd")
        == raw["runtime_sha256"]
    )
    fx_file = work / "5006-kraken-fx-rates.json"
    assert sha256(fx_file) == raw["fx_sha256"]
    rates = {time: float(close) for time, close in read(fx_file)}
    assert len(rates) == 93
    assert len(raw["runs"]) == 4 and sum(run["bars"] for run in raw["runs"]) == 26496
    assert [run["closed"] for run in raw["runs"]] == [110, 208, 116, 213]
    assert sum(run["orders"] for run in raw["runs"]) == 1298
    assert all(run["ending_position"]["size"] != 0 for run in raw["runs"])
    isolation = read(work / "round3-isolation-python.json")
    assert set(isolation) == {"file_error", "network_error"}
    assert all(error[0] == "PermissionError" for error in isolation.values())
    prior = {(row["market"], row["start"]): row for row in read(reference)["runs"]}
    bases = []
    cases = defaultdict(list)
    for run in raw["runs"]:
        assert sha256(work / run["feed"]) == run["feed_sha256"]
        bases.append(verify_base(work, run, prior))
        assert run["closed"] == len(run["ledger"])
        closed = []
        for trade in run["ledger"]:
            side = {"Buy": 1, "Sell": -1}[trade["id"]]
            assert run["start"] <= trade["entryTime"] < trade["exitTime"] < run["end"]
            quantity = abs(trade["qty"])
            entry, exit_price = trade["entryPrice"], trade["exitPrice"]
            entry_fx = rates[trade["entryTime"] // DAY * DAY]
            exit_fx = rates[trade["exitTime"] // DAY * DAY]
            assert entry_fx == trade["fx_entry"] and exit_fx == trade["fx_exit"]
            gross = side * quantity * (exit_price - entry) * exit_fx
            fee = FEE_OVERLAY * quantity * (entry * entry_fx + exit_price * exit_fx)
            assert math.isclose(gross, trade["profit"], abs_tol=1e-8)
            assert math.isclose(fee, trade["fee_sensitivity"], abs_tol=1e-8)
            assert math.isclose(
                gross - fee, trade["after_fee_sensitivity"], abs_tol=1e-8
            )
            closed.append(
                {
                    **trade,
                    "dir": side,
                    "qty": quantity,
                    "entryPrice": entry * exit_fx,
                    "exitPrice": exit_price * exit_fx,
                    "commission": fee,
                    "profit": gross - fee,
                }
            )
        cases[run["start"], run["end"]].append((run["market"], closed))

    results = []
    for (first, last), markets in sorted(cases.items()):
        assert [name for name, _ in markets] == ["BTCUSDT", "ETHUSDT"]
        attrs = {
            "id": 5006,
            "group": "FMZ · Pine Compat v2 · Kraken prior-day GBP FX",
            "exit": "Archived balance-direction market close",
            "period": f"Binance USD-M · {iso_day(first)} to {iso_day(last)} UTC exclusive",
            "archive_interval": "10m",
            "interval": "10m",
            "currency": "GBP",
        }
        for market, closed in markets:
            results.append(
                {**attrs, "market": market, **ledger_metrics(closed, CAPITAL, 1)}
            )
        pooled = [lot for _, closed in markets for lot in closed]
        results.append(
            {
                **attrs,
                "market": "BTCUSDT + ETHUSDT",
                **ledger_metrics(pooled, CAPITAL * 2, 2),
            }
        )

    report = {
        "schema": "Pine Compat FMZ 5006 archived v2 GBP account replay",
        "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
        "source_sha256": SOURCE_SHA,
        "source_url": "https://www.fmz.com/strategy/433547",
        "raw_ledger_sha256": sha256(raw_path),
        "minute_inputs": bases,
        "fx_api": FX_API,
        "isolation": isolation,
        "model": {
            "venue": "Archived Binance USD-M BTCUSDT ten-minute chart and independent ETHUSDT cross-asset run",
            "account": "Archived GBP currency, offline runtime default capital GBP 1,000,000, ten percent equity sizing, 0.001 base-asset lot step",
            "fx_policy": "Kraken completed daily USDTGBP close effective at following UTC midnight. Gross profit translates at the exit rate, and overlay fees translate at their respective fill rates.",
            "trailing_rule": "The exact archived v2 program runs. Its optional default-active trail entries omit the offset and yield only inert E_STRATEGY_EXIT_ENTRY diagnostics. A v2 branch-removal control and v5 namespace migration reproduce all original plots/settlement output apart from those diagnostics.",
            "fee_overlay": "0.075 percent per side deducted from identical settled fills. Archived commission is zero. Drawdown is realized, with ending exposure marked separately.",
        },
        "coverage": [
            [
                5006,
                "Tested · Pine Compat native v2 GBP account",
                "Exact source, independent eight-period Wilder and 34-period SMA calculations, two complete BTC/ETH ten-minute windows, all 1,298 fills reconciled to Binance one-minute prices and Kraken completed-day GBP FX.",
            ]
        ],
        "results": results,
        **raw,
    }
    write(output, report)


if __name__ == "__main__":
    finalize(*map(Path, sys.argv[1:]))
