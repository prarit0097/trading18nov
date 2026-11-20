"""Finalize #2994's source-signal and execution-price cash replay evidence."""

import math
import sys
from pathlib import Path

from research.fmz_round7_magnifier import iso_day, ledger_metrics, read, sha256, write

SOURCE = "f9ccc275870a1bd0cb3dab7160fe0a46fa4c719c07aeb139798aeb28baf7c265"
COMPAT = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
PINER = "9a4699655d9f5d0ad105b14cf68b60d6fa1cc8a608ed85b11deebaccbaccbdea"
CAPITAL = 10_000
COMMISSION_RATE = 0.00025
DAY = 86_400_000


def finalize(work, output):
    receipt = work / "2994-verified.json"
    verification = read(receipt)
    data = read(work / "2994-inputs.json")
    assert sha256(work / "source-2994.md") == SOURCE
    assert sha256(work / "priced-runtime/pine_compat/pine_compat.pyd") == COMPAT
    assert sha256(work / "2994-replay.json") == verification["native_sha256"]
    assert sha256(work / "2994-piner.json") == verification["piner_sha256"]
    assert verification["piner_engine_sha256"] == PINER
    assert sha256(work / "2994-cash-sizing.json") == verification["cash_control"]["native_sha256"]
    isolation = read(work / "round3-isolation-python.json")
    assert set(isolation) == {"file_error", "network_error"}
    assert all(x[0] == "PermissionError" for x in isolation.values())
    cases = verification["cases"]
    assert [(x["market"], len(x["closed"])) for x in cases] == [("BTCUSDT", 62), ("ETHUSDT", 70)]
    attrs = {
        "id": 2994,
        "group": "FMZ · WaveTrend order signals · Piner fixed-cash broker",
        "exit": "Named next-open market closes triggered by WaveTrend or confirmed divergence",
        "period": f"Binance USD-M · {iso_day(cases[0]['start'])} to {iso_day(cases[0]['end'])} UTC exclusive",
        "archive_interval": "1d",
        "interval": "1d",
        "currency": "USDT",
    }
    results = []
    pooled = []
    for row, feed, differing in zip(cases, data["feeds"], (0, 2), strict=True):
        assert row["market"] == feed["market"] and row["file"] == feed["file"]
        assert sha256(work / row["file"]) == row["sha256"] == feed["sha256"]
        assert row["chart_bars"] == 371 and row["base_bars"] == 8_904
        assert row["native_cash_quantities_differ"] == differing and row["open"]
        lots = row["closed"]
        assert row["order_events"] == {"entry": len(lots) + 1, "explicit": len(lots)}
        for lot in lots:
            assert row["start"] <= lot["entryTime"] < lot["exitTime"] < row["end"]
            assert lot["entryTime"] == row["start"] + lot["entryBar"] * DAY
            assert lot["exitTime"] == row["start"] + lot["exitBar"] * DAY
            entry, exit_price, qty = lot["entryPrice"], lot["exitPrice"], lot["qty"]
            assert 0 <= CAPITAL - entry * qty < entry * 0.001 + 1e-9
            assert math.isclose(lot["commission"], COMMISSION_RATE * qty * (entry + exit_price), abs_tol=1e-8)
        results.append({**attrs, "market": row["market"], **ledger_metrics(lots, CAPITAL, 1)})
        pooled.extend(lots)
    results.append({**attrs, "market": "BTCUSDT + ETHUSDT", **ledger_metrics(pooled, CAPITAL * 2, 2)})
    report = {
        "schema": "FMZ 2994 exact Pine v4 decisions and fill-price fixed-cash ledger",
        "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
        "source_sha256": SOURCE,
        "source_url": "https://www.fmz.com/strategy/438943",
        "pine_compat_sha256": COMPAT,
        "piner_js_sha256": PINER,
        "verified_sha256": sha256(receipt),
        "input_data": data,
        "isolation": isolation,
        "model": {
            "venue": "Saved Binance USD-M BTCUSDT dates, daily strategy, and 1h base, separately compared on ETHUSDT. Daily and auxiliary 4h/12h intervals are aligned to UTC and aggregated from official 1h records.",
            "signals": "Vanilla Pine v4 runs with the actual underlying candles and the source's Heikin-Ashi requests. Independent WaveTrend and confirmed-fractal code matches both indicator lines and every entry/exit flag. Perturbing lower-timeframe auxiliary feed values leaves those flags and broker decisions equal. The four HA lookahead calls are retained and reported; their requested values do not drive order flags in the saved settings.",
            "execution": "Pin-sized Piner JavaScript and interpreter replay the archived market order calls with the verified four flags and preserved order header. Actual next daily open equals the first official hourly print in its group. Fixed cash 10,000 divided by that opening fill price, then floored to the 0.001 base-asset step. The isolated reference book independently verifies all prices, lots, closing fees and daily marked equity. Pine Compat provides the signal run and a rejected previous-close quantity control.",
            "costs": "Original 0.025% per side, 10,000 USDT starting cash per symbol, omitted Pine v4 margin fields set to the legacy zero default. No spread, funding or additional slippage overlay. Performance rows and drawdown use realized lots only. Each symbol has one marked unsettled lot. Last marked equity is supplied separately.",
        },
        "coverage": [[
            2994,
            "Tested · Pine v4 WaveTrend and execution-price cash sizing",
            "Exact saved source WaveTrend and divergence flags audited on 742 BTC and ETH chart candles. Independent market settlement matches both Piner backends across 132 closed positions, configured costs and daily marks. Two remaining positions are identified separately.",
        ]],
        "results": results,
        **verification,
    }
    write(output, report)


if __name__ == "__main__":
    finalize(*map(Path, sys.argv[1:]))
