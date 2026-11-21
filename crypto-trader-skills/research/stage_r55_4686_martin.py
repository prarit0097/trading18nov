"""Stage the author's Binance ETHUSDT martingale prototype benchmark on official data."""
import argparse,csv,gzip,json,re
from datetime import datetime
from decimal import Decimal as D
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from fmz_native_round20_880_capture import sha

MINUTE5=300_000
BASE='https://data.binance.vision/data/futures/um/monthly'
PUBLISHER='https://www.fmz.com/bbs-topic/7457'
AUTHOR_SETUP='https://www.fmz.com/upload/asset/1763ccc10fd4a299b2db.png'
AUTHOR_RESULT='https://www.fmz.com/upload/asset/167521e5bd36ee139298.png'


def ms(iso):
    return int(datetime.fromisoformat(iso).timestamp()*1000)


def datasets(root,before,after):
    feeds={};provenance=[]
    for kind in ('klines','indexPriceKlines','markPriceKlines','fundingRate'):
        rows=[]
        for p in sorted(root.glob(kind+'-*.zip')):
            b=p.read_bytes();digest=sha(b)
            assert p.with_suffix('.zip.CHECKSUM').read_text().split()[0]==digest
            raw=p.name.removeprefix(kind+'-')
            postfix='ETHUSDT' if kind=='fundingRate' else 'ETHUSDT/5m'
            path=f'{BASE}/{kind}/{postfix}/{raw}'
            with ZipFile(p) as z:
                content=z.read(z.namelist()[0]).decode().splitlines()
            source=list(csv.reader(content))
            if not source[0][0].isdigit():source=source[1:]
            provenance.append({'url':path,'archive_sha256':digest,'rows':len(source)})
            for r in source:
                start=int(r[0])
                if start<before or start>=after:continue
                if kind=='fundingRate':
                    rate=D(r[2])*100_000_000
                    assert int(r[1])==8 and rate==int(rate)
                    rows.append([start,*([int(rate)]*4),0])
                else:
                    assert int(r[6])==start+MINUTE5-1
                    prices=[int((D(x)*100).to_integral_value()) for x in r[1:5]]
                    volume=D(r[5])*1000
                    assert volume==int(volume)
                    assert min(prices)>=0 and prices[2]<=min(prices[0],prices[3]) and prices[1]>=max(prices[0],prices[3])
                    rows.append([start,*prices,int(volume)])
        assert rows==sorted(rows)
        assert len({x[0] for x in rows})==len(rows)
        feeds[kind]=rows
    return feeds,provenance


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('archive','catalog','market','author-setup','author-result','output'):
        p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args()
    [row]=[s for s in json.loads(a.catalog.read_bytes())['disposition'] if s['id']==4686]
    with ZipFile(a.archive) as z: md=z.read('strategies-'+unquote(row['source'].split('/blob/')[1]))
    assert sha(md)==row['pinned_document_sha256']
    [source]=re.findall(r'(?ms)^`{3}[ \t]*javascript[ \t]*\n(.*?)^`{3}',md.decode())
    assert 'if (!IsVirtual())' in source and 'exchange.SetContractType("swap")' in source
    start,end=ms('2021-01-01T00:00:00+08:00'),ms('2021-07-01T00:00:00+08:00')
    earliest=start-24*86_400_000
    feeds,proof=datasets(a.market,earliest,end+86_400_000)
    schema=['time','open','high','low','close','vol']
    baseline={'symbol':'ETH_USDT.swap','alias':'ETHUSDT','baseCurrency':'ETH','basePrecision':3,'quoteCurrency':'USDT',
           'quotePrecision':2,'marginCurrency':'USDT','minQty':.001,'maxQty':10000,'minNotional':0,
           'maxNotional':1.7976931348623157e308,'priceTick':.01,'volumeTick':.001,'eid':'Futures_Binance',
           'contractType':'swap','marginLevel':10,'volumeMultiple':1}
    funding={**baseline,'symbol':'ETH_USDT.funding','alias':'ETH_USDT.funding','basePrecision':8,'quotePrecision':8,
        'marginCurrency':'','priceTick':1e-8,'volumeTick':1e-8,'minQty':1,'minNotional':1,'maxNotional':100_000_000}
    funding.pop('contractType')
    specs={'swap':(baseline,feeds['klines']),'index':({**baseline,'symbol':'ETH_USDT.index','contractType':'index'},feeds['indexPriceKlines']),
           'funding':(funding,feeds['fundingRate'])}
    params={'targetProfit':10,'amount':.005,'totalEq':-1,'isReset':False,'pricePrecision':2,'amountPrecision':3,'isSimulate':False,
           'SpecifyPosField':'','showLine':False,'mode':0,'maxPendingDiff':60,'increment':False}
    assert '|' + 'targetProfit' + '|10|' in md.decode()
    setup=a.author_setup.read_bytes();old=a.author_result.read_bytes()
    assert setup.startswith(b'\x89PNG') and old.startswith(b'\x89PNG')
    out={'id':4686,'source':source,'source_sha256':sha(source.encode()),'document_sha256':sha(md),'source_url':row['source'],
         'publisher':PUBLISHER,'author_settings':{'url':AUTHOR_SETUP,'sha256':sha(setup)},
         'author_old_result':{'url':AUTHOR_RESULT,'sha256':sha(old)},'parameters':params,'begin_ms':start,'end_ms':end,
         'browsed_files':proof,'feeds':{t:{'schema':schema,'detail':d,'data':r} for t,(d,r) in specs.items()},
         'independent_mark_5m':feeds['markPriceKlines']}
    payload=gzip.compress(json.dumps(out,ensure_ascii=False,separators=(',',':')).encode(),mtime=0)
    a.output.write_bytes(payload)
    print(sha(payload),len(payload),{k:len(v) for k,v in feeds.items()},out['author_settings'],flush=True)


if __name__=='__main__':main()
