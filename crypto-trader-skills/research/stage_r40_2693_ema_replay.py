"""Bind #2693 archived defaults and dated ETHUSDT recorded books, trades and warm hours."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import re
from urllib.parse import unquote
from zipfile import ZipFile

from fmz_native_round20_880_capture import request,sha
from stage_r29_4685_native import archive
from stage_r34_btc_random_book import sample_start
from stage_r37_5774_eth_book import funding, sampling
from stage_r39_5153_trade_tape import Capture,fixed

DAYS=('2025-01-01','2025-04-01')
HOUR=3_600_000
WARM=5000
PIN='e40d96585ace49f4a7e94b97049f22a51b69818809802d01ffd95f22003605aa'
PARAMS='8deb71908f128187b14ba0b9c47ef25082f262f9143a04cee9f40bf5c4692c13'
BOOK_MODES=('quotes','derivative_ticker','book_snapshot_5')


def get_source(catalog,path,page):
    [row]=[r for r in json.loads(catalog.read_bytes())['disposition'] if r['id']==2693]
    with ZipFile(path) as archive_file:
        archived=archive_file.read('strategies-'+unquote(row['source'].split('/blob/')[1]))
    assert row['pinned_document_sha256']==PIN==sha(archived)
    [src]=re.findall(r'(?ms)^`{3}[ \t]*javascript[ \t]*\n(.*?)^`{3}',archived.decode())
    form=page.read_bytes();assert sha(form)==PARAMS
    hit=re.search(r'\[\[([\\]+")targetProfit',form.decode());assert hit
    last=form.decode().index(']]',hit.start())+2
    records=json.loads(form.decode()[hit.start():last].replace(hit[1],'"'))
    author_args={f[0]:f[3] for f in records}
    overrides=dict(json.loads(re.search(r'(?m)^args: (.+)$',src)[1]))
    assert overrides=={'targetProfit':20,'amount':20,'amountPrecision':3,'isAmountForUSDT':True}
    assert '"currency":"ETH_USDT"' in src and 'basePeriod: 1m' in src and 'period: 1h' in src
    assert all(name in author_args for name in overrides)
    settings={**author_args,**overrides}
    return row['source'],src,settings,overrides


def market_trades(day,spec):
    from_ms,to_ms=sample_start(day)
    u=f"https://datasets.tardis.dev/v1/binance-futures/trades/{day.replace('-','/')}/ETHUSDT.csv.gz"
    accepted=[]
    rows=prior=clock_adjust=0
    with request(u) as response:
        length=int(response.headers['Content-Length']); assert 10_000<length<=70_000_000
        stream=Capture(response)
        with gzip.GzipFile(fileobj=stream) as f:
            assert f.readline().strip().split(b',')==[b'exchange',b'symbol',b'timestamp',b'local_timestamp',b'id',b'side',b'price',b'amount']
            for line in f:
                e,s,venue,seen,num,side,px,n=line.strip().split(b',')
                assert e==b'binance-futures' and s==b'ETHUSDT' and side in (b'buy',b'sell')
                recv,ex=int(seen),int(venue)
                assert recv>=prior;prior=recv;rows+=1
                safe=max(recv,ex)
                if from_ms*1000<safe<=to_ms*1000:
                    clock_adjust+=ex>recv
                    accepted.append([safe,int(num),fixed(px,2),fixed(n,3),int(side==b'buy'),ex,recv])
        assert stream.length==length
    accepted.sort(key=lambda x:(x[0],x[1]))
    assert len(accepted)>10_000 and len({x[1] for x in accepted})==len(accepted)
    assert all(x[2]>0 and x[3]>0 for x in accepted)
    return accepted,{'url':u,'sha256':stream.digest.hexdigest(),'daily_rows':rows,'capture_scope_rows':len(accepted),
                     'venue_clock_after_local_rows':clock_adjust,'raw_bytes':length}


def warm_months(day):
    a,b=sample_start(day)
    start=datetime.fromtimestamp((a-WARM*HOUR)/1000,timezone.utc)
    end=datetime.fromtimestamp(b/1000,timezone.utc)
    ids=range(start.year*12+start.month-1,end.year*12+end.month)
    return [f'{j//12:04}-{j%12+1:02}' for j in ids]


def source_hourly(begin,end,cache,months):
    combined=[];checks=[]
    for m in months:
        r,p=cache[m].result();combined.extend(r);checks.append(p)
    lookup={int(line[0]):line for line in combined}
    hours=[]
    for t in range(begin-WARM*HOUR,end,HOUR):
        r=lookup[t];assert int(r[6])==t+HOUR-1
        hours.append([t,*[float(v) for v in r[1:6]]])
    assert len(hours)==WARM+(end-begin)//HOUR
    return hours,checks


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('catalog','archive','author','output'):
        p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    url,src,args,overrides=get_source(a.catalog,a.archive,a.author)
    all_months=sorted(set(v for d in DAYS for v in warm_months(d)))
    scopes={}
    with ThreadPoolExecutor(max_workers=12) as pool:
        hours={m:pool.submit(archive,'ETH','klines','1h',m) for m in all_months}
        files={(d,k):pool.submit(sampling,d,k) for d in DAYS for k in BOOK_MODES}
        flow={d:pool.submit(market_trades,d,{} ) for d in DAYS}
        for day in DAYS:
            a0,a1=sample_start(day)
            bars,check=source_hourly(a0,a1,hours,warm_months(day))
            q,qp=files[day,'quotes'].result();m,mp=files[day,'derivative_ticker'].result()
            b,bp=files[day,'book_snapshot_5'].result();t,tp=flow[day].result()
            assert len(q)==len(m)==len(b)==72_001
            assert all(x[2:6]==[s[3][0][0],s[2][0][0],s[3][0][1],s[2][0][1]] for x,s in zip(q,b,strict=True))
            scopes[day]={'begin_ms':a0,'end_ms':a1,'quotes':q,'marks':m,'depth':b,'tape':t,'bars':bars,
                 'funding':funding(day,m),'proof':{'archive_hourly':check,'quotes':qp,'derivative_ticker':mp,
                   'depth':bp,'flow':tp,'exact_BBO_binding':len(b)}}
            print(day,len(t),len(bars),scopes[day]['funding']['rate'],flush=True)
    job={'source':src,'source_sha256':sha(src.encode()),'document_sha256':PIN,'url':url,'author_form_sha256':PARAMS,
         'author_args_with_overrides':args,'archived_overrides':overrides,'initial_cash_USDT':10000,'fees_pct':[0.02,0.04],
         'opening_notional_minimum_USDT':20,'scope':scopes,'native_warm_hours':WARM}
    packed=gzip.compress(json.dumps(job,ensure_ascii=False,separators=(',',':')).encode(),compresslevel=6,mtime=0)
    a.output.write_bytes(packed)
    print(len(packed),sha(packed),flush=True)


if __name__=='__main__':main()
