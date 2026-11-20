"""Observe the official offline FMZ Python lifecycle used by #5153."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import time
from urllib.parse import parse_qs,urlparse

ROOT=Path(__file__).absolute().parent


def digest(b):return hashlib.sha256(b).hexdigest()


def main():
    tape=(ROOT/'round31-1942-input.json.gz').read_bytes()
    assert digest(tape)=='87a1a5d9bc818c85656248891f49d74bd62dd251b12e70f0ce606e750fb2245c'
    playback=json.loads(gzip.decompress(tape))['scope']['2021-06-01']['market']
    loader=ROOT/'official_fmz_python.py'
    backend=ROOT/'depends/backtest_py_windows_64bit.so'
    binary=digest(backend.read_bytes())
    assert binary=='504c312b9b4b410e84c9812298964becc7ae669f253fa0790480330661b212c0'
    module=importlib.util.spec_from_file_location('fmz',loader)
    fmz=importlib.util.module_from_spec(module);module.loader.exec_module(fmz)
    def offline(url,body=None):
        loc=urlparse(url);p=parse_qs(loc.query)
        assert loc.hostname=='q.fmz.com' and loc.path=='/data/history' and body is None
        assert p['eid']==['Futures_Binance'] and p['period']==['60000']
        currency,key=p['symbol'][0].split('.')
        assert currency=='BTC_USDT' and key in playback
        start,stop=[int(p[k][0])*1000 for k in ('from','to')]
        original=playback[key]
        data=[r for r in original['data'] if start<=r[0]<=stop]
        assert data
        return json.dumps({k:original[k] for k in ('detail','schema')}|{'data':data}).encode()
    fmz.httpGet=offline
    cfg='''backtest
start: 2021-06-01 05:30:00
end: 2021-06-01 05:40:00
period: 1m
basePeriod: 1m
exchanges: [{"eid":"Futures_Binance","currency":"BTC_USDT","balance":2500,"fee":[0.02,0.04]}]
'''
    api={};saved_time=time.time
    ctx=fmz.VCtx(cfg,gApis=api); ex=api['exchange']; probe=[]
    now=lambda:api['UnixNano']()//1_000_000
    def call(name,*args):
        start=now();ret=getattr(ex,name)(*args);end=now()
        probe.append({'method':name,'args':args,'before':start,'end':end,'result':ret})
        return ret
    try:
        setup=call('SetContractType','swap')
        call('SetMarginLevel',20)
        assert api['_G']('buyp') is None
        call('GetAccount')
        quote=call('GetTicker')
        assert call('GetPosition')==[] and call('GetOrders')==[]
        call('SetDirection','buy')
        mid=round(quote['Last']-300,1)
        order=call('Buy',mid+0.04,.001)
        [resting]=call('GetOrders')
        assert resting.Id==order and resting.Type==resting['Type']==0
        call('CancelOrder',resting.Id,resting)
        call('GetOrders')
        order=call('Buy',mid+0.06,.001)
        [resting]=call('GetOrders')
        assert resting.Id==order
        call('CancelOrder',resting.Id,resting)
        call('GetOrders')
        assert call('Buy',-1,.030)
        [held]=call('GetPosition')
        assert held.Amount==held['Amount']==.030
        call('GetAccount')
    finally:
        time.time=saved_time;ctx.Join()
    (ROOT/'round39-5153-python-abi.json').write_text(json.dumps({'probe':probe,'market_sha256':digest(tape),
           'backend_sha256':binary,'loader_sha256':digest(loader.read_bytes())}),encoding='utf-8')


if __name__=='__main__':
    try:main()
    except Exception:
        import traceback
        (ROOT/'round39-5153-python-abi-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
