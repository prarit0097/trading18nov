"""Run the unchanged Turtle source on the fixed BTC inverse quarterly fixture."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import sys

ROOT=Path(__file__).absolute().parent


def run(job,with_fills):
    sys.path.insert(0,str(ROOT))
    from fmz_native_round51_4850_abi import create_context, sha
    cfg='''backtest
start: 2021-10-01 00:00:00
end: 2021-12-24 00:00:00
period: 1d
basePeriod: 1h
exchanges: [{"eid":"Futures_Binance","currency":"BTC_USD","balance":0,"stocks":0.1,"fee":[0.02,0.05]}]
'''
    fmz,ctx,g,requests=create_context(cfg,job['market'])
    ex=g['exchange']
    clock=lambda:g['UnixNano']()//1_000_000
    selected=[]
    orders=[]
    status=[]
    counts=Counter()
    position_samples=[]
    prior_position=None
    current_dir=None
    first_records=[]

    def set_contract(original):
        def bind(contract):
            assert contract=='quarter'
            size=original(contract)
            assert size['InstrumentID']==job['historical_market_symbol'] and size['VolumeMultiple']==100
            selected.append(size)
            return size
        return bind

    def direction(original):
        def bind(flag):
            nonlocal current_dir
            assert flag in ('buy','sell','closebuy','closesell')
            current_dir=flag
            return original(flag)
        return bind

    def submit(original,side):
        def invoke(price,quantity,*params):
            send=clock()
            oid=original(price,quantity,*params)
            stamp=clock()
            orders.append([send,stamp,side,current_dir,price,quantity,oid])
            if with_fills and oid:
                result=ex.GetOrder(oid)
                status.append([clock(),oid,result])
            return oid
        return invoke

    def wrap_position(original):
        def read(*args):
            nonlocal prior_position
            rows=original(*args)
            counts['GetPosition']+=1
            key=[(r['Type'],r['Amount'],r['Price']) for r in rows]
            if key!=prior_position:
                position_samples.append([clock(),rows])
                prior_position=key
            return rows
        return read

    def wrap_candle(original):
        def read(*args):
            rows=original(*args)
            counts['GetRecords']+=1
            if not first_records:
                assert len(rows)>=55
                first_records.extend(rows)
            return rows
        return read

    ex.SetContractType=set_contract(ex.SetContractType)
    ex.SetDirection=direction(ex.SetDirection)
    ex.Buy=submit(ex.Buy,'buy')
    ex.Sell=submit(ex.Sell,'sell')
    ex.GetPosition=wrap_position(ex.GetPosition)
    ex.GetRecords=wrap_candle(ex.GetRecords)
    host={'__builtins__':{'__build_class__':__build_class__,'__import__':__import__,'float':float,'int':int,'abs':abs,
                         'Exception':Exception},**g,**job['source_defaults'],'__name__':'archived_python'}
    script=job['python_source']
    assert sha(script.encode())==job['source']['code_sha256']
    exec(compile(script,'FMZ-4850.py','exec'),host)
    status_name='returned'
    try:
        host['main']()
    except fmz.StopError:
        status_name='end_of_backtest'
    finally:
        raw=json.loads(ctx.Join())
    assert status_name=='end_of_backtest' and len(selected)==1
    return {'completion':status_name,'source_market':selected[0],'orders':orders,'read_fill_events':status,'positions':position_samples,
            'counts':dict(counts),'requests':requests,'native_snapshots':raw['Snapshots'],'final_ms':raw['Time'],
            'first_records':first_records,'progress':raw['Progress'],'native_finished':raw['Finished'],'task':raw['Task']}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--receipt',required=True)
    p.add_argument('--with-fills',action='store_true')
    a=p.parse_args()
    raw=(ROOT/'round51-4850-quarter-source.json.gz').read_bytes()
    import hashlib
    source=json.loads(gzip.decompress(raw))
    d=run(source,a.with_fills)
    digest=lambda b:hashlib.sha256(b).hexdigest()
    d.update(input_sha256=digest(raw),worker_sha256=digest(Path(__file__).read_bytes()),with_fills=a.with_fills)
    (ROOT/a.receipt).write_bytes(gzip.compress(json.dumps(d,separators=(',',':')).encode(),mtime=0))


if __name__=='__main__':
    try:main()
    except Exception:
        import traceback
        (ROOT/'round51-4850-run-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
