"""Pin #4850 and a source-compatible, 100 USD BTC inverse quarter scenario."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
from decimal import Decimal as D
import gzip
import io
import json
from pathlib import Path
import re
from urllib.parse import unquote
from zipfile import ZipFile

from fmz_native_round20_880_capture import sha
from stage_r47_4417_butterfly import get

MARKET='BTCUSD_211231'
BASE='https://data.binance.vision/data/futures/cm/monthly/klines'
MONTHS=('2021-08','2021-09','2021-10','2021-11','2021-12')
PUBLIC='https://www.fmz.com/strategy/192353'


def timestamp(t):
    return int(datetime.fromisoformat(t).replace(tzinfo=timezone.utc).timestamp())*1000


def archive(month):
    filename=f'{MARKET}-1h-{month}.zip'
    url=f'{BASE}/{MARKET}/1h/{filename}'
    digest,label=get(url+'.CHECKSUM',200).decode().split()
    raw=get(url,2_000_000)
    assert digest==sha(raw) and label==filename
    bars=[]
    with ZipFile(io.BytesIO(raw)) as package:
        [file]=package.namelist()
        with package.open(file) as f:
            for row in csv.reader(io.TextIOWrapper(f,encoding='utf-8')):
                if not row[0].isdigit():continue
                stamp=int(row[0])
                assert int(row[6])==stamp+3_599_999 or stamp==timestamp('2021-12-31 07:00:00')
                prices=tuple(D(x)*10 for x in row[1:5])
                assert all(x==int(x) for x in prices)
                qty=D(row[5]);assert qty==int(qty)
                bars.append([stamp,*[int(q) for q in prices],int(qty)])
    return bars,{'url':url,'sha256':digest,'rows':len(bars),'first':bars[0][0],'last':bars[-1][0]}


def main():
    parse=argparse.ArgumentParser(description=__doc__)
    for k in ('catalog','archive','output'):
        parse.add_argument('--'+k,type=Path,required=True)
    a=parse.parse_args()
    [entry]=[s for s in json.loads(a.catalog.read_bytes())['disposition'] if s['id']==4850]
    with ZipFile(a.archive) as z:
        doc=z.read('strategies-'+unquote(entry['source'].split('/blob/')[1]))
    assert sha(doc)==entry['pinned_document_sha256']
    md=doc.decode()
    [s]=re.findall(r'(?ms)^`{3}[ \t]*python[ \t]*\n(.*?)^`{3}',md)
    assert all(k in s for k in ('SetContractType("quarter")',"55 , 'High'","55 , 'Low'",'100 * self.n'))
    assert all(v in md for v in ('|Donchian_open|20|','|Donchian_stop|10|','|Atr|20|',PUBLIC))
    assert 'backtest\nstart:' not in s
    with ThreadPoolExecutor(max_workers=5) as p:
        chunks,reports=zip(*p.map(archive,MONTHS),strict=True)
    bars=[k for group in chunks for k in group]
    assert len({k[0] for k in bars})==len(bars)
    begin=timestamp('2021-10-01');end=timestamp('2021-12-24')
    required=[t for t in range(timestamp('2021-08-01'),end+3_600_000,3_600_000)]
    assert [r[0] for r in bars if r[0]<=end]==required
    r={'source':{'url':entry['source'],'archive_sha256':sha(doc),'code_sha256':sha(s.encode()),'publisher':PUBLIC},
       'python_source':s,'source_defaults':{'Donchian_open':20,'Donchian_stop':10,'Atr':20},'archive_rows':reports,
       'historical_market_symbol':MARKET,'begin_ms':begin,'end_ms':end,'author_alternate_initial_BTC':0.1,
       'market':{'detail':{'symbol':'BTC_USD.quarter','alias':MARKET,'baseCurrency':'BTC','basePrecision':0,'quoteCurrency':'USD',
                          'quotePrecision':1,'marginCurrency':'BTC','minQty':1,'maxQty':1000000,'minNotional':0,
                          'maxNotional':1.7976931348623157e308,'priceTick':0.1,'volumeTick':1,'eid':'Futures_Binance',
                          'contractType':'quarter','marginLevel':10,'volumeMultiple':100},
                 'schema':['time','open','high','low','close','vol'],'data':[x for x in bars if x[0]<=end]},
       'assumptions':{'chart':'1d author-day-based indicator scenario, causal 1h FMZ synthetic tick feed',
                      'account':'0.1 BTC flat simulated wallet, native default 10x, explicit model fees of 0.02% maker and 0.05% taker',
                      'date':'Named December 2021 quarter throughout the first full month through the week before expiry'}}
    out=gzip.compress(json.dumps(r,separators=(',',':')).encode(),mtime=0)
    with a.output.open('xb') as f:f.write(out)
    print(sha(out),len(out),reports,flush=True)


if __name__=='__main__':main()
