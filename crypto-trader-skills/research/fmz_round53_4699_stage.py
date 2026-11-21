"""Prepare Cboe archived daily observations and exact Binance chart checks."""
from datetime import date, timedelta
from pathlib import Path
import re
import sys

from research.fmz_round7_magnifier import aggregate, date_ms, sha256, verified_archives, write
from research.fmz_round26_977 import prices
from research.fmz_round53_4699 import HOUR

BASE='https://www.cboe.com/markets/us/options/market-statistics/daily/?dt='


def main(hourly, quarter, cboe, output):
    begin,end=map(date_ms,('2023-09-30','2023-10-30'))
    months=('2023-09','2023-10')
    receipts,markets=[],{}
    for market in ('BTCUSDT','ETHUSDT'):
        h=prices(verified_archives(hourly,market,'1h',months,receipts),begin,end,HOUR)
        q=prices(verified_archives(quarter,market,'15m',months,receipts),begin,end,HOUR//4)
        disagreements=[(a,b) for a,b in zip(h,aggregate(q,4),strict=True) if a[:5]!=b[:5]]
        assert not disagreements
        markets[market]={'chart':h,'children':q,'disagreements':disagreements}
    values=[]
    start=date(2023,9,26)
    for offset in range((date(2023,10,28)-start).days):
        day=start+timedelta(days=offset)
        if day.weekday()>4:
            continue
        iso=day.isoformat()
        file=cboe/f'{iso}.html'
        data=file.read_text(encoding='utf-8')
        ratio=float(re.search(r'TOTAL PUT/CALL RATIO</td><td[^>]*>([.0-9]+)',data)[1])
        assert r'selectedDate\":\"'+iso in data
        values.append((date_ms(iso),ratio))
        receipts.append({'file':file.name,'sha256':sha256(file),'url':BASE+iso})
    assert len(values)==24
    write(output,{'markets':markets,'receipts':receipts,'pcc':values})


if __name__=='__main__':
    main(*map(Path,sys.argv[1:]))
