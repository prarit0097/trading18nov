"""Aligned October–November 2023 futures chart and genuine requested children."""
import sys
from pathlib import Path
from research.fmz_round7_magnifier import aggregate, date_ms, verified_archives, write
from research.fmz_round26_977 import prices

def main(base,minute,work):
    start,end=map(date_ms,("2023-10-24","2023-11-23"))
    receipts=[]
    markets={}
    for market in ("BTCUSDT","ETHUSDT"):
        quarter=verified_archives(base,market,"15m",("2023-10","2023-11"),receipts)
        children=verified_archives(minute,market,"1m",("2023-10","2023-11"),receipts)
        f=prices(quarter,start,end,900_000)
        s=prices(children,start,end,60_000)
        rebuilt=aggregate(s,15)
        assert len(rebuilt)==len(f) and all(a[0]==b[0] for a,b in zip(f,rebuilt,strict=True))
        mismatches=[[a[:5],b[:5]] for a,b in zip(f,rebuilt,strict=True) if a[:5]!=b[:5]]
        print(market,len(mismatches),mismatches[:4])
        markets[market]={"chart":aggregate(f,4),"quarter":f,"minute":s,"price_discrepancies":mismatches}
    write(work/"3458-feed.json",{"markets":markets,"receipts":receipts})

if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
