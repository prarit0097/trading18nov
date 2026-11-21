"""Evaluate dead-series dependencies, two clocks and the exact deviation predicate."""
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from replay_2864 import engine_options,pine_compat,sha256
from probe_1216 import objects

SOURCE='b2d0aabf92fdd23d369e59bd613fcdc4e90efba5d9dfa8babc7d2227c39b58fc'


def main():
    raw=(ROOT/'source-4142.md').read_bytes()
    assert sha256(raw)==SOURCE
    fence=chr(96)*3
    (source,)=re.findall(r'(?ms)^'+fence+r' pinescript[^\n]*\n(.*?)^'+fence,raw.decode())
    source,removed=re.subn(r'(?ms)^/\*backtest\n.*?^\*/\n*','',source)
    assert removed==1
    pruned,removed=re.subn(r'(?m)^hfib\d+ = request\.security\([^\n]+\)\n','',source)
    assert removed==11 and not re.search(r'\bhfib\d+\b',pruned)
    lean,removed=re.subn(r'(?m)^rsi(?:long|short) =[^\n]+\n','',pruned)
    assert removed==2 and not re.search(r'\brsi(?:long|short)\b',lean)
    exact=lean
    for src in ('h','l'):
        before=f'ta.dev({src}, lentt) ?'
        after=f'not na({src}[lentt - 1]) and ta.highest({src}, lentt) != ta.lowest({src}, lentt) ?'
        assert exact.count(before)==1
        exact=exact.replace(before,after)
    observe=('\nplot(long?1:0,"Long probe")\nplot(short?1:0,"Short probe")'
             '\nplot(delta,"probe MACD")\nplot(vrsi,"probe RSI")\nplot(h,"probe initial high")'
             '\nplot(hpivot,"probe HPivot")\nplot(lpivot,"probe LPivot")'
             '\nplot(last_long,"probe last long")\nplot(last_short,"probe last short")'
             '\nplot(ta.dev(h,lentt),"probe dev h")\nplot(ta.dev(l,lentt),"probe dev l")\n')
    observe+=''.join(f'\nplot({side}{n or ""}_signal?1:0,"probe {side}{n}")'
                     for side in ('long','short') for n in range(10))
    observe+=''.join(f'\nplot(short{n or ""}_{term}?1:0,"probe s{n}_{term}")'
                     for n in range(4) for term in ('sl','tp'))
    lower=json.loads((ROOT/'4142-observed-5m.json').read_bytes())
    feed=json.loads((ROOT/'4142-feed.json').read_bytes())
    report={}
    for market,chart in feed['markets'].items():
        options=engine_options(market)
        options['chart_timeframe']='1D'
        options['request_bars']['$chart']['priceScale']=100
        key=options['chart_symbol']+':5'
        cases=(('missing_auxiliary',source,chart),('literal_observed_5m',source,chart),
               ('remove_unused_requests',pruned,chart),('dead_rsi_control',lean,chart),
               ('literal_utc_cutoff',lean,chart[1:]),('exact_zero_deviation',exact,chart),
               ('exact_zero_deviation_utc',exact,chart[1:]))
        results={}
        for label,body,prices in cases:
            if label=='literal_observed_5m':
                options['request_bars'][key]=objects(lower[market])
            else:
                options['request_bars'].pop(key,None)
            try:
                result=pine_compat.run_script(body+observe,objects(prices),**options)
            except ValueError as error:
                results[label]={'error':str(error)}
                continue
            results[label]={'plots':{p['title']:p['values'] for p in result['plots']
                                    if p.get('title','').startswith('probe ') or p.get('title') in ('Long probe','Short probe')},
                            'diagnostics':result['diagnostics'],'broker':result['strategy']}
        report[market]=results
    (ROOT/'4142-native.json').write_bytes(json.dumps(report,separators=(',',':'),allow_nan=False).encode())


if __name__=='__main__':
    main()
