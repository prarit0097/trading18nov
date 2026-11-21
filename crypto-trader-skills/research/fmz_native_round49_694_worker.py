import calendar,gzip,hashlib,importlib.util,json,sys,time,traceback
from bisect import bisect_left,bisect_right
from pathlib import Path
from urllib.parse import parse_qs,urlparse
ROOT=Path(__file__).resolve().parent
class End(BaseException): pass

def main():
    path=ROOT/'depends/backtest_py_windows_64bit.so'
    assert hashlib.sha256(path.read_bytes()).hexdigest()=='504c312b9b4b410e84c9812298964becc7ae669f253fa0790480330661b212c0'
    trial=json.loads(gzip.decompress((ROOT/'round47-694-full.json.gz').read_bytes()))
    info=importlib.util.spec_from_file_location('fmz',ROOT/'official_fmz_python.py')
    sdk=importlib.util.module_from_spec(info); info.loader.exec_module(sdk)
    requested=[]
    timestamps={k:[r[0] for r in v['data']] for k,v in trial['feeds'].items()}
    def local(url,body=None):
        u=urlparse(url); q=parse_qs(u.query)
        assert u.hostname=='q.fmz.com' and u.path=='/data/history' and body is None and q['eid']==['OKX'] and q['period']==['60000'],q
        k=q['symbol'][0]; a,b=[int(q[n][0])*1000 for n in ('from','to')]
        times=timestamps[k]; rows=trial['feeds'][k]; data=rows['data'][bisect_left(times,a):bisect_right(times,b)]
        assert data and times[0]<=a and times[-1]>=b,(k,a,b)
        requested.append([k,a,b,len(data)])
        return json.dumps({**rows,'data':data},separators=(',',':')).encode()
    sdk.httpGet=local
    cfg='''backtest
start: 2019-02-20 00:00:00
end: 2020-01-10 00:03:00
period: 1m
basePeriod: 1m
exchanges: [{"eid":"OKX","currency":"BTC_USDT"},{"eid":"OKX","currency":"ETH_USDT","stocks":30},{"eid":"OKX","currency":"LTC_USDT","stocks":100}]
'''
    g={}; mktime=time.mktime
    try:
        time.mktime=calendar.timegm
        ctx=sdk.VCtx(cfg,gApis=g)
    finally:
        time.mktime=mktime
    clock=lambda:g['UnixNano']()//1_000_000
    begin=1550620800000; end=1578614400000
    try:
        originals=[{'account':e.GetAccount(),'ticker':e.GetTicker()} for e in g['exchanges']]
        original_sleep=g['Sleep']; calls=0
        first=clock(); rates=[]
        def sleep(ms):
            nonlocal calls
            calls+=1
            if calls<=12 or calls%1800==0: rates.append([calls,clock(),time.time()])
            if clock()+ms>=end-10_000: raise End()
            original_sleep(ms)
        g['Sleep']=sleep
        try:
            exec(compile(trial['source'],'archive-694.py','exec'),g)
            g['main']()
        except End:
            pass
        finish=clock()
        assert end-10_500<=finish<end,finish
        histories={}
        for symbol,e in zip(('BTC_USDT','ETH_USDT','LTC_USDT'),g['exchanges'],strict=True):
            seen=[]; since=begin
            for page in range(100):
                segment=e.GetHistoryOrders(symbol,since,100)
                assert all(since<=o['Time']<end for o in segment)
                seen.extend(segment)
                if len(segment)<100: break
                since=max(o['Time'] for o in segment)+1
            else: raise AssertionError('paging limit exceeded')
            assert len({o['Id'] for o in seen})==len(seen)
            histories[symbol]=seen
        final=[{'account':e.GetAccount(),'ticker':e.GetTicker(),'orders':e.GetOrders()} for e in g['exchanges']]
        assert 0<calls<=56000000 and first<clock() and finish<=clock()<end+120_000
        (ROOT/'round49-694-full-original-log-result.json').write_text(json.dumps({'requests':requested,'opening':originals,'final':final,'order_histories':histories,'sleep_calls':calls,'clock_witness':rates,'last_time':clock(),'source_cutoff':finish,'readback_buffer_ms':180000},ensure_ascii=False,indent=2),encoding='utf-8')
    finally:
        ctx.Join()

try: main()
except Exception:
    (ROOT/'round49-694-full-original-log-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
    raise
