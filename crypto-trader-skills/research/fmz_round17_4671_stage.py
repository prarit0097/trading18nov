"""Prepare archived FMZ #4671 hourly charts and their fifteen-minute bases."""

import json
import sys
from itertools import chain
from pathlib import Path

from research.fmz_round7_magnifier import (
    aggregate,
    date_ms,
    raw_ohlcv,
    sha256,
    verified_archives,
    write,
)

ARCHIVE_HASHES = {
    "BTCUSDT-15m-2023-09.zip": "f1f628bb4b1976ba632150bf999fde302ddcfc8899ff369a5119bdd5dba1e0d5",
    "BTCUSDT-15m-2023-10.zip": "bf3f1b7d22b67155373cbc0334ec44c34c8861bf2127ccd432698d95aa31ead6",
    "ETHUSDT-15m-2023-09.zip": "a4f6804bd2edb66ff385d70a029a52447e68f31d94cccc803aafe34bb537d8ce",
    "ETHUSDT-15m-2023-10.zip": "ecd769121c93962daf9cd5ebfc251e44466db72cf9e1487ce343888056dfadd4",
}
MINUTE = 60_000


def stage(public, work):
    start = date_ms("2023-09-08")
    end = date_ms("2023-10-08")
    inputs = []
    feeds = []
    for market in ("BTCUSDT", "ETHUSDT"):
        zips = verified_archives(public, market, "15m", ("2023-09", "2023-10"), inputs)
        assert all(sha256(path) == ARCHIVE_HASHES[path.name] for path in zips)
        rows = chain.from_iterable(raw_ohlcv(path, 15 * MINUTE) for path in zips)
        base = [bar for bar in rows if start <= bar[0] < end]
        assert [bar[0] for bar in base] == list(range(start, end, 15 * MINUTE))
        chart = aggregate(base, 4)
        entry = {
            "symbol": market,
            "from": start,
            "to": end,
            "chart": chart,
            "intrabar": base,
        }
        path = work / f"4671-authored-{market}.json"
        path.write_bytes(
            json.dumps(entry, separators=(",", ":"), allow_nan=False).encode()
        )
        feeds.append(
            {
                "file": path.name,
                "sha256": sha256(path),
                "bars": len(chart),
                "base_bars": len(base),
            }
        )
    write(work / "4671-author-data.json", {"inputs": inputs, "feeds": feeds})


if __name__ == "__main__":
    stage(*map(Path, sys.argv[1:]))
