"""Pin the archived #5148 rule to the existing separately captured BTC and ETH books."""
import argparse
import gzip
import json
from pathlib import Path
import re
from urllib.parse import unquote
from zipfile import ZipFile

from fmz_native_round20_880_capture import sha

BOOKS={'BTC':'b015d1141748c74b28500f4b93539b3d309b278a97c56bf98993c6b66f404593',
       'ETH':'c23f573d38c443416d615d7e374fd91a293395b3e33e3f14399bda9d0f8cc155'}
ARCHIVE='98c32771182eff39262622bdb102cc6fefe7095ad11e40f3f5c35346382e57ed'
SOURCE_DATES=('2021-05-01','2021-06-01')
VENUE_MINIMUM_NOTIONAL_REFERENCE='https://www.binance.com/en/support/announcement/detail/1d762daf60dd417f9d8a05d44b06a25c'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('catalog','archive','btc','eth','output'):
        p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    [r]=[c for c in json.loads(a.catalog.read_bytes())['disposition'] if c['id']==5148]
    with ZipFile(a.archive) as z:
        md=z.read('strategies-'+unquote(r['source'].split('/blob/')[1]))
    assert sha(md)==ARCHIVE
    [source]=re.findall(r'(?ms)^`{3}[ \t]*javascript[ \t]*\n(.*?)^`{3}',md.decode())
    assert all(t in source for t in ('"currency":"XXX_USDT"','"BTC_USDT"','"ETH_USDT"','basePeriod: 1h',
               "_G('tradeHistory')",'var chart = Chart', 'var n =$','MarginLevel = 50','initialFunds =10000'))
    proof={}
    for coin in BOOKS:
        raw=getattr(a,coin.lower()).read_bytes()
        assert sha(raw)==BOOKS[coin]
        packed=json.loads(gzip.decompress(raw))
        scoped=packed['scope'];assert tuple(scoped)==SOURCE_DATES
        assert packed['seeds']==[1,42,20201120] and packed['sample_step_ms']==200
        proof[coin]={}
        for day,market in scoped.items():
            bounds=[r[3] for r in market['marks']]+[r[2]/100 for r in market['marks']]+[v/100 for q in market['quotes'] for v in q[2:4]]
            floor,ceiling=min(bounds),max(bounds)
            if coin=='ETH':assert 2500<floor<=ceiling<5000
            if coin=='BTC':assert floor>5000
            proof[coin][day]={'quote_last_mark_price_floor_USDT':floor,'quote_last_mark_price_ceiling_USDT':ceiling,
                'clock_ms':[market['begin_ms'],market['end_ms']], 'source':market.get('proof',market.get('top25_proof'))}
    job={'code':source,'source_sha256':sha(source.encode()),'archive_sha256':ARCHIVE,'archive_url':r['source'],
         'book_shas':BOOKS,'observed_price_range':proof,'leverage':50,'initial_cash_USDT':10000,'fee_rate':0.0004,
         'minimum_notional_USDT':5,'minimum_notional_reference':VENUE_MINIMUM_NOTIONAL_REFERENCE,'seeds':[1,42,20201120]}
    raw=gzip.compress(json.dumps(job,ensure_ascii=False,separators=(',',':')).encode(),mtime=0)
    a.output.write_bytes(raw)
    print(len(raw),sha(raw),proof,flush=True)


if __name__=='__main__':main()
