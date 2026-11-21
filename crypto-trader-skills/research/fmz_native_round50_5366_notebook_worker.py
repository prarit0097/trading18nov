"""Run the archived author's 7,500-bar minute EMA case inside the offline host."""
import argparse
import gzip
import io
import json
from pathlib import Path
import sys

ROOT=Path(__file__).absolute().parent
CASES=('author minute case','zero commission sensitivity')


def run(case, source, raw, pd, np, prefer, chosen):
    fee=.00075 if case!='zero commission sensitivity' else 0
    frame=pd.read_csv(io.BytesIO(raw),index_col=0)
    env={'pd':pd,'np':np,'price_usdt':frame,'__name__':'authored_ema_notebook',
         '__builtins__':{'__build_class__':__build_class__,'abs':abs,'min':min,'list':list,'len':len,
                         'set':prefer,'round':round,'str':str,'print':print}}
    for i in (2,5,6):exec(compile(chosen[i],f'FMZ-part4-cell{i}.py','exec'),env)
    Parent=env['Exchange']
    orders=[]
    marks=[]

    class Audited(Parent):
        def __init__(self,*args,**kwargs):
            assert kwargs['initial_balance']==10_000 and kwargs['commission']==.00075
            kwargs['commission']=fee
            super().__init__(*args,**kwargs)

        def Update(self,t,price):
            super().Update(t,price)
            account=self.account['USDT']
            marks.append([str(t),*[float(account[k]) for k in ('realised_profit','margin','unrealised_profit','total')]])

        def Trade(self,symbol,side,price,size,msg=''):
            old=self.account[symbol]['amount']
            balance=self.account['USDT']['realised_profit']
            super().Trade(symbol,side,price,size,msg)
            a=self.account[symbol]
            orders.append([str(self.date),symbol,int(side),float(price),float(size),float(old),float(a['amount']),float(a['hold_price']),
                           float(self.account['USDT']['realised_profit']-balance)])

    env['Exchange']=Audited
    exec(compile(chosen[8],'FMZ-part4-cell8.py','exec'),env)
    e=env['stragey_2a']
    assert set(e.trade_symbols)=={v['symbol'] for v in source['data']}
    assert len(marks)==len(e.df)==source['signal_rows']
    assert all(q[4]==x for q,x in zip(marks,e.df['total'].tolist(),strict=True))
    accounts={s:{k:float(x) for k,x in a.items()} for s,a in e.account.items()}
    return {'case':case,'fee':fee,'symbols':e.trade_symbols,'orders':orders,'marks':marks,'accounts':accounts}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--receipt',required=True)
    p.add_argument('--ordinary-set',action='store_true')
    a=p.parse_args()
    sys.path[:0]=[str(ROOT),str(ROOT/'research-libs')]
    import numpy as np
    import pandas as pd
    from fmz_native_round48_4427_notebook_worker import StableSet,sha
    assert (np.__version__,pd.__version__)==('2.2.2','2.2.3')
    proof=(ROOT/'round50-5366-market-proof.json').read_bytes()
    spec=json.loads(proof)
    data=(ROOT/'r50-5366-author-minute.csv').read_bytes()
    note=(ROOT/'r48-part4-author-original.ipynb').read_bytes()
    assert sha(data)==spec['source']['csv_sha256'] and sha(note)==spec['source']['notebook_sha256']
    cells=json.loads(note)['cells']
    pinned={int(k):''.join(cells[int(k)]['source']) for k in spec['source']['source_cells']}
    assert {str(k):sha(s.encode()) for k,s in pinned.items()}==spec['source']['source_cells']
    result=[]
    for c in CASES[:1] if a.ordinary_set else CASES:
        result.append(run(c,spec,data,pd,np,set if a.ordinary_set else StableSet,pinned))
    doc={'input_proof_sha256':sha(proof),'worker_sha256':sha(Path(__file__).read_bytes()),'ordinary_set':a.ordinary_set,
         'results':result}
    (ROOT/a.receipt).write_bytes(gzip.compress(json.dumps(doc,separators=(',',':')).encode(),mtime=0))


if __name__=='__main__':
    try:main()
    except Exception:
        import traceback
        (ROOT/'round50-5366-worker-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
