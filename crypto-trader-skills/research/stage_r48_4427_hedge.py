"""Verify the linked #4427 fixed-exposure BTC hedge notebook and original market inputs."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
from decimal import Decimal as D
import io
import json
from pathlib import Path
import re
from urllib.parse import unquote
from zipfile import ZipFile

from fmz_native_round20_880_capture import sha
from stage_r47_4417_butterfly import get

NOTES='https://www.fmz.com/upload/asset/13427101e9d296c8f03.ipynb'
AUTHOR='https://www.fmz.com/upload/asset/20227de6c1d10cb9dd1.csv'
MARKET='https://data.binance.vision/data/futures/um/monthly/klines'
MONTHS=('2020-02','2020-03','2020-04')


def first_parse(row):
    return int(datetime.fromisoformat(row['0']).replace(tzinfo=timezone.utc).timestamp())*1000


def reconcile(symbol,series,local):
    official={}
    sources=[]
    for month in MONTHS:
        filename=f'{symbol}USDT-1h-{month}.zip'
        url=f'{MARKET}/{symbol}USDT/1h/{filename}'
        if local:
            payload=(local/filename).read_bytes()
            check=(local/(filename+'.CHECKSUM')).read_bytes()
        else:
            payload=get(url,2_000_000)
            check=get(url+'.CHECKSUM',200)
        checksum,label=check.decode().split()
        assert label==filename and sha(payload)==checksum
        with ZipFile(io.BytesIO(payload)) as z:
            [content]=z.namelist()
            with z.open(content) as stream:
                for row in csv.reader(io.TextIOWrapper(stream,encoding='utf-8')):
                    if not row[0].isdigit():continue
                    stamp=int(row[0]);assert stamp not in official
                    official[stamp]=[D(x) for x in row[1:5]]
        sources.append({'url':url,'checksum_sha256':checksum})
    expected=[(first_parse(x),D(x[symbol])) for x in series if x[symbol]]
    wanted=[(t,v) for t,v in expected if v!=official[t][3]]
    assert len(wanted)==1 and wanted[0][0]==expected[-1][0]==1586314800000
    t,last=wanted[0]
    assert official[t][2]<=last<=official[t][1]
    return {'symbol':symbol,'no_price_rows':len(series)-len(expected),'finalized_exact_matches':len(expected)-1,
            'first_bar_ms':expected[0][0],'terminal_bar_ms':t,'terminal_author_price':str(last),
            'terminal_official_close':str(official[t][3]),'terminal_official_ohlc':[str(v) for v in official[t]],'sources':sources}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('catalog','archive','notebook','csv','output'):
        p.add_argument('--'+k,required=True,type=Path)
    p.add_argument('--cache',type=Path)
    a=p.parse_args()
    [row]=[r for r in json.loads(a.catalog.read_bytes())['disposition'] if r['id']==4427]
    with ZipFile(a.archive) as arch:
        raw=arch.read('strategies-'+unquote(row['source'].split('/blob/')[1]))
    assert sha(raw)==row['pinned_document_sha256']
    text=raw.decode()
    assert all(key in text for key in ('https://www.fmz.com/strategy/194825','https://www.fmz.com/digest-topic/5294','|Long_symbols|BTC|'))
    symbols=re.search(r'(?m)^\|Short_symbols\|([^|]+)\|',text)[1].split(',')
    assert len(symbols)==14 and 'ETH' not in symbols
    archive=a.notebook.read_bytes()
    j=json.loads(archive)
    assert sha(archive)=='eed08c7dfa720bb29fccbfb49a57e3db09b480e41a0700a621c917f674178ee9'
    cells={i:''.join(j['cells'][i]['source']) for i in (3,17,24,27)}
    assert AUTHOR in cells[17] and 'trade_value = 2000' in cells[27] and 'commission=0.0005' in cells[27]
    market=a.csv.read_bytes();assert sha(market)=='47dac237f183390ee217aa4ca8245c8cd65873552efc243bdb6f2089d96cb483'
    prices=list(csv.DictReader(io.StringIO(market.decode('utf-8-sig'))))
    assert len(prices)==1500
    assert all(first_parse(b)-first_parse(a)==3600000 for a,b in zip(prices,prices[1:]))
    with ThreadPoolExecutor(max_workers=8) as e:
        rows=[e.submit(reconcile,s,prices,a.cache) for s in [*symbols,'BTC']]
        proof=[x.result() for x in rows]
    doc={'source':{'archive_url':row['source'],'archive_sha256':sha(raw),'author_url':'https://www.fmz.com/strategy/194825',
                   'article_url':'https://www.fmz.com/digest-topic/5294','notebook_url':NOTES,'notebook_sha256':sha(archive),
                   'original_cells':{str(i):sha(s.encode()) for i,s in cells.items()},'public_data_url':AUTHOR,'csv_sha256':sha(market)},
         'short_symbols':symbols,'long_symbols':['BTC'],'official_market_proof':proof,'rows':len(prices)}
    a.output.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(sha(a.output.read_bytes()),sum(x['finalized_exact_matches'] for x in proof),len(proof),flush=True)


if __name__=='__main__':main()
