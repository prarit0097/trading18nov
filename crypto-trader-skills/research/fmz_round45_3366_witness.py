"""Verify October 1m touch witnesses against the saved 1h candles."""
import sys
from pathlib import Path
from research.fmz_round7_magnifier import aggregate,date_ms,verified_archives,read,write
from research.fmz_round34_3038 import min_candles

WINDOWS=(("2023-10-02","2023-10-04"),("2023-10-24","2023-10-25"))

def main(public,work):
    feed=read(work/"3366-feed.json")
    market_slices={}
    receipts=[]
    for market, case in feed["markets"].items():
        minute,=verified_archives(public,market,"1m",("2023-10",),receipts)
        market_slices[market]=[]
        for first,last in WINDOWS:
            start,end=map(date_ms,(first,last))
            minute_rows=min_candles(minute,start,end)
            hour_rows=[row for row in case["hour"] if start<=row[0]<end]
            assert [list(row[:5]) for row in aggregate(minute_rows,60)]==[row[:5] for row in hour_rows]
            market_slices[market].extend(minute_rows)
    write(work/"3366-minute-witnesses.json",{"market":market_slices,"receipts":receipts})

if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
