"""Stage the checksum-bound BTC native two-sided grid input for #1942."""

import argparse
import csv
import gzip
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from fmz_native_round20_880_capture import sha
from stage_r29_4685_native import get,archive,q,scaled

PIN='7853bb2bf262c4567ac238d3552d97f0e50cb801'
SOURCE='https://github.com/fmzquant/strategies/blob/'+PIN+'/%E5%8F%8C%E5%90%91%E5%90%88%E7%BA%A6%E7%BD%91%E6%A0%BC%E4%BA%A4%E6%98%93v102.md'
SHASH='a6ac7fa9f808621e318371f9dfe3b145ccb99f49c2c9c163d94835ce67086da6'
DHASH='4994eed6d4708cda932bc12921c8c7d74d1ca3ae9248e65d99f3f3ba8c056372'
DAYS=('2021-01-01','2021-04-01','2021-06-01')
M=60_000
DAY=1440*M


def minute(kind,date):
    name=f'BTCUSDT-1m-{date}.zip'
    category='klines' if kind=='swap' else 'indexPriceKlines'
    url=f'https://data.binance.vision/data/futures/um/daily/{category}/BTCUSDT/1m/{name}'
    expected,filename=get(url+'.CHECKSUM',200).decode().split()
    raw=get(url,250_000)
    assert sha(raw)==expected and filename==name
    with ZipFile(io.BytesIO(raw)) as z:
        [f]=z.namelist()
        with z.open(f) as fh:
            rows=[x for x in csv.reader(io.TextIOWrapper(fh,encoding='utf-8')) if x[0].isdigit()]
    assert len(rows)==1440 and all(int(r[6])-int(r[0])==M-1 for r in rows)
    data=[[int(a[0]),*[scaled(x,10) for x in a[1:5]],scaled(a[5],1000) if kind=='swap' else 0] for a in rows]
    return data,{'url':url,'sha256':expected,'rows':len(data),'checksum_url':url+'.CHECKSUM'}


def stage_day(day,pool):
    base=datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    now=int(base.timestamp()*1000)
    days=[(base+timedelta(days=d)).date().isoformat() for d in (-1,0,1)]
    binding={}
    captures={kind:[pool.submit(minute,kind,d) for d in days] for kind in ('swap','index')}
    refs={kind:pool.submit(q,'BTC',kind,'feed',M,now,now+DAY) for kind in ('swap','index','funding')}
    funding={m:pool.submit(archive,'BTC','fundingRate','',m) for m in sorted({d[:7] for d in days})}
    for k in ('swap','index','funding'):
        market,proof=refs[k].result()
        if k in ('swap','index'):
            parts=[f.result() for f in captures[k]]
            rows=[r for items,_ in parts for r in items]
            assert [r[0] for r in rows]==list(range(now-DAY,now+DAY*2,M))
        else:
            parts=[f.result() for f in funding.values()]
            rows=[[int(r[0]),*([scaled(r[2],10**8)]*4),0] for chunk,_ in parts for r in chunk if now-DAY<=int(r[0])<=now+2*DAY]
            assert any(now<=r[0]<now+DAY for r in rows)
        checked={r[0]:r for r in rows}
        candidates=[r for r in market['data'] if r[0] in checked and r[0]<now+DAY]
        assert all(checked[r[0]]==r for r in candidates)
        assert len(candidates)==(3 if k=='funding' else 1440),(day,k,len(candidates))
        binding[k]={'data':rows,'detail':market['detail'],'schema':market['schema'],
                    'refs':{'public_fmz':proof,'exact_overlap':len(candidates),'venue':[s for _,s in parts]}}
    print(day,'bound',[(k,v['refs']['exact_overlap']) for k,v in binding.items()],flush=True)
    return {'begin':now,'end':now+DAY,'market':binding}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    with ZipFile(a.archive) as z:
        raw=z.read('strategies-'+unquote(SOURCE.split('/blob/')[1]))
    [script]=re.findall(r'(?ms)^\x60{3}[ \t]*javascript[ \t]*\n(.*?)^\x60{3}',raw.decode())
    assert sha(raw)==DHASH and sha(script.encode())==SHASH
    assert '"balance":2000' in script and 'period: 1m' in script and 'basePeriod: 1m' in script
    with ThreadPoolExecutor(max_workers=12) as pool:
        scopes={d:stage_day(d,pool) for d in DAYS}
    job={'source':script,'document_sha256':DHASH,'source_sha256':SHASH,'url':SOURCE,'scope':scopes,
         'fees_pct':[0.02,0.04],'wallet_USDT':2000,'mode':'native simulated bid/ask and complete limit fill'}
    data=gzip.compress((json.dumps(job,ensure_ascii=False,separators=(',',':'))+'\n').encode(),mtime=0)
    a.output.write_bytes(data)
    print(len(data),sha(data),flush=True)


if __name__=='__main__':
    main()
