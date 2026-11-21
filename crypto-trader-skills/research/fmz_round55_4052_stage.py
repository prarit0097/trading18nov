"""Load source-tested 1h and 5m archives and the independently resolved BTC day."""
from pathlib import Path
import sys

from research.fmz_round7_magnifier import aggregate, date_ms, sha256, verified_archives, write
from research.fmz_round26_977 import prices

HOUR=3_600_000
MINUTE=60_000
CORRECTED='60fbc08c0a73afa5f04d8bc9b8b960cb782435147c1a1080a2b449714db1ea20'


def main(work, hourly, daily_minutes, child_directories):
    start,end=map(date_ms,('2022-11-14','2023-11-20'))
    correction_start,correction_end=map(date_ms,('2023-11-10','2023-11-11'))
    months=('2022-11','2022-12',*(f'2023-{i:02}' for i in range(1,12)))
    receipts,markets=[],{}
    for market in ('BTCUSDT','ETHUSDT'):
        child_paths=[]
        for month in months:
            name=f'{market}-5m-{month}.zip'
            source=next(directory for directory in child_directories if (directory/name).is_file())
            child_paths.extend(verified_archives(source,market,'5m',(month,),receipts))
        five=prices(child_paths,start,end,5*MINUTE)
        hour=prices(verified_archives(hourly,market,'1h',months,receipts),start,end,HOUR)
        differ=[(a,b) for a,b in zip(hour,aggregate(five,12),strict=True) if a[:5]!=b[:5]]
        assert len(differ)==(2 if market=='BTCUSDT' else 0)
        corrected=five
        if market=='BTCUSDT':
            assert sha256(daily_minutes)==CORRECTED
            day=prices([daily_minutes],correction_start,correction_end,MINUTE)
            other={v[0]:v for v in aggregate(day,5)}
            corrected=[other.get(v[0],v) for v in five]
            receipts.append({'name':daily_minutes.name,'sha256':CORRECTED,
                             'url':'https://data.binance.vision/data/futures/um/daily/klines/BTCUSDT/1m/'+daily_minutes.name})
        assert [r[:5] for r in hour]==[r[:5] for r in aggregate(corrected,12)]
        assert (len(corrected),len(hour))==(106848,8904)
        markets[market]={'hour':hour,'five':corrected,'chart':aggregate(hour,24),'differences':differ,
                         'changed_ohlc_5m':sum(a[:5]!=b[:5] for a,b in zip(five,corrected,strict=True))}
    write(work/'4052-feed-corrected.json',{'markets':markets,'receipts':receipts})


if __name__=='__main__':
    paths=list(map(Path,sys.argv[1:]))
    main(paths[0],paths[1],paths[2],paths[3:])
