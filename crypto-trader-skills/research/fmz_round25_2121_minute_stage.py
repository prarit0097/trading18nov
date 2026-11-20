"""Resolve only the #2121 hours where both protective price levels were hit."""

import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path

from research.fmz_round7_magnifier import aggregate, sha256, write
from research.fmz_round8_fx import csv_rows

HOUR = 3_600_000
MINUTE = 60_000


def stage(public, work):
    audit = json.loads((work / "2121-verified.json").read_bytes())
    items = []
    for case in audit["results"]:
        market = case["market"]
        payload = json.loads((work / case["file"]).read_bytes())
        archival = {row[0]: row for row in payload["hour"]}
        for lot in case["ambiguities"]:
            stamp = lot["effective_base_exit"]
            date = datetime.fromtimestamp(stamp / 1000, UTC).date().isoformat()
            name = f"{market}-1m-{date}.zip"
            path = public / name
            checksum = sha256(path)
            assert (public / f"{name}.CHECKSUM").read_text().split() == [checksum, name]
            candles = []
            for r in csv_rows(path):
                if not r[0].isdigit() or not stamp <= (t := int(r[0])) < stamp + HOUR:
                    continue
                o, high, low, c, v = map(float, r[1:6])
                assert int(r[6]) == t + MINUTE - 1
                assert 0 < low <= min(o, c) <= max(o, c) <= high and v > 0
                candles.append([t, o, high, low, c, v])
            assert [row[0] for row in candles] == list(range(stamp, stamp + HOUR, MINUTE))
            hour, = aggregate(candles, 60)
            known = archival[stamp]
            assert list(hour[:5]) == known[:5]
            assert math.isclose(hour[5], known[5], rel_tol=1e-11, abs_tol=1e-8)
            items.append({
                "market": market, "time": stamp, "archive_name": name, "sha256": checksum,
                "url": f"https://data.binance.vision/data/futures/um/daily/klines/{market}/1m/{name}",
                "parent": known, "minutes": candles,
            })
    assert len(items) == 24
    write(work / "2121-minute-inputs.json", {"cases": items})


if __name__ == "__main__":
    stage(*map(Path, sys.argv[1:]))
