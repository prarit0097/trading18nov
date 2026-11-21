"""Bind #4417's named original notebook and check its six historical Binance price legs."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
from decimal import Decimal as D
import io
import json
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from fmz_native_round20_880_capture import request, sha

ABB='https://www.fmz.com/upload/asset/'
NOTE=ABB+'1bc8575bad003167f2d.ipynb?name=%E5%B8%81%E5%AE%89%E4%BA%A4%E5%89%B2%E5%90%88%E7%BA%A6%E7%AD%96%E7%95%A53.ipynb'
HISTORY=ABB+'1420b2081ecd122522d.csv'
LEGS=[f'{coin}USD_{key}' for coin in ('BTC','ETH') for key in ('200925','201225','PERP')]
ROOT='https://data.binance.vision/data/futures/cm/monthly/klines'
MONTHS=('2020-08','2020-09')
NATIVE_PERIOD=300_000


def get(u, limit):
    with request(u) as response:
        raw=response.read(limit+1)
    assert 0<len(raw)<=limit
    return raw


def ohlc(symbol,local):
    out={}
    proof=[]
    for m in MONTHS:
        file=f'{symbol}-5m-{m}.zip'
        url=f'{ROOT}/{symbol}/5m/{file}'
        if local:
            receipt=(local/(file+'.CHECKSUM')).read_bytes()
            raw=(local/file).read_bytes()
        else:
            receipt=get(url+'.CHECKSUM',200)
            raw=get(url,2_000_000)
        checksum,name=receipt.decode().split()
        assert name==file and checksum==sha(raw)
        count=0
        with ZipFile(io.BytesIO(raw)) as archive:
            [member]=archive.namelist()
            with archive.open(member) as f:
                for row in csv.reader(io.TextIOWrapper(f,encoding='utf-8')):
                    if not row[0].isdigit():continue
                    t=int(row[0]); assert t%NATIVE_PERIOD==0 and t not in out
                    out[t]=tuple(D(v) for v in row[1:5])
                    count+=1
        proof.append({'archive_url':url,'source_zip_sha256':checksum,'rows':count})
    return out,proof


def market_time(view):
    return round(datetime.fromisoformat(view).replace(tzinfo=timezone.utc).timestamp()*1000)


def check(symbol,records,official,proof):
    joined=[(market_time(r['']),D(r[symbol])) for r in records if r[symbol]]
    assert all(b[0]-a[0]==NATIVE_PERIOD for a,b in zip(joined,joined[1:]))
    assert all(t in official for t,x in joined)
    failed=[]
    for t,v in joined:
        a=official[t]
        if v!=a[3]:failed.append({'at_ms':t,'author':str(v),'independent_OHLC':[str(x) for x in a]})
    assert len(failed)==1 and failed[0]['at_ms']==joined[-1][0]==1600050600000
    z=failed[0]
    assert D(z['independent_OHLC'][2])<=D(z['author'])<=D(z['independent_OHLC'][1])
    return {'symbol':symbol,'first_price_bar_ms':joined[0][0],'last_price_bar_ms':joined[-1][0],
            'independent_final_candle_close':z['independent_OHLC'][3],'exact_finalized_price_matches':len(joined)-1,
            'terminal_snapshot_discrepancy':z,'binance_files':proof}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('catalog','archive','notebook','author-csv','output'):
        p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--cached-binance-zips',type=Path)
    a=p.parse_args()
    [row]=[x for x in json.loads(a.catalog.read_bytes())['disposition'] if x['id']==4417]
    with ZipFile(a.archive) as z:
        archived=z.read('strategies-'+unquote(row['source'].split('/blob/')[1]))
    assert sha(archived)==row['pinned_document_sha256']
    assert b'https://www.fmz.com/digest-topic/6102' in archived
    assert b'if(IsVirtual())' in archived and b'Futures_Binance' in archived
    n=a.notebook.read_bytes()
    assert sha(n)=='b7cc256da48f2e99489043feec81276c71e36b80d7a6908ebefe3c931533d983'
    j=json.loads(n)
    assert HISTORY in ''.join(j['cells'][3]['source'])
    raw=a.author_csv.read_bytes()
    assert sha(raw)=='b30db1ace801c3b5acbe4af0c79699a8c8423351daa978fb8bcd3474ffbdcc80'
    lines=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    assert len(lines)==8767
    with ThreadPoolExecutor(max_workers=6) as pool:
        reads={symbol:pool.submit(ohlc,symbol,a.cached_binance_zips) for symbol in LEGS}
        all_legs=[check(symbol,lines,*future.result()) for symbol,future in reads.items()]
    control={'source':{'source_url':row['source'],'published_runtime_doc_sha256':sha(archived),
              'author_notebook_url':NOTE,'author_notebook_sha256':sha(n),'author_csv_url':HISTORY,'author_csv_sha256':sha(raw),
              'source_cells':{str(i):sha(''.join(j['cells'][i]['source']).encode()) for i in (13,14,18)}},
              'prices':all_legs,'csv_price_rows':len(lines),'effective_timezone':'UTC matches with no offset'}
    a.output.write_text(json.dumps(control,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(sha(a.output.read_bytes()),[(m['symbol'],m['exact_finalized_price_matches']) for m in all_legs],flush=True)


if __name__=='__main__':main()
