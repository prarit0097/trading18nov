"""Pin #5153 and stream its two recorded Binance BTCUSDT aggressive-trade windows."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote
from zipfile import ZipFile

from fmz_native_round20_880_capture import request,sha
from stage_r35_197_recorded_depth import fixed

BOOK='b015d1141748c74b28500f4b93539b3d309b278a97c56bf98993c6b66f404593'
LIMIT=70_000_000


class Capture:
    def __init__(self,stream):
        self.stream=stream
        self.digest=hashlib.sha256()
        self.length=0

    def read(self,n):
        chunk=self.stream.read(n)
        self.length+=len(chunk)
        assert self.length<=LIMIT
        self.digest.update(chunk)
        return chunk


def trade_tape(day,spec):
    first=spec['begin_ms']*1000;last=spec['end_ms']*1000
    url=f"https://datasets.tardis.dev/v1/binance-futures/trades/{day.replace('-','/')}/BTCUSDT.csv.gz"
    tape=[]
    prev=total=adjusted=0
    with request(url) as response:
        size=int(response.headers['Content-Length'])
        assert response.status==200 and 10_000<size<=LIMIT
        byte_stream=Capture(response)
        with gzip.GzipFile(fileobj=byte_stream) as gz:
            assert gz.readline().strip().split(b',')==[b'exchange',b'symbol',b'timestamp',b'local_timestamp',b'id',b'side',b'price',b'amount']
            for line in gz:
                e,s,venue,seen,num,side,px,n=line.strip().split(b',')
                assert (e,s)==(b'binance-futures',b'BTCUSDT') and side in (b'buy',b'sell')
                local=int(seen);stamp=int(venue)
                assert local>=prev
                prev=local;total+=1
                if first<max(local,stamp)<=last:
                    adjusted+=int(stamp>local)
                    tape.append([max(local,stamp),int(num),fixed(px,2),fixed(n,3),int(side==b'buy'),stamp,local])
        assert byte_stream.length==size
    assert len(tape)>10_000 and len({r[1] for r in tape})==len(tape)
    tape.sort(key=lambda row:(row[0],row[1]))
    assert all(p[2]>0 and p[3]>0 and p[0]>=p[5] and p[0]>=p[6] for p in tape)
    return {'tape':tape,'reference':{'url':url,'sha256':byte_stream.digest.hexdigest(),'raw_rows':total,
            'raw_bytes':size,'scoped_rows':len(tape),'exchange_clock_later_than_local_rows':adjusted,
            'first_eligible_us':tape[0][0],'last_eligible_us':tape[-1][0]}}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('catalog','archive','book','output'):
        p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    [row]=[r for r in json.loads(a.catalog.read_bytes())['disposition'] if r['id']==5153]
    with ZipFile(a.archive) as arc:
        md=arc.read('strategies-'+unquote(row['source'].split('/blob/')[1]))
    archive_sha=sha(md)
    assert archive_sha==row['pinned_document_sha256']
    [script]=re.findall(r'(?ms)^`{3}[ \t]*python[ \t]*\n(.*?)^`{3}',md.decode())
    params=dict(json.loads(re.search(r'(?m)^args: (.+)$',script)[1]))
    assert params=={'H':30,'n1':.001,'grid':300,'xia':50000}
    assert '|M|20|' in md.decode() and '|shang|60000|' in md.decode()
    params.update(M=20,shang=60000)
    archived=json.loads(re.search(r'(?m)^exchanges: (.+)$',script)[1])
    assert archived==[{'eid':'Futures_Binance','currency':'BTC_USDT','balance':2500}]
    assert 'period: 1m' in script and 'basePeriod: 1m' in script
    raw=a.book.read_bytes();assert sha(raw)==BOOK
    book=json.loads(gzip.decompress(raw));settings=book['scope']
    with ThreadPoolExecutor(max_workers=2) as p:
        entries={d:p.submit(trade_tape,d,s) for d,s in settings.items()}
        tape={d:r.result() for d,r in entries.items()}
    job={'source_py':script,'archive_sha256':archive_sha,'source_sha256':sha(script.encode()),'source_url':row['source'],
         'settings':params,'starting_cash_USDT':2500,'books_sha256':BOOK,'tapes':tape,'fees_pct':[0.02,0.04]}
    packed=gzip.compress(json.dumps(job,ensure_ascii=False,separators=(',',':')).encode(),compresslevel=6,mtime=0)
    a.output.write_bytes(packed)
    print({d:t['reference'] for d,t in tape.items()},len(packed),sha(packed),flush=True)


if __name__=='__main__':
    main()
