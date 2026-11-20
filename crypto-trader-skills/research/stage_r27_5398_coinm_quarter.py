"""Stage a source-bound #5398 ETH inverse quarterly benchmark."""

import argparse
import csv
import gzip
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from fmz_native_round20_880_capture import HashReader,request,sha,update_ohlc

HOUR=3600
US=1_000_000
SYMBOL="ETHUSD_211231"
VENUE="binance-delivery"
DAYS=("2021-10-01","2021-11-01","2021-12-01")
MONTHS=("2021-09","2021-10","2021-11")
AGE_MAX=2*US
DEPTH_HORIZON=100_000
START_MIN=5
END_MIN=23*60+55
FEE="0.0005"
SOURCE_URL=("https://github.com/fmzquant/strategies/blob/7853bb2bf262c4567ac238d3552d97f0e50cb801/"
            "%E8%B6%8B%E5%8A%BF%E7%AD%96%E7%95%A5V10-%E5%85%AC%E5%BC%80.md")
AUTHOR_URL="https://www.fmz.com/strategy/320782"
DOC_SHA="ffc973c03f536251fc7ff52a53e27ac9fb724f71e5247e7602f3619ff30545df"
CODE_SHA="f1eeff31165a5d012bdae4b629237b191c0517d0ab1c24177d605220ffabc90d"


def moment(d):
    return int(datetime.fromisoformat(d).replace(tzinfo=timezone.utc).timestamp())


def bytes_at(url,limit):
    with request(url) as res:
        data=res.read(limit+1)
        assert res.status==200 and len(data)<=limit
    return data


def author(cache):
    raw=cache.read_bytes() if cache else bytes_at(AUTHOR_URL,1_500_000)
    text=raw.decode()
    start=re.search(r'\[\[(\\+")TradeCurrency',text)
    end=text.index(']]',start.start())+2
    args=json.loads(text[start.start():end].replace(start[1],'"'))
    settings={r[0]:r[3] for r in args if not r[0].startswith('$$$__cmd__')}
    assert len(settings)==29 and settings["MarginLevel"]==5 and settings["AmountPrecision"]==0
    return {"url":AUTHOR_URL,"html_sha256":sha(raw),"settings":settings}


def binance(grain,kind,interval,date):
    name=f"{SYMBOL}-{interval}-{date}.zip"
    root="https://data.binance.vision/data/futures/cm"
    url=f"{root}/{grain}/{kind}/{SYMBOL}/{interval}/{name}"
    check = bytes_at(url+".CHECKSUM",200)
    digest, named=check.decode().split()
    assert named==name
    raw=bytes_at(url,600_000)
    assert sha(raw)==digest
    with ZipFile(io.BytesIO(raw)) as zipped:
        [inside]=zipped.namelist()
        with zipped.open(inside) as f:
            lines=csv.reader(io.TextIOWrapper(f,encoding="utf-8"))
            result=[]
            for line in lines:
                if not line[0].isdigit():
                    continue
                result.append([int(line[0])//1000,*map(float,line[1:6])])
    return result,{"url":url,"sha256":digest,"checksum_url":url+".CHECKSUM","rows":len(result)}


def ticks(day,kind,proof):
    url=f"https://datasets.tardis.dev/v1/{VENUE}/{kind}/{day.replace('-','/')}/{SYMBOL}.csv.gz"
    with request(url) as response:
        size=int(response.headers['Content-Length'])
        assert response.status==200 and 0<size<=30_000_000
        streamed=HashReader(response)
        count=prev=first=0
        with gzip.GzipFile(fileobj=streamed) as gz,io.TextIOWrapper(gz,encoding="utf-8") as f:
            for row in csv.DictReader(f):
                assert row["exchange"]==VENUE and row["symbol"]==SYMBOL
                local=int(row["local_timestamp"])
                ex=int(row["timestamp"])
                assert local>=prev
                prev=local
                first=first or local
                count+=1
                yield local,ex,row
        assert streamed.bytes==size
    proof.update(url=url,sha256=streamed.sha.hexdigest(),bytes=size,rows=count,first_us=first,last_us=prev)


def trade_states(day,clock):
    proof={}; out=[]; current=None; bars={}; ranges={}; i=0
    for local,ex,row in ticks(day,"trades",proof):
        while i<len(clock) and local>clock[i]*US:
            assert current and max(current[:2])<=clock[i]*US
            out.append(current); i+=1
        p=float(row["price"])
        v=int(float(row["amount"]))
        stamp=ex//(HOUR*US)*HOUR
        ranges[stamp]=update_ohlc(ranges.get(stamp),p)
        bars[stamp]=bars.get(stamp,0)+v
        if not current or stamp>current[2]:
            current=[local,ex,stamp,p,p,p,p,v]
        elif stamp==current[2]:
            current=[local,ex,stamp,*update_ohlc(current[3:7],p),current[7]+v]
    assert len(out)==len(clock)
    return out,proof,[[t,*h,bars[t]] for t,h in sorted(ranges.items())]


def quote_states(day,clock):
    proof={}; out=[]; prior=None; item=None; i=0
    for local,ex,row in ticks(day,"quotes",proof):
        while i<len(clock) and local>clock[i]*US+DEPTH_HORIZON:
            assert prior is not None
            out.append(item or [*prior,prior[4],prior[5],True,True,0]); i+=1; item=None
        if not row['bid_price'] or not row['ask_price']:
            continue
        q=[local,ex,float(row['bid_price']),float(row['ask_price']),int(float(row['bid_amount'])),int(float(row['ask_amount']))]
        if i<len(clock) and local>clock[i]*US:
            assert prior is not None
            if item is None:
                item=[*prior,prior[4],prior[5],True,True,0]
            item[6]=min(item[6],q[4]); item[7]=min(item[7],q[5]); item[8] &= q[2]==item[2]; item[9] &= q[3]==item[3]; item[10]+=1
        prior=q
    assert len(out)==len(clock)
    return out,proof


def mark_states(day,clock):
    proof={}; out=[]; prior=None; i=0; funding=0
    for local,ex,row in ticks(day,"derivative_ticker",proof):
        while i<len(clock) and local>clock[i]*US:
            assert prior and max(prior[:2])<=clock[i]*US
            out.append(prior); i+=1
        funding+=bool(row.get('funding_timestamp') or row.get('funding_rate'))
        if row['mark_price']:
            prior=[local,ex,float(row['mark_price'])]
    assert len(out)==len(clock) and funding==0
    proof['populated_funding_events']=funding
    return out,proof


def scenario(day,old,old_refs,pool):
    day0=moment(day)
    clock=list(range(day0+START_MIN*60,day0+END_MIN*60+1,5))
    tasks={kind:pool.submit(f,day,clock) for kind,f in (("trade",trade_states),("quote",quote_states),("mark",mark_states))}
    mark_min,p=binance("daily","markPriceKlines","1m",day)
    trade_hour,pt=binance("daily","klines","1h",day)
    trade,rt,totals=tasks['trade'].result(); quote,rq=tasks['quote'].result(); mark,rm=tasks['mark'].result()
    actual={r[0]:r[1:] for r in totals}
    op=sum(r[1:5]==actual[r[0]][:4] for r in trade_hour if r[0] in actual)
    cl=sum(r[4]==actual[r[0]][3] for r in trade_hour if r[0] in actual)
    assert len(trade_hour)==24 and len(mark_min)==1440 and len(actual)==24
    assert cl>=23
    ref_mark={r[0]:r for r in mark_min}
    mark_cross=sum(ref_mark[(q[0]//US//60)*60][3]<=q[2]<=ref_mark[(q[0]//US//60)*60][2] for q in mark)
    assert mark_cross/len(mark)>0.99
    seed=[r for r in old if r[0]<day0][-500:]
    assert len(seed)>=120 and seed[-1][0]==day0-HOUR
    assert all(b[0]-a[0]==HOUR for a,b in zip(seed,seed[1:]))
    print(day,len(seed),len(clock),'OHLC',op,'close',cl,'mark range',mark_cross,flush=True)
    return {"start":clock[0],"end":clock[-1],"history":seed,"ohlc_tape_check":{"hourly_rows":len(trade_hour),"exact_ohlc":op,"exact_close":cl,"in_minute_mark_bounds":mark_cross},
            "historical_bars":old_refs,"official_trade_hour":pt,"official_mark_minute":p,"direct_market":{"trades":rt,"quotes":rq,"derivative_ticker":rm},
            "day_official_hourly":trade_hour,"tardis_day_aggregates":totals,
            "samples":[[t,a,b,c] for t,a,b,c in zip(clock,trade,quote,mark,strict=True)]}


def main():
    parse=argparse.ArgumentParser(description=__doc__)
    parse.add_argument('--archive',type=Path,required=True)
    parse.add_argument('--author-page',type=Path)
    parse.add_argument('--output',type=Path,required=True)
    args=parse.parse_args()
    path='strategies-'+unquote(SOURCE_URL.split('/blob/')[1])
    with ZipFile(args.archive) as z:
        md=z.read(path)
    [code]=re.findall(r'(?ms)^\x60{3}[ \t]*javascript[ \t]*\n(.*?)^\x60{3}',md.decode())
    assert sha(md)==DOC_SHA and sha(code.encode())==CODE_SHA
    cfg=author(args.author_page)
    with ThreadPoolExecutor(max_workers=8) as pool:
        month=list(pool.map(lambda m:binance('monthly','klines','1h',m),MONTHS))
        hist=sorted(r for part,_ in month for r in part)
        scenarios={d:scenario(d,hist,[p for _,p in month],pool) for d in DAYS}
    job={"source":code,"source_sha256":CODE_SHA,"document_sha256":DOC_SHA,"source_url":SOURCE_URL,
        "author":cfg,"symbol":SYMBOL,"fee":FEE,"starting_cash_eth":"0.02","scope":scenarios,
        "age_max_us":AGE_MAX,"depth_horizon_us":DEPTH_HORIZON,"date_range":"Three predeclared first-of-month days, 00:05–23:55 UTC"}
    out=gzip.compress((json.dumps(job,ensure_ascii=False,separators=(',',':'))+'\n').encode(),mtime=0)
    args.output.write_bytes(out)
    print(len(out),sha(out),flush=True)


if __name__=="__main__":
    main()
