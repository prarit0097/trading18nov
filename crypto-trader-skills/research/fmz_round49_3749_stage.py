"""Prepare #3749's official minute tapes and independent quarter-hour checks."""
import sys
from pathlib import Path
from hashlib import sha256
from research.fmz_round7_magnifier import aggregate,date_ms,verified_archives,write
from research.fmz_round26_977 import prices

def main(minutes,quarter,work):
    start,end=map(date_ms,("2023-11-08","2023-11-15"))
    receipts=[]
    markets={}
    for market in ("BTCUSDT","ETHUSDT"):
        tape=prices(verified_archives(minutes,market,"1m",("2023-11",),receipts),start,end,60_000)
        parent=prices(verified_archives(quarter,market,"15m",("2023-11",),receipts),start,end,900_000)
        comparable=aggregate(tape,15)
        assert [r[0] for r in comparable]==[r[0] for r in parent]
        mismatches=[[list(a[:5]),list(b[:5])] for a,b in zip(parent,comparable,strict=True) if a[:5]!=b[:5]]
        markets[market]={"chart":tape,"observed_source_disagreements":mismatches}
    daily_path=work.parent/"BTCUSDT-1m-2023-11-10.zip"
    daily_hash="60fbc08c0a73afa5f04d8bc9b8b960cb782435147c1a1080a2b449714db1ea20"
    assert daily_hash==sha256(daily_path.read_bytes()).hexdigest()
    observed_day, observed_stop=map(date_ms,("2023-11-10","2023-11-11"))
    daily=prices([daily_path],observed_day,observed_stop,60_000)
    src=markets["BTCUSDT"]["chart"]
    assert len(daily)==1440
    other={row[0]:row for row in daily}
    markets["BTCUSDT"]["daily_comparison"]=[other.get(row[0],row) for row in src]
    write(work/"3749-feed.json",{"markets":markets,"receipts":receipts,"btc_daily_receipt":{"file":daily_path.name,"sha256":daily_hash}})

if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
