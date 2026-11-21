"""Replay #4052 in the offline Pine runtime with literal and venue-lot controls."""
from itertools import batched
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from replay_2864 import engine_options,pine_compat,sha256
from probe_1216 import objects

SOURCE='2ff4b968f45aae983caf4ed28bc68e27aba22fd5cb99e86de65d7fa0e7d72f72'


def programs():
    raw=(ROOT/'source-4052.md').read_bytes()
    assert sha256(raw)==SOURCE
    fence=chr(96)*3
    (archived,)=re.findall(r'(?ms)^'+fence+r' pinescript[^\n]*\n(.*?)^'+fence,raw.decode())
    source,removed=re.subn(r'(?ms)^/\*backtest\n.*?^\*/\n*','',archived)
    assert removed==1
    pruned,removed=re.subn(r'(?m)^strategy\.initial_capital\s*=\s*50000[ \t]*\n','',source)
    assert removed==pruned.count('overlay=true )')==1
    relocated=pruned.replace('overlay=true )','overlay=true, initial_capital=50000 )')
    reference=pruned.replace('strategy.initial_capital','50000')
    whole=relocated
    for side,rounding,sign in (('long','floor','+'),('short','ceil','-')):
        for level in range(5):
            qty=f'{side}Entryqty{level}'
            px=f'{side}EntryPrice{level}'
            old=f'qty={qty}, limit={px}'
            new=f'qty={qty} * 1000, limit=math.{rounding}({px} / syminfo.mintick {sign} 0.000000001) * syminfo.mintick'
            assert whole.count(old)==1
            whole=whole.replace(old,new)
    return {'literal':source,'relocated':relocated,'reference_only':reference,'whole_lot_grid':whole}


def smaller_ohlcv(rows, bucket):
    return [(g[0][0],g[0][1],max(r[2] for r in g),min(r[3] for r in g),g[-1][4],sum(r[-1] for r in g))
            for g in batched(rows,bucket,strict=True)]


def main(mode):
    assert mode in ('baseline','whole')
    source=programs()
    names=('literal','relocated','reference_only') if mode=='baseline' else ('whole_lot_grid',)
    feed=json.loads((ROOT/'4052-feed-corrected.json').read_bytes())
    observe=('\nplot(Buy_ok?1:0,"Gate")\nplot(Sell_ok?1:0,"Sell")\nplot(strategy.opentrades,"Life")'
             '\nplot(strategy.position_avg_price,"Average")\nplot(strategy.position_size,"Position")'
             '\nplot(longTP,"Take Profit Price")\nplot(rsi1_sec_long,"RSI5")\nplot(rsi2_sec_long,"RSI15")'
             '\nplot(rsi3_sec_long,"RSI30")\nplot(cci1_sec_long,"CCI5")\nplot(cci2_sec_long,"CCI15")'
             '\nplot(cci3_sec_long,"CCI30")\nplot(cci_sec,"CCI60")\n')
    report={}
    for market,data in feed['markets'].items():
        options=engine_options(market)
        options['chart_timeframe']='1D'
        if mode=='whole':
            options['request_bars']['$chart'].update(pointValue=.001,quantityStep='1',minContract='1')
        five=data['five']
        key=options['chart_symbol']
        for interval,rows in (('5',five),('15',smaller_ohlcv(five,3)),('30',smaller_ohlcv(five,6)),('60',data['hour'])):
            options['request_bars'][f'{key}:{interval}']=objects(rows)
        chart=objects(data['chart'])
        cases={}
        for name in names:
            try:
                r=pine_compat.run_script(source[name]+observe,chart,**options)
            except (ValueError,RuntimeError) as error:
                cases[name]={'error':str(error)[:4500]}
                continue
            cases[name]={'broker':r['strategy'],'diagnostics':r['diagnostics'],
                         'plots':[(p.get('title'),p['values']) for p in r['plots']]}
        report[market]=cases
    name='4052-full.json' if mode=='baseline' else '4052-whole-grid.json'
    (ROOT/name).write_bytes(json.dumps(report,separators=(',',':'),allow_nan=False).encode())


if __name__=='__main__':
    main(sys.argv[1])
