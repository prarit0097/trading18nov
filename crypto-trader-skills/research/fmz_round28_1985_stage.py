"""Stage real 5m and 120m candles for #1985's mixed-version merge diagnostic."""

import json
import sys
from pathlib import Path

from research.fmz_round7_magnifier import aggregate, date_ms, raw_ohlcv, sha256, verified_archives, write


def stage(public, work):
    start, end = map(date_ms, ("2024-01-28", "2024-02-04"))
    manifest, feeds = [], []
    for market in ("BTCUSDT", "ETHUSDT"):
        paths = verified_archives(public, market, "5m", ("2024-01", "2024-02"), manifest)
        bars = [r for p in paths for r in raw_ohlcv(p, 300_000) if start <= r[0] < end]
        assert [r[0] for r in bars] == list(range(start, end, 300_000))
        auxiliary = aggregate(bars, 24)
        path = work / f"1985-{market}.json"
        path.write_bytes(json.dumps({"market": market, "start": start, "end": end, "chart": bars, "higher": auxiliary}, separators=(",", ":")).encode())
        feeds.append({"market": market, "file": path.name, "sha256": sha256(path), "chart_bars": len(bars), "higher_bars": len(auxiliary)})
    write(work / "1985-inputs.json", {"official_archives": manifest, "feeds": feeds})


if __name__ == "__main__":
    stage(*map(Path, sys.argv[1:]))
