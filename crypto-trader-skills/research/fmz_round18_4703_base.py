"""Fetch official hourly quotes on the archived pivot strategy's execution days."""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen

from research.fmz_round7_magnifier import iso_day, sha256, write

DAY = 86_400_000
HOUR = 3_600_000


def fetch(work, output):
    probe = json.loads((work / "4703-probe.json").read_bytes())
    requests = sorted(
        {
            (case["market"], order["time"])
            for case in probe
            for order in case["authored"]["strategy"]["orders"]
        }
    )
    assert len(requests) == 14

    def task(z):
        market, start = z
        assert start % DAY == 0
        basename = f"4703-{market}-{iso_day(start)}.json"
        file = output / basename
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={market}&interval=1h&startTime={start}&endTime={start + DAY - 1}&limit=24"
        if not file.is_file():
            with urlopen(url, timeout=30) as response:
                assert response.status == 200
                data = response.read()
            values = json.loads(data)
            assert [row[0] for row in values] == list(range(start, start + DAY, HOUR))
            file.write_bytes(data)
        values = json.loads(file.read_bytes())
        assert [row[0] for row in values] == list(range(start, start + DAY, HOUR))
        assert all(row[6] == row[0] + HOUR - 1 for row in values)
        return {
            "market": market,
            "date": start,
            "file": basename,
            "sha256": sha256(file),
            "url": url,
        }

    with ThreadPoolExecutor(max_workers=3) as pool:
        records = list(pool.map(task, requests))
    write(output / "4703-hourly-manifest.json", records)


if __name__ == "__main__":
    fetch(*map(Path, sys.argv[1:]))
