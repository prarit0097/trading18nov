"""Finalize all #2121 bracket fills using the independently confirmed minute path."""

import math
import sys
from pathlib import Path

from research.fmz_round7_magnifier import iso_day, ledger_metrics, read, sha256, write

SOURCE = "44c5bcf86c7e0df8c55182eb2015f3a95962e94305dabad05d1371ed1b58094a"
PINE = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
FEE = .00075
CAPITAL = 1_000_000


def finalize(work, output):
    verified = work / "2121-refined.json"
    audit = read(verified)
    monthly = read(work / "2121-inputs.json")
    minutes = work / "2121-minute-inputs.json"
    prices = read(minutes)["cases"]
    assert sha256(work / "source-2121.md") == SOURCE
    assert sha256(work / "priced-runtime/pine_compat/pine_compat.pyd") == PINE
    assert sha256(work / "2121-verified.json") == audit["prior_verified_sha256"]
    assert sha256(minutes) == audit["verified_minutes_sha256"]
    assert audit["missing_group_control"] == ["W_MAGNIFIER_FALLBACK"]
    isolation = read(work / "round3-isolation-python.json")
    assert set(isolation) == {"file_error", "network_error"}
    assert all(error[0] == "PermissionError" for error in isolation.values())
    final_results, pooled = [], []
    frame = None
    for row, ref, expected_minute_count, expected_price_changes in zip(
        audit["reports"], monthly["feeds"], (15, 9), (7, 4), strict=True
    ):
        assert (row["market"], row["file"]) == (ref["market"], ref["file"])
        assert sha256(work / row["file"]) == row["sha256"] == ref["sha256"]
        assert row["chart_bars"] == 371 and row["reference_bars"] == 4452 and row["base_bars"] == 8904
        data = read(work / row["file"])
        assert row["capital"] == CAPITAL and row["open"] is None
        assert row["signals"] == {"up": 21, "down": 22}
        refinements = row["minute_resolutions"]
        assert len(refinements) == expected_minute_count
        assert sum(p["before_price"] != p["after_price"] for p in refinements) == expected_price_changes
        lots = []
        for trade in row["ledger"]:
            side = {"Buy": 1, "Sell": -1}[trade["id"]]
            assert trade["qty"] == side and not trade["both_price_levels_hit"]
            assert data["start"] <= trade["entryTime"] <= trade["exitTime"] <= trade["effective_base_exit"] < data["end"]
            p, q = trade["entryPrice"], trade["exitPrice"]
            gross, fee = side * (q - p), FEE * (p + q)
            assert math.isclose(trade["profit"], gross, abs_tol=1e-8)
            assert math.isclose(trade["fee"], fee, abs_tol=1e-8)
            assert math.isclose(trade["after_fee"], gross - fee, abs_tol=1e-8)
            lots.append({**trade, "dir": side, "qty": 1, "exitTime": trade["effective_base_exit"], "commission": fee, "profit": gross - fee})
        assert len(lots) == 43
        current = f"Binance USD-M · {iso_day(data['start'])} to {iso_day(data['end'])} UTC exclusive"
        assert frame in (None, current)
        frame = current
        final_results.append({"market": row["market"], **ledger_metrics(lots, CAPITAL, 0)})
        pooled.extend(lots)
    final_results.append({"market": "BTCUSDT + ETHUSDT", **ledger_metrics(pooled, CAPITAL * 2, 0)})
    attrs = {
        "id": 2121,
        "group": "FMZ · dual SuperTrend · minute-audited brackets",
        "exit": "500-tick target and 400-tick stop",
        "period": frame,
        "archive_interval": "1d",
        "interval": "1d",
        "currency": "USDT",
    }
    minute_receipts = [{k: v for k, v in r.items() if k != "minutes"} for r in prices]
    assert len(minute_receipts) == 24
    report = {
        "schema": "FMZ 2121 full intrabar-confirmed bracket replay",
        "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
        "source_url": "https://www.fmz.com/strategy/433448",
        "source_sha256": SOURCE,
        "engine_sha256": PINE,
        "verified_sha256": sha256(verified),
        "input_data": monthly,
        "minute_receipts": minute_receipts,
        "isolation": isolation,
        "model": {
            "signals": "The Pine v4 archive retains its two recursive SuperTrend state families. The six self-references are explicitly typed and assigned. The request spelling and legacy visual constants are normalized. Normalized v4, chart-only v5 and the refined intrabar v5 reproduce the same independent signals. The 2h assistance selects the last confirmed child in each daily chart period.",
            "execution": "The source's fixed one-unit order goes to the next daily open and attaches a 500-tick target and 400-tick stop. The saved market metadata is BTC 0.1 USDT tick and ETH 0.01 USDT tick. Each of the 24 hours with both levels reached is replaced by 60 complete matching Binance minutes. The first triggering minute reaches one side or opens through it, so all choices are determined by the data. Fill amounts follow the emulator bracket model and do not represent independently observed executable quotes.",
            "costs": "The zero-commission archive gives gross P&L, with a separate 0.075% fee per side on the same prices. Equity starts at the Pine default of 1,000,000 USDT per symbol. There are no remaining positions. Drawdown uses realized equity and the effective lower-candle exit timestamps.",
        },
        "coverage": [[
            2121,
            "Tested · dual SuperTrend with minute-audited brackets",
            "Complete saved Binance daily and 2h decision periods. 86 verified fixed-size closes and no unfinished position. Resolved all 24 both-level hours with checksum-pinned 1m evidence. The removed-group control demonstrates fallback detection.",
        ]],
        "results": [{**attrs, **row} for row in final_results],
        **audit,
    }
    write(output, report)


if __name__ == "__main__":
    finalize(*map(Path, sys.argv[1:]))
