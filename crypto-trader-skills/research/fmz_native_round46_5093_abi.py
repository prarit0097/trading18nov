"""Check native FMZ Python spot defaults for #5093 using an offline authored-config fixture."""
import calendar
import hashlib
import importlib.util
import json
from pathlib import Path
import time
from urllib.parse import parse_qs,urlparse

ROOT=Path(__file__).absolute().parent


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    data=(ROOT/'round45-5094-abi-input.json').read_bytes()
    feed=json.loads(data)
    engine=ROOT/'official_fmz_python.py'
    binary=sha((ROOT/'depends/backtest_py_windows_64bit.so').read_bytes())
    assert binary=='504c312b9b4b410e84c9812298964becc7ae669f253fa0790480330661b212c0'
    spec=importlib.util.spec_from_file_location('fmz',engine)
    fmz=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fmz)

    def offline(url,body=None):
        u=urlparse(url)
        q=parse_qs(u.query)
        assert u.hostname=='q.fmz.com' and u.path=='/data/history' and body is None
        assert q['eid']==['Binance'] and q['period']==['60000'] and q['symbol']==['BTC_USDT']
        a,b=[int(q[k][0])*1000 for k in ('from','to')]
        return json.dumps({k:feed[k] for k in ('detail','schema')}|{'data':[r for r in feed['data'] if a<=r[0]<=b]}).encode()

    fmz.httpGet=offline
    config='''backtest
start: 2019-09-01 00:00:00
end: 2019-09-01 00:25:00
period: 1h
basePeriod: 1m
exchanges: [{"eid":"Binance","currency":"BTC_USDT","stocks":0,"fee":[0,0]}]
'''
    old_local=time.mktime
    real_time=time.time
    api={}
    try:
        time.mktime=calendar.timegm
        ctx=fmz.VCtx(config,gApis=api)
    finally:
        time.mktime=old_local
    e=api['exchange']
    clock=lambda:api['UnixNano']()//1_000_000
    events=[]

    def record(method,*args):
        start=clock()
        out=getattr(e,method)(*args)
        events.append({'method':method,'arguments':args,'before':start,'after':clock(),'output':out})
        return out

    try:
        balance=record('GetAccount')
        assert (balance['Balance'],balance['Stocks'])==(10000,0)
        midpoint=record('GetTicker')['Last']
        depth=record('GetDepth')
        assert depth.Asks and depth.Bids
        assert api['_N'](9512.498665,4)==9512.4986
        for pct,qty in ((.0049,.0100014),(.005,.0100055),(.0051,.0100096)):
            request=midpoint-50+pct
            identity=record('Buy',request,qty)
            order=record('GetOrder',identity)
            assert order.Id==identity and order.Status==0
            assert abs(order.Price-round(request*100)/100)<1e-8
            assert order.Amount==round(qty*100000)/100000
            assert record('CancelOrder',identity)
            assert record('GetOrder',identity).Status==2
        assert all(q['after']-q['before']==200 for q in events)
    finally:
        time.time=real_time
        ctx.Join()
    (ROOT/'round46-5093-abi.json').write_text(json.dumps({'balance':balance,'market_sha256':sha(data),'events':events,
        'loader_sha256':sha(engine.read_bytes()),'engine_sha256':binary}),encoding='utf-8')


if __name__=='__main__':
    try:main()
    except Exception:
        import traceback
        (ROOT/'round46-5093-abi-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
