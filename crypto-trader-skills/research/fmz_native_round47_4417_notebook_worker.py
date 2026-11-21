"""Run the author's exact butterfly strategy cells in an offline Python notebook host."""
import argparse
import ast
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys

ROOT=Path(__file__).absolute().parent
SYMBOLS={'BTC':13,'ETH':14}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def cell_without_presentation(cell):
    tree=ast.parse(cell)
    plotted=tree.body.pop()
    assert isinstance(plotted,ast.Expr) and isinstance(plotted.value,ast.Call)
    assert isinstance(plotted.value.func,ast.Attribute) and plotted.value.func.attr=='plot'
    retained='\n'.join(cell.split('\n')[:plotted.lineno-1])+'\n'
    assert ast.dump(ast.parse(retained))==ast.dump(tree)
    return retained


def run(pd, cells, frame, coin, case, fee, final):
    selected=SYMBOLS[coin]
    if final:
        frame=frame.copy()
        for symbol,price in final.items():frame.loc[frame.index[-1],symbol]=float(price)
    bindings={'pd':pd,'df':frame,'__name__':'archived_research',
              '__builtins__':{'__build_class__':__build_class__, 'abs':abs, 'len':len,
                             'min':min, 'max':max, 'print':print, 'round':round, 'str':str}}
    exec(compile(cells[18],'FMZ-4417-exchange.py','exec'),bindings)
    original=bindings['Exchange']
    transactions=[]
    marks=[]

    class Audit(original):
        def __init__(self,*args,**kwargs):
            assert kwargs['initial_balance']==10000 and kwargs['taker_fee']==.0002
            if fee is not None:kwargs['taker_fee']=fee
            super().__init__(*args,**kwargs)

        def Update(self,date,symbols,closes):
            super().Update(date,symbols,closes)
            book=self.account['USDT']
            marks.append([str(date),*[float(book[k]) for k in ('realised_profit','unrealised_profit','margin','fee','total')],
                          [float(closes[s]) for s in symbols]])

        def Trade(self,symbol,direction,price,amount,msg='',maker=True):
            before=dict(self.account[symbol]);wallet=dict(self.account['USDT'])
            super().Trade(symbol,direction,price,amount,msg,maker)
            after=self.account[symbol];now=self.account['USDT']
            assert not maker
            transactions.append([str(self.date),symbol,int(direction),float(price),float(amount),
                                 float(before['amount']),float(after['amount']),float(after['hold_price']),
                                 float(now['realised_profit']-wallet['realised_profit']),
                                 float(now['fee']-wallet['fee'])])

    bindings['Exchange']=Audit
    active=cell_without_presentation(cells[selected])
    exec(compile(active,f'FMZ-4417-{coin}.py','exec'),bindings)
    e=bindings['e']
    assert len(marks)==len(e.df) and len(marks)>7000
    assert all(abs(x-y)<1e-9 for x,y in zip(e.df['profit'].tolist(),[r[1]+r[2] for r in marks],strict=True))
    terminal_legs={s:{k:float(v) for k,v in e.account[s].items()} for s in e.trade_symbols}
    terminal_balance={k:float(v) for k,v in e.account['USDT'].items()}
    return {'coin':coin,'case':case,'chart':marks,'transactions':transactions,'symbols':e.trade_symbols,
            'active_cell_sha256':digest(active.encode()),'engine_cell_sha256':digest(cells[18].encode()),
            'fee_rate':e.taker_fee,'final_legs':terminal_legs,'final_account':terminal_balance}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--receipt',required=True)
    a=p.parse_args()
    sys.path.insert(0,str(ROOT/'research-libs'))
    import pandas as pd
    import numpy as np
    assert pd.__version__=='2.2.3' and np.__version__=='2.2.2'
    note=(ROOT/'r47-4417-author-original.ipynb').read_bytes()
    history=(ROOT/'round47-4417-author-market.csv').read_bytes()
    proof=(ROOT/'round47-4417-crosscheck.json').read_bytes()
    check=json.loads(proof)
    nb=json.loads(note)
    assert digest(note)==check['source']['author_notebook_sha256']
    assert digest(history)==check['source']['author_csv_sha256']
    cells={k:''.join(nb['cells'][k]['source']) for k in (13,14,18)}
    assert {str(k):digest(v.encode()) for k,v in cells.items()}==check['source']['source_cells']
    df=pd.read_csv(io.BytesIO(history),index_col=0)
    df.index=pd.to_datetime(df.index)
    assert len(df)==8767 and not df.index.has_duplicates
    confirmed_final={r['symbol']:r['independent_final_candle_close'] for r in check['prices']}
    rows=[]
    for coin in SYMBOLS:
        rows.append(run(pd,cells,df,coin,'authored research',None,None))
        rows.append(run(pd,cells,df,coin,'0.04% fixed-grid taker fee',.0004,None))
        rows.append(run(pd,cells,df,coin,'official finalized terminal candle',None,confirmed_final))
    output={'verification':{'notebook_sha256':digest(note),'csv_sha256':digest(history),'official_candle_proof_sha256':digest(proof),
                            'numpy_version':np.__version__,'pandas_version':pd.__version__,'worker_sha256':digest(Path(__file__).read_bytes())},
            'results':rows}
    payload=json.dumps(output,ensure_ascii=False,separators=(',',':')).encode()
    (ROOT/a.receipt).write_bytes(gzip.compress(payload,mtime=0))


if __name__=='__main__':
    try: main()
    except Exception:
        import traceback
        (ROOT/'round47-4417-worker-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
