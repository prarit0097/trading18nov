"""Bind exact archived martingale sources and #5150 native hourly requests."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
from pathlib import Path
import re
from urllib.parse import unquote
from zipfile import ZipFile

from fmz_native_round20_880_capture import sha
from stage_r29_4685_native import archive, q, scaled, to_market

ARCHIVE='7853bb2bf262c4567ac238d3552d97f0e50cb801'
BOUND='b015d1141748c74b28500f4b93539b3d309b278a97c56bf98993c6b66f404593'
HOUR=3_600_000
PIN={5147:('344060','15534f58dd4690dc6a0f12a22e889b390cd48dd7a27adb372185a9504aa86b95'),
     5149:('353603','ec69cffd500cbc9ccf656b6d0550c01e384d41923c4f5601f710e5c9517690af'),
     5150:('356471','d3e5c04f41e19fb076793bcf2f653f5bb391074f45006c0b2b527db7b51347fa')}


def fetch_sources(backlog,archive_path):
    catalog=json.loads(backlog.read_bytes())['disposition']
    with ZipFile(archive_path) as pin:
        result={}
        for r in catalog:
            i=r['id']
            if i not in PIN: continue
            author,expected=PIN[i]
            url=r['source']; assert url.split('/blob/')[1].startswith(ARCHIVE+'/')
            doc=pin.read('strategies-'+unquote(url.split('/blob/')[1])); assert sha(doc)==expected
            [script]=re.findall(r'(?ms)^`{3}[ \t]*javascript[ \t]*\n(.*?)^`{3}',doc.decode())
            assert 'period: 1d' in script and 'basePeriod: 1h' in script
            defaults={}
            if i==5150:
                for k,value in re.findall(r'(?m)^\|([a-zA-Z]+)\|([^|]+)\|',doc.decode()):
                    if k in ('Argument',):
                        continue
                    defaults[k]=json.loads(value) if value!='swap' else value
                assert len(defaults)==12 and defaults['ShortAmount']==100 and defaults['MarginLevel']==50
                assert defaults['short'] is True and defaults['long'] is False
            result[i]={'script':script,'script_sha256':sha(script.encode()),'archive_sha256':expected,'url':url,
                       'original_publisher':f'https://www.fmz.com/strategy/{author}','defaults':defaults}
    assert result.keys()==PIN.keys()
    return result


def bind(day,scope,kind):
    branch={'swap':('klines','1h'),'index':('indexPriceKlines','1h'),'funding':('fundingRate','')}
    archive_label,size=branch[kind]
    begin,end=scope['begin_ms'],scope['end_ms']
    step=HOUR
    native,n_proof=q('BTC',kind,'feed',step,begin-48*HOUR,end+48*HOUR)
    keys=sorted({day[:7],(day[:4]+'-'+(str(int(day[5:7])-1).zfill(2)))})
    downloads=[archive('BTC',archive_label,size,m) for m in keys]
    all_rows=[r for part,_ in downloads for r in part]
    if kind=='funding':
        exact={int(r[0]):scaled(r[2],100_000_000) for r in all_rows}
        check=[r for r in native['data'] if begin<=r[0]<end]
        assert len(check)==1
        maximum=max(abs(exact[r[0]]-r[1]) for r in check)
        assert maximum<=1
    else:
        lookup={r[0]:r for r in to_market(all_rows,step,kind=='swap')}
        check=[r for r in native['data'] if begin<=r[0]<=end]
        match=[]
        for r in check:
            original=lookup[r[0]]
            factor=0.1
            match.append([abs(r[i]-round(original[i]*factor)) for i in range(1,5)])
        maximum=max(n for row in match for n in row)
        assert len(match)==5 and maximum<=1,(day,kind,match)
    return {**native,'verification':{'matching_window_rows':len(check),'maximum_scaled_difference':maximum,'native':n_proof,
               'binance_monthly_archives':[meta for _,meta in downloads]}}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ('book25','archive','catalog','output'):
        ap.add_argument('--'+k,type=Path,required=True)
    a=ap.parse_args()
    history=a.book25.read_bytes(); assert sha(history)==BOUND
    specs=json.loads(gzip.decompress(history))['scope']
    sources=fetch_sources(a.catalog,a.archive)
    with ThreadPoolExecutor(max_workers=6) as p:
        files={(d,k):p.submit(bind,d,spec,k) for d,spec in specs.items() for k in ('swap','index','funding')}
        native={day:{'begin':spec['begin_ms'],'end':spec['end_ms'],
                     'data':{k:files[day,k].result() for k in ('swap','index','funding')}} for day,spec in specs.items()}
    job={'sources':sources,'recorded_book_sha256':BOUND,'native_hourly':native,'starting_USDT':10000}
    raw=gzip.compress(json.dumps(job,ensure_ascii=False,separators=(',',':')).encode(),mtime=0)
    a.output.write_bytes(raw)
    print(len(raw),sha(raw),flush=True)


if __name__=='__main__':
    main()
