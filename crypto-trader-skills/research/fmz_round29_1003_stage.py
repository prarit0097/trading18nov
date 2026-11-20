"""Stage #1003 actual 15m, 30m and 1h archived windows."""

import json
import sys
from pathlib import Path

from research.fmz_round7_magnifier import aggregate, date_ms, raw_ohlcv, sha256, verified_archives, write

M15 = 900_000


def stage(public, work):
    start, end = map(date_ms, ("2023-08-09", "2023-09-08"))
    archives, feeds = [], []
    for market in ("BTCUSDT", "ETHUSDT"):
        paths = verified_archives(public, market, "15m", ("2023-08", "2023-09"), archives)
        base = [r for z in paths for r in raw_ohlcv(z, M15) if start <= r[0] < end]
        assert [r[0] for r in base] == list(range(start, end, M15))
        chart = aggregate(base, 4)
        thirty = aggregate(base, 2)
        path = work / f"1003-{market}.json"
        path.write_bytes(json.dumps({"market": market, "start": start, "end": end, "chart": chart, "reference": thirty, "execution": base}, separators=(",", ":")).encode())
        feeds.append({"market": market, "file": path.name, "sha256": sha256(path), "chart_bars": len(chart), "reference_bars": len(thirty), "base_bars": len(base)})
    write(work / "1003-inputs.json", {"official_archives": archives, "feeds": feeds})


if __name__ == "__main__":
    stage(*map(Path, sys.argv[1:]))
