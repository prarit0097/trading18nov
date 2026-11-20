"""Collect compact, causal BitMEX inverse SAR replay inputs from public captures."""

import csv
import gzip
import hashlib
import io
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, unquote
from urllib.request import Request, urlopen
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent.parent
SCRATCH = ROOT / "native-round11-scratch"
SANDBOX = ROOT / "round3-native"
DAYS = ("2020-02-01","2020-08-01")
HOUR = 3600
DAY = HOUR * 24
US = 1_000_000
LIMIT = 50_000_000
SOURCE = "https://datasets.tardis.dev/v1/bitmex"
FMZ = "https://q.fmz.com/data/history"
USER_AGENT = {"User-Agent":"Mozilla/5.0"}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def request(url):
    return urlopen(Request(url,headers=USER_AGENT),timeout=25)


class HashReader:
    def __init__(self, response):
        self.response = response
        self.sha = hashlib.sha256()
        self.bytes = 0

    def read(self,size):
        data = self.response.read(size)
        self.bytes += len(data)
        assert self.bytes <= LIMIT
        self.sha.update(data)
        return data


def capture_file(day,label,proof):
    url = f"{SOURCE}/{label}/{day.replace('-','/')}/XBTUSD.csv.gz"
    proof.update(url=url,dataset=label)
    with request(url) as response:
        length = int(response.headers["Content-Length"])
        assert response.status == 200 and length <= LIMIT
        stream = HashReader(response)
        first = previous = 0
        max_gap = count = 0
        with gzip.GzipFile(fileobj=stream) as gz, io.TextIOWrapper(gz,encoding="utf-8") as src:
            for row in csv.DictReader(src):
                assert row["exchange"] == "bitmex" and row["symbol"] == "XBTUSD"
                current = int(row["local_timestamp"])
                assert current >= previous
                if not first:
                    first = current
                if previous:
                    max_gap = max(max_gap,current-previous)
                previous = current
                count += 1
                yield current,row
        assert stream.bytes == length
        proof.update(bytes=length,sha256=stream.sha.hexdigest(),rows=count,
                     first_local_us=first,last_local_us=previous,max_gap_us=max_gap)


def q(day, bars, symbol="XBT_USD.swap", section="feed", step=DAY):
    params = {"eid":"Futures_BitMEX","symbol":symbol,"event":section,
              "period":step*1000,"from":day,"to":day+step*(bars-1)}
    url = FMZ + "?" + urlencode(params)
    with request(url) as response:
        raw = response.read(300_001)
        assert response.status == 200 and len(raw) <= 300_000
    rows = json.loads(raw)
    if isinstance(rows,dict):
        rows = rows["data"]
    return rows,{"url":url,"sha256":sha(raw),"bytes":len(raw),"rows":len(rows)}


def update_ohlc(ohlc,price):
    if ohlc is None:
        return [price,price,price,price]
    return [ohlc[0],max(ohlc[1],price),min(ohlc[2],price),price]


def sample(day, mid, begin, end, label):
    chosen = list(range(begin * US, end * US + 1, 5 * US))
    idx = 0
    states = []
    prior = None
    proof = {}
    exchange_hours = {}
    total = None
    funding = []
    for local,row in capture_file(day,label,proof):
        if idx < len(chosen) and local > chosen[idx]:
            assert prior is not None
            while idx < len(chosen) and local > chosen[idx]:
                states.append(prior)
                idx += 1
        exchange_time = int(row["timestamp"])
        if label == "trades":
            if exchange_time >= mid * US and exchange_time < (mid+DAY) * US:
                price = float(row["price"])
                hour = exchange_time//US//HOUR*HOUR
                exchange_hours[hour] = update_ohlc(exchange_hours.get(hour),price)
                total = update_ohlc(total,price)
                prior = [local,exchange_time,*total]
        elif label == "quotes":
            values = [float(row[k]) for k in ("bid_price","ask_price","bid_amount","ask_amount")]
            assert values[0] < values[1] and min(values)>0
            prior = [local,exchange_time,*values]
        else:
            if row["mark_price"] and row["last_price"] and row["funding_timestamp"] and row["funding_rate"]:
                values = [float(row[k]) for k in ("mark_price","index_price","last_price")]
                f_time = int(row["funding_timestamp"])
                f_rate = row["funding_rate"]
                prior = [local,exchange_time,*values,f_time,f_rate]
                if abs(exchange_time-(mid+4*HOUR)*US) <= 10*US:
                    funding.append(prior)
    assert idx == len(chosen) == 5761
    result = {"sample_rows":states,"provider":proof}
    if label == "trades":
        assert len(exchange_hours)==24 and total
        result.update(daily=total,hourly=exchange_hours)
    elif label == "derivative_ticker":
        result.update(funding_near_settlement=funding)
    return result


def gather(day):
    mid = int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())
    begin,end = mid+2*HOUR,mid+10*HOUR
    with ThreadPoolExecutor(max_workers=3) as pool:
        partials = {
            label:pool.submit(sample,day,mid,begin,end,label)
            for label in ("trades","quotes","derivative_ticker")
        }
        pieces = {label:v.result() for label,v in partials.items()}
    daily_near,qdproof=q(mid-DAY,3)
    hourly_near,qhproof=q(mid,24,step=HOUR)
    fmz_hold = [q(mid-1000*DAY+i*DAY,min(300,1000-i)) for i in range(0,1000,300)]
    bars = {bar[0]:bar[1:] for part,_ in fmz_hold for bar in part}
    by_date = {
        "begin":begin,"end":end,"today":mid,
        "captures":{label:packet["provider"] for label,packet in pieces.items()},
        "daily_exchange":pieces["trades"]["daily"],
        "hourly_exchange":pieces["trades"]["hourly"],
        "daily_fmz_near":daily_near,
        "hourly_fmz_near":hourly_near,
        "fmz_history_rows":[[stamp,*v] for stamp,v in sorted(bars.items())],
        "fmz_history_references":[qdproof,qhproof,*[proof for _,proof in fmz_hold]],
        "funding_near_settlement":pieces["derivative_ticker"]["funding_near_settlement"],
        "samples":[
            [t,*trade,*quote,*deriv]
            for t,trade,quote,deriv in zip(range(begin,end+1,5),*(pieces[k]["sample_rows"] for k in ("trades","quotes","derivative_ticker")),strict=True)
        ],
    }
    print(day,"market OHLC",by_date["daily_exchange"],"FMZ",daily_near,
        "warm bars",len(bars),"funding observations",len(by_date["funding_near_settlement"]), flush=True)
    for shift in (-2,-1,0,1,2):
        matches = sum(1 for qh in hourly_near if qh[1:5] == by_date["hourly_exchange"].get(qh[0]+shift*HOUR))
        if matches:
            print(day,"hourly shift",shift,"exact matches",matches,flush=True)
    return by_date


def main():
    all_authors=json.loads((SCRATCH/"r19-native-public-parameter-proofs.json").read_text(encoding="utf-8"))
    author=next(x for x in all_authors if x["id"]==880)
    url=author["archive_url"]
    with ZipFile(ROOT/"fmz.zip") as archive:
        raw=archive.read("strategies-"+unquote(url.split("/blob/",1)[1]))
    import re
    [code]=re.findall(r"(?ms)^\x60{3}[ \t]*javascript[ \t]*\n(.*?)^\x60{3}",raw.decode())
    assert sha(raw)==author["archive_sha256"] and sha(code.encode())==author["archive_source_sha256"]
    scenarios={day:gather(day) for day in DAYS}
    job={
        "source":code,"source_sha256":sha(code.encode()),"author":author,
        "scenarios":scenarios,
    }
    packed=gzip.compress((json.dumps(job,ensure_ascii=False,separators=(",",":"))+"\n").encode(),mtime=0)
    out=SANDBOX/"round20-xbtusd-sar-tape.json.gz"
    with out.open("xb") as f:
        f.write(packed)
    print(out,len(packed),sha(packed))


if __name__=="__main__":
    main()
