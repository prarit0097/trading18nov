"""Aligned December 2023 futures chart and genuine requested children."""
import sys
from pathlib import Path
from research.fmz_round7_magnifier import aggregate, date_ms, verified_archives, write
from research.fmz_round26_977 import prices

def main(base,minute,work):
    start,end=map(date_ms,("2023-12-01","2024-01-01"))
    receipts=[]
    markets={}
    for market in ("BTCUSDT","ETHUSDT"):
        quarter=verified_archives(base,market,"15m",("2023-12",),receipts)
        children=verified_archives(minute,market,"1m",("2023-12",),receipts)
        f=prices(quarter,start,end,900_000)
        s=prices(children,start,end,60_000)
        assert [r[:5] for r in f]==[r[:5] for r in aggregate(s,15)]
        markets[market]={"chart":aggregate(f,12),"quarter":f,"minute":s}
    write(work/"4026-feed.json",{"markets":markets,"receipts":receipts})

if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
