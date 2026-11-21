"""Independent first-entry and release-clock evidence for FMZ #4699."""
from bisect import bisect_right
from math import fsum, isclose
from pathlib import Path
from statistics import pstdev
import sys

from research.fmz_round7_magnifier import date_ms, read, sha256, verified_archives, write
from research.fmz_round26_977 import prices

HOUR=3_600_000
MINUTE=60_000
SOURCE='377ddfdbd0aeeeb0a18550d2f357a50f034ab40810ceadb85c38aa1c4450ec6c'
ENGINE='6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda'
OFFSETS=(21,22,24,30,36,48)


def calculations(daily, chart, delay):
    checkpoints=[day+delay*HOUR for day,_ in daily]
    indices=[bisect_right(checkpoints,bar[0]+HOUR-1)-1 for bar in chart]
    assert min(indices)>=0
    assert all(checkpoints[i]<=bar[0]+HOUR-1 for i,bar in zip(indices,chart,strict=True))
    ratio=[daily[i][1] for i in indices]
    fast=[None]*19+[fsum(ratio[i-19:i+1])/20 for i in range(19,len(ratio))]
    mid,high,low=[None]*48,[None]*48,[None]*48
    for i in range(48,len(fast)):
        vals=fast[i-29:i+1]
        center=fsum(vals)/30
        deviation=1.5*pstdev(vals)
        mid.append(center)
        high.append(center+deviation)
        low.append(center-deviation)
    return fast,mid,high,low


def evidence(delay, chart, children, series, raw):
    assert raw['diagnostics']==raw['broker']['diagnostics']==[]
    for ours,(_,native) in zip(series,raw['plots'][:4],strict=True):
        assert all(a==b or (None not in (a,b) and isclose(a,b,abs_tol=1e-9,rel_tol=0))
                   for a,b in zip(ours,native,strict=True))
    fast,_,high,_=series
    gap=[None]*48+[a-b for a,b in zip(fast[48:],high[48:],strict=True)]
    buys=[i for i in range(49,len(fast)) if gap[i]<-1e-12 and gap[i-1]>=-1e-12]
    actual=[i for i,b in enumerate(dict(raw['plots'])['Buy']) if b]
    if delay<=24:
        assert actual==buys
    else:
        # Nonzero offsets can alter initial same-value histories near a float equality.
        assert all(i in buys or abs(gap[i])<1e-12 for i in actual)
        assert all(i in actual or abs(gap[i-1])<1e-12 or abs(gap[i])<1e-12 for i in buys)
    first=raw['broker']['orders'][0]
    i=first['barIndex']
    assert i==buys[0]+1==actual[0]+1 and first['id']=='Long' and first['direction']=='strategy.long'
    assert chart[i][:2]==children[4*i][:2]==[first['time'],first['price']]
    return {'release_hours_after_cboe_date_utc_midnight':delay,'first_entry':first,
            'native_candidate_positions_closed':len(raw['broker']['trades']),
            'first_signal_index':buys[0],'exact_threshold_tie_omissions':sorted(set(buys)-set(actual))}


def main(work, minute, out):
    assert sha256(work/'source-4699.md')==SOURCE
    assert sha256(work/'priced-runtime/pine_compat/pine_compat.pyd')==ENGINE
    feed_path,native_path=work/'4699-feed.json',work/'4699-native.json'
    feed,native=read(feed_path),read(native_path)
    assert len(feed['pcc'])==24
    assert dict(feed['pcc'])[date_ms('2023-10-04')]==1.59
    cases=[]
    minute_receipts=[]
    for market,candles in feed['markets'].items():
        chart,children=candles['chart'],candles['children']
        assert len(chart)==720 and len(children)==2880 and candles['disagreements']==[]
        controls=[evidence(delay,chart,children,calculations(feed['pcc'],chart,delay),native[market][str(delay)])
                  for delay in OFFSETS]
        archive=verified_archives(minute,market,'1m',('2023-10',),minute_receipts)
        for control in controls:
            first=control['first_entry']
            data=prices(archive,first['time'],first['time']+MINUTE,MINUTE)
            assert data[0][:2]==(first['time'],first['price'])
        assert len({c['first_entry']['price'] for c in controls})>=5
        assert len({c['native_candidate_positions_closed'] for c in controls})>1
        literal=native[market]['None']
        assert literal['diagnostics']==literal['broker']['diagnostics']==[]
        cases.append({'market':market,'release_scenarios':controls,
                      'generic_daily_venue_merge_close_count':len(literal['broker']['trades'])})
    isolation=read(work/'round3-isolation-python.json')
    assert set(isolation)=={'file_error','network_error'} and all(v[0]=='PermissionError' for v in isolation.values())
    write(out,{'schema':'FMZ #4699 verified dataset and release-time sensitivity','source_sha256':SOURCE,
               'source_revision':'7853bb2bf262c4567ac238d3552d97f0e50cb801',
               'source_url':'https://www.fmz.com/strategy/430668',
               'symbol_identity_url':'https://www.tradingview.com/symbols/USI-PCC/',
               'engine_sha256':ENGINE,'input_sha256':sha256(feed_path),'native_sha256':sha256(native_path),
               'receipts':feed['receipts'],'minute_receipts':minute_receipts,
               'exchange_date_ratio_values':feed['pcc'],'isolation':isolation,'cases':cases,
               'coverage':[[4699,'Pending · Cboe daily publication clock',
                            'The 24 exact Cboe total put/call dates and all crypto archives are verified. Six plausible availability clocks change authentic first-entry prices and native settled-trade counts. The saved Pine input does not specify the historical feed release clock. A timestamped source replay is needed before scoring.']],
               'results':[]})


if __name__=='__main__':
    main(*map(Path,sys.argv[1:]))
