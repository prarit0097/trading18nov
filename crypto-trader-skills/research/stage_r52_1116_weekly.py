"""Bind the legacy Dual Thrust Python source to a real dated OKEX BTC weekly contract."""
import argparse
import csv
from decimal import Decimal as D
import gzip
import io
import json
from pathlib import Path
import re
from urllib.parse import unquote
from zipfile import ZipFile

from fmz_native_round20_880_capture import request, sha
from stage_r42_3717_spot import StreamDigest

DAY0=1567296000000
DATA='https://datasets.tardis.dev/v1/okex-futures/trades/2019/09/01/BTC-USD-190906.csv.gz'
AUTHOR='https://www.fmz.com/strategy/21856'
SYMBOL='BTC-USD-190906'


def observe():
    bars={}
    rows=0
    previous=0
    min_stamp=0
    with request(DATA) as resp:
        stream=StreamDigest(resp)
        with gzip.GzipFile(fileobj=stream) as gz,io.TextIOWrapper(gz,encoding='utf-8') as body:
            for raw in csv.DictReader(body):
                assert raw['exchange']=='okex-futures' and raw['symbol']==SYMBOL
                assert raw['side'] in ('buy','sell')
                stamp=int(raw['timestamp']);received=int(raw['local_timestamp'])
                assert received>=previous
                previous=received
                first=min(stamp,received)
                min_stamp=min(min_stamp or first,first)
                minute=stamp//60_000_000*60_000
                if not DAY0<=minute<DAY0+86_400_000:continue
                p=D(raw['price'])*100
                n=D(raw['amount'])
                assert p==int(p) and n==int(n) and int(n)>0
                rows+=1
                item=[stamp,int(raw['id']),int(p),int(n)]
                bars.setdefault(minute,[]).append(item)
        assert stream.size==int(resp.headers['Content-Length'])
    ordered=[]
    for ts,seq in sorted(bars.items()):
        seq.sort()
        prices=[q[2] for q in seq]
        ordered.append([ts,prices[0],max(prices),min(prices),prices[-1],sum(x[3] for x in seq)])
    missing=sorted(set(range(DAY0,DAY0+86_400_000,60_000))-set(bars))
    assert len(ordered)>1300 and rows>10_000
    return ordered,{'url':DATA,'sha256':stream.sha.hexdigest(),'bytes':stream.size,'market_trade_count':rows,'missing_minutes_ms':missing}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('catalog','archive','author','output'):
        p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    [row]=[s for s in json.loads(a.catalog.read_bytes())['disposition'] if s['id']==1116]
    with ZipFile(a.archive) as archive:
        b=archive.read('strategies-'+unquote(row['source'].split('/blob/')[1]))
    assert sha(b)==row['pinned_document_sha256']
    md=b.decode()
    [script]=re.findall(r'(?ms)^`{3}[ \t]*python[ \t]*\n(.*?)^`{3}',md)
    assert 'if exchange.GetName() != \'Futures_OKCoin\'' in script and 'SetContractType(["this_week","next_week","quarter"]' in script
    assert '|ContractTypeIdx|0|' in md and '|MarginLevelIdx|0|' in md
    pub=a.author.read_bytes();s=pub.decode()
    f=re.search(r'\[\[([\\]+")ContractTypeIdx',s)
    author=json.loads(s[f.start():s.index(']]',f.start())+2].replace(f[1],'"'))
    options={x[0]:x[3] for x in author}
    assert options.pop('ContractTypeIdx')=='$$$__list__$$$当周|次周|季度'
    assert options.pop('MarginLevelIdx')=='$$$__list__$$$10|20'
    assert options=={'NPeriod':4,'Ks':.5,'Kx':.5,'AmountOP':1,'Interval':2000,'LoopInterval':3,'PeriodShow':500}
    options.update(ContractTypeIdx=0,MarginLevelIdx=0)
    prices,trade_proof=observe()
    out={'source_url':row['source'],'source_sha256':sha(script.encode()),'archive_sha256':sha(b),'script':script,
         'publisher':AUTHOR,'publisher_snapshot_sha256':sha(pub),'params':options,'trade_proof':trade_proof,
         'named_market':SYMBOL,'begin_ms':DAY0+6*3_600_000,'end_ms':DAY0+22*3_600_000,
         'market':{'detail':{'symbol':'BTC_USD.this_week','alias':SYMBOL,'baseCurrency':'BTC','basePrecision':0,
                             'quoteCurrency':'USD','quotePrecision':2,'marginCurrency':'BTC','minQty':1,'maxQty':10000,
                             'minNotional':0,'maxNotional':1.7976931348623157e308,'priceTick':.01,'volumeTick':1,'eid':'Futures_OKCoin',
                             'contractType':'this_week','marginLevel':10,'volumeMultiple':100},
                   'schema':['time','open','high','low','close','vol'],'data':prices}}
    payload=gzip.compress(json.dumps(out,ensure_ascii=False,separators=(',',':')).encode(),mtime=0)
    with a.output.open('xb') as f:f.write(payload)
    print(sha(payload),len(payload),trade_proof,flush=True)


if __name__=='__main__':main()
