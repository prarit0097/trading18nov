"""Emit the saved opening-range zero-trade benchmark and guard sensitivity."""

import sys
from pathlib import Path

from research.fmz_round7_magnifier import iso_day, ledger_metrics, read, sha256, write

SOURCE = "f2715f774c0f3c96ed574b3d865b5a9d8078e392827d00d5ecd8375ccaac729e"
ENGINE = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
CAPITAL = 1_000_000


def finalize(work, output):
    proof = work / "1003-verified.json"
    audit = read(proof)
    data = read(work / "1003-inputs.json")
    assert sha256(work / "source-1003.md") == SOURCE
    assert sha256(work / "priced-runtime/pine_compat/pine_compat.pyd") == ENGINE
    isolation = read(work / "round3-isolation-python.json")
    assert set(isolation) == {"file_error", "network_error"}
    assert all(e[0] == "PermissionError" for e in isolation.values())
    cases = audit["cases"]
    assert [row["market"] for row in cases] == ["BTCUSDT", "ETHUSDT"]
    for row, feed, changed in zip(cases, data["feeds"], (10, 8), strict=True):
        assert (row["market"], row["file"]) == (feed["market"], feed["file"])
        assert sha256(work / row["file"]) == row["sha256"] == feed["sha256"]
        assert row["chart_bars"] == 720 and row["reference_bars"] == 1440 and row["base_bars"] == 2880
        assert row["session_starts"] == 22 and row["verified_zero_trades"]
        assert row["altered_na_guard_orders"] == changed
    attrs = {
        "id": 1003, "group": "FMZ · archived Pine v2 opening-range clock",
        "exit": "Source range or moving-average close",
        "period": f"Binance USD-M · {iso_day(cases[0]['start'])} to {iso_day(cases[0]['end'])} UTC exclusive",
        "archive_interval": "1h", "interval": "1h", "currency": "USDT",
    }
    report = {
        "schema": "FMZ 1003 native session timing and zero-order opening-range replay",
        "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
        "source_url": "https://www.fmz.com/strategy/426261",
        "source_sha256": SOURCE, "engine_sha256": ENGINE,
        "verified_sha256": sha256(proof), "input_data": data, "isolation": isolation,
        "model": {
            "source": "The archive's v2 symbol and timeframe aliases and legacy plot arrow arguments are normalized. The saved v_input_10=true explicitly enables shorts. All source rules and the unguarded opening-range reset are preserved.",
            "clock": "A 09:30–10:00 session window has no 1h opening bar. The 10:00–11:00 window appears at 10:00 UTC weekdays. At 30m there are exactly 22 valid session starts per market. Weekday session membership and the virtual daily session timestamp are calculated independently.",
            "zero_order_proof": "The archived reset compares a session timestamp with its immediately previous value using !=. A missing previous value does not trigger the comparison. Within each session the next value remains equal. Therefore neither range becomes available and neither direction orders a trade. Complete native flat marks and empty orders agree on both markets.",
            "sensitivity": "An explicit missing-value guard detects the 22 session starts. That optional source edit creates 10 BTC and 8 ETH diagnostic order events. Its outcomes are kept outside the saved variant metrics.",
        },
        "coverage": [[
            1003,
            "Tested · legacy session range stays undefined · no trades",
            "Complete saved UTC 1h/30m/15m data, restored archived short override and independent weekday clock. No range or trades under the pinned v2 rule. Explicit NA guard changes output and remains diagnostic only.",
        ]],
        "results": [
            {**attrs, "market": market, **ledger_metrics([], capital, 0)}
            for market, capital in (("BTCUSDT", CAPITAL), ("ETHUSDT", CAPITAL), ("BTCUSDT + ETHUSDT", 2 * CAPITAL))
        ],
        **audit,
    }
    write(output, report)


if __name__ == "__main__":
    finalize(*map(Path, sys.argv[1:]))
