"""Use public last-day minute data to respect the exact #1073 end timestamp."""

import json
import math
import sys
from pathlib import Path

from research.fmz_round7_magnifier import aggregate, date_ms, sha256, verified_archives, write
from research.fmz_round8_fx import csv_rows

M1 = 60_000
M15 = 15 * M1
MARKETS = ("BTCUSDT", "ETHUSDT")
TERMINAL = {
    "BTCUSDT": "1e873acca2d20efa6597a0ea4a6a14792cb5a4004bd1ab294519a4601bc5c39b",
    "ETHUSDT": "c8fcfad41d208796da1b0d843411323e3558cdaa437f5a40919374500aaf19ca",
}


def checked_rows(path, first, last, step):
    for row in csv_rows(path):
        if not row[0].isdigit() or not first <= (time := int(row[0])) < last:
            continue
        o, high, low, c, volume = map(float, row[1:6])
        assert int(row[6]) == time + step - 1
        assert 0 < low <= min(o, c) <= max(o, c) <= high and volume >= 0
        if volume == 0:
            assert o == high == low == c and float(row[7]) == int(row[8]) == 0
        yield time, o, high, low, c, volume


def stage(monthly, terminal, work):
    first, midnight = map(date_ms, ("2022-04-16", "2022-05-16"))
    last = midnight - M1
    receipts, outputs = [], []
    for market in MARKETS:
        archive_paths = verified_archives(monthly, market, "15m", ("2022-04", "2022-05"), receipts)
        quarter = [row for path in archive_paths for row in checked_rows(path, first, midnight, M15)]
        assert [row[0] for row in quarter] == list(range(first, midnight, M15))
        zero_prints = [row[0] for row in quarter if row[5] == 0]
        assert zero_prints == [1651444200000]
        assert all(row[5] > 0 for row in quarter[::8])
        name = f"{market}-1m-2022-05-15.zip"
        daily = terminal / name
        assert sha256(daily) == TERMINAL[market]
        assert (terminal / f"{name}.CHECKSUM").read_text().split() == [TERMINAL[market], name]
        receipts.append({"name": name, "sha256": TERMINAL[market], "url": f"https://data.binance.vision/data/futures/um/daily/klines/{market}/1m/{name}"})
        tail = list(checked_rows(daily, midnight - M15, midnight, M1))
        assert [row[0] for row in tail] == list(range(midnight - M15, midnight, M1))
        assert all(row[5] > 0 for row in tail)
        whole, = aggregate(tail, 15)
        assert whole[:5] == quarter[-1][:5]
        assert math.isclose(whole[5], quarter[-1][5], rel_tol=0, abs_tol=1e-7)
        clipped, = aggregate(tail[:-1], 14)
        assert tail[-1][0] == last
        clipped_base = [*quarter[:-1], clipped]
        data = {
            "market": market, "start": first, "end": last, "base": clipped_base,
            "chart": aggregate(clipped_base, 8), "hour": aggregate(clipped_base, 4),
            "four": aggregate(clipped_base, 16), "half": aggregate(clipped_base, 48),
            "terminal_full_quarter": whole, "terminal_clipped_quarter": clipped,
            "excluded_minute": tail[-1],
        }
        path = work / f"1073-{market}.json"
        path.write_bytes(json.dumps(data, separators=(",", ":"), allow_nan=False).encode())
        outputs.append({"market": market, "file": path.name, "sha256": sha256(path), "chart_bars": len(data["chart"]), "base_bars": len(clipped_base), "zero_print_quarters": zero_prints})
    write(work / "1073-inputs.json", {"inputs": receipts, "feeds": outputs})


if __name__ == "__main__":
    stage(*map(Path, sys.argv[1:]))
