"""Replay the dated Cboe feed under each explicitly hypothetical availability clock."""
from bisect import bisect_right
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from replay_2864 import engine_options,pine_compat,sha256
from probe_1216 import objects

SOURCE='377ddfdbd0aeeeb0a18550d2f357a50f034ab40810ceadb85c38aa1c4450ec6c'
HOUR=3_600_000
DAILY='request.security("USI:PCC","D",close)'


def main():
    raw=(ROOT/'source-4699.md').read_bytes()
    assert sha256(raw)==SOURCE
    fence=chr(96)*3
    (source,)=re.findall(r'(?ms)^'+fence+r' pinescript[^\n]*\n(.*?)^'+fence,raw.decode())
    source,removed=re.subn(r'(?ms)^/\*backtest\n.*?^\*/\n*','',source)
    assert removed==source.count(DAILY)==1
    clocked=source.replace(DAILY,'request.security("USI:PCC",timeframe.period,close)')
    observe=('\nplot(isBuy?1:0,"Buy")\nplot(isSell?1:0,"Sell")\nplot(isSL?1:0,"SL gate")'
             '\nplot(isTP?1:0,"TP gate")\nplot(isCloseShort?1:0,"Short exit gate")'
             '\nplot(strategy.position_avg_price,"Entry price")\nplot(strategy.position_size,"Position")\n')
    feed=json.loads((ROOT/'4699-feed.json').read_bytes())
    dates=feed['pcc']
    daily=[(t,*[value]*4,0) for t,value in dates]
    report={}
    for market,data in feed['markets'].items():
        chart=data['chart']
        report[market]={}
        options=engine_options(market)
        options['chart_timeframe']='60'
        options['request_bars'][options['chart_symbol']+':15']=objects(data['children'])
        for clock in (None,21,22,24,30,36,48):
            if clock is None:
                body,interval,reference=source,'D',daily
            else:
                body,interval=clocked,'60'
                ready=[t+clock*HOUR for t,_ in dates]
                indices=[bisect_right(ready,b[0]+HOUR-1)-1 for b in chart]
                assert min(indices)>=0
                reference=[(b[0],*daily[i][1:]) for b,i in zip(chart,indices,strict=True)]
            result=pine_compat.run_script(body+observe,objects(chart),**{
                **options,'request_bars':{**options['request_bars'],f'USI:PCC:{interval}':objects(reference)}})
            report[market][str(clock)]={'plots':[(p.get('title'),p['values']) for p in result['plots']],
                                        'diagnostics':result['diagnostics'],'broker':result['strategy']}
    (ROOT/'4699-native.json').write_bytes(json.dumps(report,separators=(',',':'),allow_nan=False).encode())


if __name__=='__main__':
    main()
