"""Freeze #1985's source-backed causal projection differences outside results."""

import sys
from pathlib import Path

from research.fmz_round7_magnifier import read, sha256, write

SOURCE = "96e08e35c70481f1f4011e3b34d390df3d4ad4fe24f08608b63da512e5890d5a"
ENGINE = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"


def finalize(work, output):
    assert sha256(work / "source-1985.md") == SOURCE
    assert sha256(work / "priced-runtime/pine_compat/pine_compat.pyd") == ENGINE
    inputs = read(work / "1985-inputs.json")
    raw = work / "1985-replay.json"
    results = []
    for replay, ref, changed, on_closed, off_closed in zip(
        read(raw), inputs["feeds"], (20, 12), (68, 50), (58, 47), strict=True
    ):
        assert replay["market"] == ref["market"]
        path = work / ref["file"]
        assert sha256(path) == ref["sha256"]
        frame = read(path)
        chart, higher = frame["chart"], frame["higher"]
        assert len(chart) == 2016 and len(higher) == 84
        original = replay["raw"]["exceptions"]
        legacy = replay["v2_default"]["exceptions"]
        assert all(row.startswith("E_LEGACY_REFERENCE_TYPE") for row in original + legacy)
        before, after = replay["v5_lookahead_on"], replay["v5_lookahead_off"]
        assert len(before["strategy"]["trades"]) == on_closed
        assert len(after["strategy"]["trades"]) == off_closed
        assert not before["diagnostics"] and not after["diagnostics"]
        (current, buy, sell), (confirmed, new_buy, new_sell) = (
            tuple(p["values"] for p in replay_mode["plots"][-3:])
            for replay_mode in (before, after)
        )
        differences = []
        for i, (a, b, x, y, u, v) in enumerate(zip(current, confirmed, buy, sell, new_buy, new_sell, strict=True)):
            offset = i // 24
            assert a == higher[offset][4]
            assert b == (None if i < 23 else higher[(i + 1) // 24 - 1][4])
            if (x, y) != (u, v):
                signal_close = chart[i][0] + 300_000
                reference_close = higher[offset][0] + 7_200_000
                assert signal_close < reference_close and a != b
                differences.append({
                    "chart_bar": i, "signal_close": signal_close, "htf_close": reference_close,
                    "unconfirmed_close": a, "last_confirmed_close": b,
                    "lookahead_on_long_short": [x, y], "lookahead_off_long_short": [u, v],
                })
        assert len(differences) == changed
        results.append({
            **ref, "shared_signal_observations": len(chart),
            "diagnostic_lookahead_trade_count": on_closed,
            "diagnostic_confirmed_trade_count": off_closed,
            "original_compiler_diagnostics": original, "lookahead_changes": differences,
        })
    disposition = [
        1985,
        "Pending · mixed Pine version and active unconfirmed 120m data",
        "Saved 5m BTC/ETH source calls request.security from a v2 declaration. The documented legacy 120m projection uses unconfirmed candle data for 20 BTC and 12 ETH changed decisions. A causal v5 lookahead-off setting changes historical orders and needs authored confirmation. No result row generated for either diagnostic.",
    ]
    report = {
        "schema": "FMZ 1985 mixed-version higher-timeframe causality evidence",
        "source_sha256": SOURCE, "engine_sha256": ENGINE, "raw_replay_sha256": sha256(raw),
        "source_url": "https://www.fmz.com/strategy/441065", "input_data": inputs,
        "higher_timeframe_reference": "https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/#lookahead",
        "mode_diagnostics": results, "coverage": [disposition], "results": [],
    }
    write(output, report)


if __name__ == "__main__":
    finalize(*map(Path, sys.argv[1:]))
