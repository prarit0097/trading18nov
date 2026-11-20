"""Stage archived USD #2514 input, complete 4h references and prior-day FX."""

import json
import sys
from itertools import chain
from pathlib import Path

from research.fmz_round7_magnifier import aggregate, date_ms, raw_ohlcv, sha256, verified_archives, write

HOUR = 3_600_000
DAY = HOUR * 24
MONTHS = ("2022-10", "2022-11", "2022-12") + tuple(f"2023-{i:02}" for i in range(1, 6))
MARKETS = ("BTCUSDT", "ETHUSDT")
FX_SHA = "b02737308751e548a358e32d3b3fea23466d29fb7c42e0ace29a6cf97218787a"


def stage(public, fx, work):
    first, last = map(date_ms, ("2022-10-17", "2023-05-14"))
    checks, feeds = [], []
    for market in MARKETS:
        paths = verified_archives(public, market, "1h", MONTHS, checks)
        hourly = [row for row in chain.from_iterable(raw_ohlcv(path, HOUR) for path in paths) if first <= row[0] < last]
        assert [row[0] for row in hourly] == list(range(first, last, HOUR))
        chart, base = (aggregate(hourly, span) for span in (24, 4))
        name = f"2514-{market}.json"
        path = work / name
        payload = {"market": market, "start": first, "end": last, "chart": chart, "base": base, "hours": hourly}
        path.write_bytes(json.dumps(payload, separators=(",", ":"), allow_nan=False).encode())
        feeds.append({"file": name, "sha256": sha256(path), "chart_bars": len(chart), "base_bars": len(base), "market": market})
    assert sha256(fx) == FX_SHA
    daily = sorted(row for row in json.loads(fx.read_bytes()) if first - DAY <= row[0] * 1000 < last - DAY)
    assert [row[0] * 1000 for row in daily] == list(range(first - DAY, last - DAY, DAY))
    assert all(row[1] <= min(row[3], row[4]) <= max(row[3], row[4]) <= row[2] and row[5] > 0 for row in daily)
    prepared = work / "2514-prior-usd.json"
    rules = {"schemaVersion": 1, "pairs": [{"from": "USDT", "to": "USD", "rates": [{"effectiveTime": row[0] * 1000 + DAY, "rate": row[4]} for row in daily]}]}
    write(prepared, rules)
    write(work / "2514-inputs.json", {"official_archives": checks, "feeds": feeds, "fx": {"source_sha256": FX_SHA, "file": prepared.name, "sha256": sha256(prepared)}})


if __name__ == "__main__":
    stage(*map(Path, sys.argv[1:]))
