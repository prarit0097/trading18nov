"""Isolate the literal run, release-clock transport and documented symmetric crossing."""
from bisect import bisect_right
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from replay_2864 import engine_options,pine_compat,sha256
from probe_1216 import objects

HOUR=3_600_000
SOURCE='8a74f1b585b4236106aa576e00dd76afff0d53f67d7735cb500c5a78eaa3ea42'
REQUEST='request.security(i_VIticker, i_VItf, close)'
TRANSPORT='request.security(i_VIticker, timeframe.period, close)'
CROSS='ta.cross(i_critVFI, VFI)'
EXPLICIT='((VFI > i_critVFI and VFI[1] <= i_critVFI) or (VFI < i_critVFI and VFI[1] >= i_critVFI))'


def fixture():
    chart=[(1_700_000_000_000+HOUR*i,n,n,n,n,1) for i,n in enumerate((12,8,8,12,10,8,10,12))]
    options=engine_options('BTCUSDT')
    options['chart_timeframe']='60'
    script='''//@version=5
indicator("symmetric cross fixture")
k=input.int(10)
plot(ta.cross(k,close)?1:0,"constant first")
plot(ta.cross(close,k)?1:0,"constant second")
plot(((close>k and close[1]<=k) or (close<k and close[1]>=k))?1:0,"explicit")
'''
    result=pine_compat.run_script(script,objects(chart),**options)
    assert result['diagnostics']==[]
    return {p['title']:p['values'] for p in result['plots']}


def main():
    archive=(ROOT/'source-4868.md').read_bytes()
    assert sha256(archive)==SOURCE
    fence=chr(96)*3
    (source,)=re.findall(r'(?ms)^'+fence+r' pinescript[^\n]*\n(.*?)^'+fence,archive.decode())
    source,removed=re.subn(r'(?ms)^/\*backtest\n.*?^\*/\n*','',source)
    assert removed==source.count(REQUEST)==source.count(CROSS)==1
    plain='\n'.join(line.expandtabs(4) for line in source.splitlines())+'\n'
    timed=plain.replace(REQUEST,TRANSPORT)
    fixed=timed.replace(CROSS,EXPLICIT)
    swapped=timed.replace(CROSS,'ta.cross(VFI, i_critVFI)')
    observe=('\nplot(VIX,"obs vix")\nplot(VIup,"obs viu")\nplot(ATRup,"obs atru")'
             '\nplot(VFI,"obs vfi")\nplot(VFI10,"obs vfi10")\nplot(Long?1:0,"obs long")'
             '\nplot(Sseasonal?1:0,"obs seas")\nplot(Svol?1:0,"obs svol")\nplot(Scrit?1:0,"obs crit")\n')
    feed=json.loads((ROOT/'4868-feed.json').read_bytes())
    sessions=feed['vix_sessions']
    releases=[r[0]+21*HOUR+15*60_000 for r in sessions]
    report={}
    for market,data in feed['markets'].items():
        report[market]={}
        options=engine_options(market)
        options['chart_timeframe']='60'
        options['request_bars']['$currencyRates']={
            'schemaVersion':1,'pairs':[{'from':'USDT','to':'USD','rates':[
                {'effectiveTime':int(t),'rate':rate} for t,rate in sorted(feed['rates'].items())]}]}
        chart=data['chart']
        indices=[bisect_right(releases,bar[0]+HOUR-1)-1 for bar in chart]
        assert min(indices)>=0
        aligned=[(bar[0],*sessions[i][1:]) for bar,i in zip(chart,indices,strict=True)]
        original_data={'VIX:D':objects(sessions)}
        timed_data={'VIX:60':objects(aligned)}
        for name,body,requests in (('literal',source,original_data),('whitespace',plain,original_data),
                 ('causal_vix_close',timed,timed_data),('swapped',swapped,timed_data),('verified',fixed,timed_data)):
            result=pine_compat.run_script(body+observe,objects(chart),**{
                **options,'request_bars':{**options['request_bars'],**requests}})
            report[market][name]={'diagnostics':result['diagnostics'],'broker':result['strategy'],
                                  'plots':{p['title']:p['values'] for p in result['plots'] if p.get('title','').startswith('obs ')}}
    (ROOT/'4868-native.json').write_bytes(json.dumps(report,separators=(',',':'),allow_nan=False).encode())
    (ROOT/'4868-cross-fixture.json').write_bytes(json.dumps(fixture(),separators=(',',':')).encode())


if __name__=='__main__':
    main()
