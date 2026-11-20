"""Stage saved daily rolling-volume #3805 inputs from hourly Binance archives."""

import json
import sys
from pathlib import Path

from research.fmz_round7_magnifier import aggregate, date_ms, raw_ohlcv, sha256, verified_archives, write

HOUR = 3_600_000
MONTHS = tuple(f"2023-{m:02}" for m in range(1, 13)) + ("2024-01",)


def stage(public, work):
    first, last = map(date_ms, ("2023-01-25", "2024-01-31"))
    books, feeds = [], []
    for market in ("BTCUSDT", "ETHUSDT"):
        paths = verified_archives(public, market, "1h", MONTHS, books)
        candles = [r for p in paths for r in raw_ohlcv(p, HOUR) if first <= r[0] < last]
        assert [r[0] for r in candles] == list(range(first, last, HOUR))
        chart = aggregate(candles, 24)
        path = work / f"3805-{market}.json"
        data = {"market": market, "start": first, "end": last, "hourly": candles, "chart": chart}
        path.write_bytes(json.dumps(data, separators=(",", ":"), allow_nan=False).encode())
        feeds.append({"market": market, "file": path.name, "sha256": sha256(path), "chart_bars": len(chart), "base_bars": len(candles)})
    write(work / "3805-inputs.json", {"official_archives": books, "feeds": feeds})


if __name__ == "__main__":
    stage(*map(Path, sys.argv[1:]))
