"""Record #3952's direct legacy-vs-confirmed daily decision difference."""

import math
import sys
from pathlib import Path

from research.fmz_round7_magnifier import read, sha256, write

SOURCE = "4d54a899e3638fd582f3fcec3126da7aa72ad1314d0b4915906e99c10dc20624"
ENGINE = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
H4, DAY = 14_400_000, 86_400_000


def finalize(work, output):
    assert sha256(work / "source-3952.md") == SOURCE
    assert sha256(work / "priced-runtime/pine_compat/pine_compat.pyd") == ENGINE
    market = read(work / "3952-inputs.json")
    proof = work / "3952-replay.json"
    details = []
    for item, row, before_close in zip(read(proof), market["feeds"], (3, 2), strict=True):
        assert item["market"] == row["market"]
        data = work / row["file"]
        assert sha256(data) == row["sha256"]
        payload = read(data)
        chart, daily = payload["chart"], payload["higher"]
        assert len(chart) == 180 and len(daily) == 30
        assert item["raw"]["exceptions"][0].startswith("E_LEX_CHAR")
        assert item["legacy"]["strategy"] == item["v5_on"]["strategy"]
        assert [p["values"] for p in item["legacy"]["plots"][-5:]] == [p["values"] for p in item["v5_on"]["plots"][-5:]]
        on, off = tuple(item[key] for key in ("v5_on", "v5_off"))
        assert not on["diagnostics"] and not off["diagnostics"]
        assert (len(on["strategy"]["trades"]), len(off["strategy"]["trades"])) == (4, 2)
        for_lookahead = [p["values"] for p in on["plots"][-5:]]
        for_confirmed = [p["values"] for p in off["plots"][-5:]]
        differences = []
        for i, (a, b) in enumerate(zip(zip(*for_lookahead), zip(*for_confirmed), strict=True)):
            for native, k in ((a[0], i // 6), (b[0], (i + 1) // 6 - 1)):
                if k < 1:
                    assert native is None
                else:
                    old = daily[k - 1][4]
                    ratio = (daily[k][4] - old) / old
                    assert math.isclose(ratio, native, abs_tol=1e-10)
            if i % 6 != 5 and a[1:3] != b[1:3]:
                signal, available = chart[i][0] + H4, daily[i // 6][0] + DAY
                assert signal < available
                differences.append({"bar": i, "four_hour_close": signal, "daily_close": available, "lookahead": a, "confirmed": b})
        assert len(differences) == before_close
        details.append({**row, "early_entry_changes": differences, "lookahead_diagnostic_lots": 4, "confirmed_diagnostic_lots": 2})
    report = {
        "schema": "FMZ 3952 active daily close dependency evidence",
        "source_sha256": SOURCE, "engine_sha256": ENGINE,
        "source_url": "https://www.fmz.com/strategy/426842",
        "raw_diagnostic_sha256": sha256(proof), "input_data": market,
        "evidence": details,
        "coverage": [[
            3952,
            "Pending · active Pine v2 daily-close lookahead",
            "The v2 legacy route and explicit lookahead-on v5 control exactly match. Legacy confidence sees the final 24h close before that close exists. Confirmed daily timing changes three early BTC entries and two ETH entries, and changes closures. A source-authorized causal policy is needed before reporting results.",
        ]],
        "results": [],
    }
    write(output, report)


if __name__ == "__main__":
    finalize(*map(Path, sys.argv[1:]))
