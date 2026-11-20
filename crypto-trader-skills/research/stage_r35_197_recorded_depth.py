"""Extend the pinned #197 BTC quote sample with causal top-five snapshots."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path

from fmz_native_round20_880_capture import request, sha

PARENT='c6c145c88f2bf50c1948ffc265e6967b0ecdfbe89327579fe0937694e65da1ff'
CAP=80_000_000


class Capture:
    def __init__(self,response):
        self.response=response
        self.bytes=0
        self.hash=hashlib.sha256()

    def read(self,size):
        data=self.response.read(size)
        self.bytes+=len(data)
        assert self.bytes<=CAP
        self.hash.update(data)
        return data


def fixed(field,precision):
    """Parse venue's exact positive decimal without binary price rounding."""
    whole,sep,fraction=field.partition(b'.')
    assert len(fraction)<=precision
    return int(whole)*10**precision+int(fraction.ljust(precision,b'0'))


def levels(row):
    ask=[]
    bid=[]
    for offset in range(4,24,4):
        for target, i in ((ask,offset),(bid,offset+2)):
            p,q=row[i:i+2]
            assert bool(p)==bool(q)
            if p:
                target.append([fixed(p,2),fixed(q,3)])
    assert min(len(ask),len(bid))>0
    assert all(a[0]<b[0] for a,b in zip(ask,ask[1:])) and all(a[0]>b[0] for a,b in zip(bid,bid[1:]))
    assert bid[0][0]<ask[0][0] and all(min(level)>0 for level in ask+bid)
    return ask,bid


def before(day, spec, step):
    start=spec['begin_ms']*1000
    end=spec['end_ms']*1000
    clocks=range(start,end+1,step*1000)
    idx=0
    samples=[]
    previous=None
    last_local=first_local=observations=0
    ref=f"https://datasets.tardis.dev/v1/binance-futures/book_snapshot_5/{day.replace('-','/')}/BTCUSDT.csv.gz"
    with request(ref) as resp:
        size=int(resp.headers['Content-Length'])
        assert 10_000<size<=CAP and resp.status==200
        stream=Capture(resp)
        with gzip.GzipFile(fileobj=stream) as gz:
            columns=gz.readline().strip().split(b',')
            assert columns[:4]==[b'exchange',b'symbol',b'timestamp',b'local_timestamp'] and len(columns)==24
            for raw in gz:
                row=raw.rstrip(b'\r\n').split(b',',4)
                exchange,symbol,stamp,received= row[:4]
                assert exchange==b'binance-futures' and symbol==b'BTCUSDT'
                local=int(received)
                assert local>=last_local
                if not first_local:
                    first_local=local
                last_local=local
                observations+=1
                if idx==len(clocks):
                    continue
                while idx<len(clocks) and local>clocks[idx]:
                    assert previous is not None
                    event,venue,prior=previous
                    ask,bid=levels(prior)
                    samples.append([event,venue,ask,bid])
                    idx+=1
                if idx<len(clocks):
                    ex=int(stamp)
                    assert ex<=local
                    previous=(local,ex,row[:4]+row[4].split(b','))
        assert size==stream.bytes
    assert len(samples)==len(clocks)
    diff_count=0
    worst_age=0
    per_sec_differences=[]
    for t, book, quote in zip(clocks,samples,spec['quotes'],strict=True):
        local,venue,asks,bids=book
        assert venue<=local<=t
        age=t-local
        worst_age=max(worst_age,age)
        if [bids[0][0],asks[0][0],bids[0][1],asks[0][1]] != quote[2:6]:
            diff_count+=1
            if len(per_sec_differences)<8:
                per_sec_differences.append([t, book[:2],bids[0],asks[0],quote[:6]])
    proof=dict(url=ref,bytes=size,sha256=stream.hash.hexdigest(),raw_rows=observations,first_local_us=first_local,
               last_local_us=last_local,replay_grid_rows=len(samples),BBO_match_rows=len(samples)-diff_count,
               BBO_difference_examples=per_sec_differences,worst_snapshot_age_us=worst_age)
    print(day,proof,flush=True)
    return samples,proof


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    raw=args.input.read_bytes(); assert sha(raw)==PARENT
    old=json.loads(gzip.decompress(raw)); specs=old['scope']
    assert list(specs)==['2021-05-01','2021-06-01']
    with ThreadPoolExecutor(max_workers=2) as pool:
        promises={day:pool.submit(before,day,s,old['sample_step_ms']) for day,s in specs.items()}
        added={day:task.result() for day,task in promises.items()}
    for day, (samples,proof) in added.items():
        specs[day]['depth']=samples
        specs[day]['depth_proof']=proof
    old['sources']={'197':old['sources']['197']}
    old['parent_input_sha256']=PARENT
    old['max_market_order_snapshot_age_us']=1_000_000
    packed=gzip.compress(json.dumps(old,ensure_ascii=False,separators=(',',':')).encode(),mtime=0)
    args.output.write_bytes(packed)
    print(len(packed),sha(packed),flush=True)


if __name__=='__main__':
    main()
