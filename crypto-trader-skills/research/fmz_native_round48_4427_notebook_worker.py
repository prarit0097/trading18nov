"""Run the archived fixed-dollar alt-short / BTC-long author notebook offline."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys

ROOT=Path(__file__).absolute().parent


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class StableSet(set):
    def __iter__(self):
        return iter(sorted(super().__iter__()))

    def __sub__(self, other):
        return StableSet(super().__sub__(other))


def run(cells,frame,manifest,pd,np,mode,regular):
    if mode=='official final candle':
        frame=frame.copy()
        for price in manifest['official_market_proof']:
            frame.loc[frame.index[-1],price['symbol']]=float(price['terminal_official_close'])
    expected_fee=.0005 if mode!='zero commission' else 0
    globals_={'pd':pd,'np':np,'price_usdt':frame,'__name__':'published_research',
              '__builtins__':{'__build_class__':__build_class__,'abs':abs,'list':list,'min':min,'print':print,'round':round,
                              'set':set if regular else StableSet,'str':str}}
    for k in (3,24):
        exec(compile(cells[k],f'FMZ-4427-author-cell{k}.py','exec'),globals_)
    Parent=globals_['Exchange']
    orders=[]
    states=[]

    class Audited(Parent):
        def __init__(self,*args,**kwargs):
            assert kwargs['commission']==.0005 and kwargs['initial_balance']==10_000
            kwargs['commission']=expected_fee
            super().__init__(*args,**kwargs)

        def Update(self,date,close):
            before=self.account['USDT']['realised_profit']
            super().Update(date,close)
            wallet=self.account['USDT']
            states.append([str(date),*[float(wallet[k]) for k in ('realised_profit','margin','unrealised_profit','total')],
                           float(wallet['realised_profit']-before)])

        def Trade(self,symbol,direction,price,amount,msg=''):
            previous=self.account[symbol]['amount']
            current=self.account['USDT']['realised_profit']
            super().Trade(symbol,direction,price,amount,msg)
            observed=self.account[symbol]
            orders.append([str(self.date),symbol,int(direction),float(price),float(amount),float(previous),
                           float(observed['amount']),float(observed['hold_price']),float(self.account['USDT']['realised_profit']-current)])

    globals_['Exchange']=Audited
    exec(compile(cells[27],'FMZ-4427-author-cell27.py','exec'),globals_)
    engine=globals_['stragey_1']
    assert engine.trade_symbols[-1]=='BTC' and set(engine.trade_symbols[:-1])==set(manifest['short_symbols'])
    assert len(engine.df)==len(states)==len(frame)
    assert all(float(engine.df['total'].iloc[k])==row[4] for k,row in enumerate(states))
    summary={s:{k:float(v) for k,v in q.items()} for s,q in engine.account.items()}
    return {'mode':mode,'iteration':list(engine.trade_symbols),'commission':engine.commission,'marks':states,
            'orders':orders,'accounts':summary}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--receipt',required=True)
    p.add_argument('--ordinary-set',action='store_true')
    a=p.parse_args()
    sys.path.insert(0,str(ROOT/'research-libs'))
    import pandas as pd
    import numpy as np
    assert pd.__version__=='2.2.3' and np.__version__=='2.2.2'
    notebook=(ROOT/'r48-part1-author-original.ipynb').read_bytes()
    data=(ROOT/'r48-author-usdm.csv').read_bytes()
    staged=(ROOT/'round48-4427-market-proof.json').read_bytes()
    manifest=json.loads(staged)
    assert sha(data)==manifest['source']['csv_sha256'] and sha(notebook)==manifest['source']['notebook_sha256']
    active=json.loads(notebook)['cells']
    cells={k:''.join(active[k]['source']) for k in (3,17,24,27)}
    assert {str(k):sha(v.encode()) for k,v in cells.items()}==manifest['source']['original_cells']
    prices=pd.read_csv(io.BytesIO(data),index_col=0)
    prices.index=pd.to_datetime(prices.index)
    outcomes=[]
    cases=['author research'] if a.ordinary_set else ['author research','zero commission','official final candle']
    for case in cases:outcomes.append(run(cells,prices,manifest,pd,np,case,a.ordinary_set))
    record={'input_proof_sha256':sha(staged),'worker_sha256':sha(Path(__file__).read_bytes()),
            'pandas':pd.__version__,'numpy':np.__version__,'ordinary_set':a.ordinary_set,'results':outcomes}
    (ROOT/a.receipt).write_bytes(gzip.compress(json.dumps(record,separators=(',',':')).encode(),mtime=0))


if __name__=='__main__':
    try:main()
    except Exception:
        import traceback
        (ROOT/'round48-4427-worker-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
