"""Finalize the independently audited #2514 ratings and USD ledger."""

import math
import sys
from pathlib import Path

from research.fmz_round7_magnifier import iso_day, ledger_metrics, read, sha256, write

SOURCE = "b8092e2408152bd6c8c87000ff6ed99e9732f2a59f8b70d9333cfc4668e142a3"
COMPAT = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
CAPITAL = 500
FEE = 0.00075
DAY = 86_400_000
FX_URL = "https://api.exchange.coinbase.com/products/USDT-USD/candles?granularity=86400&start=2022-10-16T00%3A00%3A00Z&end=2023-05-14T00%3A00%3A00Z"


def finalize(work, output):
    receipt = work / "2514-verified.json"
    audit = read(receipt)
    data = read(work / "2514-inputs.json")
    assert sha256(work / "source-2514.md") == SOURCE
    assert sha256(work / "priced-runtime/pine_compat/pine_compat.pyd") == COMPAT
    assert sha256(work / "2514-replay.json") == audit["native_sha256"]
    assert audit["last_4h_fixture"]["values"] == [[104.5, 110.5, 116.5], [100, 106, 112]]
    fx_path = work / data["fx"]["file"]
    assert sha256(fx_path) == data["fx"]["sha256"]
    rates = {r["effectiveTime"]: r["rate"] for r in read(fx_path)["pairs"][0]["rates"]}
    assert len(rates) == 209
    isolation = read(work / "round3-isolation-python.json")
    assert set(isolation) == {"file_error", "network_error"}
    assert all(error[0] == "PermissionError" for error in isolation.values())
    cases = audit["cases"]
    attrs = {
        "id": 2514,
        "group": "FMZ · 4h composite rating · Coinbase prior-day USD FX",
        "exit": "One-unit flip to the opposite score via the next daily open",
        "period": f"Binance USD-M · {iso_day(cases[0]['start'])} to {iso_day(cases[0]['end'])} UTC exclusive",
        "archive_interval": "1d",
        "interval": "1d",
        "currency": "USD",
    }
    results = []
    pooled = []
    for row, ref, expected in zip(cases, data["feeds"], (55, 57), strict=True):
        assert row["file"] == ref["file"] and row["market"] == ref["market"]
        assert sha256(work / row["file"]) == row["sha256"] == ref["sha256"]
        assert row["votes_matched"] == 25 * row["chart_bars"] == 5225
        assert row["chart_bars"] == 209 and row["base_bars"] == 1254
        assert row["unsettled"]["side"] in (-1, 1)
        assert row["minimum_marked_equity_before_fee_overlay"] < 0
        assert list(rates) == list(range(row["start"], row["end"], DAY))
        lots = []
        for lot, reversal in zip(row["closed"], row["reversals"], strict=True):
            side = lot["side"]
            assert lot["qty"] == side and side in (-1, 1)
            assert lot["entryTime"] == row["start"] + lot["entryBarIndex"] * DAY
            assert lot["exitTime"] == row["start"] + lot["exitBarIndex"] * DAY
            assert reversal["qty"] == 2 and reversal["time"] == lot["exitTime"]
            assert row["start"] <= lot["entryTime"] < lot["exitTime"] < row["end"]
            exit_fx, entry_fx = rates[lot["exitTime"]], rates[lot["entryTime"]]
            assert lot["fx_exit"] == exit_fx and lot["fx_entry"] == entry_fx
            entry, exit_price = lot["entryPrice"], lot["exitPrice"]
            gross = side * (exit_price - entry) * exit_fx
            fee = FEE * (entry * entry_fx + exit_price * exit_fx)
            assert math.isclose(lot["profit"], gross, abs_tol=1e-8)
            assert math.isclose(lot["fee_overlay"], fee, abs_tol=1e-8)
            assert math.isclose(lot["after_fee"], gross - fee, abs_tol=1e-8)
            lots.append({
                **lot, "dir": side, "qty": 1,
                "entryPrice": entry * exit_fx, "exitPrice": exit_price * exit_fx,
                "commission": fee, "profit": gross - fee,
            })
        assert len(lots) == expected
        metrics = ledger_metrics(lots, CAPITAL, 1)
        assert math.isclose(metrics["gross"], row["gross"], abs_tol=1e-8)
        assert math.isclose(metrics["after_fees"], row["after_fee"], abs_tol=1e-8)
        results.append({**attrs, "market": row["market"], **metrics})
        pooled.extend(lots)
    results.append({**attrs, "market": "BTCUSDT + ETHUSDT", **ledger_metrics(pooled, CAPITAL * 2, 2)})
    report = {
        "schema": "FMZ 2514 archived Pine v4 daily ratings and execution-date USD conversion",
        "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
        "source_url": "https://www.fmz.com/strategy/430022",
        "source_sha256": SOURCE,
        "pine_compat_sha256": COMPAT,
        "verified_sha256": sha256(receipt),
        "input_data": data,
        "fx_source_url": FX_URL,
        "isolation": isolation,
        "model": {
            "venue": "Saved Binance USD-M BTCUSDT UTC dates, daily chart and hourly base. ETHUSDT uses the same dates and fixed archive parameters. Each 4h reference is constructed from four public 1h candles.",
            "source": "The v4 file used 20 v5 request names. They are normalized to the v4 security alias. Ten bare color values receive their v4 namespace. The 14 moving-average votes preserve the archived SMA helpers even for variables named EMA, Hull or VWMA. The RSI helper receives a provably integer input length and the disabled Ichimoku component remains zero.",
            "signals": "The documented default lower-timeframe request selects the final 4h candle confirmed during each UTC daily bar. A three-day fixture distinguishes that alignment from selecting the first child with lookahead. An independent reference matches all 10,450 votes, three rating lines and 418 chart bars.",
            "execution": "One base unit or a two-unit opposite-side market order to reverse the existing position. All orders settle at the next daily open and reconcile to the first public 1h opening price. Each archived USD account starts at 500. Coinbase USDT-USD closes are effective from the next UTC day. Realized price movement is converted using the exit-day effective FX. Each 0.075% fee is converted on its own execution date.",
            "risk": "The archived legacy declaration has no margin constraint, so orders continue with negative account equity. Daily and closed-trade equity both document drawdown. The results describe that historical simulator setup and do not establish a risk-qualified $500 trading plan.",
        },
        "coverage": [[
            2514,
            "Tested · Pine v4 4h composite rating and USD conversion",
            "Saved BTC UTC dates and ETH cross-asset test. Complete official 1h and 4h timing, independently verified vote and USD ledgers, 112 closes, and two explicitly open remainders. Unconstrained archived margin permits negative equity.",
        ]],
        "results": results,
        **audit,
    }
    write(output, report)


if __name__ == "__main__":
    finalize(*map(Path, sys.argv[1:]))
