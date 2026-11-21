"""Execute the unchanged #3717 Python source in the official offline FMZ engine."""
import argparse
from bisect import bisect_left, bisect_right
import calendar
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).absolute().parent
WORK = ROOT/'round42-3717-native-bars.json.gz'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run(job, minutes, snapshot_seconds):
    loader=ROOT/'official_fmz_python.py'
    binary=digest((ROOT/'depends/backtest_py_windows_64bit.so').read_bytes())
    assert binary=='504c312b9b4b410e84c9812298964becc7ae669f253fa0790480330661b212c0'
    spec=importlib.util.spec_from_file_location('fmz',loader)
    fmz=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fmz)
    market=job['feed']
    times=[row[0] for row in market['data']]
    requests=[]

    def offline(url, body=None):
        loc=urlparse(url); q=parse_qs(loc.query)
        assert loc.hostname=='q.fmz.com' and loc.path=='/data/history' and body is None
        assert q['eid']==['Binance'] and q['symbol']==['BTC_USDT'] and q['period']==['60000']
        assert q['event'][0] in ('feed','detail')
        t0,t1=[int(q[k][0])*1000 for k in ('from','to')]
        left,right=bisect_left(times,t0),bisect_right(times,t1)
        assert left<right,(t0,t1)
        response=market['data'][left:right]
        requests.append([q['event'][0],t0,t1,len(response)])
        return json.dumps({k:market[k] for k in ('detail','schema')}|{'data':response},separators=(',',':')).encode()

    fmz.httpGet=offline
    [config]=re.findall(r"(?s)^'''(backtest.*?)'''",job['script'])
    end=job['end'] if minutes is None else job['begin']+minutes*60
    if minutes:
        config=config.replace('end: 2021-09-01 00:00:00','end: '+datetime.fromtimestamp(end,timezone.utc).strftime('%Y-%m-%d %H:%M:%S'))
    assert digest(job['script'].encode())==job['script_sha256']
    actual_time=time.time
    local_mktime=time.mktime
    api={}
    try:
        time.mktime=calendar.timegm
        task=fmz.parseTask(config)
        task['Options']['MaxRuntimeLogs']=100_000
        task['Options']['SnapshotPeriod']=snapshot_seconds*1000
        sim=fmz.VCtx(task,gApis=api)
    finally:
        time.mktime=local_mktime
    clock=lambda:api['UnixNano']()//1_000_000
    assert clock()==job['begin']*1000
    ex=api['exchange']
    ledger=[]
    counts=Counter()
    changed={}
    last_ticker=[]

    def submit(original, side):
        def wrapped(price, qty, *other):
            out=original(price,qty,*other)
            counts[side]+=1
            ledger.append(['order',clock(),side,price,qty,out])
            if out and price==-1:
                # Observe immediate market outcomes through a native read-only accessor
                # later, using the engine's transaction report to preserve source time here.
                counts['market_order']+=1
            return out
        return wrapped

    old_order,old_account,old_ticker=ex.GetOrder,ex.GetAccount,ex.GetTicker

    def query_order(oid):
        out=old_order(oid)
        counts['GetOrder']+=1
        if out:
            fields=tuple(out[k] for k in ('Status','DealAmount','AvgPrice'))
            if fields!=changed.get(oid):
                changed[oid]=fields
                ledger.append(['status',clock(),oid,*fields])
        return out

    def query_account():
        out=old_account()
        counts['GetAccount']+=1
        ledger.append(['account',clock(),*[out[k] for k in ('Balance','FrozenBalance','Stocks','FrozenStocks')]])
        return out

    def query_ticker():
        out=old_ticker()
        counts['GetTicker']+=1
        if out:
            last_ticker[:]=[clock(),out['Time'],out['Last']]
        return out

    ex.Buy=submit(ex.Buy,'buy')
    ex.Sell=submit(ex.Sell,'sell')
    ex.GetOrder=query_order
    ex.GetAccount=query_account
    ex.GetTicker=query_ticker
    settings={'__builtins__':{'int':int,'float':float,'dict':dict,'set':set,'min':min,'range':range,'__build_class__':__build_class__},
              '__name__':'archived_strategy',**job['params'],**api}
    exec(compile(job['script'],'FMZ-3717.py','exec'),settings)
    outcome='returned'
    last=None
    try:
        settings['main']()
    except fmz.StopError as e:
        outcome='end_of_backtest'
        last=type(e).__name__
    except Exception:
        import traceback
        outcome='source_or_host_error'
        last=traceback.format_exc()
    finally:
        time.time=actual_time
        report=json.loads(sim.Join())
        for key in ('Elapsed','LoadElapsed'):
            report.pop(key,None)
    return {'outcome':outcome,'reason':last,'counts':dict(counts),'begin':job['begin'],'end':end,'tape':ledger,
            'report':report,'last_ticker':last_ticker,'backend_sha256':binary,'loader_sha256':digest(loader.read_bytes()),
            'offline_requests':requests}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--minutes',type=int)
    p.add_argument('--snapshot-seconds',type=int,default=3600)
    p.add_argument('--receipt',required=True)
    a=p.parse_args()
    job=WORK.read_bytes()
    outcome=run(json.loads(gzip.decompress(job)),a.minutes,a.snapshot_seconds)
    redacted={'input_sha256':digest(job),'worker_sha256':digest(Path(__file__).read_bytes()),**outcome}
    result=(json.dumps(redacted,ensure_ascii=False,separators=(',',':'))+'\n').encode()
    (ROOT/a.receipt).write_bytes(gzip.compress(result,mtime=0))


if __name__=='__main__':
    try:
        main()
    except Exception:
        import traceback
        (ROOT/'round42-3717-native-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
