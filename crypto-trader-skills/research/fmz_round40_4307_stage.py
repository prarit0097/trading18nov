"""Build exact Jan 2025 chart and lower candles with provenance."""
import sys
from pathlib import Path
from research.fmz_round7_magnifier import aggregate,date_ms,raw_ohlcv,verified_archives,write
from research.fmz_round34_3038 import min_candles

def main(daily, minutes, out):
    start,end=map(date_ms,("2025-01-01","2025-01-25"))
    receipts=[]
    data={}
    for market in ("BTCUSDT","ETHUSDT"):
        day,=verified_archives(daily,market,"1d",("2025-01",),receipts)
        minute,=verified_archives(minutes,market,"1m",("2025-01",),receipts)
        chart=[r for r in raw_ohlcv(day,86_400_000) if start<=r[0]<end]
        candles=min_candles(minute,start,end)
        assert [c[0] for c in candles]==list(range(start,end,60_000))
        assert [r[:5] for r in chart]==[r[:5] for r in aggregate(candles,1440)]
        data[market]={"D":chart,"1":candles,"5":aggregate(candles,5),"15":aggregate(candles,15)}
    write(out/"4307-feed.json",{"market_data":data,"receipts":receipts})

if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
