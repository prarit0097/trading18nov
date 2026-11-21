import calendar,gzip,hashlib,importlib.util,json,random,sys,time,traceback
from pathlib import Path
from urllib.parse import parse_qs,urlparse
ROOT=Path(__file__).resolve().parent
ID,SEED=map(int,sys.argv[1:3])
class End(BaseException): pass

def main():
    dll=ROOT/'depends/backtest_py_windows_64bit.so'
    assert hashlib.sha256(dll.read_bytes()).hexdigest()=='504c312b9b4b410e84c9812298964becc7ae669f253fa0790480330661b212c0'
    raw=(ROOT/'round50-666-667-input.json.gz').read_bytes(); inputs=json.loads(gzip.decompress(raw)); model=inputs['sources'][str(ID)]
    sys.path.insert(0,str(ROOT/'research-libs'))
    info=importlib.util.spec_from_file_location('fmz',ROOT/'official_fmz_python.py'); sdk=importlib.util.module_from_spec(info); info.loader.exec_module(sdk)
    fetched=[]; archive=inputs['market']
    def local(url,body=None):
        u=urlparse(url); q=parse_qs(u.query)
        assert u.hostname=='q.fmz.com' and u.path=='/data/history' and body is None and q['eid'][0] in ('Futures_OKCoin','Futures_OKX')
        assert q['period']==['60000'] and q['symbol']==['BTC_USD.this_week']
        a,b=[int(q[k][0])*1000 for k in ('from','to')]
        rows=[r for r in archive['data'] if a<=r[0]<=b]; assert rows
        fetched.append([a,b,len(rows)])
        return json.dumps({**archive,'data':rows},separators=(',',':')).encode()
    sdk.httpGet=local
    config='''backtest
start: 2019-09-01 06:00:00
end: 2019-09-01 22:03:00
period: 15m
basePeriod: 1m
exchanges: [{"eid":"Futures_OKCoin","currency":"BTC_USD","balance":0,"stocks":0.1,"fee":[0.02,0.05]}]
'''
    g={}; orig=time.mktime
    try: time.mktime=calendar.timegm; ctx=sdk.VCtx(config,gApis=g)
    finally: time.mktime=orig
    e=g['exchange']; clock=lambda:g['UnixNano']()//1_000_000; actual_sleep=g['Sleep']; end=inputs['end_ms']
    submitted=[]; chosen=[]; direction=None; first_records=[]
    def remember(fn):
        def wrapped(*args):
            value=fn(*args)
            assert value['InstrumentID']==inputs['named_market'] and value['VolumeMultiple']==100
            chosen.append(value)
            return value
        return wrapped
    target_direction=e.SetDirection
    def set_direction(value):
        nonlocal direction
        direction=value; return target_direction(value)
    def order(method):
        def tracked(p,q,*other):
            before=clock(); ticket=method(p,q,*other); submitted.append([before,clock(),direction,p,q,ticket]); return ticket
        return tracked
    records=e.GetRecords
    def record_once(*args):
        values=records(*args)
        if not first_records: first_records.extend(values)
        return values
    def sleep(ms):
        assert ms==30000
        if clock()+ms>=end: raise End()
        actual_sleep(ms)
    e.SetContractType=remember(e.SetContractType); e.SetDirection=set_direction
    e.GetRecords=record_once; e.Buy=order(e.Buy); e.Sell=order(e.Sell); g['Sleep']=sleep
    if ID==667: random.seed(SEED)
    try:
        try:
            host=g|model['settings']; exec(compile(model['source'],f'catalogue-{ID}.py','exec'),host); host['main']()
        except End:
            pass
        cut=clock()
        assert end-30000<=cut<end and submitted and chosen
        held=e.GetPosition(); expected=e.GetAccount(); orders=[e.GetOrder(row[-1]) for row in submitted if row[-1]]
        report={'id':ID,'seed':SEED,'input_sha256':hashlib.sha256(raw).hexdigest(),'choices':chosen,'submitted':submitted,'orders':orders,'held':held,'account':expected,'source_cutoff':cut,'requests':fetched,'first_records':first_records}
        tag=sys.argv[3]
        (ROOT/f'round50-{ID}-{SEED}-{tag}.json').write_text(json.dumps(report,separators=(',',':')),encoding='utf-8')
    finally: ctx.Join()

try: main()
except BaseException:
    (ROOT/f'round50-{ID}-{SEED}-error.txt').write_text(traceback.format_exc(),encoding='utf-8'); raise
