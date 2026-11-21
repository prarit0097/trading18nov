"""Pin the complete daily Binance interval and a real unused-request witness."""
from itertools import product
from pathlib import Path
import sys

from research.fmz_round7_magnifier import aggregate, date_ms, read, sha256, verified_archives, write
from research.fmz_round26_977 import prices

DAY=86_400_000
MINUTE=60_000
EARLY_SHA='432a90f646700f899add2beed5e2a63a74b9de1d52dc018318963d1a7649cafd'
SYMBOLS=('BTCUSDT','ETHUSDT')


def main(work, minute, caches):
    cut,begin,end=map(date_ms,('2019-12-23','2020-01-01','2024-10-12'))
    months=[f'{year}-{month:02d}' for year,month in product(range(2020,2025),range(1,13))
            if (year,month)<=(2024,10)]
    receipts=[]
    market={}
    lower={}
    early=work/'4142-binance-dec2019.json'
    assert sha256(early)==EARLY_SHA
    earlier=read(early)
    for symbol in SYMBOLS:
        files=[]
        for month in months:
            name=f'{symbol}-1d-{month}.zip'
            selected=next(folder for folder in caches if (folder/name).is_file())
            files.extend(verified_archives(selected,symbol,'1d',(month,),receipts))
        prefix=earlier[symbol]
        assert all(c[6]==c[0]+DAY-1 and len(c)==12 and c[8]>0 for c in prefix)
        market[symbol]=[(r[0],*map(float,r[1:6])) for r in prefix]+prices(files,begin,end,DAY)
        assert [r[0] for r in market[symbol]]==list(range(cut,end,DAY))
        receipts.append({'name':f'{symbol} native December 2019 response',
                         'url':f'https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1d&startTime={cut}&endTime={begin-1}&limit=9',
                         'merged_response_sha256':EARLY_SHA})
        raw=verified_archives(minute,symbol,'1m',('2023-10',),receipts)
        lower[symbol]=aggregate(prices(raw,date_ms('2023-10-01'),date_ms('2023-10-03'),MINUTE),5)
        assert len(lower[symbol])==576
    write(work/'4142-feed.json',{'markets':market,'receipts':receipts})
    write(work/'4142-observed-5m.json',lower)


if __name__=='__main__':
    paths=list(map(Path,sys.argv[1:]))
    main(paths[0],paths[1],paths[2:])
