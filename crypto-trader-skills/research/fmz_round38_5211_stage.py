
"""Stage exact historical last-5m samples for all #5211 daily decisions."""

import sys
from pathlib import Path
from research.fmz_round7_magnifier import aggregate,date_ms,raw_ohlcv,verified_archives,write
from research.fmz_round32_trailing_offset import daily_rates
from research.fmz_round26_977 import prices

def main(hour,ltf,fx,work):
    start,end=map(date_ms,("2022-12-15","2023-12-21"))
    rate, fx_receipts=daily_rates(fx)
    months=("2022-12",*(f"2023-{i:02d}" for i in range(1,13)))
    firsts=list(range(start,end,86400_000))
    account={"schemaVersion":1,"pairs":[{"from":"USDT","to":"USD","rates":[
        {"effectiveTime":stamp,"rate":float(rate[stamp])} for stamp in firsts]}]}
    receipts,cases=[],[]
    windows=[tuple(map(date_ms,pair)) for pair in (("2023-06-17","2023-06-23"),("2023-09-26","2023-10-03"),("2023-10-20","2023-10-25"))]
    for m in ("BTCUSDT","ETHUSDT"):
        hour_paths=verified_archives(hour,m,"1h",months,receipts)
        five_paths=verified_archives(ltf,m,"5m",months,receipts)
        h=[bar for path in hour_paths for bar in raw_ohlcv(path,3600_000) if start<=bar[0]<end]
        f=prices(five_paths,start,end,300_000)
        assert all(0 < lo <= min(o,c) <= max(o,c) <= hi and v>=0 and (v>0 or o==hi==lo==c)
                   for _,o,hi,lo,c,v in f)
        assert [r[0] for r in h]==list(range(start,end,3600_000))
        assert [r[0] for r in f]==list(range(start,end,300_000))
        chart=aggregate(h,24)
        assert [r[:5] for r in chart]==[r[:5] for r in aggregate(f,288)]
        last=f[287::288]
        head=f[:7*288]
        witness=[bar for bar in f if any(a<=bar[0]<b for a,b in windows)]
        cases.append({"market":m,"chart":chart,"last":last,"sample":head,"witness":witness,"full_lower_bars":len(f)})
    write(work/"5211-inputs.json",{"cases":cases,"archive_receipts":receipts,"fx":account,"fx_receipts":fx_receipts})
if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
