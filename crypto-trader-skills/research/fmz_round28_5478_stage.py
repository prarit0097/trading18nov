"""Prepare exact #5478 Dec 2023 chart, 5m base and USD configuration."""

import json
import sys
from pathlib import Path

from research.fmz_round7_magnifier import aggregate, date_ms, raw_ohlcv, sha256, verified_archives, write

DAY = 86_400_000
FX = "60773183a8ddfa1c633656d64679abb23e4725677f216a0fe829283682dcece1"


def stage(public, fx, root):
    a, b = map(date_ms, ("2023-12-20", "2023-12-27"))
    paths, tested = [], []
    for market in ("BTCUSDT", "ETHUSDT"):
        source, = verified_archives(public, market, "1m", ("2023-12",), paths)
        minute = [r for r in raw_ohlcv(source, 60_000) if a <= r[0] < b]
        assert [r[0] for r in minute] == list(range(a, b, 60_000))
        chart, base = (aggregate(minute, batch) for batch in (45, 5))
        path = root / f"5478-{market}.json"
        path.write_bytes(json.dumps({"market": market, "start": a, "end": b, "chart": chart, "base": base}, separators=(",", ":")).encode())
        tested.append({"market": market, "file": path.name, "sha256": sha256(path), "chart_bars": len(chart), "base_bars": len(base)})
    assert sha256(fx) == FX
    daily = sorted(x for x in json.loads(fx.read_bytes()) if a - DAY <= x[0] * 1000 < b - DAY)
    assert [row[0] * 1000 for row in daily] == list(range(a - DAY, b - DAY, DAY))
    quote = root / "5478-usd-prior.json"
    write(quote, {"schemaVersion": 1, "pairs": [{"from": "USDT", "to": "USD", "rates": [{"effectiveTime": r[0] * 1000 + DAY, "rate": r[4]} for r in daily]}]})
    write(root / "5478-inputs.json", {"archives": paths, "feeds": tested, "fx": {"file": quote.name, "sha256": sha256(quote), "source_sha256": FX}})


if __name__ == "__main__":
    stage(*map(Path, sys.argv[1:]))
