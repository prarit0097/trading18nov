"""Stage the nearest public first-of-month Binance spot tape for legacy FMZ #5094."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import re
from urllib.parse import unquote
from zipfile import ZipFile

from fmz_native_round20_880_capture import request, sha
from stage_r35_197_recorded_depth import fixed
from stage_r42_3717_spot import StreamDigest

DATE='2019-09-01'
BEGIN=int(datetime.fromisoformat(DATE).replace(tzinfo=timezone.utc).timestamp())
END=BEGIN+22*3600


def datafeed(channel):
    path=DATE.replace('-','/')
    url=f'https://datasets.tardis.dev/v1/binance/{channel}/{path}/BTCUSDT.csv.gz'
    quotes={}
    prints=[]
    total=0
    previous=0
    with request(url) as response:
        s=StreamDigest(response)
        with gzip.GzipFile(fileobj=s) as fd:
            cols=fd.readline().strip().split(b',')
            assert cols[:4]==[b'exchange',b'symbol',b'timestamp',b'local_timestamp']
            assert len(cols)==(104 if channel=='book_snapshot_25' else 8)
            for row in fd:
                fields=row.rstrip().split(b',')
                assert fields[:2]==[b'binance',b'BTCUSDT']
                venue,local=map(int,fields[2:4])
                assert local>=previous
                previous=local
                eligible=max(venue,local)
                total+=1
                if not BEGIN*1_000_000<=eligible<END*1_000_000:
                    continue
                if channel=='trades':
                    n,signed,px,qty=fields[4:]
                    assert signed in (b'buy',b'sell')
                    prints.append([eligible,venue,local,int(n),int(signed==b'buy'),fixed(px,2),fixed(qty,8)])
                else:
                    stamp=(eligible+999_999)//1_000_000
                    if stamp>=END:
                        continue
                    if stamp not in quotes or eligible>=quotes[stamp][0]:
                        quotes[stamp]=(eligible,venue,local,fields[4:])
        assert total>100_000 and s.size==int(response.headers['Content-Length'])
    if channel=='trades':
        assert len({q[3] for q in prints})==len(prints)
        results=sorted(prints,key=lambda r:(r[0],r[3]))
    else:
        results=[]
        for sec,(eligible,venue,local,raw) in sorted(quotes.items()):
            book=[fixed(v,2 if idx%2==0 else 8) if v else 0 for idx,v in enumerate(raw)]
            assert len(book)==100
            assert 0<book[2]<book[0]
            assert min(book[i] for i in range(12))>0
            results.append([sec,eligible,venue,local,book])
    return results,{'url':url,'sha256':s.sha.hexdigest(),'raw_bytes':s.size,'raw_rows':total,'scope_rows':len(results)}


def strategy(catalog,archive):
    [row]=[s for s in json.loads(catalog.read_bytes())['disposition'] if s['id']==5094]
    with ZipFile(archive) as z:
        raw=z.read('strategies-'+unquote(row['source'].split('/blob/')[1]))
    assert sha(raw)==row['pinned_document_sha256']
    text=raw.decode()
    [code]=re.findall(r'(?ms)^`{3}[ \t]*javascript[ \t]*\n(.*?)^`{3}',text)
    [backtest]=re.findall(r'(?s)^/\*backtest\n(.*?)\*/',code)
    assert all(v in backtest for v in ('start: 2019-09-05 00:00:00','end: 2019-09-05 22:00:00','period: 1h','mode: 1'))
    [options]=json.loads(re.search(r'(?m)^exchanges: (.+)$',backtest)[1])
    assert options=={'eid':'Binance','currency':'BTC_USDT','fee':[0,0]}
    params={'BurstThresholdPct':5e-05,'BurstThresholdVol':10,'MinStock':.1,'CalcNetInterval':60,'BalanceTimeout':10_000,'TickInterval':280}
    for key in params:
        default=re.search(r'^\|'+key+r'\|([^|]+)\|',text,re.M)[1]
        assert float(default)==params[key]
    return {'source':code,'source_sha256':sha(code.encode()),'archive_sha256':sha(raw),'source_url':row['source'],
            'args':params,'settings':options,'saved_date':'2019-09-05','recorded_alternate_date':DATE,
            'begin':BEGIN,'end':END}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('catalog','archive','output'):
        p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    spec=strategy(a.catalog,a.archive)
    with ThreadPoolExecutor(max_workers=2) as pool:
        d,t=pool.submit(datafeed,'book_snapshot_25'),pool.submit(datafeed,'trades')
        book,bp=d.result()
        tape,tp=t.result()
    spec.update(book=book,tape=tape,data={'book':bp,'prints':tp})
    data=gzip.compress(json.dumps(spec,separators=(',',':')).encode(),compresslevel=4,mtime=0)
    with a.output.open('xb') as f:f.write(data)
    print(sha(data),len(data),spec['data'],flush=True)


if __name__=='__main__':main()
