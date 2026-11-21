"""Run the exact #5091 Python source with recorded feeds in the FMZ AppContainer."""
import calendar
import gzip
import hashlib
import importlib.util
import json
from bisect import bisect_left, bisect_right
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import re
import time
import sys
import traceback
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).parent
def stamp(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

def main():
    path=ROOT/"depends/backtest_py_windows_64bit.so"
    assert hashlib.sha256(path.read_bytes()).hexdigest()=="504c312b9b4b410e84c9812298964becc7ae669f253fa0790480330661b212c0"
    date=sys.argv[1]
    data=json.loads(gzip.decompress((ROOT/f"r47-5091-{date}-feed.gz").read_bytes()))
    spec=importlib.util.spec_from_file_location("fmz",ROOT/"official_fmz_python.py")
    sdk=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sdk)
    requested=[]
    feeds=data["feeds"]
    times={k:[r[0] for r in v["data"]] for k,v in feeds.items()}
    def local(url, body=None):
        parsed=urlparse(url)
        q=parse_qs(parsed.query)
        assert parsed.hostname=="q.fmz.com" and parsed.path=="/data/history" and body is None
        requested.append(q)
        assert q["eid"]==["Binance"] and q["period"]==["1000"],q
        k=q["symbol"][0]
        start,end=[int(q[n][0])*1000 for n in ("from","to")]
        left,right=bisect_left(times[k],start),bisect_right(times[k],end)
        assert left<right and times[k][0]<=start and times[k][-1]>=end,(k,start,end)
        d=feeds[k]
        return json.dumps({"detail":d["detail"],"schema":d["schema"],"data":d["data"][left:right]},separators=(",",":")).encode()

    sdk.httpGet=local
    begin,end=data["begin"],data["end"]
    scope = "audit"
    if len(sys.argv)>3:
        end=begin+int(sys.argv[3])
        scope=f"prefix-{sys.argv[3]}"
    cfg, n = re.subn(r"(?m)^(start|end):.*$", lambda m: f"{m[1]}: {stamp(begin if m[1]=='start' else end)}",data["source_config"])
    assert n==2
    g={}
    original_mktime=time.mktime
    try:
        time.mktime=calendar.timegm
        task=sdk.parseTask(cfg)
        assert [x["Stocks"] for x in task["Exchanges"]]==[0,3]
        assert [x["FeeMaker"] for x in task["Exchanges"]]==[0,150]
        for e in task["Exchanges"]:
            e["BasePeriod"]=1000
            e["DepthDeep"]=5
            e["TradesMode"]=0
        task["Options"]["DepthDeep"]=5
        task["Options"]["TradesMode"]=0
        task["Options"]["MaxRuntimeLogs"]=4000
        task["Options"]["SnapshotPeriod"]=100 if len(sys.argv)==2 else int(sys.argv[2])
        ctx=sdk.VCtx(task,gApis=g)
    finally:
        time.mktime=original_mktime
    t=lambda:g["UnixNano"]()//1_000_000
    counts=Counter()
    market_order_queries=[]
    trail=[]
    def capture(method,k,name):
        def wrap(*args):
            value=method(*args)
            counts[f"{k}:{name}"]+=1
            if name in ("Buy","Sell","CancelOrder"):
                trail.append([k,name,t(),args,value])
            elif name=="GetAccount":
                market_order_queries.append([k,"account",t(),dict(value)])
            elif name=="GetOrders":
                market_order_queries.append([k,"open",t(),[dict(v) for v in value]])
            elif name=="GetOrder" and value is not None:
                market_order_queries.append([k,"order",t(),dict(value)])
            elif counts[f"{k}:{name}"]<=2:
                trail.append([k,name,t(),len(value) if isinstance(value,list) else bool(value)])
            return value
        return wrap
    settings={"BurstThresholdPct":.00127,"BurstThresholdVol":10,"MinStock":.001,"CalcNetInterval":60,"BalanceTimeout":10000,"TickInterval":280}
    g.update(settings)
    for e,name in zip(g["exchanges"],feeds,strict=True):
        for field in ("GetTrades","GetDepth","Buy","Sell","CancelOrder","GetOrder","GetOrders","GetAccount"):
            setattr(e,field,capture(getattr(e,field),name,field))
    outcome="returned"
    err=None
    try:
        exec(compile(data["source"],"archive-5091.py","exec"),g)
        opening=t()
        g["main"]()
    except sdk.StopError:
        outcome="native end of backtest"
    except Exception:
        outcome="exception"
        err=traceback.format_exc()
    finally:
        last=t()
        report=json.loads(ctx.Join())
        result={"outcome":outcome,"err":err,"requests":requested,"task":task,"opening":opening,"last":last,"counts":dict(counts),"trail":trail,"native_summary":{k:v for k,v in report.items() if k not in ("Chart","RawData")}}
        result.update({"actual_feed":data["proof"],"source_digest":data["raw_document_sha256"],"native_hash":hashlib.sha256(path.read_bytes()).hexdigest(),"loader_hash":hashlib.sha256((ROOT/"official_fmz_python.py").read_bytes()).hexdigest(),"author_endpoint_reads":market_order_queries,"effective_parameters":settings})
        with gzip.GzipFile(filename=str(ROOT/f"r49-5091-{date}-{scope}.gz"),mode="wb",mtime=0) as out:
            out.write(json.dumps(result,ensure_ascii=False,default=str,separators=(",",":")).encode())

if __name__ == '__main__':
    try:
        main()
    except BaseException:
        (ROOT/f"r49-5091-{sys.argv[1]}-error.txt").write_text(traceback.format_exc(),encoding="utf-8")
        raise
