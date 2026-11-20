"""Stage pinned BTC/ETH minute scopes and Binance spot order constraints for #5510."""

import csv
import gzip
import hashlib
import io
import json
import re
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote, unquote
from urllib.request import Request,urlopen
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parent.parent
BOX=ROOT/"round3-native-python"
WORK=ROOT/"nonpine"/"binance"
D=Decimal
IST=timezone(timedelta(hours=5,minutes=30))
SCOPES=(("2026-09-23","2026-10-21"),("2026-10-21","2026-11-04"))
COINS=("BTC","ETH")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def timestamp(text):
    return int(datetime.fromisoformat(text).replace(tzinfo=IST).timestamp())*1_000_000


def filters():
    target="/api/v3/exchangeInfo?symbols="+quote('["BTCUSDT","ETHUSDT"]')
    sources=("https://data-api.binance.vision","https://api.binance.com")
    records=[]
    for host in sources:
        url=host+target
        with urlopen(Request(url,headers={"User-Agent":"Mozilla/5.0"}),timeout=20) as response:
            raw=response.read(70_001)
            assert response.status==200 and len(raw)<=70_000
        body=json.loads(raw)
        selected={}
        for info in body["symbols"]:
            symbol=info["symbol"]
            assert symbol in {c+"USDT" for c in COINS}
            k=next(x for x in info["filters"] if x["filterType"]=="NOTIONAL")
            assert D(k["minNotional"])==D(5) and k["applyMinToMarket"] and k["avgPriceMins"]==5
            assert info["quoteAsset"]=="USDT" and info["quoteOrderQtyMarketAllowed"] and "MARKET" in info["orderTypes"]
            selected[symbol]={"min_notional":k["minNotional"],"avg_price_minutes":k["avgPriceMins"],
                              "markets_allowed":info["quoteOrderQtyMarketAllowed"],
                              "quote_asset":info["quoteAsset"],"apply_min_to_market":k["applyMinToMarket"]}
        records.append({"url":url,"response_sha256":sha(raw),"filter":selected, "server_time":body.get("serverTime")})
    assert records[0]["filter"]==records[1]["filter"]
    return records


def tape(coin):
    origin=json.loads((WORK/"manifest.json").read_bytes())
    bundle={}
    proofs=[]
    sat=60_000_000
    start=timestamp(SCOPES[0][0])-sat*5
    end=timestamp(SCOPES[-1][-1])
    for file in sorted(WORK.glob(f"klines-spot-{coin}USDT-1m-2026-*.zip")):
        if "-08." in file.name:
            continue
        raw=file.read_bytes()
        known=origin[file.name]
        assert sha(raw)==known["sha256_or_error"]
        proofs.append(known)
        with ZipFile(io.BytesIO(raw)) as archive:
            [member]=archive.namelist()
            with archive.open(member) as stream:
                for row in csv.reader(io.TextIOWrapper(stream,encoding="ascii")):
                    at=int(row[0])
                    if start<=at<end:
                        assert len(row[0])==16 and int(row[6])==at+sat-1
                        assert at not in bundle
                        _,op,hi,lo,cl,volume=row[:6]
                        low,high,close=map(D,(lo,hi,cl))
                        assert D(0)<low<=D(op)<=high and low<=close<=high and D(volume)>0
                        bundle[at]=(lo,hi,cl)
    assert len(proofs)==6
    assert sorted(bundle)==list(range(start,end,sat))
    scopes=[]
    for begin,end in SCOPES:
        first,last=timestamp(begin),timestamp(end)
        covered=[bundle[t] for t in range(first-sat*5,last,sat)]
        low=min(D(p[0]) for p in covered)
        high=max(D(p[1]) for p in covered)
        assert low>0 and high/low<D(2)
        prices=[bundle[t-sat][2] for t in range(first,last,sat)]
        scopes.append({"coin":coin,"begin_ms":first//1000,"end_ms":last//1000,
                       "begin_ist":begin,"end_ist":end,"price":prices,"source_intervals":len(covered),
                       "low":str(low),"high":str(high),"max_notional_bound":str(high/low)})
    return scopes,proofs


def main():
    path=ROOT/"native-round11-scratch"/"r25-5510-source-job.json"
    if path.exists():
        source=json.loads(path.read_bytes())
    else:
        with ZipFile(ROOT/"fmz.zip") as source_zip:
            member=next(m for m in source_zip.namelist() if m.endswith("/追涨杀跌.md"))
            raw=source_zip.read(member)
        assert sha(raw)=="3f73ed3e345e468c47499d22776ea6486b03d9223e6cecbcd30cb43547d986d1"
        text=raw.decode("utf-8-sig")
        assert "|PERIOD|60|" in text and "|LENGTH|1440|" in text
        [code]=re.findall(r"(?ms)^\x60{3}[ \t]*python[ \t]*\n(.*?)^\x60{3}",text)
        assert sha(code.encode())=="be44e1fc60b138cd1ae07a4150361e1692685852e8860470a76f13cac3a378ab"
        source={"code":code,"archive":member,"archive_sha256":sha(raw),"code_sha256":sha(code.encode()),
                "parameter_origin":"Pinned archive public table","args":{"PERIOD":60,"LENGTH":1440}}
    receipts=filters()
    all_scopes=[]
    market_proof={}
    for coin in COINS:
        scopes,proof=tape(coin)
        all_scopes.extend(scopes)
        market_proof[coin]=proof
    result={**source,"filter_receipts":receipts,"market":market_proof,"scopes":all_scopes}
    raw=gzip.compress((json.dumps(result,separators=(",",":"),ensure_ascii=False)+"\n").encode(),mtime=0)
    out=BOX/"r25-5510-source-tape.json.gz"
    with out.open("xb") as file:file.write(raw)
    print(sha(raw),len(raw),[(t["coin"],t["begin_ist"],len(t["price"]),t["max_notional_bound"]) for t in all_scopes])


if __name__=="__main__":
    main()
