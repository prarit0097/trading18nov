"""Capture the literal failure and three isolated capital interpretations."""
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).parent
sys.path.insert(0,str(ROOT))
from replay_2864 import engine_options,pine_compat,sha256
from probe_1216 import objects


def main():
    archive=(ROOT/'source-4881.md').read_bytes()
    assert sha256(archive)=='098a846965c3984fb2e34e338735e99820537fc0b3a6efd9657ef381b5589814'
    fence=chr(96)*3
    (source,)=re.findall(r'(?ms)^'+fence+r' pinescript[^\n]*\n(.*?)^'+fence,archive.decode())
    source,removed=re.subn(r'(?ms)^/\*backtest\n.*?^\*/\n*','',source)
    assert removed==1
    assert source.count('strategy.initial_capital = 50000')==source.count('initial_capital=20000')==1
    declaration=source.replace('strategy.initial_capital = 50000','')
    whole=declaration.replace('initial_capital=20000','initial_capital=50000')
    risk=declaration.replace('strategy.initial_capital','50000')
    formula='(100.0 - (100.0 / (1.0 + m / totalprice)))'
    observe=('\nplot(myrsi,"rsi")\nplot(entryl?1:0,"entry")\nplot(exit1?1:0,"exit1")'
             '\nplot(exit2?1:0,"exit2")\nplot(close_Stop?1:0,"stop loss")'
             '\nplot(close_Target?1:0,"target")\nplot(sl,"sl")\nplot(tp,"tp")'
             '\nplot(strategy.position_size,"position")\n')
    cases={'literal':source,'wallet20_rsi_original':declaration}
    for name,body in (('wallet20',declaration),('wallet50',whole),('wallet20_risk50',risk)):
        assert body.count('rsi(m, totalprice)')==body.count('calc_on_order_fills=true')==1
        cases[name]=body.replace('rsi(m, totalprice)',formula)
    for name in ('wallet20','wallet50','wallet20_risk50'):
        cases[name+'_confirmed']=cases[name].replace('calc_on_order_fills=true','calc_on_order_fills=false')
    markets=json.loads((ROOT/'4881-feed.json').read_bytes())['markets']
    report={}
    for market,data in markets.items():
        report[market]={}
        options=engine_options(market)
        options['chart_timeframe']='60'
        options['request_bars'][options['chart_symbol']+':15']=objects(data['children'])
        for name,body in cases.items():
            try:
                result=pine_compat.run_script(body+observe,objects(data['chart']),**options)
            except ValueError as error:
                report[market][name]={'error':str(error)}
                continue
            report[market][name]={'diagnostics':result['diagnostics'],
                                   'plots':{p['title']:p['values'] for p in result['plots']},
                                   'broker':result['strategy']}
    (ROOT/'4881-native.json').write_bytes(json.dumps(report,separators=(',',':'),allow_nan=False).encode())


if __name__=='__main__':
    main()
