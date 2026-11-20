"""Stage actual daily and four-hour decision candles for the #3952 timing proof."""

import json
import sys
from pathlib import Path

from research.fmz_round7_magnifier import aggregate, date_ms, raw_ohlcv, sha256, verified_archives, write


def stage(public, work):
    start, end = map(date_ms, ("2023-08-14", "2023-09-13"))
    receipts, feeds = [], []
    for market in ("BTCUSDT", "ETHUSDT"):
        paths = verified_archives(public, market, "1h", ("2023-08", "2023-09"), receipts)
        prices = [r for p in paths for r in raw_ohlcv(p, 3_600_000) if start <= r[0] < end]
        assert [r[0] for r in prices] == list(range(start, end, 3_600_000))
        chart, higher = (aggregate(prices, n) for n in (4, 24))
        path = work / f"3952-{market}.json"
        path.write_bytes(json.dumps({"market": market, "start": start, "end": end, "chart": chart, "higher": higher}, separators=(",", ":")).encode())
        feeds.append({"market": market, "file": path.name, "sha256": sha256(path), "chart_bars": len(chart), "higher_bars": len(higher)})
    write(work / "3952-inputs.json", {"official_archives": receipts, "feeds": feeds})


if __name__ == "__main__":
    stage(*map(Path, sys.argv[1:]))
