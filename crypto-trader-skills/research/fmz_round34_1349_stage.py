import sys
from pathlib import Path
from research.fmz_round7_magnifier import aggregate,date_ms,raw_ohlcv,verified_archives,write
from research.fmz_round34_3038 import min_candles

def main(public_daily, public_minutes, work):
    a,b=map(date_ms,("2023-01-02","2023-10-30"))
    start,end=map(date_ms,("2023-10-24","2023-10-25"))
    scopes={}
    receipts=[]
    for market in ("BTCUSDT","ETHUSDT"):
        days=verified_archives(public_daily,market,"1d",tuple(f"2023-{i:02d}" for i in range(1,11)),receipts)
        rows=[r for path in days for r in raw_ohlcv(path,86400_000) if a<=r[0]<b]
        assert [r[0] for r in rows]==list(range(a,b,86400_000))
        minute,=verified_archives(public_minutes,market,"1m",("2023-10",),receipts)
        scopes[market]={"chart":aggregate(min_candles(minute,start,end),3),"week":aggregate(rows,7)}
    write(work/"1349-inputs.json",{**scopes,"receipts":receipts})

if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
