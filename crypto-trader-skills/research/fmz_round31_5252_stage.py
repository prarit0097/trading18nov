import sys
from pathlib import Path

from research.fmz_round7_magnifier import aggregate,date_ms,raw_ohlcv,read,verified_archives,write

work,days=map(Path,sys.argv[1:])
d0,d1=map(date_ms,("2023-12-04","2024-01-29"))
start,end=map(date_ms,("2024-01-01","2024-01-25"))
cases,receipts=[],[]
for ref in read(work/"1070-inputs.json")["feeds"]:
    market=ref["market"]
    paths=verified_archives(days,market,"1d",("2023-12","2024-01"),receipts)
    day=[row for path in paths for row in raw_ohlcv(path,86400000) if d0<=row[0]<d1]
    assert [r[0] for r in day]==list(range(d0,d1,86400000))
    week=aggregate(day,7)
    base=[r for r in read(work/ref["file"])["base"] if start<=r[0]<end]
    assert [r[0] for r in base]==list(range(start,end,900000))
    chart=aggregate(base,16)
    cases.append({"market":market,"chart":chart,"week":week})
write(work/"5252-inputs.json",{"cases":cases,"weekly_receipts":receipts})
