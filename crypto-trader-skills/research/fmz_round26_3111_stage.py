"""Stage #3111's saved 45m chart from exact official five-minute candles."""

import json
import sys
from pathlib import Path

from research.fmz_round7_magnifier import aggregate, date_ms, raw_ohlcv, sha256, verified_archives, write

STEP = 300_000


def stage(public, work):
    start, end = map(date_ms, ("2024-01-29", "2024-02-05"))
    checks, feeds = [], []
    for market in ("BTCUSDT", "ETHUSDT"):
        paths = verified_archives(public, market, "5m", ("2024-01", "2024-02"), checks)
        base = [row for path in paths for row in raw_ohlcv(path, STEP) if start <= row[0] < end]
        assert [r[0] for r in base] == list(range(start, end, STEP))
        chart = aggregate(base, 9)
        path = work / f"3111-{market}.json"
        path.write_bytes(json.dumps({"market": market, "start": start, "end": end, "base": base, "chart": chart}, separators=(",", ":"), allow_nan=False).encode())
        feeds.append({"market": market, "file": path.name, "sha256": sha256(path), "chart_bars": len(chart), "base_bars": len(base)})
    write(work / "3111-inputs.json", {"official_archives": checks, "feeds": feeds})


if __name__ == "__main__":
    stage(*map(Path, sys.argv[1:]))
