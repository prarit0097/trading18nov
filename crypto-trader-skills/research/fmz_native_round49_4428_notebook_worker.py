"""Execute the author’s two historical EMA notebooks cells in the isolated research host."""
import argparse
import gzip
import io
import json
from pathlib import Path
import sys

ROOT=Path(__file__).absolute().parent
SCOPES=(('all altcoins',16),('filtered author basket',22),('all altcoins zero commission',16),('official terminal candle',16))


def run(cells,frame,manifest,pd,np,sets,case,selected):
    if case=='official terminal candle':
        frame=frame.copy()
        for q in manifest['proof']:frame.loc[frame.index[-1],q['symbol']]=float(q['terminal_official_close'])
    fee=0 if case=='all altcoins zero commission' else .0005
    ns={'pd':pd,'np':np,'price_usdt':frame,'__name__':'archived_ema_research',
        '__builtins__':{'__build_class__':__build_class__,'abs':abs,'list':list,'min':min,'print':print,'round':round,'set':sets,'str':str}}
    for f in (2,5,6):exec(compile(cells[f],f'FMZ-4428-research-cell{f}.py','exec'),ns)
    Parent=ns['Exchange']
    marks=[]
    orders=[]

    class Audit(Parent):
        def __init__(self,*args,**kwargs):
            assert kwargs['commission']==.0005 and kwargs['initial_balance']==10_000
            kwargs['commission']=fee
            super().__init__(*args,**kwargs)

        def Trade(self,symbol,side,price,size,msg=''):
            old=float(self.account[symbol]['amount'])
            start=float(self.account['USDT']['realised_profit'])
            super().Trade(symbol,side,price,size,msg)
            state=self.account[symbol]
            orders.append([str(self.date),symbol,int(side),float(price),float(size),old,float(state['amount']),float(state['hold_price']),
                           float(self.account['USDT']['realised_profit'])-start])

        def Update(self,date,price):
            before=self.account['USDT']['realised_profit']
            super().Update(date,price)
            state=self.account['USDT']
            marks.append([str(date),*[float(state[k]) for k in ('realised_profit','margin','unrealised_profit','total')],
                         float(state['realised_profit']-before)])

    ns['Exchange']=Audit
    exec(compile(cells[selected],f'FMZ-4428-research-cell{selected}.py','exec'),ns)
    e=ns['e']
    assert 'BTC' not in e.trade_symbols and len(marks)==len(e.df)==len(frame)
    assert len(e.trade_symbols)==(23 if selected==16 else 19)
    assert (selected==16)==('ETH' in e.trade_symbols)
    assert all(row[4]==value for row,value in zip(marks,e.df['total'].tolist(),strict=True))
    end={sym:{k:float(v) for k,v in q.items()} for sym,q in e.account.items()}
    return {'case':case,'cell':selected,'fee_rate':fee,'symbols':list(e.trade_symbols),'final_account':end,'marks':marks,'orders':orders}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--receipt',required=True)
    p.add_argument('--ordinary-set',action='store_true')
    a=p.parse_args()
    sys.path[:0]=[str(ROOT),str(ROOT/'research-libs')]
    import numpy as np
    import pandas as pd
    from fmz_native_round48_4427_notebook_worker import StableSet, sha
    assert (np.__version__,pd.__version__)==('2.2.2','2.2.3')
    proof=(ROOT/'round49-4428-market-proof.json').read_bytes()
    manifest=json.loads(proof)
    src=(ROOT/'r48-part2-author-original.ipynb').read_bytes()
    assert sha(src)==manifest['source']['notebook_sha256']
    cells={int(n):''.join(json.loads(src)['cells'][int(n)]['source']) for n in manifest['source']['cells']}
    assert {str(k):sha(q.encode()) for k,q in cells.items()}==manifest['source']['cells']
    raw=(ROOT/'r48-author-usdm.csv').read_bytes()
    assert sha(raw)==manifest['source']['csv_sha256']
    frame=pd.read_csv(io.BytesIO(raw),index_col=0)
    frame.index=pd.to_datetime(frame.index)
    tested=SCOPES[:1] if a.ordinary_set else SCOPES
    curves=[run(cells,frame,manifest,pd,np,set if a.ordinary_set else StableSet,case,step) for case,step in tested]
    doc={'proof_sha256':sha(proof),'worker_sha256':sha(Path(__file__).read_bytes()),'ordinary_set':a.ordinary_set,'results':curves}
    (ROOT/a.receipt).write_bytes(gzip.compress(json.dumps(doc,separators=(',',':')).encode(),mtime=0))


if __name__=='__main__':
    try:main()
    except Exception:
        import traceback
        (ROOT/'round49-4428-worker-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
