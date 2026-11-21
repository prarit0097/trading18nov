"""Verify the inverse contract wallet and fees in the official isolated FMZ engine."""
import calendar
from decimal import Decimal as D
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import time
from urllib.parse import parse_qs,urlparse

ROOT=Path(__file__).absolute().parent
ABI_CONFIG='''backtest
start: 2021-10-01 00:00:00
end: 2021-10-01 06:00:00
period: 1d
basePeriod: 1h
exchanges: [{"eid":"Futures_Binance","currency":"BTC_USD","balance":0,"stocks":0.1,"fee":[0.02,0.05]}]
'''


def sha(b):return hashlib.sha256(b).hexdigest()


def create_context(cfg,market):
    f=importlib.util.spec_from_file_location('fmz',ROOT/'official_fmz_python.py')
    fmz=importlib.util.module_from_spec(f)
    f.loader.exec_module(fmz)
    requested=[]
    def local(url, body=None):
        u=urlparse(url);q=parse_qs(u.query)
        wanted='BTC_USD.quarter'
        assert u.hostname=='q.fmz.com' and u.path=='/data/history' and body is None and q['eid']==['Futures_Binance'],url
        assert q['symbol']==[wanted] and q['period']==['3600000'],url
        a,b=[int(q[n][0])*1000 for n in ('from','to')]
        values=[r for r in market['data'] if a<=r[0]<=b]
        assert values,(a,b)
        requested.append([q['event'][0],a,b,len(values)])
        return json.dumps({key:market[key] for key in ('schema','detail')}|{'data':values},separators=(',',':')).encode()
    fmz.httpGet=local
    g={}
    local_time=time.mktime
    try:
        time.mktime=calendar.timegm
        ctx=fmz.VCtx(cfg,gApis=g)
    finally:
        time.mktime=local_time
    return fmz,ctx,g,requested


def main():
    b=(ROOT/'round51-4850-quarter-source.json.gz').read_bytes()
    data=json.loads(gzip.decompress(b))
    exe=ROOT/'depends/backtest_py_windows_64bit.so'
    assert sha(exe.read_bytes())=='504c312b9b4b410e84c9812298964becc7ae669f253fa0790480330661b212c0'
    fmz,ctx,g,requests=create_context(ABI_CONFIG,data['market'])
    e=g['exchange']
    probe=[]
    def call(name,*args):
        start=g['UnixNano']()//1_000_000
        value=getattr(e,name)(*args)
        probe.append([name,start,g['UnixNano']()//1_000_000,args,value])
        return value
    try:
        target=call('SetContractType','quarter')
        cash=call('GetAccount')
        assert cash['Stocks']==.1 and cash['FrozenStocks']==0
        records=call('GetRecords')
        quote=call('GetTicker')
        call('SetDirection','buy')
        one=call('Buy',quote['Sell']*1.01,1)
        opening=call('GetOrder',one)
        held=call('GetPosition')
        quote=call('GetTicker')
        call('SetDirection','closebuy')
        two=call('Sell',quote['Buy']*.99,1)
        closing=call('GetOrder',two)
        assert call('GetPosition')==[]
        terminal=call('GetAccount')
        assert opening.Status==closing.Status==1 and opening.DealAmount==closing.DealAmount==1
        open_px,close_px=D(str(opening.AvgPrice)),D(str(closing.AvgPrice))
        fee=D('.0005')*100*(1/open_px+1/close_px)
        pnl=100*(1/open_px-1/close_px)
        assert abs(D(str(terminal['Stocks']))-D('.1')-pnl+fee)<D('1e-10'),(terminal,pnl,fee)
    finally:
        ctx.Join()
    result={'input_sha256':sha(b),'engine_sha256':sha(exe.read_bytes()),'data_requests':requests,'probe':probe,
            'initial_bar_count':len(records),'quarter_result':target,'independent_one_lot_PnL_BTC':str(pnl),'independent_fee_BTC':str(fee)}
    (ROOT/'round51-4850-abi.json').write_text(json.dumps(result,separators=(',',':')),encoding='utf-8')


if __name__=='__main__':
    try:main()
    except Exception:
        import traceback
        (ROOT/'round51-4850-abi-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
