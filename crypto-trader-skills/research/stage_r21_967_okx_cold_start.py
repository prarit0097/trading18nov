"""Prepare direct first-of-month dated OKEX captures for cold-start #967 feasibility."""

import csv
import gzip
import hashlib
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote
from urllib.request import Request,urlopen
from zipfile import ZipFile

from stage_r20_880_bitmex_sar import HashReader,sha,update_ohlc

ROOT=Path(__file__).resolve().parent.parent
SCRATCH=ROOT/"native-round11-scratch"
BOX=ROOT/"round3-native"
DAYS=("2020-02-01","2020-03-01")
SYMBOL="BTC-USD-200327"
US=1_000_000
STEP=900
HOUR=3600


def source_rows(day,kind,proof):
    url=f"https://datasets.tardis.dev/v1/okex-futures/{kind}/{day.replace('-','/')}/{SYMBOL}.csv.gz"
    req=Request(url,headers={"User-Agent":"Mozilla/5.0"})
    with urlopen(req,timeout=30) as res:
        stream=HashReader(res)
        length=int(res.headers["Content-Length"])
        assert res.status==200 and 0<length<35_000_000
        count=0
        previous=0
        with gzip.GzipFile(fileobj=stream) as gz,io.TextIOWrapper(gz,encoding="utf-8") as text:
            for row in csv.DictReader(text):
                assert row["exchange"]=="okex-futures" and row["symbol"]==SYMBOL
                local=int(row["local_timestamp"])
                assert local>=previous
                previous=local
                count+=1
                yield local,row
        assert stream.bytes==length
        proof.update(url=url,sha256=stream.sha.hexdigest(),bytes=length,rows=count,
                     last_local_us=previous)


def sampled(day,middle,limit,kind):
    timestamps=range(middle*US,limit*US+1,US)
    slots=[None]*len(timestamps)
    if kind=="trades":
        slots=[[] for _ in timestamps]
    proof={}
    bar_state={}
    funding_fields=0
    idx=0
    prev=None
    for local,row in source_rows(day,kind,proof):
        exchange_time=int(row["timestamp"])
        while idx<len(timestamps) and timestamps[idx]<local:
            if kind!="trades":
                slots[idx]=prev
            idx+=1
        if idx==len(timestamps):
            continue
        if kind=="quotes":
            quote=[local,exchange_time,float(row["bid_price"]),float(row["ask_price"]),
                   int(float(row["bid_amount"])),int(float(row["ask_amount"]))]
            # Serialized venue capture includes crossed reconnect states. Preserve them for the fill gate.
            prev=quote
        elif kind=="derivative_ticker":
            if row["funding_timestamp"] or row["funding_rate"]:
                funding_fields+=1
            if row["mark_price"]:
                prev=[local,exchange_time,float(row["mark_price"])]
        elif middle*US<=exchange_time<limit*US:
            stamp=exchange_time//US//STEP*STEP
            price=float(row["price"])
            changed=update_ohlc(bar_state.get(stamp),price)
            if changed!=bar_state.get(stamp):
                bar_state[stamp]=changed
                updates=slots[idx]
                if updates and updates[-1][0]==stamp:
                    updates[-1]=[stamp,*changed]
                else:
                    updates.append([stamp,*changed])
    assert idx==len(timestamps)
    proof.update(funding_field_events=funding_fields)
    if kind=="trades":
        proof.update(closed_interval_count=len(bar_state), first_closed=next(iter(bar_state.items())))
        assert list(range(middle,limit,STEP))==sorted(bar_state)
    else:
        assert all(s is not None for s in slots[60:])
    return slots,proof


def gather(day):
    middle=int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())
    limit=middle+20*HOUR
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures={k:pool.submit(sampled,day,middle,limit,k) for k in ("trades","quotes","derivative_ticker")}
        r={k:f.result() for k,f in futures.items()}
    packet={"start":middle,"end":limit,"interval_ms":1000,"symbol":SYMBOL,
            "data":{k:v[0] for k,v in r.items()},"proof":{k:v[1] for k,v in r.items()}}
    print(day,packet["proof"],flush=True)
    return packet


def main():
    authors=json.loads((SCRATCH/"r19-native-public-parameter-proofs.json").read_text(encoding="utf-8"))
    author=next(a for a in authors if a["id"]==967)
    assert author["args"]=={"Amount":1,"TradeInterval":2000,"PriceTick":0.5,"Symbol":"quarter","pd":45,"factor":3}
    link=author["archive_url"]
    with ZipFile(ROOT/"fmz.zip") as archive:
        raw=archive.read("strategies-"+unquote(link.split("/blob/",1)[1]))
    [source]=re.findall(r"(?ms)^\x60{3}[ \t]*javascript[ \t]*\n(.*?)^\x60{3}",raw.decode())
    assert sha(raw)==author["archive_sha256"] and sha(source.encode())==author["archive_source_sha256"]
    pack={"author":author,"source":source,"source_sha256":sha(source.encode()),
          "scopes":{day:gather(day) for day in DAYS}}
    raw=gzip.compress((json.dumps(pack,ensure_ascii=False,separators=(",",":"))+"\n").encode(),mtime=0)
    out=BOX/"round21-967-okx-cold-start.json.gz"
    with out.open("xb") as f:
        f.write(raw)
    print("compact packet",len(raw),sha(raw),flush=True)


if __name__=="__main__":
    main()
