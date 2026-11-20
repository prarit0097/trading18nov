"""Prepare source-aligned Binance daily candles and original 1h archive receipts."""
from pathlib import Path
import sys
from research.fmz_round7_magnifier import aggregate, date_ms, raw_ohlcv, verified_archives, write

def main(public, sandbox):
    start, end = map(date_ms, ("2022-11-14", "2023-11-20"))
    months = ("2022-11", "2022-12", *(f"2023-{m:02d}" for m in range(1,12)))
    markets = {}
    receipts = []
    for market in ("BTCUSDT", "ETHUSDT"):
        files=verified_archives(public,market,"1h",months,receipts)
        source = [r for f in files for r in raw_ohlcv(f,3_600_000) if start <= r[0] < end]
        assert [r[0] for r in source] == list(range(start,end,3_600_000))
        markets[market] = aggregate(source,24)
    write(sandbox/"5530-feed.json", {"markets":markets, "receipts":receipts})

if __name__ == "__main__":
    main(*map(Path,sys.argv[1:]))
