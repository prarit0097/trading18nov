"""Stage the saved 5-day study from checksum-verified USD-M base candles."""
import sys
from pathlib import Path
from research.fmz_round7_magnifier import aggregate,date_ms,verified_archives,write
from research.fmz_round26_977 import prices

def main(public,minutes,sandbox):
    start,end=map(date_ms,("2023-11-18","2023-11-23"))
    cases={}
    receipts=[]
    for market in ("BTCUSDT","ETHUSDT"):
        path,=verified_archives(public,market,"15m",("2023-11",),receipts)
        base=prices([path],start,end,900_000)
        assert [r[0] for r in base] == list(range(start,end,900_000))
        minute,=verified_archives(minutes,market,"1m",("2023-11",),receipts)
        tape=prices([minute],start,end,60_000)
        assert [x[:5] for x in aggregate(tape,15)]==[x[:5] for x in base]
        cases[market]={"chart":aggregate(base,4),"base":base,"3":aggregate(tape,3),"5":aggregate(tape,5)}
    write(sandbox/"1807-feed.json",{"markets":cases,"receipts":receipts})

if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
