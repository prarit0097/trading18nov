"""Prepare checksummed ETH/LTC Binance inputs for exact FMZ source and template replay."""

import argparse
import csv
import gzip
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import unquote,urlencode
from zipfile import ZipFile

from fmz_native_round20_880_capture import request,sha

BEGIN=1630454400000
END=1641427200000
HOUR=3600000
DAY=24*HOUR
STEP=900000
ASSETS=('ETH','LTC')
MONTHS_15=('2021-09','2021-10','2021-11','2021-12','2022-01')
MONTHS_SMALL_WARM=('2021-05','2021-06','2021-07','2021-08')
MONTHS_WARM=('2020-10','2020-11','2020-12','2021-01','2021-02','2021-03','2021-04','2021-05','2021-06','2021-07','2021-08')
PIN='7853bb2bf262c4567ac238d3552d97f0e50cb801'
URL='https://github.com/fmzquant/strategies/blob/'+PIN+'/%E6%95%B0%E5%AD%97%E8%B4%A7%E5%B8%81%E6%9C%9F%E8%B4%A7%E5%A4%9A%E5%93%81%E7%A7%8DATR%E7%AD%96%E7%95%A5%E6%95%99%E5%AD%A6.md'
TEMPLATE_PATH='strategies-'+PIN+'/\u6570\u5b57\u8d27\u5e01\u671f\u8d27\u4ea4\u6613\u7c7b\u5e93\u6d4b\u8bd5\u7248.md'
DOC_SHA='2666ed12c11e594776d8f1407426450912c9fcb8a67fdcf5f36af30891571ac1'
SOURCE_SHA='730be6d7ee34991014a24d30edf00dd222122f6bb3588fa564cbf4c35ae954ea'
HELPER_DOC_SHA='eeabd483ce664adb3da6ba465b6489ad6f40ccff1319d5c6fe389333c4e5c888'
HELPER_SHA='87154be8bf09cad65af71bf82097fc344aa738fff9c37ca21e0bd26a63ef89a3'


def get(url,cap):
    with request(url) as f:
        raw=f.read(cap+1)
        assert f.status==200 and len(raw)<=cap
    return raw


def form(ref,first,cache):
    url=f'https://www.fmz.com/strategy/{ref}'
    raw=cache.read_bytes() if cache else get(url,1_500_000)
    text=raw.decode()
    start=re.search(r'\[\[(\\+")'+first,text)
    end=text.index(']]',start.start())+2
    items=json.loads(text[start.start():end].replace(start[1],'"'))
    return {'url':url,'html_sha256':sha(raw),'args':{r[0].split('@')[0]:r[3] for r in items}}


def q(coin,alias,event,step,from_ms,to_ms):
    spec=dict(eid='Futures_Binance',symbol=coin+'_USDT.'+alias,event=event,detail='true',round='true',
         period=step,**{'from':from_ms//1000,'to':to_ms//1000})
    url='https://q.fmz.com/data/history?'+urlencode(spec)
    raw=get(url,1_500_000)
    parsed=json.loads(raw)
    assert parsed['detail']['symbol']==spec['symbol']
    return parsed,{'url':url,'sha256':sha(raw),'rows':len(parsed['data'])}


def archive(coin,category,interval,month):
    symbol=coin+'USDT'
    name=f'{symbol}-{interval or category}-{month}.zip'
    suffix=f'{interval}/' if interval else ''
    url=f'https://data.binance.vision/data/futures/um/monthly/{category}/{symbol}/{suffix}{name}'
    code,n=get(url+'.CHECKSUM',200).decode().split()
    assert n==name
    raw=get(url,500_000)
    assert sha(raw)==code
    with ZipFile(io.BytesIO(raw)) as z:
        [f]=z.namelist()
        with z.open(f) as s:
            rows=[r for r in csv.reader(io.TextIOWrapper(s,encoding='utf-8')) if r[0].isdigit()]
    return rows,{'url':url,'sha256':code,'rows':len(rows),'checksum_url':url+'.CHECKSUM'}


def scaled(value,n):
    return int((Decimal(value)*n).to_integral_value(rounding=ROUND_HALF_UP))


def to_market(rows,step,vol):
    out=[]
    for r in rows:
        t=int(r[0]); assert t%step==0 and int(r[6])-t==step-1
        out.append([t,*[scaled(x,100) for x in r[1:5]],scaled(r[5],1000) if vol else 0])
    return out


def to_funding(rows):
    out=[]
    for r in rows:
        t=int(r[0]); assert r[1]=='8' and abs(t-round(t/(8*HOUR))*8*HOUR)<2000
        at=round(t/(8*HOUR))*8*HOUR
        val=scaled(r[2],100_000_000)
        out.append([at,val,val,val,val,0])
    return out


def source_parts(z,p,doc,code):
    b=z.read(p)
    [v]=re.findall(r'(?ms)^\x60{3}[ \t]*javascript[ \t]*\n(.*?)^\x60{3}',b.decode())
    assert sha(b)==doc and sha(v.encode())==code
    return v


def stage_coin(p,coin):
    types={'swap':('klines','15m',MONTHS_SMALL_WARM+MONTHS_15),'index':('indexPriceKlines','15m',MONTHS_SMALL_WARM+MONTHS_15),
           'funding':('fundingRate','',MONTHS_15),'daily':('klines','1d',MONTHS_WARM+MONTHS_15)}
    bins={(kind,m):p.submit(archive,coin,c,t,m) for kind,(c,t,months) in types.items() for m in months}
    qs={kind:p.submit(q,coin,'swap' if kind=='daily' else kind,'fill' if kind=='daily' else 'feed',
                  DAY if kind=='daily' else STEP,
                  BEGIN-320*DAY if kind=='daily' else BEGIN,
                  END+DAY if kind=='daily' else BEGIN+7*DAY) for kind in types}
    binding={}
    for kind,(cat,timeframe,ms) in types.items():
        reference,q_proof=qs[kind].result()
        raw=[bins[(kind,m)].result() for m in ms]
        combined=[r for part,_ in raw for r in part]
        direct=to_funding(combined) if kind=='funding' else to_market(combined,DAY if kind=='daily' else STEP,kind in ('swap','daily'))
        by_t={r[0]:r for r in direct}
        assert len(by_t)==len(direct)
        common=[r for r in reference['data'] if r[0] in by_t]
        assert len(common)>0
        counts=[sum(r[i]==by_t[r[0]][i] for r in common) for i in range(1,6)]
        assert counts[3]/len(common)>=0.94,(coin,kind,counts,len(common))
        if kind=='funding':
            assert counts[:4]==[len(common)]*4
        step=(DAY if kind=='daily' else 8*HOUR if kind=='funding' else STEP)
        first=(BEGIN-315*DAY if kind=='daily' else BEGIN if kind=='funding' else BEGIN-110*DAY)
        relevant=[r for r in direct if first<=r[0]<=END+DAY]
        assert [r[0] for r in relevant]==list(range(first,END+DAY+1,step))
        binding[kind]={'schema':reference['schema'],'detail':reference['detail'],'data':relevant,
                  'checks':{'overlap':len(common),'equal_ohlcv':counts,'fmz':q_proof,'exchange_checksums':[k for _,k in raw]}}
        print(coin,kind,len(relevant),'crosschecks',counts,len(common),flush=True)
    return binding


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for a in ('archive','output','author-page','template-page'):
        p.add_argument('--'+a,type=Path,required=a in ('archive','output'))
    a=p.parse_args()
    with ZipFile(a.archive) as z:
        source=source_parts(z,'strategies-'+unquote(URL.split('/blob/')[1]),DOC_SHA,SOURCE_SHA)
        template=source_parts(z,TEMPLATE_PATH,HELPER_DOC_SHA,HELPER_SHA)
    params=dict(json.loads(re.search(r'(?m)^args: (.+)$',source)[1]))
    assert [{k:v for k,v in r.items()} for r in json.loads(params['params'])]==[
        {'symbol':'swap','period':86400,'stopLoss':0.07,'atrPeriod':10,'emaPeriod':20,'trackRatio':2,'openRatio':0.1}]*2
    pub=form(339344,'params',a.author_page)
    lib=form(203258,'Interval',a.template_page)
    assert pub['args']['onlyOne'] is True and lib['args']=={'Interval':500,'MinAmount':1,'SlidePrice':5}
    with ThreadPoolExecutor(max_workers=16) as pool:
        feeds={c:stage_coin(pool,c) for c in ASSETS}
    obj={'source':source,'template':template,'source_sha256':SOURCE_SHA,'template_sha256':HELPER_SHA,
         'source_doc_sha256':DOC_SHA,'template_doc_sha256':HELPER_DOC_SHA,'source_url':URL,'from_ms':BEGIN,'to_ms':END,
         'source_public_form':pub,'template_public_form':lib,'embedded_params':params,'feeds':feeds}
    packed=gzip.compress((json.dumps(obj,ensure_ascii=False,separators=(',',':'))+'\n').encode(),mtime=0)
    a.output.write_bytes(packed)
    print(len(packed),sha(packed))


if __name__=='__main__':
    main()
