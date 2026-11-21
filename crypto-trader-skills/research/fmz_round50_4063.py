"""Causal quarter timing and independent Binance USD-M ledger for FMZ #4063."""
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal as D
import math
from pathlib import Path
import sys

from research.fmz_round7_magnifier import aggregate, date_ms, ledger_metrics, read, sha256, verified_archives, write
from research.fmz_round26_977 import prices

DAY=86_400_000
HOUR=3_600_000
CAPITAL=D(20_000)
FEE=D('.0001')
STEP=D('.001')
SOURCE='6957b333b9e4b5829b0c38f19b8c052e5a9b2e0c34e0b4ed9b637491eddcff71'
ENGINE='6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda'


def quarter(stamp):
    dt=datetime.fromtimestamp(stamp/1000,UTC)
    return dt.year, (dt.month-1)//3+1


def direction(current, previous):
    high,low=current
    prior_high,prior_low=previous
    return (high>prior_high and low>prior_low)-(high<prior_high and low<prior_low)


def expected_values(data, confirmed):
    boundaries=[row[0] for row in data['quarter']]
    out={name:[] for name in ('HTF High','HTF Low','prior high','prior low','buy','sell')}
    for row in data['chart']:
        stamp=row[0]
        j=max(i for i,b in enumerate(boundaries) if b<=stamp)
        if confirmed and (j+1==len(boundaries) or stamp+DAY<boundaries[j+1]):
            j-=1
        assert j>=1
        values=data['quarter'][j][2:4]
        previous=data['quarter'][j-1][2:4]
        signal=direction(values,previous)
        for name,value in zip(out,(*values,*previous,int(signal==1),int(signal==-1)),strict=True):
            out[name].append(value)
    return out


def comparison(data, saved, confirmed):
    developing={}
    for row in data['daily']:
        key=quarter(row[0])
        developing.setdefault(key,[]).append(row)
    detail=[]
    for i,bar in enumerate(data['chart']):
        q=quarter(bar[0])
        full=developing[q]
        seen=[r for r in full if r[0]<=bar[0]]
        high,low=max(r[2] for r in seen),min(r[3] for r in seen)
        assert high<=saved['HTF High'][i] and low>=saved['HTF Low'][i]
        future=high<saved['HTF High'][i] or low>saved['HTF Low'][i]
        prior=saved['prior high'][i],saved['prior low'][i]
        asof=direction((high,low),prior)
        frozen=saved['buy'][i]-saved['sell'][i]
        delayed=confirmed['buy'][i]-confirmed['sell'][i]
        if frozen!=asof:
            assert future
        if future:
            detail.append({'bar':bar[0],'future_extreme':True,'saved_signal':frozen,'known_as_of_signal':asof,
                           'confirmed_signal':delayed,'saved_prices':[saved['HTF High'][i],saved['HTF Low'][i]],
                           'known_as_of_prices':[high,low]})
    diff=[r for r in detail if r['saved_signal']!=r['known_as_of_signal']]
    return {'bars_with_future_prices':len(detail),'bars_with_signal_difference_vs_developing_quarter':len(diff),
            'bars_with_signal_difference_vs_confirmed_option':sum((a-b)!=(c-d) for a,b,c,d in zip(
                saved['buy'],saved['sell'],confirmed['buy'],confirmed['sell'],strict=True)),
            'first_direction_changed':diff[0] if diff else None}


def reconciled_model(chart, signals, native, public, market, receipts):
    broker=native['broker']
    assert not broker['diagnostics']
    assert Counter(d['code'] for d in native['diagnostics'])=={'W_LEGACY_SECURITY_LOOKAHEAD':8}
    cash=CAPITAL
    position=None
    pending=0
    trades,orders=[],[]
    for i,(bar,equity) in enumerate(zip(chart,broker['equity'],strict=True)):
        stamp=bar[0]
        opening,close=D(str(bar[1])),D(str(bar[4]))
        if pending and (position is None or position['side']!=pending):
            old=D(0) if position is None else position['side']*position['qty']
            available=cash+opening*old
            qty=available/(opening*(1+FEE))//STEP*STEP
            assert qty>0
            if position is not None:
                initial=position['price']
                old_qty=position['qty']
                fee=(initial+opening)*old_qty*FEE
                gross=(opening-initial)*position['side']*old_qty
                trades.append({'id':position['id'],'dir':position['side'],'entryTime':position['time'],
                               'exitTime':stamp,'entryPrice':float(initial),'exitPrice':float(opening),
                               'qty':float(old_qty),'profit':float(gross-fee),'commission':float(fee)})
            name='Buy' if pending>0 else 'Sell'
            change=pending*qty-old
            orders.append({'id':name,'barIndex':i,'time':stamp,'direction':'strategy.long' if pending>0 else 'strategy.short',
                           'qty':float(abs(change)),'price':float(opening)})
            cash-=change*opening+abs(change)*opening*FEE
            position={'id':name,'time':stamp,'side':pending,'qty':qty,'price':opening}
            month=datetime.fromtimestamp(stamp/1000,UTC).strftime('%Y-%m')
            hours=prices(verified_archives(public,market,'1h',(month,),receipts),stamp,stamp+DAY,HOUR)
            assert aggregate(hours,24)[0][:5]==tuple(bar[:5])
            assert hours[0][1]==float(opening)
        inventory=D(0) if position is None else position['side']*position['qty']*close
        for key,value in (('cash',cash),('marketValue',inventory),('equity',cash+inventory)):
            assert math.isclose(equity[key],float(value),rel_tol=0,abs_tol=1e-7),(market,i,key,equity[key],value)
        pending=signals['buy'][i]-signals['sell'][i]
    assert orders==broker['orders']
    for expected,observed in zip(trades,broker['trades'],strict=True):
        for key in ('id','entryTime','exitTime','entryPrice','exitPrice'):
            assert expected[key]==observed[key]
        assert expected['qty']*expected['dir']==observed['qty']
        assert math.isclose(expected['profit'],observed['profit'],abs_tol=1e-8)
    assert position is not None
    terminal={**position,'qty':float(position['qty']),'price':float(position['price']),'mark':float(close),
              'gross_unrealized':float((close-position['price'])*position['side']*position['qty']),
              'fee_paid_open_trade':float(position['price']*position['qty']*FEE)}
    return trades,orders,terminal


def main(work, public, out):
    assert sha256(work/'source-4063.md')==SOURCE
    assert sha256(work/'priced-runtime/pine_compat/pine_compat.pyd')==ENGINE
    inp=work/'4063-feed.json'
    raw=work/'4063-native.json'
    feed,native=read(inp),read(raw)
    receipts=[]
    cases=[]
    for market,data in feed['markets'].items():
        assert len(data['chart'])==371
        assert [r[0] for r in data['chart']]==list(range(date_ms('2022-11-14'),date_ms('2023-11-20'),DAY))
        saved=expected_values(data,False)
        confirmed=expected_values(data,True)
        for mode,plots in (('as_saved',saved),('confirmed_input',confirmed)):
            for key,series in plots.items():
                assert native[market][mode]['plots'][key]==series,(market,mode,key)
        diagnostic=comparison(data,saved,confirmed)
        assert diagnostic['bars_with_signal_difference_vs_developing_quarter']>0
        trades,orders,terminal=reconciled_model(data['chart'],confirmed,native[market]['confirmed_input'],public,market,receipts)
        assert len(trades)==1 and len(orders)==2
        cases.append({'market':market,'saved_repainting_diagnostic':diagnostic,'trades':trades,'orders':orders,'terminal':terminal})
    isolation=read(work/'round3-isolation-python.json')
    assert set(isolation)=={'file_error','network_error'} and all(v[0]=='PermissionError' for v in isolation.values())
    attrs={'id':4063,'group':'FMZ Pine v4 · source option lookahead=false, offset=0','exit':'Quarter-end confirmed signals and next daily open reversals',
           'period':'Binance USD-M · 2022-11-14 to 2023-11-20 UTC exclusive','interval':'1d','archive_interval':'1h','currency':'USDT'}
    results=[{**attrs,'market':c['market'],**ledger_metrics(c['trades'],float(CAPITAL),1)} for c in cases]
    results.append({**attrs,'market':'BTCUSDT + ETHUSDT','group':attrs['group']+' · pooled',**ledger_metrics(
        [t for c in cases for t in c['trades']],float(2*CAPITAL),2)})
    write(out,{'schema':'FMZ #4063 author-confirmed input replay with saved-default future-price diagnostics',
               'source_url':'https://www.fmz.com/strategy/432807','source_revision':'7853bb2bf262c4567ac238d3552d97f0e50cb801',
               'source_sha256':SOURCE,'engine_sha256':ENGINE,'input_sha256':sha256(inp),'native_sha256':sha256(raw),
               'daily_source_receipts':feed['receipts'],'event_hour_receipts':receipts,'isolation':isolation,
               'source_fee_per_side':float(FEE),'cases':cases,
               'coverage':[[4063,'Tested · author option lookahead=false; saved default repaints',
                        'Actual source option confirms each 3M bar before using its range. The saved default supplies future prices and has no reported performance. Every reported order independently matches price, quantity, fees and equity.']],
               'results':results})


if __name__=='__main__':
    main(*map(Path,sys.argv[1:]))
