"""Finalize #5478's exact native PSAR replay and independently verified USD P&L."""

import math
import sys
from pathlib import Path

from research.fmz_round7_magnifier import iso_day, ledger_metrics, read, sha256, write

SOURCE = "d433f98b53fedb2edca6f2ed1e8f6692b4f70058a2cc9d85a28591ba546449e7"
ENGINE = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
FX_URL = "https://api.exchange.coinbase.com/products/USDT-USD/candles?granularity=86400&start=2023-12-19T00%3A00%3A00Z&end=2023-12-27T00%3A00%3A00Z"
DAY, FEE, CAPITAL = 86_400_000, .001, 5000


def finalize(work, output):
    proof = work / "5478-verified.json"
    audit = read(proof)
    data = read(work / "5478-inputs.json")
    assert sha256(work / "source-5478.md") == SOURCE
    assert sha256(work / "priced-runtime/pine_compat/pine_compat.pyd") == ENGINE
    assert sha256(work / "5478-replay.json") == audit["raw_sha256"]
    path = work / data["fx"]["file"]
    assert sha256(path) == data["fx"]["sha256"]
    rates = {x["effectiveTime"]: x["rate"] for x in read(path)["pairs"][0]["rates"]}
    assert len(rates) == 7
    isolation = read(work / "round3-isolation-python.json")
    assert set(isolation) == {"file_error", "network_error"}
    assert all(v[0] == "PermissionError" for v in isolation.values())
    cases = audit["cases"]
    attrs = {
        "id": 5478,
        "group": "FMZ · PSAR/EMA · Coinbase prior-day USD FX",
        "exit": "Named next-open close after bearish confirmation",
        "period": f"Binance USD-M · {iso_day(cases[0]['start'])} to {iso_day(cases[0]['end'])} UTC exclusive",
        "archive_interval": "45m", "interval": "45m", "currency": "USD",
    }
    results, pooled = [], []
    for row, ref, expected in zip(cases, data["feeds"], (3, 2), strict=True):
        assert (row["file"], row["market"]) == (ref["file"], ref["market"])
        assert sha256(work / row["file"]) == ref["sha256"] == row["sha256"]
        assert row["finished_flat"] and row["chart_bars"] == 224 and row["base_bars"] == 2016
        lots = []
        for t in row["ledger"]:
            price, exit_price, amount = t["entryPrice"], t["exitPrice"], t["qty"]
            entry_rate, exit_rate = rates[t["entryTime"] // DAY * DAY], rates[t["exitTime"] // DAY * DAY]
            assert (t["entry_fx"], t["exit_fx"]) == (entry_rate, exit_rate)
            assert t["id"] == "long" and row["start"] <= t["entryTime"] < t["exitTime"] < row["end"]
            gross = amount * (exit_price - price) * exit_rate
            fees = FEE * amount * (price * entry_rate + exit_price * exit_rate)
            assert math.isclose(gross, t["gross"], abs_tol=1e-8)
            assert math.isclose(fees, t["commission"], abs_tol=1e-8)
            assert math.isclose(gross - fees, t["profit"], abs_tol=1e-8)
            one_unit_cost = price * entry_rate * (1 + FEE)
            budget = t["equity_at_entry"] * .2
            assert 0 <= budget - one_unit_cost * amount < one_unit_cost * .001 + 1e-8
            lots.append({**t, "dir": 1, "entryPrice": price * exit_rate, "exitPrice": exit_price * exit_rate})
        assert len(lots) == expected
        results.append({**attrs, "market": row["market"], **ledger_metrics(lots, CAPITAL, 0)})
        pooled.extend(lots)
    results.append({**attrs, "market": "BTCUSDT + ETHUSDT", **ledger_metrics(pooled, CAPITAL * 2, 0)})
    report = {
        "schema": "FMZ 5478 exact PSAR/EMA and percent-of-equity USD replay",
        "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
        "source_sha256": SOURCE, "source_url": "https://www.fmz.com/strategy/436902",
        "engine_sha256": ENGINE, "verified_sha256": sha256(proof), "input_data": data,
        "fx_source_url": FX_URL, "isolation": isolation,
        "model": {
            "source": "Unmodified Pine v4 strategy body. Default direction is long only. EMA9/EMA21 confirms PSAR reversals. The optional PSAR stop and EMA200 filter are disabled. The apparent rolling clock gate is re-assigned true by the code. Two execution clocks 366 days apart give the same direct output.",
            "venue": "The saved Binance USD-M BTCUSDT 45m/5m period is constructed from complete official 1m records. ETHUSDT uses the same separately funded rules. Each fill agrees with the first true 5m opening price after the qualifying closed bar.",
            "execution": "Initial USD 5,000 per market. The native percentage sizing budgets 20% of current equity at the execution price including entry commission, rounded to the 0.001 base-asset step. Seven prior-completed Coinbase USD rates convert fills and marks. Native fees are 0.1% each side and valued on the transaction day. The verifier checks active indicator values, every quantity, price, cost and 448 marked balances. Gross excludes commissions. Drawdown uses settled equity.",
        },
        "coverage": [[
            5478,
            "Tested · exact PSAR/EMA with USD sizing",
            "Saved BTC 45m/5m and ETH comparison, five verified closes using source costs and causal daily FX. Explicitly verified disabled stop and date gate, and two independent replay clocks.",
        ]],
        "results": results,
        **audit,
    }
    write(output, report)


if __name__ == "__main__":
    finalize(*map(Path, sys.argv[1:]))
