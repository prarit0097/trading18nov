"""Stage the shared checksummed BTCUSDT native replay input for FMZ #4834 and #4835."""

import argparse
import gzip
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from fmz_native_round20_880_capture import sha
from stage_r29_4685_native import archive, q, scaled, form

B=1619827200000
H=3600000
D=24*H
E=1630108800000
ID_META={
 4834: {'slug':'%E6%B5%8B%E8%AF%95-%E5%85%B3%E4%BA%8E%E4%BD%BF%E7%94%A8kdj%E4%B8%8Evol%E9%87%8F%E7%AD%9B%E9%80%89%E5%8F%AF%E8%83%BD%E4%BC%9A%E6%B6%A8%E7%9A%84%E5%B8%81%E7%A7%8D',
        'document_sha256':'0611a3144361ae3b2a261a895c14741cdd10c25d3cea9f9bb857537f2f17c3e4',
        'code_sha256':'1628ae9e49e8e9603eb5608d3a048b7e78744a080861fdc14a0a0c2891fe7381',
        'publisher':313036,'end':1622160000000,'bet':10,'record_hours':1},
 4835: {'slug':'%E6%B5%8B%E8%AF%95-%E5%85%B3%E4%BA%8E%E9%A9%AC%E4%B8%81%E9%95%BF%E6%9C%9F%E6%95%88%E6%9E%9C',
        'document_sha256':'4fe2ea9964cd4c580b6c886597985508aca0b8b827898bb974031899de43b7f1',
        'code_sha256':'4f83acde521eae11b08255752eaea5e4ba8d6c8f28ff132c1e72a2bbc42681a5',
        'publisher':313486,'end':E,'bet':100,'record_hours':4},
}
ROOT='https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/'
WARM=('2020-10','2020-11','2020-12','2021-01','2021-02','2021-03','2021-04')
ACTIVE=('2021-05','2021-06','2021-07','2021-08','2021-09')
PACK={
 'swap':('klines','1h',WARM+ACTIVE,H),
 'index':('indexPriceKlines','1h',WARM+ACTIVE,H),
 'funding':('fundingRate','',ACTIVE,8*H),
 'fill4h':('klines','4h',WARM+ACTIVE,4*H),
 'fill1d':('klines','1d',WARM+ACTIVE,D),
}


def stage_market(pool):
    ai={(kind,m):pool.submit(archive,'BTC',cat,interval,m) for kind,(cat,interval,months,_) in PACK.items() for m in months}
    fq={kind:pool.submit(q,'BTC','swap' if kind.startswith('fill') else kind,'fill' if kind.startswith('fill') else 'feed',
          step if kind!='funding' else H,B,B+5*D) for kind,(_,_,_,step) in PACK.items()}
    result={}
    for kind,(_,_,months,step) in PACK.items():
        official=[ai[(kind,m)].result() for m in months]
        joined=[row for rows,_ in official for row in rows]
        if kind=='funding':
            direct=[[int(r[0]),*([scaled(r[2],100_000_000)]*4),0] for r in joined]
            assert all(r[1]=='8' for r in joined)
            assert all(abs(b[0]-a[0]-step)<2000 for a,b in zip(direct,direct[1:]))
        else:
            direct=[[int(r[0]),*[scaled(x,10) for x in r[1:5]],scaled(r[5],1000) if kind!='index' else 0] for r in joined]
            assert [p[0] for p in direct]==list(range(direct[0][0],direct[-1][0]+1,step))
        origin=direct[0][0]
        shape,ref=fq[kind].result()
        check={p[0]:p for p in direct}
        overlap=[x for x in shape['data'] if x[0] in check and x[0]<B+5*D]
        eq=sum(r==check[r[0]] for r in overlap)
        print(kind,len(direct),eq,len(overlap),flush=True)
        assert len(overlap)>=1 and eq==len(overlap),(kind,len(overlap),eq)
        direct=[x for x in direct if origin<=x[0]<=E+2*D]
        result[kind]={'schema':shape['schema'],'detail':shape['detail'],'data':direct,
                      'refs':{'fmz_overlap':ref,'exact_agreement':eq,'query_terminal_candle_excluded':True,'exchange':[r for _,r in official]}}
    return result


def digest_code(z,meta):
    url=ROOT+meta['slug']+'.md'
    name='strategies-'+unquote(url.split('/blob/')[1]); raw=z.read(name)
    text=raw.decode()
    [source]=re.findall(r'(?ms)^\x60{3}[ \t]*javascript[ \t]*\n(.*?)^\x60{3}',text)
    assert sha(raw)==meta['document_sha256'] and sha(source.encode())==meta['code_sha256']
    assert 'args: [["OpType",1]]' in source and 'basePeriod: 1h' in source and '"currency":"BTC_USDT"' in source
    when=re.search(r'(?m)^end: (.+)$',source)[1]
    assert int(datetime.fromisoformat(when).replace(tzinfo=timezone.utc).timestamp())*1000==meta['end']
    params={'MarginLevel':20,'amountScale':3,'priceScale':5,'bet':meta['bet'],'OpType':1}
    assert all(f'|{name}|{value}|' in text for name,value in params.items() if name!='OpType')
    return {**meta,'source':source,'url':url,'params':params}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('archive','author-cache','output'):
        p.add_argument('--'+k,type=Path,required=k in ('archive','output'))
    a=p.parse_args()
    with ZipFile(a.archive) as z:
        sources={str(k):digest_code(z,v) for k,v in ID_META.items()}
    published=form(313036,'MarginLevel',a.author_cache)
    assert all(published['args'][k]==v for k,v in sources['4834']['params'].items() if k!='OpType')
    sources['4834']['current_public_form']=published
    with ThreadPoolExecutor(max_workers=16) as pool:
        data=stage_market(pool)
    res={'source':sources,'market':data,'start':B,'end':E,'step_ms':H,'balance':10000,'fee_pct':[0.02,0.04]}
    b=gzip.compress((json.dumps(res,ensure_ascii=False,separators=(',',':'))+'\n').encode(),mtime=0)
    a.output.write_bytes(b)
    print(len(b),sha(b),flush=True)


if __name__=='__main__':
    main()
