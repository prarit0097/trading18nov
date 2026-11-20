"""Stage the archived September 2023 30-minute BTC and ETH validation scope."""

import sys
from pathlib import Path

from research.fmz_round7_magnifier import aggregate,date_ms,raw_ohlcv,verified_archives,write

def stage(public,work):
    start,end=map(date_ms,("2023-09-04","2023-09-11"))
    cases,receipts=[],[]
    for market in ("BTCUSDT","ETHUSDT"):
        path,=verified_archives(public,market,"15m",("2023-09",),receipts)
        base=[r for r in raw_ohlcv(path,900_000) if start<=r[0]<end]
        assert [r[0] for r in base]==list(range(start,end,900_000))
        cases.append({"market":market,"chart":aggregate(base,2)})
    write(work/"355-inputs.json",{"cases":cases,"market_receipts":receipts})

if __name__=="__main__":
    stage(*map(Path,sys.argv[1:]))
