"""Freeze diagnostics for archived mixed-type Pine equality without ranking them."""

import sys
from collections import Counter
from pathlib import Path

from research.fmz_round7_magnifier import read, sha256, write

SOURCE = "4680d886ec40d847a9b7547624cdedc3b00e4045fc36d61051ad9c6275df442e"
ENGINE = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
COMPARISONS = (
    "series bool as a control",
    "series bool equals integer 1",
    "series bool equals literal true",
    "true boolean input equals integer 1",
    "series bool equals integer 0",
    "literal true equals integer 1",
    "literal false equals integer 0",
    "integer 1 equals integer 1",
)


def summarize(work, output):
    assert sha256(work / "source-1404.md") == SOURCE
    assert sha256(work / "priced-runtime/pine_compat/pine_compat.pyd") == ENGINE
    minimum = work / "1404-equality.json"
    comparisons = read(minimum)
    assert comparisons["v4"] == [
        [0, 1, 1], [0, 0, 0], [0, 1, 1], [0, 0, 0],
        [0, 0, 0], [0, 0, 0], [0, 0, 0], [1, 1, 1],
    ]
    assert comparisons["v5"] == [
        [0, 1, 1], [0, 1, 1], [0, 1, 1], [1, 1, 1],
        [1, 0, 0], [1, 1, 1], [1, 1, 1], [1, 1, 1],
    ]
    market_inputs = read(work / "1404-inputs.json")
    raw = work / "1404-replay.json"
    diagnostics = []
    for result, ref, legacy_count, modern_split in zip(
        read(raw), market_inputs["feeds"], (8, 13), (4, 6), strict=True
    ):
        assert result["file"] == ref["file"]
        assert sha256(work / ref["file"]) == ref["sha256"]
        assert ref["chart_bars"] == 3360 and ref["base_bars"] == 10080
        assert ref["zero_print_timestamps"] == []
        assert result["invalid"]["exception"] == [
            "E_PARSE_EXPR:Error:40:26: expected expression",
            "E_ASSIGN_TYPE:Error:51:5: cannot assign input float to `stop` of type input int",
        ]
        version_map = {k: result[k] for k in ("original", "migrated", "base", "explicit_bool")}
        assert all(not r["diagnostics"] and not r["strategy"]["diagnostics"] for r in version_map.values())
        legacy, migrated, base, explicit = tuple(version_map.values())
        assert migrated["strategy"] == base["strategy"] == explicit["strategy"]
        assert [p["values"] for p in base["plots"]] == [p["values"] for p in explicit["plots"]]
        legacy_lots = Counter(lot["id"] for lot in legacy["strategy"]["trades"])
        base_lots = Counter(lot["id"] for lot in base["strategy"]["trades"])
        assert legacy_lots == {"short": legacy_count}
        assert base_lots == {"long": modern_split, "short": modern_split}
        assert all(legacy["plots"][-4]["values"][i] == 0 for i in range(ref["chart_bars"]))
        assert any(level == 1 for level in base["plots"][-4]["values"])
        diagnostics.append({
            "market": ref["market"],
            "v4_chart_only_closes_by_side": dict(legacy_lots),
            "v5_same_comparison_and_explicit_bool_closes_by_side": dict(base_lots),
            "v5_complete_base_matches_chart_only": True,
            "raw_buy_and_sell_series_match": (
                [p["values"] for p in legacy["plots"][-6:-4]]
                == [p["values"] for p in base["plots"][-6:-4]]
            ),
        })
    assert all(row["raw_buy_and_sell_series_match"] for row in diagnostics)
    report = {
        "schema": "FMZ #1404 pending mixed-type-equality evidence",
        "source": "https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/%E5%88%A9%E7%94%A8%E5%8F%8C%E5%90%91RSI%E7%AA%81%E7%A0%B4%E7%AD%96%E7%95%A5Dual-RSI-Breakthrough-Strategy.md",
        "source_sha256": SOURCE,
        "engine_sha256": ENGINE,
        "raw_replay_sha256": sha256(raw),
        "minimal_repro_sha256": sha256(minimum),
        "date_window_utc": ["2023-12-19", "2023-12-26"],
        "references": [
            "https://www.fmz.com/strategy/436754",
            "https://www.fmz.com/digest-topic/9637",
            "https://www.tradingview.com/pine-script-docs/v4/language/operators/#comparison-operators",
            "https://www.tradingview.com/pine-script-docs/v4/language/type-system/#type-casting",
            "https://github.com/binance/binance-public-data",
        ],
        "inputs": market_inputs,
        "minimal_probe": [
            {"expression": expr, "v4": v4, "v5": v5}
            for expr, v4, v5 in zip(COMPARISONS, comparisons["v4"], comparisons["v5"], strict=True)
        ],
        "archive_diagnostics": diagnostics,
        "coverage": [[
            1404,
            "Pending · FMZ Pine v4 mixed bool/integer equality",
            "Pinned Binance 3m/1m BTC and ETH feeds are complete. Literal archived buy==1/sell==1 keep the decision state at zero in Pine Compat v4. They toggle it in Pine Compat v5, which exactly matches the explicit-boolean variant. The case changes side and close counts. FMZ documents permissive comparisons, but an authoritative trace for this archived host build and exact bool/integer operator is still needed.",
        ]],
        "results": [],
    }
    write(output, report)


if __name__ == "__main__":
    summarize(*map(Path, sys.argv[1:]))
