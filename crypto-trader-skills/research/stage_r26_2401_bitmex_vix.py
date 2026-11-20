"""Stage exact #2401 XBTUSD trade, quote, mark and seed data with no account access."""

import argparse
import re
from datetime import timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from zipfile import ZipFile
import gzip
import json

from fmz_native_round20_880_capture import DAY, HOUR, US, capture_file, request, sha, update_ohlc

DAYS = ("2019-05-01", "2019-06-01")
WARM_COMMIT = "8e3e1a5eaeaf1af4de4fd77dbecca5deb644c5b9"
WARM_REPO = "https://github.com/Celeborn2BeAlive/bitmex-xbtusd-history"
WARM_RAW = f"https://raw.githubusercontent.com/Celeborn2BeAlive/bitmex-xbtusd-history/{WARM_COMMIT}"
ARCHIVE_PATH = ("strategies-7853bb2bf262c4567ac238d3552d97f0e50cb801/"
                "\u5415\u795e-\u7b80\u6613\u6ce2\u52a8\u7387\u7b56\u7565.md")
ARCHIVE_HASH = "34c676efd2d098351a40a6bd59a13742c92c2338d2cb4b3fc4bd74873250fc64"
SOURCE_HASH = "ee93abbb891ec5aa95d7ed862137586102b69b1e7b40e4b34530950ce7ab581f"
STEP = 900
FILL_WINDOW = 100_000


def moment(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())


def mirror(day, code, cache):
    sec = {"1m":60,"5m":300}[code]
    name = f"XBTUSD-{day}-{code}.json"
    url = f"{WARM_RAW}/{code}/{name}"
    if cache:
        raw = (cache / f"r26-2401-{day}-{code}.json").read_bytes()
    else:
        with request(url) as response:
            raw = response.read(150_001)
    assert len(raw) <= 150_000
    bar = json.loads(raw)
    assert bar["openTimestamp"] == moment(day)
    cols = [bar[key] for key in ("open","high","low","close","volume")]
    assert all(len(x) == DAY//sec for x in cols)
    count = STEP//sec
    out = []
    for i in range(0,len(cols[0]),count):
        o,h,l,c,v = (col[i:i+count] for col in cols)
        assert all(x>0 for series in (o,h,l,c) for x in series)
        out.append([bar["openTimestamp"]+i*sec,o[0],max(h),min(l),c[-1],sum(v)])
    return out, {"url":url,"sha256":sha(raw),"bytes":len(raw),"raw_bars":len(cols[0]),"seconds":sec}


def trading(day, clocks):
    proof={}
    pending=[]
    closed={}
    current=None
    i=0
    for local, row in capture_file(day,"trades",proof):
        while i<len(clocks) and local>clocks[i]*US:
            assert current is not None
            pending.append([*current])
            i+=1
        ex=int(row["timestamp"])
        assert ex<=local
        at=ex//(STEP*US)*STEP
        price=float(row["price"])
        size=int(row["amount"])
        closed[at]=update_ohlc(closed.get(at),price)
        if current is None or at>current[2]:
            current=[local,ex,at,price,price,price,price,size]
        elif at==current[2]:
            current=[local,ex,at,*update_ohlc(current[3:7],price),current[7]+size]
    assert len(pending)==len(clocks)
    return pending,proof,closed


def quotes(day,clocks):
    proof={}
    snapshots=[]
    active=None
    previous=None
    i=0
    for local,row in capture_file(day,"quotes",proof):
        while i<len(clocks) and local>clocks[i]*US+FILL_WINDOW:
            if active is None:
                assert previous is not None
                active=[*previous,previous[4],previous[5],True,True,0]
            snapshots.append(active)
            i+=1
            active=None
        entry=[local,int(row["timestamp"]),float(row["bid_price"]),float(row["ask_price"]),
            int(row["bid_amount"]),int(row["ask_amount"])]
        assert entry[1]<=local and entry[2]<entry[3] and min(entry[2:])>0
        if i<len(clocks) and local>clocks[i]*US:
            if active is None:
                assert previous is not None and previous[0]<=clocks[i]*US
                active=[*previous,previous[4],previous[5],True,True,0]
            active[6]=min(active[6],entry[4]); active[7]=min(active[7],entry[5])
            active[8] &= entry[2]==active[2]; active[9] &= entry[3]==active[3]; active[10]+=1
        previous=entry
    assert len(snapshots)==len(clocks)
    return snapshots,proof


def marks(day,clocks):
    proof={}
    snapshots=[]
    funding={}
    prev=None
    i=0
    settlement=[moment(day)+h*HOUR for h in (4,12,20)]
    for local,row in capture_file(day,"derivative_ticker",proof):
        while i<len(clocks) and local>clocks[i]*US:
            assert prev is not None
            snapshots.append(prev)
            i+=1
        if not row["mark_price"] or not row["funding_timestamp"] or not row["funding_rate"]:
            continue
        ex=int(row["timestamp"])
        due=int(row["funding_timestamp"])
        assert ex<=local
        prev=[local,ex,float(row["mark_price"]),float(row["index_price"]),due,row["funding_rate"]]
        for at in settlement:
            if at*US-10*US <= local <= at*US+60*US:
                funding.setdefault(str(at),[]).append(prev)
    assert len(snapshots)==len(clocks)
    return snapshots,proof,funding


def scenario(p,day,cache):
    parsed=datetime.fromisoformat(day)
    prev=[(parsed-timedelta(days=d)).date().isoformat() for d in (2,1)]
    mid=moment(day)
    begin=mid+2*HOUR
    end=mid+22*HOUR
    clocks=list(range(begin,end+1,5))
    futures={name:p.submit(f,day,clocks) for name,f in (("trades",trading),("quotes",quotes),("marks",marks))}
    mirror_rows={}
    market_refs=[]
    for date in (*prev,day):
        primary,ref1=mirror(date,"1m",cache)
        second,ref2=mirror(date,"5m",cache)
        matches=sum(a[:5]==b[:5] for a,b in zip(primary,second,strict=True))
        close_matches=sum(a[4]==b[4] for a,b in zip(primary,second,strict=True))
        assert close_matches==96
        market_refs.append({"date":date,"one_minute":ref1,"five_minutes":ref2,"mirrors_ohlc_equal":matches,"mirrors_close_equal":close_matches})
        mirror_rows[date]=primary
    tr,t_proof,raw_bars=futures["trades"].result()
    qt,q_proof=futures["quotes"].result()
    md,m_proof,funding=futures["marks"].result()
    same_day=mirror_rows[day]
    overlap=[r for r in same_day if r[0] in raw_bars]
    close_matches=sum(r[4]==raw_bars[r[0]][3] for r in overlap)
    ohlc_matches=sum(r[1:5]==raw_bars[r[0]] for r in overlap)
    market_crosscheck=dict(mirror_vs_capture_close_equal=close_matches,mirror_vs_capture_ohlc_equal=ohlc_matches,comparable=len(overlap))
    assert len(overlap)==96 and close_matches>=95
    history=[r for d in (*prev,day) for r in mirror_rows[d] if r[0]+STEP<=begin]
    print(day,"warmup",len(history),market_crosscheck,"funding",[(k,len(v)) for k,v in funding.items()],flush=True)
    return {"begin":begin,"end":end,"wallet_xbt":2,"history":history,"mirror_references":market_refs,
        "market_crosscheck":market_crosscheck,"funding_near":funding,
        "captures":{"trades":t_proof,"quotes":q_proof,"derivative_ticker":m_proof},
        "intra_trade_candle_ohlc":[[t,*raw_bars[t]] for t in sorted(raw_bars) if mid<=t<mid+DAY],
        "data":[[t,a,b,c] for t,a,b,c in zip(clocks,tr,qt,md,strict=True)]}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive",type=Path,required=True)
    ap.add_argument("--cache",type=Path)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    with ZipFile(args.archive) as archive:
        md=archive.read(ARCHIVE_PATH)
    [code]=re.findall(r"(?ms)^\x60{3}[ \t]*javascript[ \t]*\n(.*?)^\x60{3}",md.decode())
    assert sha(md)==ARCHIVE_HASH and sha(code.encode())==SOURCE_HASH
    assert all(x in code for x in ("period: 15m", "XBTUSD","2019-04-18","2020-04-17"))
    assert all(x in md.decode() for x in ("|N|90|","|Amount|100|"))
    with ThreadPoolExecutor(max_workers=6) as pool:
        scenarios={day:scenario(pool,day,args.cache) for day in DAYS}
    job={"source":code,"source_sha256":SOURCE_HASH,"archive_sha256":ARCHIVE_HASH,
         "archive_path":ARCHIVE_PATH,"clock_seconds":5,"quote_observation_us":FILL_WINDOW,
         "settings":{"period":"15m","N":90,"Amount":100,"start":"2019-04-18 00:00:00",
                     "end":"2020-04-17 23:59:00","contract":"XBTUSD","exchange":"Futures_BitMEX"},
         "scenarios":scenarios}
    packed=gzip.compress((json.dumps(job,ensure_ascii=False,separators=(",",":"))+"\n").encode(),mtime=0)
    args.output.write_bytes(packed)
    print(args.output,len(packed),sha(packed),flush=True)


if __name__=="__main__":
    main()
