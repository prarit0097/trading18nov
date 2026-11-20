"""Crosswalk every #5153 maker witness to Binance's official checksummed aggregate archive."""
import argparse
from bisect import bisect_left
from concurrent.futures import ThreadPoolExecutor
import csv
import io
import gzip
import json
from pathlib import Path
from zipfile import ZipFile

from stage_r29_4685_native import get
from fmz_native_round20_880_capture import sha
from stage_r35_197_recorded_depth import fixed


def check_date(day,targets):
    wanted=sorted(targets)
    label=f'BTCUSDT-aggTrades-{day}.zip'
    url=f'https://data.binance.vision/data/futures/um/daily/aggTrades/BTCUSDT/{label}'
    digest,name=get(url+'.CHECKSUM',200).decode().split()
    assert name==label
    raw=get(url,70_000_000);assert sha(raw)==digest
    found={};count=0
    with ZipFile(io.BytesIO(raw)) as z:
        [member]=z.namelist()
        with z.open(member) as f:
            for row in csv.reader(io.TextIOWrapper(f,encoding='utf-8')):
                if not row[0].isdigit():continue
                count+=1
                agg,px,qty,low,high,t,buyer_maker=row[:7]
                a,b=int(low),int(high)
                left=bisect_left(wanted,a)
                group=[]
                while left<len(wanted) and wanted[left]<=b:
                    key=wanted[left]; rec=targets[key]
                    assert key not in found and buyer_maker.lower() in ('true','false')
                    close=abs(int(t)-rec[5]//1000)
                    assert close<=100,(day,key,close)
                    trade_px,units=fixed(px.encode(),2),fixed(qty.encode(),3)
                    assert trade_px==rec[2] and int(buyer_maker.lower()=='false')==rec[4] and units>=rec[3]
                    found[key]={'raw_id':key,'raw_venue_us':rec[5],'aggressor_buy':rec[4],'raw_cents':rec[2],'raw_units':rec[3],
                                'aggregate_id':int(agg),'aggregate_ms':int(t),'aggregate_units':units,'aggregate_first_id':a,'aggregate_last_id':b}
                    group.append(rec[3]);left+=1
                if group:assert sum(group)<=fixed(qty.encode(),3)
    assert found.keys()==targets.keys()
    return {'url':url,'checksum_url':url+'.CHECKSUM','archive_sha256':digest,'aggregate_rows':count,
            'all_witnesses':[found[i] for i in wanted]}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('input','receipt','output'):
        p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    native=a.receipt.read_bytes();raw=a.input.read_bytes()
    event=json.loads(native);job=json.loads(gzip.decompress(raw))
    assert event['input_sha256']==sha(raw)
    needed={day:set() for day in job['tapes']}
    for trial in event['results']:
        for e in trial['events']:
            if e.get('liquidity')=='maker':needed[trial['day']].update(o[0] for o in e['proof'])
    assert all(needed.values())
    digest={day:{x[1]:x for x in spec['tape'] if x[1] in needed[day]} for day,spec in job['tapes'].items()}
    assert all(set(digest[d])==list_set for d,list_set in needed.items())
    with ThreadPoolExecutor(max_workers=2) as p:
        work={day:p.submit(check_date,day,ids) for day,ids in digest.items()}
        out={day:t.result() for day,t in work.items()}
    a.output.write_text(json.dumps({'input_sha256':sha(raw),'receipt_sha256':sha(native),'reports':out},indent=2)+'\n',encoding='utf-8',newline='\n')
    print([(d,len(s['all_witnesses'])) for d,s in out.items()],sha(a.output.read_bytes()),flush=True)


if __name__=='__main__': main()
