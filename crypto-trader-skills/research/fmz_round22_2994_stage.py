"""Prepare #2994 archived 1h data and deterministic day and intraday aggregations."""

import json
import sys
from pathlib import Path

from research.fmz_round7_magnifier import aggregate, date_ms, raw_ohlcv, sha256, verified_archives, write

HOUR = 3_600_000
MONTHS = tuple(f"2023-{i:02}" for i in range(1, 13)) + ("2024-01",)
MARKETS = ("BTCUSDT", "ETHUSDT")


def stage(public, work):
    first, last = map(date_ms, ("2023-01-09", "2024-01-15"))
    checks, feeds = [], []
    for market in MARKETS:
        paths = verified_archives(public, market, "1h", MONTHS, checks)
        hourly = [
            row for path in paths for row in raw_ohlcv(path, HOUR)
            if first <= row[0] < last
        ]
        assert [row[0] for row in hourly] == list(range(first, last, HOUR))
        day, half, four = (aggregate(hourly, span) for span in (24, 12, 4))
        name = f"2994-{market}.json"
        path = work / name
        payload = {"market": market, "start": first, "end": last, "day": day, "hour": hourly, "four": four, "half": half}
        path.write_bytes(json.dumps(payload, separators=(",", ":"), allow_nan=False).encode())
        feeds.append({"file": name, "sha256": sha256(path), "chart_bars": len(day), "base_bars": len(hourly), "market": market})
    write(work / "2994-inputs.json", {"official_archives": checks, "feeds": feeds})


if __name__ == "__main__":
    stage(*map(Path, sys.argv[1:]))
