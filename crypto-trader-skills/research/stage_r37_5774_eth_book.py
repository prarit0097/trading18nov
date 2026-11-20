"""Stage past Binance ETH recorded depth for the archived named hedge variant."""
import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
from urllib.parse import unquote
from zipfile import ZipFile

from fmz_native_round20_880_capture import request,sha
from stage_r29_4685_native import archive,get,scaled
from stage_r34_btc_random_book import sample_start
from stage_r35_197_recorded_depth import fixed

DAYS=('2021-05-01','2021-06-01')
SYMBOL='ETHUSDT'
STEP=200
MAX_BYTES=300_000_000
ARCHIVE='5a434cdbc6dd19e28baa3eb869c40e1e54ed2cd9be370dc2ac4a3053e371cd69'


class Reader:
    def __init__(self,response):
        self.resp=response
        self.n=0
        self.hash=hashlib.sha256()

    def read(self,size):
        s=self.resp.read(size);self.n+=len(s);self.hash.update(s)
        assert self.n<=MAX_BYTES
        return s


def decode_book(row):
    ask=[];bid=[]
    assert len(row)%4==0
    for i in range(0,len(row),4):
        for pos,levels in ((i,ask),(i+2,bid)):
            p,q=row[pos:pos+2]
            assert bool(p)==bool(q)
            if p:
                levels.append([fixed(p.encode(),2),fixed(q.encode(),3)])
    assert ask and bid and bid[0][0]<ask[0][0]
    assert all(a[0]<b[0] for a,b in zip(ask,ask[1:])) and all(a[0]>b[0] for a,b in zip(bid,bid[1:]))
    assert all(min(x)>0 for x in ask+bid)
    return ask,bid


def sample_parse(mode,tail):
    if mode=='quotes':
        a,pa,pb,b=tail
        return [fixed(p.encode(),scale) for p,scale in ((pb,2),(pa,2),(b,3),(a,3))]
    if mode=='derivative_ticker':
        due,rate,_,_,last,index,mark=tail
        if not all((last,index,mark,due,rate)):
            return None
        return [scaled(last,100),float(mark),float(index),int(due),rate]
    return list(decode_book(tail))


def sampling(day,kind):
    from_ms,to_ms=sample_start(day)
    ticks=range(from_ms*1000,(to_ms+1)*1000,STEP*1000)
    data=[];previous=None;parsed=None;i=last=0
    url=f"https://datasets.tardis.dev/v1/binance-futures/{kind}/{day.replace('-','/')}/{SYMBOL}.csv.gz"
    with request(url) as r:
        byte_count=int(r.headers['Content-Length'])
        assert r.status==200 and 10_000<byte_count<=MAX_BYTES
        stream=Reader(r); first=rows=0
        with gzip.GzipFile(fileobj=stream) as f:
            header=f.readline().decode().strip().split(',')
            assert header[:4]==['exchange','symbol','timestamp','local_timestamp']
            assert len(header)=={'quotes':8,'derivative_ticker':11,'book_snapshot_5':24,'book_snapshot_25':104}[kind]
            for line in f:
                ex,sym,n,clock,rest=line.rstrip().split(b',',4)
                assert ex==b'binance-futures' and sym==SYMBOL.encode()
                arrive=int(clock)
                assert arrive>=last
                if not first:first=arrive
                last=arrive;rows+=1
                if i==len(ticks):continue
                while i<len(ticks) and arrive>ticks[i]:
                    assert previous is not None
                    recv,venue,body=previous
                    assert venue<=recv<=ticks[i]
                    if parsed is None:parsed=sample_parse(kind,body.decode().split(','))
                    assert parsed is not None
                    data.append([recv,venue,*parsed]);i+=1
                if i<len(ticks):
                    if kind=='derivative_ticker' and not all(rest.split(b',')[4:]):continue
                    previous=(arrive,int(n),rest);parsed=None
        assert stream.n==byte_count
    assert len(ticks)==len(data)
    return data,{'url':url,'records':rows,'bytes':byte_count,'sha256':stream.hash.hexdigest(),
                 'start_local_us':first,'end_local_us':last,'replay_grid_rows':len(data)}


def funding(day,marks):
    begin,_=sample_start(day)
    boundary=begin+2*3_600_000
    official,rate_ref=archive('ETH','fundingRate','',day[:7])
    [(epoch,interval,r)]=[row for row in official if abs(int(row[0])-boundary)<=100]
    assert interval=='8'
    tick_idx=(boundary-begin)//STEP
    before=next(m for m in reversed(marks[:tick_idx+1]) if m[5]==boundary*1000)
    after=next(m for m in marks[tick_idx:] if m[5]>boundary*1000)
    observed_indicative_rate=float(before[6])
    label=f'{SYMBOL}-1m-{day}.zip'
    url=f'https://data.binance.vision/data/futures/um/daily/markPriceKlines/{SYMBOL}/1m/{label}'
    digest,fn=get(url+'.CHECKSUM',200).decode().split(); raw=get(url,400_000)
    assert fn==label and sha(raw)==digest
    with ZipFile(io.BytesIO(raw)) as z:
        [member]=z.namelist()
        with z.open(member) as f:
            bars=[row for row in csv.reader(io.TextIOWrapper(f,encoding='utf-8')) if row[0].isdigit() and boundary-60_000<=int(row[0])<=boundary]
    assert len(bars)==2
    low=min(float(row[3]) for row in bars);high=max(float(row[2]) for row in bars)
    assert all(low<=m[3]<=high for m in (before,after))
    return {'boundary_ms':boundary,'exchange_settlement_ms':int(epoch),'rate':float(r),'prior_mark':before,'next_mark':after,
            'official_two_minute_mark_price_bounds_USDT':[low,high],
            'pre_settlement_capture_indicative_rate':observed_indicative_rate,'official_funding_source':rate_ref,'official_mark_minute_source':{'url':url,'sha256':digest}}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('archive','catalog','output'):
        p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--levels',type=int,choices=(5,25),default=5)
    a=p.parse_args()
    [r]=[x for x in json.loads(a.catalog.read_bytes())['disposition'] if x['id']==5774]
    with ZipFile(a.archive) as z:
        raw=z.read('strategies-'+unquote(r['source'].split('/blob/')[1]))
    assert sha(raw)==ARCHIVE
    [source]=re.findall(r'(?ms)^`{3}[ \t]*javascript[ \t]*\n(.*?)^`{3}',raw.decode())
    assert all(x in source for x in ('"currency":"xxx_USDT"',"['ETH_Usdt'",'basePeriod: 1h','position[0].Type','MarginLevel = 20'))
    kinds=('quotes','derivative_ticker',f'book_snapshot_{a.levels}')
    result={}
    with ThreadPoolExecutor(max_workers=6) as pool:
        tasks={(d,k):pool.submit(sampling,d,k) for d in DAYS for k in kinds}
        for d in DAYS:
            q,qr=tasks[d,kinds[0]].result()
            m,mr=tasks[d,kinds[1]].result()
            depth,dr=tasks[d,kinds[2]].result()
            begin,end=sample_start(d)
            assert len(q)==len(m)==len(depth)==72_001
            assert all(x[2:6]==[b[3][0][0],b[2][0][0],b[3][0][1],b[2][0][1]] for x,b in zip(q,depth,strict=True))
            result[d]={'begin_ms':begin,'end_ms':end,'quotes':q,'marks':m,'depth':depth,'funding':funding(d,m),
                       'proof':{'quote':qr,'mark':mr,'depth':dr,'exact_BBO_matches':len(q)}}
            print(d,'rates',result[d]['funding']['rate'],'capture rows',qr['records'],mr['records'],dr['records'],flush=True)
    job={'source':source,'archive_sha256':ARCHIVE,'source_sha256':sha(source.encode()),'source_url':r['source'],'level_count':a.levels,
         'venue':'Binance USD-M ETHUSDT perpetual','source_variant':'First symbol explicitly named in the archive, ETH_Usdt',
         'starting_cash_USDT':10000,'taker_rate':0.0004,'leverage':20,'sample_step_ms':STEP,'seeds':[1,42,20201120],
         'scope':result}
    blob=gzip.compress(json.dumps(job,ensure_ascii=False,separators=(',',':')).encode(),compresslevel=6,mtime=0)
    a.output.write_bytes(blob)
    print(len(blob),sha(blob),flush=True)


if __name__=='__main__':main()
