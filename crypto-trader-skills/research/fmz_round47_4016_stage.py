"""Aligned February 2024 futures chart and genuine requested children."""
import sys
from pathlib import Path
from research.fmz_round7_magnifier import aggregate, date_ms, verified_archives, write
from research.fmz_round26_977 import prices

def main(base,minute,work):
    start,end=map(date_ms,("2024-02-17","2024-02-18"))
    warm_start=date_ms("2024-02-12")
    receipts=[]
    markets={}
    for market in ("BTCUSDT","ETHUSDT"):
        quarter=verified_archives(base,market,"15m",("2024-02",),receipts)
        children=verified_archives(minute,market,"1m",("2024-02",),receipts)
        f=prices(quarter,start,end,900_000)
        s=prices(children,start,end,60_000)
        assert [r[:5] for r in f]==[r[:5] for r in aggregate(s,15)]
        f_warm=prices(quarter,warm_start,end,900_000)
        m_warm=prices(children,warm_start,end,60_000)
        assert [r[:5] for r in f_warm] == [r[:5] for r in aggregate(m_warm,15)]
        markets[market]={"chart":aggregate(f,4),"quarter":f,"minute":s,"warm_chart":aggregate(f_warm,4),"warm_minute":m_warm}
    write(work/"4016-feed.json",{"markets":markets,"receipts":receipts})

if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
