"""Prepare exactly the saved 2h chart from verified Binance 15m archives."""
import sys
from pathlib import Path
from research.fmz_round7_magnifier import aggregate, date_ms, verified_archives, write
from research.fmz_round26_977 import prices

def main(public, sandbox):
    start,end=map(date_ms,("2023-11-04","2023-12-04"))
    cases={}
    receipts=[]
    for market in ("BTCUSDT","ETHUSDT"):
        files=verified_archives(public,market,"15m",("2023-11","2023-12"),receipts)
        base=prices(files,start,end,900_000)
        assert [r[0] for r in base] == list(range(start,end,900_000))
        cases[market]={"chart":aggregate(base,8),"daily":aggregate(base,96),"base":base}
    write(sandbox/"3301-feed.json",{"markets":cases,"receipts":receipts})

if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
