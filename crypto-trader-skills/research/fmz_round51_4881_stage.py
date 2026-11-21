"""Verify the complete archived USD-M chart and its quarter-hour children."""
from pathlib import Path
import sys

from research.fmz_round7_magnifier import aggregate, date_ms, verified_archives, write
from research.fmz_round26_977 import prices


def main(hourly, quarter, output):
    start,end=map(date_ms,('2023-08-19','2023-09-18'))
    months=('2023-08','2023-09')
    receipts=[]
    markets={}
    for market in ('BTCUSDT','ETHUSDT'):
        h=prices(verified_archives(hourly,market,'1h',months,receipts),start,end,3_600_000)
        q=prices(verified_archives(quarter,market,'15m',months,receipts),start,end,900_000)
        differences=[(a,b) for a,b in zip(h,aggregate(q,4),strict=True) if a[:5]!=b[:5]]
        assert not differences
        markets[market]={'chart':h,'children':q,'disagreements':differences}
    write(output,{'markets':markets,'receipts':receipts})


if __name__=='__main__':
    main(*map(Path,sys.argv[1:]))
