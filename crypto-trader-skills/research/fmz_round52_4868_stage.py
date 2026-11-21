"""Prepare checksum-pinned market, Cboe VIX and Coinbase USDT-USD inputs."""
import csv
from datetime import UTC, datetime
from pathlib import Path
import sys

from research.fmz_round7_magnifier import aggregate, date_ms, read, sha256, verified_archives, write
from research.fmz_round26_977 import prices
from research.fmz_round52_4868 import DAY, HOUR

FX_SHA='ed3d9b34c756d3b3d67c31cc9125eaf71d50b1ce572da5318276e555a84f55df'
VIX_SHA='0d9c033a1ee06d41832ef98ce17d84910c8c386d890daca5cb24bbf9cd4af8d5'
FX_URL=('https://api.exchange.coinbase.com/products/USDT-USD/candles?granularity=86400'
        '&start=2023-11-29T00%3A00%3A00Z&end=2024-01-02T00%3A00%3A00Z')
VIX_URL='https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv'


def main(hourly, quarter, vix, fx, output):
    start,end=map(date_ms,('2023-12-01','2024-01-01'))
    receipts=[]
    markets={}
    for market in ('BTCUSDT','ETHUSDT'):
        h=prices(verified_archives(hourly,market,'1h',('2023-12',),receipts),start,end,HOUR)
        q=prices(verified_archives(quarter,market,'15m',('2023-12',),receipts),start,end,HOUR//4)
        difference=[(a,z) for a,z in zip(h,aggregate(q,4),strict=True) if a[:5]!=z[:5]]
        assert not difference
        markets[market]={'chart':h,'children':q,'disagreements':difference}
    assert sha256(fx)==FX_SHA and sha256(vix)==VIX_SHA
    sessions={}
    with vix.open(encoding='ascii',newline='') as handle:
        for row in csv.DictReader(handle):
            d=datetime.strptime(row['DATE'],'%m/%d/%Y').replace(tzinfo=UTC)
            t=int(d.timestamp()*1000)
            if start-7*DAY<=t<end:
                assert d.weekday()<5 and t not in sessions and d.date().isoformat()!='2023-12-25'
                opening,high,low,close=(float(row[k]) for k in ('OPEN','HIGH','LOW','CLOSE'))
                assert low<=min(opening,close)<=max(opening,close)<=high
                sessions[t]=[t,opening,high,low,close,0]
    assert len(sessions)==25 and list(sessions)==sorted(sessions)
    rates={}
    for day,low,high,opening,close,volume in read(fx):
        assert 0<low<=min(opening,close)<=max(opening,close)<=high and volume>0
        rates[day*1000+DAY]=close
    assert all(t in rates for t in range(start,end,DAY))
    receipts.extend([{'name':'VIX_History.csv','sha256':VIX_SHA,'url':VIX_URL},
                     {'name':'USDT-USD daily Coinbase response','sha256':FX_SHA,'url':FX_URL}])
    write(output,{'markets':markets,'receipts':receipts,'rates':rates,'vix_sessions':list(sessions.values())})


if __name__=='__main__':
    main(*map(Path,sys.argv[1:]))
