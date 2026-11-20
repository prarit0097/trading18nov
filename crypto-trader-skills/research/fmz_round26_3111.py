"""Emit the authored BTC result and keep ETH lookahead evidence outside metrics."""

import math
import sys
from pathlib import Path

from research.fmz_round7_magnifier import iso_day, ledger_metrics, read, sha256, write

SOURCE = "9d07debc4023acd5925f1ffe221f15516983d25501279b94f89c3c90aeb12570"
ENGINE = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
FEE, CAPITAL = .00075, 1_000_000


def finalize(work, output):
    proof = work / "3111-verified.json"
    verified = read(proof)
    inputs = read(work / "3111-inputs.json")
    assert sha256(work / "source-3111.md") == SOURCE
    assert sha256(work / "priced-runtime/pine_compat/pine_compat.pyd") == ENGINE
    assert sha256(work / "3111-replay.json") == verified["raw_sha256"]
    isolation = read(work / "round3-isolation-python.json")
    assert set(isolation) == {"file_error", "network_error"}
    assert all(x[0] == "PermissionError" for x in isolation.values())
    btc, eth = verified["results"]
    assert btc["market"] == "BTCUSDT" and eth["market"] == "ETHUSDT"
    for row, feed in zip((btc, eth), inputs["feeds"], strict=True):
        assert row["market"] == feed["market"] and row["file"] == feed["file"]
        assert sha256(work / feed["file"]) == row["sha256"] == feed["sha256"]
        assert row["chart_bars"] == 224 and row["base_bars"] == 2016
    assert btc["capital"] == CAPITAL and btc["unsettled"][0] == -1
    assert len(btc["ledger"]) == 29
    assert [c["lot"]["entryBarIndex"] for c in eth["unresolved_eth_controls"]] == [76, 110]
    lots = []
    for t in btc["ledger"]:
        side = {"KAMAL": 1, "KAMAS": -1}[t["id"]]
        assert t["qty"] == side
        assert btc["start"] <= t["entryTime"] < t["exitTime"] < btc["end"]
        gross = side * (t["exitPrice"] - t["entryPrice"])
        fee = FEE * (t["entryPrice"] + t["exitPrice"])
        assert math.isclose(t["profit"], gross, abs_tol=1e-8)
        assert math.isclose(t["fee"], fee, abs_tol=1e-8)
        assert math.isclose(t["after_fee"], gross - fee, abs_tol=1e-8)
        lots.append({**t, "dir": side, "qty": 1, "commission": fee, "profit": gross - fee})
    report = {
        "schema": "FMZ 3111 verified authored BTC market with ETH causality controls",
        "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
        "source_sha256": SOURCE,
        "source_url": "https://www.fmz.com/strategy/441140",
        "engine_sha256": ENGINE,
        "verified_sha256": sha256(proof),
        "input_data": inputs,
        "isolation": isolation,
        "model": {
            "source": "The Pine v2 file used later-version names for a security request with the current symbol and the current timeframe. The v2 route evaluates the exact recursive KAMA in that same context. A typed v5 request and a direct v5 evaluation give identical source series and broker results. The v2 integer division in round(7/2) gives 3. Keeping an unrounded float and rounding to 4 changes the actual results.",
            "btc_scope": "On the archived saved Binance BTC 45m and 5m data, fill recalculations and the confirmed-bar-only control are identical. Independent KAMA/HMA state, first traded 5m opens, named closing orders, 59 entry/exit events and 224 marked-equity rows all match. BTC carries one short at the end. The 0.075% per-side fee overlay leaves archived zero-commission fills unchanged.",
            "eth_causality": "At bars 76 and 110, the historical fill-recalculation mode opens and reverses ETH at the same opening price, using a sell signal requiring information from the completed 45m bar. An as-of-open evaluation gives an active buy and no sell. Both 5m replay and independent reconstruction reproduce the discrepancy. ETH is diagnostic only and lacks a qualified historical performance row.",
        },
        "coverage": [[
            3111,
            "Tested · authored BTC KAMA/HMA; ETH causality unresolved",
            "Saved native BTC is independently verified with 29 settled lots; 5m and no-fill-recalculation controls agree. ETH same-open reversals depend on a future completed chart bar and are recorded only as unresolved evidence.",
        ]],
        "results": [{
            "id": 3111, "market": "BTCUSDT", "group": "FMZ · BTC KAMA/HMA causal history",
            "exit": "Named next-open close and opposite entry",
            "period": f"Binance USD-M · {iso_day(btc['start'])} to {iso_day(btc['end'])} UTC exclusive",
            "archive_interval": "45m", "interval": "45m", "currency": "USDT",
            **ledger_metrics(lots, CAPITAL, 1),
        }],
        "verified_scopes": verified["results"],
        "raw_sha256": verified["raw_sha256"],
    }
    write(output, report)


if __name__ == "__main__":
    finalize(*map(Path, sys.argv[1:]))
