"""Finalize the #1073 archive-restored cash ledger and exact time-bound receipts."""

import math
import sys
from pathlib import Path

from research.fmz_round7_magnifier import iso_day, ledger_metrics, read, sha256, write

SOURCE = "50de3085564b9c1ab144405b1d6f4af89ee4efff64845a3227dd50c63154fa71"
BODY = "667c34a5e4412baa521862ecf2aad24914f9c04b8eefb2df5c603ed5c69712f7"
COMPAT = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
PINER = "9a4699655d9f5d0ad105b14cf68b60d6fa1cc8a608ed85b11deebaccbaccbdea"
CAPITAL = 10_000
FEE = 0.00025
STEP = 7_200_000


def finalize(work, output):
    receipt = work / "1073-verified.json"
    audit = read(receipt)
    data = read(work / "1073-inputs.json")
    assert sha256(work / "source-1073.md") == SOURCE
    assert sha256(work / "priced-runtime/pine_compat/pine_compat.pyd") == COMPAT
    assert sha256(work / "1073-replay.json") == audit["native_sha256"]
    assert sha256(work / "1073-piner.json") == audit["piner_sha256"]
    assert audit["piner_engine_sha256"] == PINER
    assert audit["restored_body_sha256"] == BODY
    assert [lot["qty"] for lot in audit["cash_fixture"]] == [52.548, 36.023]
    isolation = read(work / "round3-isolation-python.json")
    assert set(isolation) == {"file_error", "network_error"}
    assert all(x[0] == "PermissionError" for x in isolation.values())
    cases = audit["cases"]
    assert [row["market"] for row in cases] == ["BTCUSDT", "ETHUSDT"]
    attrs = {
        "id": 1073,
        "group": "FMZ · Restored WaveTrend declaration · 2h fixed-cash replay",
        "exit": "Named market order at the next 2h open",
        "period": f"Binance USD-M · {iso_day(cases[0]['start'])} to {iso_day(cases[0]['end'])} 23:59 UTC exclusive",
        "archive_interval": "2h",
        "interval": "2h",
        "currency": "USDT",
    }
    results, pooled = [], []
    for row, reference, expected in zip(cases, data["feeds"], (56, 67), strict=True):
        assert (row["market"], row["file"]) == (reference["market"], reference["file"])
        assert sha256(work / row["file"]) == row["sha256"] == reference["sha256"]
        assert row["chart_bars"] == 360 and row["base_bars"] == 2880
        assert row["end"] - row["start"] == 360 * STEP - 60_000
        assert row["excluded_minute"][0] == row["end"]
        assert row["terminal_ohlcv"][0] == row["end"] - 14 * 60_000
        assert row["zero_print_quarters"] == reference["zero_print_quarters"] == [1651444200000]
        assert row["zero_prints_at_execution_open"] == 0
        lots = row["closed"]
        assert len(lots) == expected and row["open"]
        assert row["order_events"] == {"entry": expected + 1, "explicit": expected}
        for lot in lots:
            assert row["start"] <= lot["entryTime"] < lot["exitTime"] < row["end"]
            assert lot["entryTime"] == row["start"] + lot["entryBar"] * STEP
            assert lot["exitTime"] == row["start"] + lot["exitBar"] * STEP
            quote, qty = lot["entryPrice"], lot["qty"]
            assert 0 <= CAPITAL - quote * qty < quote * .001 + 1e-9
            assert math.isclose(lot["commission"], FEE * qty * (quote + lot["exitPrice"]), abs_tol=1e-8)
        results.append({**attrs, "market": row["market"], **ledger_metrics(lots, CAPITAL, 1)})
        pooled.extend(lots)
    results.append({**attrs, "market": "BTCUSDT + ETHUSDT", **ledger_metrics(pooled, CAPITAL * 2, 2)})
    report = {
        "schema": "FMZ 1073 exact declared restoration and 2h cash settlement",
        "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
        "source_url": "https://www.fmz.com/strategy/363822",
        "source_sha256": SOURCE,
        "pine_compat_sha256": COMPAT,
        "piner_sha256": PINER,
        "verification_sha256": sha256(receipt),
        "input_data": data,
        "isolation": isolation,
        "model": {
            "source": "Remove the two slashes preceding the archived strategy declaration. Both capitals, cash sizing and commission were present in that declaration. The restored Pine v4 program is byte-identical to the independently verified active #2994 body. The saved wrapper dates, instrument and resolution are #1073's own.",
            "venue": "Archived Binance USD-M BTCUSDT, 2h chart/15m base, plus separate ETHUSDT. All emitted order events are before the literal 23:59 UTC saved end. At the right boundary the last full quarter is replaced by the 14 completed underlying minute bars known before the cutoff; the minute opening at 23:59 is explicitly excluded. Each market's only zero-print quarter is carried as an interior signal observation and no execution uses it.",
            "signals": "Restored Pine v4 plus actual lower and higher feeds. Independent WaveTrend and confirmed divergence model matches both control curves and all four order flags on 720 bars. Warnings about Heikin-Ashi lookahead remain visible; the independent decision calculation requires only the actual two-hour chart.",
            "execution": "Original 10,000 USDT strategy cash divided by the next 2h open, floored in 0.001 base units as in the fixed-cash fixture. Actual opening prices come from the first positive-volume 15m candle in each used 2h group. Both Piner backends agree with independent cash, position and marked equity. The old signal-close quantity control changes four ETH entries.",
            "costs": "Archived 0.025% fee per side and 10,000 USDT initial capital per instrument. Closed-trade metrics leave the two open positions separate. Spread, funding and additional slippage are outside this replay.",
        },
        "coverage": [[
            1073,
            "Tested · restored archived WaveTrend declaration",
            "Uncommented exact source declaration equals the pinned #2994 program. All 123 BTC/ETH closed positions, 248 entry/close events and every chart mark independently verified to the literal saved cutoff and original fee schedule.",
        ]],
        "results": results,
        **audit,
    }
    write(output, report)


if __name__ == "__main__":
    finalize(*map(Path, sys.argv[1:]))
