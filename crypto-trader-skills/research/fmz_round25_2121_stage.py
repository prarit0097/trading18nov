"""Stage actual daily, 2h decision and 1h execution archives for #2121."""

import json
import sys
from pathlib import Path

from research.fmz_round7_magnifier import aggregate, date_ms, raw_ohlcv, sha256, verified_archives, write

HOUR = 3_600_000
MONTHS = ("2022-11", "2022-12") + tuple(f"2023-{i:02}" for i in range(1, 12))


def stage(public, work):
    start, end = map(date_ms, ("2022-11-20", "2023-11-26"))
    receipts, feeds = [], []
    for market in ("BTCUSDT", "ETHUSDT"):
        paths = verified_archives(public, market, "1h", MONTHS, receipts)
        lower = [row for path in paths for row in raw_ohlcv(path, HOUR) if start <= row[0] < end]
        assert [row[0] for row in lower] == list(range(start, end, HOUR))
        chart, refs = (aggregate(lower, span) for span in (24, 2))
        name = f"2121-{market}.json"
        path = work / name
        payload = {"market": market, "start": start, "end": end, "chart": chart, "references": refs, "hour": lower}
        path.write_bytes(json.dumps(payload, separators=(",", ":"), allow_nan=False).encode())
        feeds.append({"market": market, "file": name, "sha256": sha256(path), "chart_bars": len(chart), "reference_bars": len(refs), "base_bars": len(lower)})
    write(work / "2121-inputs.json", {"official_archives": receipts, "feeds": feeds})


if __name__ == "__main__":
    stage(*map(Path, sys.argv[1:]))
