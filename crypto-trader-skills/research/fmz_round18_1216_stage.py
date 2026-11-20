"""Build archived 15-minute charts and complete 5-minute groups for #1216."""

import json
import sys
from decimal import Decimal
from pathlib import Path

from research.fmz_round7_magnifier import (
    aggregate,
    date_ms,
    read,
    sha256,
    verified_archives,
    write,
)
from research.fmz_round8_fx import csv_rows

MINUTE = 60_000
ARCHIVE_HASHES = {
    "BTCUSDT-5m-2023-09.zip": "7f44a35a1dc7f23c82a35c9afcaa8c64bf533734c913ab7c5f85eb0e5fbc76e1",
    "ETHUSDT-5m-2023-09.zip": "a0c54377ba4b17c4e1016770cee160c71a5fb0b6fd1041cd5f626e7575f89afa",
}


def selected_rows(archive, start, end):
    for row in csv_rows(archive):
        if not row[0].isdigit():
            continue
        stamp = int(row[0])
        if start <= stamp < end:
            assert int(row[6]) == stamp + 5 * MINUTE - 1
            open_, high, low, close, volume = map(Decimal, row[1:6])
            assert (
                0 < low <= min(open_, close) <= max(open_, close) <= high and volume > 0
            )
            yield (stamp, *map(float, (open_, high, low, close, volume)))


def record(work, market, start, stop, chart, lower, origins, kind):
    assert [bar[0] for bar in chart] == list(range(start, stop, 15 * MINUTE))
    assert [bar[0] for bar in lower] == list(range(start, stop, 5 * MINUTE))
    payload = {
        "symbol": market,
        "start": start,
        "end": stop,
        "chart": chart,
        "lower": lower,
    }
    path = work / f"1216-{market}-{start}.json"
    path.write_bytes(
        json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
    )
    return {
        "file": path.name,
        "sha256": sha256(path),
        "market": market,
        "chart_bars": len(chart),
        "base_bars": len(lower),
        "source_inputs": origins,
        "sample": kind,
    }


def stage(official, minute_work, minute_reference, work):
    start, end = map(date_ms, ("2023-09-19", "2023-09-26"))
    official_manifest = []
    samples = []
    for market in ("BTCUSDT", "ETHUSDT"):
        (archive,) = verified_archives(
            official, market, "5m", ("2023-09",), official_manifest
        )
        digest = sha256(archive)
        assert digest == ARCHIVE_HASHES[archive.name]
        source = list(selected_rows(archive, start, end))
        samples.append(
            record(
                work,
                market,
                start,
                end,
                aggregate(source, 3),
                source,
                [digest],
                "Saved FMZ range",
            )
        )
    for known in read(minute_reference)["runs"]:
        path = minute_work / known["file"]
        assert sha256(path) == known["sha256"]
        one_minute = read(path)
        samples.append(
            record(
                work,
                known["market"],
                known["start"],
                known["stop"],
                aggregate(one_minute, 15),
                aggregate(one_minute, 5),
                [known["sha256"]],
                "Project comparison range",
            )
        )
    write(
        work / "1216-inputs.json",
        {"official_archives": official_manifest, "samples": samples},
    )


if __name__ == "__main__":
    stage(*map(Path, sys.argv[1:]))
