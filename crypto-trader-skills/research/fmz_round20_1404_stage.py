"""Prepare the two pinned 3m/1m #1404 public replay frames."""

import json
import sys
from decimal import Decimal
from pathlib import Path

from research.fmz_round7_magnifier import aggregate, date_ms, sha256, verified_archives, write
from research.fmz_round8_fx import csv_rows

ARCHIVES = {
    "BTCUSDT-1m-2023-12.zip": "947ea9b1c5dfa301f1d5ff89d28f3ee49bc73eef2cfa1f0dc4024048458eb60b",
    "ETHUSDT-1m-2023-12.zip": "6ebf84e9b991619d772af5d9835175c5e456688c33c72affa35b3aecbac30d09",
}
MINUTE = 60_000


def stage(official, work):
    first, last = map(date_ms, ("2023-12-19", "2023-12-26"))
    checks, feeds = [], []
    for market in ("BTCUSDT", "ETHUSDT"):
        path, = verified_archives(official, market, "1m", ("2023-12",), checks)
        assert sha256(path) == ARCHIVES[path.name]
        lower, no_prints = [], []
        for row in csv_rows(path):
            if not row[0].isdigit():
                continue
            stamp = int(row[0])
            if not first <= stamp < last:
                continue
            assert int(row[6]) == stamp + MINUTE - 1
            o, h, low, c, v = map(Decimal, row[1:6])
            assert 0 < low <= min(o, c) <= max(o, c) <= h and v >= 0
            if v == 0:
                assert o == h == low == c and Decimal(row[7]) == Decimal(row[8]) == 0
                no_prints.append(stamp)
            lower.append([stamp, *map(float, (o, h, low, c, v))])
        assert [row[0] for row in lower] == list(range(first, last, MINUTE))
        chart = aggregate(lower, 3)
        name = f"1404-{market}.json"
        path = work / name
        payload = {"market": market, "start": first, "end": last, "chart": chart, "lower": lower}
        path.write_bytes(json.dumps(payload, separators=(",", ":"), allow_nan=False).encode())
        feeds.append({"file": name, "sha256": sha256(path), "chart_bars": len(chart), "base_bars": len(lower), "market": market, "zero_print_timestamps": no_prints})
    write(work / "1404-inputs.json", {"official_archives": checks, "feeds": feeds})


if __name__ == "__main__":
    stage(*map(Path, sys.argv[1:]))
