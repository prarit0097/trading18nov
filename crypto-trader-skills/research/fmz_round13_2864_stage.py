"""Prepare checked Binance one-minute chart windows for FMZ #2864."""

import json
import sys
from itertools import chain
from pathlib import Path

from research.fmz_round7_magnifier import (
    date_ms,
    raw_ohlcv,
    read,
    sha256,
    verified_archives,
)


def stage(work, public, reference):
    hashes = {item["name"]: item["sha256"] for item in read(reference)["inputs"]}
    inputs = []
    refs = []
    for market in ("BTCUSDT", "ETHUSDT"):
        archives = verified_archives(
            public, market, "1m", ("2026-08", "2026-09", "2026-10"), inputs
        )
        assert all(sha256(path) == hashes[path.name] for path in archives)
        candles = list(
            chain.from_iterable(raw_ohlcv(path, 60_000) for path in archives)
        )
        for a, b in (("2026-08-01", "2026-09-01"), ("2026-09-01", "2026-11-01")):
            start, stop = date_ms(a), date_ms(b)
            window = [bar for bar in candles if start <= bar[0] < stop]
            assert [bar[0] for bar in window] == list(range(start, stop, 60_000))
            path = work / f"2864-{market}-{a}.json"
            path.write_text(
                json.dumps(window, separators=(",", ":"), allow_nan=False),
                encoding="utf8",
            )
            refs.append(
                {
                    "file": path.name,
                    "market": market,
                    "start": start,
                    "stop": stop,
                    "bars": len(window),
                    "sha256": sha256(path),
                }
            )
    (work / "2864-inputs.json").write_text(
        json.dumps({"origins": inputs, "feeds": refs}, indent=2) + "\n", encoding="utf8"
    )


if __name__ == "__main__":
    stage(*map(Path, sys.argv[1:]))
