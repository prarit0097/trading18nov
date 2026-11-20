"""Stream public top-25 #197 depth and crossbind its first five with the original stage."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path

from fmz_native_round20_880_capture import request, sha
from stage_r35_197_recorded_depth import fixed

PARENT='46b1e4572d7696e949cb4c87ce99cf4d59904ae6556cda2a473e70bc6bc0ddc8'
CAP=265_000_000
STEP=200


class Capture:
    def __init__(self, response):
        self.response=response
        self.bytes=0
        self.hash=hashlib.sha256()

    def read(self, size):
        data=self.response.read(size)
        self.bytes+=len(data)
        assert self.bytes<=CAP
        self.hash.update(data)
        return data


def compact(source):
    pairs=source.split(b',')
    assert len(pairs)==100
    out=[[],[]]
    prev=[0,10**10]
    for i in range(0,100,4):
        for side in (0,1):
            base=i+2*side
            p,q=pairs[base:base+2]
            assert bool(p)==bool(q)
            if not p:
                continue
            price,qty=fixed(p,2),fixed(q,3)
            assert qty>0 and (price>prev[side] if side==0 else price<prev[side])
            prev[side]=price
            out[side].extend([price,qty])
    assert all(len(side)>=10 for side in out) and out[1][0]<out[0][0]
    return [','.join(map(str,side)) for side in out]


def snapshots(day,spec):
    clocks=range(spec['begin_ms']*1000,spec['end_ms']*1000+1,STEP*1000)
    url=f"https://datasets.tardis.dev/v1/binance-futures/book_snapshot_25/{day.replace('-','/')}/BTCUSDT.csv.gz"
    previous=None
    previous_compact=None
    records=0
    samples=[]
    last=first=0
    j=0
    compressed_five_match=0
    age_max=0
    with request(url) as resp:
        size=int(resp.headers['Content-Length'])
        assert resp.status==200 and 1_000_000<size<=CAP
        stream=Capture(resp)
        with gzip.GzipFile(fileobj=stream) as gz:
            header=gz.readline().strip().split(b',')
            assert len(header)==104 and header[:4]==[b'exchange',b'symbol',b'timestamp',b'local_timestamp']
            for line in gz:
                exchange,instrument,event,received,fields=line.rstrip(b'\r\n').split(b',',4)
                assert (exchange,instrument)==(b'binance-futures',b'BTCUSDT')
                local=int(received)
                assert local>=last
                if not first: first=local
                last=local
                records+=1
                if j==len(clocks):
                    continue
                while j<len(clocks) and local>clocks[j]:
                    assert previous is not None
                    arrival,stamp,side=previous
                    if previous_compact is None:
                        previous_compact=compact(side)
                    previous_five=spec['depth'][j]
                    for saved,packed in zip(previous_five[2:],previous_compact,strict=True):
                        n=2*len(saved)
                        assert list(map(int,packed.split(',',n)[:n]))==[x for pair in saved for x in pair]
                    compressed_five_match+=1
                    assert stamp<=arrival<=clocks[j]
                    age_max=max(age_max,clocks[j]-arrival)
                    samples.append([arrival,stamp,*previous_compact])
                    j+=1
                if j<len(clocks):
                    previous=(local,int(event),fields)
                    previous_compact=None
        assert stream.bytes==size
    assert len(samples)==len(clocks)==compressed_five_match
    return samples,dict(url=url,sha256=stream.hash.hexdigest(),bytes=size,rows=records,first_local_us=first,last_local_us=last,
                         matched_top5_replay_grid_rows=compressed_five_match,max_book_age_us=age_max)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    raw=a.input.read_bytes(); assert sha(raw)==PARENT
    job=json.loads(gzip.decompress(raw))
    with ThreadPoolExecutor(max_workers=2) as pool:
        files={d:pool.submit(snapshots,d,s) for d,s in job['scope'].items()}
        for day,f in files.items():
            depth,proof=f.result()
            pack=job['scope'][day]
            pack['depth']=depth
            pack['top25_proof']=proof
            print(day,proof,flush=True)
    job['max_market_order_snapshot_age_us']=5_000_000
    job['full_depth_input_parent_sha256']=PARENT
    job['max_observed_levels']=25
    packed=gzip.compress(json.dumps(job,ensure_ascii=False,separators=(',',':')).encode(),compresslevel=6,mtime=0)
    a.output.write_bytes(packed)
    print(len(packed),sha(packed),flush=True)


if __name__=='__main__':
    main()
