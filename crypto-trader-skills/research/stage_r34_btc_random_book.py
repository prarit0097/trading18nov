"""Bind two archived BTC futures stochastic rules to causal recorded quotes."""

import argparse
import csv
import gzip
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from fmz_native_round20_880_capture import HashReader, request, sha
from stage_r29_4685_native import archive, get, scaled

ARCHIVE='7853bb2bf262c4567ac238d3552d97f0e50cb801'
DAYS=('2021-05-01','2021-06-01')
UTC_HOUR=3_600_000
STEP=200
SEEDS=(1,42,20201120)
PINNED={197:('CTA%E7%AD%96%E7%95%A5%E4%B9%8B%E5%95%86%E5%93%81%E6%9C%9F%E8%B4%A7%E7%AE%80%E6%98%93%E9%A9%AC%E4%B8%81%E6%A0%BC%E5%B0%94.md','275287'),
        4692:('%E6%96%90%E6%B3%A2%E9%82%A3%E5%A5%91%E6%95%B0%E5%88%97%E7%AD%96%E7%95%A5.md','353314'),
        5685:('%E9%A9%AC%E4%B8%81%E6%A0%BC%E5%B0%94%E6%89%93%E5%8D%B0%E6%94%B6%E7%9B%8A%E5%9B%BE%E8%A1%A8.md','353467')}


def sample_start(day):
    day_start=int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()*1000)
    return day_start+6*UTC_HOUR, day_start+10*UTC_HOUR


def capture(day,label,proof):
    url=f"https://datasets.tardis.dev/v1/binance-futures/{label}/{day.replace('-','/')}/BTCUSDT.csv.gz"
    with request(url) as response:
        count=int(response.headers['Content-Length'])
        assert response.status==200 and count<=50_000_000
        stream=HashReader(response)
        seen=previous=first=0
        with gzip.GzipFile(fileobj=stream) as packed, io.TextIOWrapper(packed,encoding='utf-8') as decoded:
            for row in csv.DictReader(decoded):
                assert row['exchange']=='binance-futures' and row['symbol']=='BTCUSDT'
                at=int(row['local_timestamp'])
                assert at>=previous
                if not first:
                    first=at
                previous=at
                seen+=1
                yield at,row
        assert stream.bytes==count
        proof.update(url=url,sha256=stream.sha.hexdigest(),rows=seen,bytes=count,first_local_us=first,last_local_us=previous)


def open_quotes(day):
    begin,end=sample_start(day)
    clocks=range(begin*1000,(end+1)*1000,STEP*1000)
    i=0
    samples=[]
    previous=active=None
    details={}
    for at,r in capture(day,'quotes',details):
        if i==len(clocks):
            continue
        while i<len(clocks) and at>clocks[i]+100_000:
            assert previous is not None
            if active is None:
                active=[*previous,previous[4],previous[5]]
            samples.append(active)
            i+=1
            active=None
        entry=[at,int(r['timestamp']),scaled(r['bid_price'],100),scaled(r['ask_price'],100),
               scaled(r['bid_amount'],1000),scaled(r['ask_amount'],1000)]
        assert entry[1]<=at and entry[2]<entry[3] and min(entry[2:])>0
        if i<len(clocks) and at>clocks[i]:
            if active is None:
                active=[*previous,previous[4],previous[5]]
            for j in range(2):
                active[6+j]=min(active[6+j],entry[4+j]) if active[2+j]==entry[2+j] else 0
        previous=entry
    assert len(samples)==len(clocks)
    assert all(q[1]<=q[0]<=t for q,t in zip(samples,clocks,strict=True))
    return samples,details


def marked(day):
    begin,end=sample_start(day)
    clocks=range(begin*1000,(end+1)*1000,STEP*1000)
    marks=[]
    previous=None
    i=0
    proof={}
    for at,r in capture(day,'derivative_ticker',proof):
        if i==len(clocks):
            continue
        while i<len(clocks) and at>clocks[i]:
            assert previous is not None
            marks.append(previous)
            i+=1
        if not r['last_price'] or not r['mark_price'] or not r['index_price']:
            continue
        previous=[at,int(r['timestamp']),scaled(r['last_price'],100),float(r['mark_price']),float(r['index_price']),
                  int(r['funding_timestamp']),r['funding_rate']]
        assert previous[1]<=at and min(previous[2:5])>0
    assert len(marks)==len(clocks) and all(r[1]<=r[0]<=t for r,t in zip(marks,clocks,strict=True))
    expected=begin+2*UTC_HOUR
    rows,venue=archive('BTC','fundingRate','',day[:7])
    [(at,interval,rate)]=[r for r in rows if abs(int(r[0])-expected)<2000]
    assert interval=='8'
    at,rate=int(at),float(rate)
    before=next(m for tp,m in reversed(list(zip(clocks,marks))) if tp<=expected*1000 and m[5]==expected*1000)
    assert abs(float(before[6])-rate)<1e-10
    after=next(m for tp,m in zip(clocks,marks) if tp>=expected*1000 and m[5]>expected*1000)
    label=f'BTCUSDT-1m-{day}.zip'
    url=f'https://data.binance.vision/data/futures/um/daily/markPriceKlines/BTCUSDT/1m/{label}'
    digest,fn=get(url+'.CHECKSUM',200).decode().split()
    raw=get(url,500_000)
    assert fn==label and sha(raw)==digest
    with ZipFile(io.BytesIO(raw)) as z:
        [fname]=z.namelist()
        with z.open(fname) as f:
            window=[r for r in csv.reader(io.TextIOWrapper(f,encoding='utf-8')) if r[0].isdigit() and expected-60_000<=int(r[0])<=expected]
    assert len(window)==2
    lower=min(float(r[3]) for r in window)
    upper=max(float(r[2]) for r in window)
    assert all(lower<=m[3]<=upper for m in (before,after))
    return marks,{'ticks':proof,'rate':venue,'mark_1m':{'url':url,'sha256':digest}}, {
        'boundary_ms':expected,'exchange_settlement_ms':at,'rate':rate,'prior_mark':before,'next_mark':after,
        'official_two_minute_mark_price_bounds_USDT':[lower,upper]}


def source_set(path):
    found={}
    with ZipFile(path) as z:
        for i,(member,authored) in PINNED.items():
            doc=z.read(f'strategies-{ARCHIVE}/{unquote(member)}')
            [source]=re.findall(r'(?ms)^`{3}[ \t]*javascript[ \t]*\n(.*?)^`{3}',doc.decode())
            assert 'Futures_Binance' in source and 'period: 1d' in source and 'Math.random()' in source
            found[i]={'source':source,'document_sha256':sha(doc),'source_sha256':sha(source.encode()),
                'archive_url':f'https://github.com/fmzquant/strategies/blob/{ARCHIVE}/{member}',
                'author_url':f'https://www.fmz.com/strategy/{authored}'}
    return found


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    for key in ('archive','output','native_contract'):
        cli.add_argument('--'+key.replace('_','-'),type=Path,required=True)
    a=cli.parse_args()
    sources=source_set(a.archive)
    control=a.native_contract.read_bytes()
    with ThreadPoolExecutor(max_workers=4) as p:
        quotes={d:p.submit(open_quotes,d) for d in DAYS}
        marks={d:p.submit(marked,d) for d in DAYS}
        scopes={}
        for day in DAYS:
            q,qproof=quotes[day].result()
            m,mproof,funding=marks[day].result()
            begin,end=sample_start(day)
            assert len(q)==len(m)==(end-begin)//STEP+1
            scopes[day]={'begin_ms':begin,'end_ms':end,'quotes':q,'marks':m,'funding':funding,
                         'quote_ref':qproof,'mark_ref':mproof}
            print(day,'quotes',qproof['rows'],'derivative ticker',mproof['ticks']['rows'],'rate',funding['rate'],flush=True)
    job={'scope':scopes,'sources':sources,'sample_step_ms':STEP,'seeds':SEEDS,'starting_cash_USDT':10000,'initial_cash_native_control':json.loads(control),
         'control_sha256':sha(control),'commission_rate':0.0004}
    packed=gzip.compress(json.dumps(job,ensure_ascii=False,separators=(',',':')).encode(),mtime=0)
    a.output.write_bytes(packed)
    print(len(packed),sha(packed),flush=True)


if __name__=='__main__':
    main()
