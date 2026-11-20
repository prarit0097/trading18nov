"""Independently roll verified official Binance minute data to archive host base period."""

import hashlib
import json
import sys
from itertools import chain, pairwise
from pathlib import Path

from research.fmz_round7_magnifier import (
    aggregate,
    date_ms,
    raw_ohlcv,
    read,
    sha256,
    verified_archives,
)

MONTHS = ("2026-08", "2026-09", "2026-10")
WINDOWS = (("2026-08-01", "2026-09-01"), ("2026-09-01", "2026-11-01"))
MINUTE = 60_000


def stage(scratch, public, frozen):
    pinned = {row["name"]: row["sha256"] for row in read(frozen)["inputs"]}
    receipt = []
    manifest = []
    for market in ("BTCUSDT", "ETHUSDT"):
        archives = verified_archives(public, market, "1m", MONTHS, manifest)
        assert all(sha256(path) == pinned[path.name] for path in archives)
        records = list(
            chain.from_iterable(raw_ohlcv(path, MINUTE) for path in archives)
        )
        assert all(left[0] + MINUTE == right[0] for left, right in pairwise(records))
        for first, last in WINDOWS:
            start, end = date_ms(first), date_ms(last)
            candles = [r for r in records if start <= r[0] < end]
            assert len(candles) * MINUTE == end - start
            chart = aggregate(candles, 60)
            lower = aggregate(candles, 15)
            earlier = read(scratch / f"feed-{market}-60-10-{first}.json")
            assert [list(row) for row in chart] == earlier["chart"]
            assert len(chart) * 4 == len(lower)
            path = scratch / f"native-base-{market}-{first}.json"
            contents = json.dumps(
                lower, separators=(",", ":"), allow_nan=False
            ).encode()
            path.write_bytes(contents)
            receipt.append(
                {
                    "name": path.name,
                    "sha256": hashlib.sha256(contents).hexdigest(),
                    "15m_bars": len(lower),
                }
            )
    payload = {"inputs": manifest, "derived": receipt}
    (scratch / "5708-input-manifest.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf8"
    )


if __name__ == "__main__":
    stage(*map(Path, sys.argv[1:]))
