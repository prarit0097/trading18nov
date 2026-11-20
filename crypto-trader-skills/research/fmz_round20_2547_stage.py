"""Stage #2547 FMZ saved hourly and quarter-hour futures inputs."""

import json
import sys
from decimal import Decimal
from pathlib import Path

from research.fmz_round7_magnifier import aggregate, date_ms, sha256, verified_archives, write
from research.fmz_round8_fx import csv_rows

M15 = 900_000
ARCHIVES = {
    "BTCUSDT-15m-2023-10.zip": "bf3f1b7d22b67155373cbc0334ec44c34c8861bf2127ccd432698d95aa31ead6",
    "ETHUSDT-15m-2023-10.zip": "ecd769121c93962daf9cd5ebfc251e44466db72cf9e1487ce343888056dfadd4",
    "BTCUSDT-15m-2023-11.zip": "e70b84bec57cc0a76f9066cf5277b8c2ea3f4f4f03771f478a350160fa81b564",
    "ETHUSDT-15m-2023-11.zip": "cd0ddd41ffd597a7c886cc84406c7e12d8de1d1a330680e9f47fe50f474f46ec",
}


def stage(official, work):
    first, last = map(date_ms, ("2023-10-24", "2023-11-23"))
    checks = []
    feeds = []
    for market in ("BTCUSDT", "ETHUSDT"):
        paths = verified_archives(official, market, "15m", ("2023-10", "2023-11"), checks)
        lower = []
        no_prints = []
        for path in paths:
            assert sha256(path) == ARCHIVES[path.name]
            for row in csv_rows(path):
                if not row[0].isdigit():
                    continue
                t = int(row[0])
                if first <= t < last:
                    assert int(row[6]) == t + M15 - 1
                    o, h, l, c, v = map(Decimal, row[1:6])
                    assert 0 < l <= min(o, c) <= max(o, c) <= h and v >= 0
                    if v == 0:
                        assert o == h == l == c and Decimal(row[7]) == Decimal(row[8]) == 0
                        no_prints.append(t)
                    lower.append([t, *map(float, (o, h, l, c, v))])
        assert [row[0] for row in lower] == list(range(first, last, M15))
        chart = aggregate(lower, 4)
        name = f"2547-{market}.json"
        path = work / name
        payload = {"market": market, "start": first, "end": last, "chart": chart, "lower": lower}
        path.write_bytes(json.dumps(payload, separators=(",", ":"), allow_nan=False).encode())
        feeds.append({"file": name, "sha256": sha256(path), "chart_bars": len(chart), "base_bars": len(lower), "market": market, "zero_print_timestamps": no_prints})
    write(work / "2547-inputs.json", {"official_archives": checks, "feeds": feeds})


if __name__ == "__main__":
    stage(*map(Path, sys.argv[1:]))
