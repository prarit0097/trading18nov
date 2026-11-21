"""Stage recorded Binance spot event feeds for the #5091 compatibility replay."""
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
import gzip
import hashlib
import json
import re
import sys

document,root=map(Path,sys.argv[1:3])
date=sys.argv[3]
assert date in ("2026-10-01","2026-11-19")
raw=document.read_bytes()
digest=hashlib.sha256(raw).hexdigest()
expected="39a88ca1b1bd6671eff96af5dc47100140298e3de56da9bb715999b34b991a7c"
assert digest==expected
fence=chr(96)*3
(source,)=re.findall(r"(?ms)^"+fence+r" python[^\n]*\n(.*?)^"+fence,raw.decode())
(source_config,)=re.findall(r"(?s)^\'\'\'(backtest.*?)\'\'\'",source)
schema=["time","asks","bids","close","vol","position","trades"]
d={"source":source,"source_config":source_config,"raw_document_sha256":digest,"feeds":{m:{"schema":schema} for m in ("BTC_USDT","ETH_USDT")},"proof":{}}
mark=datetime.fromisoformat(date+"T12:00:00+00:00")
d["begin"]=begin=int(mark.timestamp());d["end"]=end=begin+1200
go=begin-10005
for product in d["feeds"]:
    complete=[]
    links=[]
    for low,high in [(go,begin-5000),(begin-5000,end+10)]:
        args={"detail":"true","round":"true","feeder":"local","event":"feed","eid":"Binance","depth":5,"trades":1,"custom":0,"period":1000,"symbol":product,"from":low,"to":high}
        url="https://q.fmz.com/data/history?"+urlencode(args)
        with urlopen(url,timeout=45) as f: raw=f.read(50_000_001)
        assert len(raw)<=50_000_000
        feed=json.loads(raw)
        assert feed["schema"]==d["feeds"][product]["schema"] and feed["detail"]["symbol"]==product
        assert all(low*1000<=v[0]<=high*1000 for v in feed["data"])
        rows=[r for r in feed["data"] if r[0]<high*1000]
        assert rows[0][0]-low*1000<5000 and high*1000-rows[-1][0]<5000
        complete.extend(rows)
        links.append({"url":url,"bytes":len(raw),"event_content_sha256":hashlib.sha256(json.dumps(rows,separators=(",",":")).encode()).hexdigest(),"rows":len(rows)})
    times=[r[0] for r in complete]
    assert times==sorted(times) and times[0]<=(begin-10000)*1000 and times[-1]>=end*1000
    assert all(t1-t0<=5000 for t0,t1 in zip(times,times[1:]))
    chart=[r for r in complete if begin*1000<=r[0]<end*1000]
    trade_rows=sum(bool(r[-1]) for r in chart)
    book_rows=sum(len(r[1])>=3 and len(r[2])>=3 for r in chart)
    assert trade_rows>100 and book_rows>100
    d["feeds"][product]={k:v for k,v in feed.items() if k in ("detail","schema")}|{"data":complete}
    d["proof"][product]={"downloads":links,"first":times[0],"last":times[-1],"replay_events":len(chart),"nonempty_trade_rows":trade_rows,"depth_three_rows":book_rows}
    print(product,d["proof"][product],flush=True)
with gzip.GzipFile(filename=str(root/f"r47-5091-{date}-feed.gz"),mode="wb",compresslevel=2,mtime=0) as f:
    f.write(json.dumps(d,ensure_ascii=False,separators=(",",":")).encode())
