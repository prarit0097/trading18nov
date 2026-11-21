"""Run the original legacy Dual Thrust Python source in an offline native weekly scenario."""
import argparse
import calendar
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import time
from urllib.parse import parse_qs, urlparse

ROOT=Path(__file__).absolute().parent
CONFIG='''backtest
start: 2019-09-01 06:00:00
end: 2019-09-01 22:00:00
period: 1h
basePeriod: 1m
exchanges: [{"eid":"Futures_OKCoin","currency":"BTC_USD","balance":0,"stocks":0.1,"fee":[0.02,0.05]}]
'''


def digest(raw):return hashlib.sha256(raw).hexdigest()


def run(data):
    market=data['market']
    spec=importlib.util.spec_from_file_location('fmz',ROOT/'official_fmz_python.py')
    fmz=importlib.util.module_from_spec(spec);spec.loader.exec_module(fmz)
    calls=[]
    def incoming(url,body=None):
        u=urlparse(url);q=parse_qs(u.query)
        assert u.hostname=='q.fmz.com' and u.path=='/data/history' and body is None
        assert q['eid'] in (['Futures_OKCoin'],['Futures_OKX']) and q['period']==['60000']
        assert q['symbol']==['BTC_USD.this_week']
        start,end=[int(q[k][0])*1000 for k in ('from','to')]
        candles=[k for k in market['data'] if start<=k[0]<=end]
        assert candles
        calls.append([q['eid'][0],start,end,len(candles)])
        return json.dumps({'schema':market['schema'],'detail':market['detail'],'data':candles},separators=(',',':')).encode()
    fmz.httpGet=incoming
    ctx_api={}
    local=time.mktime
    try:
        time.mktime=calendar.timegm
        context=fmz.VCtx(CONFIG,gApis=ctx_api)
    finally:time.mktime=local
    e=ctx_api['exchange']
    assert e.GetName()=='Futures_OKCoin'
    clock=lambda:ctx_api['UnixNano']()//1_000_000
    real_rate=e.SetRate
    current=None
    directions=[]
    statuses={}
    orders=[]
    chosen=[]
    accounts=[]
    bars=[]
    def set_rate(rate):
        assert rate==1
        result=real_rate(rate)
        directions.append(['rate',clock(),rate]);return result
    real_ct=e.SetContractType
    def contract(which):
        assert which=='this_week'
        value=real_ct(which)
        assert value['InstrumentID']==data['named_market'] and value['VolumeMultiple']==100
        chosen.append(value)
        return value
    real_side=e.SetDirection
    def direction(value):
        nonlocal current
        current=value
        return real_side(value)
    def submit(original,method):
        def recorded(price,qty,*other):
            oid=original(price,qty,*other)
            orders.append([clock(),method,current,price,qty,oid])
            return oid
        return recorded
    fetch=e.GetOrder
    def audited(oid):
        status=fetch(oid)
        if status:
            message=(status['Status'],status['AvgPrice'],status['DealAmount'])
            if oid not in statuses or statuses[oid][-1][2]!=message:
                statuses.setdefault(oid,[]).append([clock(),status,message])
        return status
    original_account=e.GetAccount
    def account():
        result=original_account()
        accounts.append([clock(),result]);return result
    original_records=e.GetRecords
    def get_records(*args):
        q=original_records(*args)
        if not bars:bars.extend(q)
        return q
    e.SetRate=set_rate;e.SetContractType=contract;e.SetDirection=direction
    e.Buy=submit(e.Buy,'buy');e.Sell=submit(e.Sell,'sell')
    e.GetOrder=audited;e.GetAccount=account;e.GetRecords=get_records
    host={'__builtins__':{'__build_class__':__build_class__,'__import__':__import__,'BaseException':BaseException,
                         'len':len,'min':min,'max':max,'range':range,'str':str},**ctx_api,**data['params'],'__name__':'author_dual_thrust'}
    assert digest(data['script'].encode())==data['source_sha256']
    exec(compile(data['script'],'FMZ-1116.py','exec'),host)
    result='returned'
    try:host['main']()
    except fmz.StopError:result='finished'
    finally:raw=json.loads(context.Join())
    assert result=='finished' and raw['Finished'] and raw['Progress']==100
    return {'outcome':result,'orders':orders,'order_observations':statuses,'source_account_observations':accounts,'first_records':bars,
            'market_request_receipts':calls,'native_market_choice':chosen,'rate_proof':directions,'snapshots':raw['Snapshots'],
            'ending_ms':raw['Time'],'summary':raw['Task']}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--receipt',required=True)
    args=p.parse_args()
    raw=(ROOT/'round52-1116-weekly-input.json.gz').read_bytes()
    result=run(json.loads(gzip.decompress(raw)))
    result['input_sha256']=digest(raw)
    result['worker_sha256']=digest(Path(__file__).read_bytes())
    result['engine_sha256']=digest((ROOT/'depends/backtest_py_windows_64bit.so').read_bytes())
    (ROOT/args.receipt).write_bytes(gzip.compress(json.dumps(result,separators=(',',':')).encode(),mtime=0))


if __name__=='__main__':
    try:main()
    except BaseException:
        import traceback
        (ROOT/'round52-1116-worker-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
