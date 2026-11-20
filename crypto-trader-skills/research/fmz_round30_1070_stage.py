"""Prepare the declared January 2024 #1070 BTC and ETH comparison."""

import json
import sys
from pathlib import Path

from research.fmz_round7_magnifier import aggregate, date_ms, raw_ohlcv, sha256, verified_archives, write


def stage(public, work):
    start, end = map(date_ms, ("2024-01-01", "2024-02-01"))
    archives, feeds = [], []
    for market in ("BTCUSDT", "ETHUSDT"):
        path, = verified_archives(public, market, "15m", ("2024-01",), archives)
        base = [row for row in raw_ohlcv(path, 900_000) if start <= row[0] < end]
        assert [row[0] for row in base] == list(range(start, end, 900_000))
        chart = aggregate(base, 2)
        stage_path = work / f"1070-{market}.json"
        stage_path.write_bytes(json.dumps({"market": market, "start": start, "end": end, "chart": chart, "base": base}, separators=(",", ":")).encode())
        feeds.append({"market": market, "file": stage_path.name, "sha256": sha256(stage_path), "chart_bars": len(chart), "base_bars": len(base)})
    write(work / "1070-inputs.json", {"official_archives": archives, "feeds": feeds})


if __name__ == "__main__":
    stage(*map(Path, sys.argv[1:]))
