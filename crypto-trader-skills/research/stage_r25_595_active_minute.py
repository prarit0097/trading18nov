"""Capture causal active one-minute market bars from Binance spot spot prints."""

import csv
import gzip
import hashlib
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,urlopen
from zipfile import ZipFile

from stage_r20_880_bitmex_sar import HashReader

ROOT=Path(__file__).resolve().parent.parent
BOX=ROOT/"round3-native"
FIL=ROOT/"round3-native-python/r25-5510-source-tape.json.gz"
SCOPES=[(coin,date) for coin in ("BTC","ETH") for date in ("2026-10-01","2026-11-01")]
US=1_000_000
WINDOW=3600


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def prepare(key):
    coin,day=key
    midnight=int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())
    start,end=midnight+7200,midnight+7200+WINDOW
    url=f"https://datasets.tardis.dev/v1/binance/trades/{day.replace('-','/')}/{coin}USDT.csv.gz"
    req=Request(url,headers={"User-Agent":"Mozilla/5.0"})
    last=None
    poll=start
    samples=[]
    current_minute=None
    min_price=None
    max_price=None
    first_known=None
    last_available=0
    seen=0
    with urlopen(req,timeout=30) as response:
        assert response.status==200
        size=int(response.headers["Content-Length"])
        market=HashReader(response)
        with gzip.GzipFile(fileobj=market) as gz,io.TextIOWrapper(gz,encoding="utf-8") as text:
            for row in csv.DictReader(text):
                local=int(row["local_timestamp"])
                exchange_time=int(row["timestamp"])
                assert row["exchange"]=="binance" and row["symbol"]==coin+"USDT"
                assert local>=last_available
                last_available=local
                while poll<end and poll*US<local:
                    assert last is not None
                    samples.append([poll,*last])
                    poll+=1
                if poll==end:
                    break
                minute=exchange_time//US//60*60
                p=float(row["price"])
                assert p>0
                if first_known is None:first_known=exchange_time
                min_price=p if min_price is None else min(min_price,p)
                max_price=p if max_price is None else max(max_price,p)
                if current_minute is None or minute>current_minute:
                    first=p
                    current_minute=minute
                elif minute<current_minute:
                    # Retain the latest currently open minute on a late prior-bar event.
                    continue
                last=[local,exchange_time,current_minute,first,p]
                seen+=1
    assert poll==end and len(samples)==WINDOW and max_price/min_price<2
    assert first_known//US<=start-60
    proof={"url":url,"compressed_prefix_sha256":market.sha.hexdigest(),
           "archive_bytes":size,"read_prefix_bytes":market.bytes,"trade_updates":seen,
           "max_price_ratio":max_price/min_price}
    return {"coin":coin,"day":day,"start":start,"end":end,"samples":samples,"proof":proof}


def main():
    spot=json.loads(gzip.decompress(FIL.read_bytes()))
    with ZipFile(ROOT/"fmz.zip") as z:
        member=next(m for m in z.namelist() if m.endswith("/MartinGale-Strategy1.md"))
        raw=z.read(member)
    assert sha(raw)=="8e9aa037c55342214a296da86931a4866083e122a8867c22e9e5adff4e2822ef"
    [source]=re.findall(r"(?ms)^\x60{3}[ \t]*javascript[ \t]*\n(.*?)^\x60{3}",raw.decode("utf-8-sig"))
    assert sha(source.encode())=="7a7471ae23a3f881ddfa5a23286dd8cdb78409b8301aac7c960957f19b0fe7ba"
    with ThreadPoolExecutor(max_workers=3) as executor:
        results=list(executor.map(prepare,SCOPES))
    job={"source":source,"source_sha256":sha(source.encode()),"archive_sha256":sha(raw),
         "archive":member,"filters":spot["filter_receipts"],"scopes":results}
    data=gzip.compress((json.dumps(job,separators=(",",":"),ensure_ascii=False)+"\n").encode(),mtime=0)
    out=BOX/"r25-595-binance-active-minute-job.json.gz"
    with out.open("xb") as f:f.write(data)
    for r in results:print(r["coin"],r["day"],r["proof"],flush=True)
    print("compact job",len(data),sha(data),flush=True)


if __name__=="__main__":
    main()
