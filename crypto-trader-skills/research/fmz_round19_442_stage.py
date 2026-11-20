"""Stage the original seven-day #442 Binance chart and prior-day USD rates."""

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
from research.fmz_round8_fx import csv_rows, prior_close_rates

DAY = 86_400_000
MINUTES_15 = 900_000
FX_SHA = "6239aded455e686c90f7a93f4cb11391097c64cb96580035ea874960ef472f7f"
ARCHIVES = {
    "BTCUSDT-15m-2023-12.zip": "f6b191e620d269d229dee0c5b9abfb6e9610bd0a8e6718d2a96e0e820a013bb0",
    "ETHUSDT-15m-2023-12.zip": "8df8f98f81eda3ffc0a3514d9b643c0701c433fb2ee2241dac4e04abe6d312c1",
}


def stage(inputs, work):
    start, end = map(date_ms, ("2023-12-13", "2023-12-20"))
    usd = inputs / "442-usdt-usd-archive-fx.json"
    assert sha256(usd) == FX_SHA
    supplied = prior_close_rates(read(usd))
    rates = supplied["pairs"][0]["rates"]
    rates[:] = [r for r in rates if start <= r["effectiveTime"] < end]
    assert [r["effectiveTime"] for r in rates] == list(range(start, end, DAY))
    fx_file = work / "442-rates.json"
    fx_file.write_bytes(
        json.dumps(supplied, separators=(",", ":"), allow_nan=False).encode()
    )
    records = []
    sources = []
    for market in ("BTCUSDT", "ETHUSDT"):
        (archive,) = verified_archives(inputs, market, "15m", ("2023-12",), sources)
        assert sha256(archive) == ARCHIVES[archive.name]
        base = []
        for r in csv_rows(archive):
            if not r[0].isdigit():
                continue
            stamp = int(r[0])
            if start <= stamp < end:
                o, h, l, c, v = map(Decimal, r[1:6])
                assert int(r[6]) == stamp + MINUTES_15 - 1
                assert 0 < l <= min(o, c) <= max(o, c) <= h and v > 0
                base.append([stamp, *map(float, (o, h, l, c, v))])
        assert [r[0] for r in base] == list(range(start, end, MINUTES_15))
        out = work / f"442-historical-{market}.json"
        chart = aggregate(base, 2)
        result = {
            "market": market,
            "start": start,
            "stop": end,
            "chart": chart,
            "base": base,
        }
        out.write_bytes(
            json.dumps(result, separators=(",", ":"), allow_nan=False).encode()
        )
        records.append(
            {
                "market": market,
                "file": out.name,
                "sha256": sha256(out),
                "chart_bars": len(chart),
                "base_bars": len(base),
            }
        )
    manifest = {
        "fx": {
            "file": fx_file.name,
            "sha256": sha256(fx_file),
            "source_sha256": FX_SHA,
        },
        "market_archives": sources,
        "records": records,
    }
    write(work / "442-inputs.json", manifest)


if __name__ == "__main__":
    stage(*map(Path, sys.argv[1:]))
