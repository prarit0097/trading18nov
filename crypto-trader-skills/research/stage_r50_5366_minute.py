"""Bind the public minute EMA research variant to Binance USD-M venue archives."""
import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
import csv
from decimal import Decimal as D
import io
import json
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from fmz_native_round20_880_capture import sha
from stage_r47_4417_butterfly import get

PART4='https://www.fmz.com/digest-topic/5430'
NOTE='https://www.fmz.com/upload/asset/1e5d2f766d2b7db9709.ipynb'
AUTHOR='https://www.fmz.com/upload/asset/2b1fa7ab641385067ad.csv'
MARKET='https://data.binance.vision/data/futures/um/monthly/klines'
MONTHS=('2020-02','2020-03','2020-04')


def matches(a,b):
    return abs(a-b)<=max(D('1e-12'),abs(a)*D('1e-12'))


def bind(symbol,source):
    times={int(x['']):D(x[symbol]) for x in source if x[symbol]}
    remaining=set(times)
    missing=[]
    outside=[]
    proof=[]
    exact=0
    for month in MONTHS:
        label=f'{symbol}USDT-1m-{month}.zip'
        url=f'{MARKET}/{symbol}USDT/1m/{label}'
        checksum,confirmed=get(url+'.CHECKSUM',200).decode().split()
        raw=get(url,9_000_000)
        assert label==confirmed and sha(raw)==checksum
        with ZipFile(io.BytesIO(raw)) as archive:
            [name]=archive.namelist()
            with archive.open(name) as f:
                for bar in csv.reader(io.TextIOWrapper(f,encoding='utf-8')):
                    if not bar[0].isdigit():continue
                    t=int(bar[0])
                    if t not in remaining:continue
                    remaining.remove(t)
                    author=times[t]
                    close=D(bar[4])
                    if matches(author,close):
                        exact+=1
                    else:
                        item={'utc_bar_ms':t,'original':str(author),'official':str(close),
                              'official_high':bar[2],'official_low':bar[3]}
                        missing.append(item)
                        if not D(bar[3])-D('1e-10')<=author<=D(bar[2])+D('1e-10'):
                            outside.append(item)
        proof.append({'url':url,'verified_sha256':checksum})
    assert not remaining,(symbol,len(remaining))
    assert exact+len(missing)==len(times)
    return {'symbol':symbol,'first_bar_ms':min(times),'last_bar_ms':max(times),'checked':len(times),
            'matching_closed_prices':exact,'different_observations':missing,'outside_official_candle':outside,'checksums':proof}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('catalog','archive','notebook','csv','output'):
        p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    [scope]=[r for r in json.loads(a.catalog.read_bytes())['disposition'] if r['id']==5366]
    with ZipFile(a.archive) as arc:
        doc=arc.read('strategies-'+unquote(scope['source'].split('/blob/')[1]))
    assert sha(doc)==scope['pinned_document_sha256']
    text=doc.decode()
    assert all(w in text for w in ('https://www.fmz.com/bbs-topic/5364','Alpha = 0.001','Update_base_price_time_interval = 60','Max_diff = 0.4'))
    nb=a.notebook.read_bytes();assert sha(nb)=='374cabdfbbc6aa93fa865c95f3dc14bc728837741e3196bf99c7ca5c56799716'
    content=json.loads(nb)['cells']
    active={k:''.join(content[k]['source']) for k in (2,4,5,6,8)}
    assert AUTHOR in active[4] and 'Alpha = 0.001' in active[8] and 'price_usdt.iloc[-7500:]' in active[8]
    assert 'commission=0.00075' in active[8] and 'trade_value = 300' in active[8]
    [symbols]=ast.parse(active[2]).body;chosen=ast.literal_eval(symbols.value)
    assert 'BTC' in chosen and 'ETH' in chosen and len(chosen)==24
    raw=a.csv.read_bytes();assert sha(raw)=='9db1aa6eb7cd07ce9128ab946e636343752dce60879d5453346bd17c1d5efa86'
    lines=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    assert len(lines)==77160 and sorted(set(lines[0])- {''})==sorted(chosen)
    assert all(int(b[''])-int(c[''])==60000 for c,b in zip(lines,lines[1:]))
    with ThreadPoolExecutor(max_workers=8) as pool:
        pending={s:pool.submit(bind,s,lines) for s in sorted(chosen)}
        markets=[]
        for s,work in pending.items():
            c=work.result();markets.append(c)
            print(s,c['checked'],c['matching_closed_prices'],len(c['different_observations']),len(c['outside_official_candle']),flush=True)
    out={'source':{'archive_url':scope['source'],'archive_sha256':sha(doc),'publisher':'https://www.fmz.com/strategy/196784',
                   'linked_predecessor_article':'https://www.fmz.com/bbs-topic/5364','author_minute_research':PART4,
                   'notebook_url':NOTE,'notebook_sha256':sha(nb),'source_cells':{str(k):sha(v.encode()) for k,v in active.items()},
                   'csv_url':AUTHOR,'csv_sha256':sha(raw)},'data':markets,'full_warm_rows':len(lines),
         'signal_rows':7500,'native_market':'Binance USD-M BTC and ETH perpetuals within full 24-symbol basket'}
    a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(sha(a.output.read_bytes()),sum(x['matching_closed_prices'] for x in markets),flush=True)


if __name__=='__main__':main()
