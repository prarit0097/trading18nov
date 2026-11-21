"""Prove that initial-capital ambiguity is inert in the archived #4881 replay."""
from datetime import UTC, datetime
from decimal import Decimal as D
import math
from pathlib import Path
import sys

from research.fmz_round7_magnifier import aggregate, ledger_metrics, read, sha256, verified_archives, write
from research.fmz_round26_977 import prices

ORDER_CASH = D(20_000)
FEE = D('.0025')
STEP = D('.001')
SOURCE = '098a846965c3984fb2e34e338735e99820537fc0b3a6efd9657ef381b5589814'
ENGINE = '6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda'
MINUTE = 60_000


def movements(bar, previous):
    _, op, high, low, close, _ = bar
    _, _, previous_high, previous_low, previous_close, _ = previous
    return (abs(high-previous_low), abs(low-previous_high),
            max(high-low, abs(high-previous_close), abs(low-previous_close)))


def calculate(history, row, previous_bands, previous):
    bucket = [*history[-13:], movements(row,previous)]
    if len(bucket) != 14:
        return None,None,False,False
    up,down,tr = (math.fsum(data) for data in zip(*bucket,strict=True))
    up,down = up/tr,down/tr
    a,b = previous_bands
    if a is None:
        return up,down,False,False
    return up,down,up>down and a<=b and row[4]>=previous[2],down>up and b<=a and row[4]<=previous[3]


def model(chart, children, broker, per_bar):
    histories = []
    plot = {name:[] for name in ('VI +','VI -','rsi','entry','exit1','exit2','stop loss','target')}
    previous_bands = None,None
    trades, orders, callbacks, observed_inventory = [],[],[],[]
    position = None
    for i,row in enumerate(chart):
        prior = chart[i-1] if i else None
        ts, opening, high, low, close, volume = row
        price = D(str(opening))
        first = children[4*i]
        assert ts==first[0] and opening==first[1]
        pending = (plot['entry'][-1],plot['exit1'][-1]) if i else (False,False)
        before = position
        qty = D(0)
        if pending[1] and position:
            t,entry,qty = position
            fee = (entry+price)*qty*FEE
            gross = (price-entry)*qty
            trade={'entryTime':t,'exitTime':ts,'entryPrice':float(entry),'exitPrice':float(price),
                   'dir':1,'qty':float(qty),'profit':float(gross-fee),'commission':float(fee)}
            trades.append(trade)
            orders.append({'id':'Close entry(s) order Long','barIndex':i,'time':ts,'direction':'strategy.close',
                           'qty':float(qty),'price':float(price)})
            position = None
        if pending[0] and not before:
            signal_price = D(str(prior[4]))
            qty = ORDER_CASH/signal_price//STEP*STEP
            position = ts,price,qty
            orders.append({'id':'Long','barIndex':i,'time':ts,'direction':'strategy.long',
                           'qty':float(qty),'price':float(price)})
        if qty>0:
            o = ts,opening,opening,opening,opening,0
            _,_,new_entry,new_exit = calculate(histories,o,previous_bands,prior)
            assert not (new_exit if position else new_entry), (i,new_exit,new_entry)
            callbacks.append({'hour':i,'price':opening,'new_entry_signal':new_entry,'new_exit_signal':new_exit})
        if position:
            _,entry,quantity=position
            for child in children[4*i:4*i+4]:
                observed_inventory.extend((float((D(str(p))-entry)*quantity),child[0],p)
                                          for p in child[2:4])
        if before and position is None:
            observed_inventory.append((float((price-before[1])*before[2]),ts,opening))
        values = calculate(histories,row,previous_bands,prior) if prior else (None,None,False,False)
        if prior:
            histories.append(movements(row,prior))
        a,b,entry,exit=values
        previous_bands=a,b
        ratio=100-100/(1+14/((opening+high+low+close)/4))
        assert ratio<70
        for name,value in zip(plot,(a,b,ratio,entry,exit,False,False,False),strict=True):
            plot[name].append(value)
    limits=min(observed_inventory),max(observed_inventory)
    assert -1400 < limits[0][0] <= limits[1][0] < 3200
    assert orders==broker['orders'], next(((a,b) for a,b in zip(orders,broker['orders']) if a!=b),
                                         (len(orders),len(broker['orders'])))
    assert position is None
    for t,native in zip(trades,broker['trades'],strict=True):
        assert all(t[k]==native[k] for k in ('entryTime','exitTime','entryPrice','exitPrice','qty'))
        assert math.isclose(t['profit'],native['profit'],abs_tol=1e-8)
    for name,independent in plot.items():
        assert all(a==b or (None not in (a,b) and math.isclose(a,b,abs_tol=1e-9))
                   for a,b in zip(independent,per_bar[name],strict=True)),name
    return trades,orders,callbacks,limits


def minutes_for(market, stamp, count, daily_directory, monthly_directory, receipts):
    day=datetime.fromtimestamp(stamp/1000,UTC).strftime('%Y-%m-%d')
    if day.startswith('2023-08'):
        name=f'{market}-1m-{day}.zip'
        file=daily_directory/name
        digest=sha256(file)
        assert (daily_directory/f'{name}.CHECKSUM').read_text().split()==[digest,name]
        receipts.append({'name':name,'sha256':digest,
                         'url':f'https://data.binance.vision/data/futures/um/daily/klines/{market}/1m/{name}'})
        selected=[file]
    else:
        selected=verified_archives(monthly_directory,market,'1m',(day[:7],),receipts)
    return prices(selected,stamp,stamp+count*MINUTE,MINUTE)


def main(work, monthly, out):
    assert sha256(work/'source-4881.md')==SOURCE
    assert sha256(work/'priced-runtime/pine_compat/pine_compat.pyd')==ENGINE
    feed_path=work/'4881-feed.json'
    raw_path=work/'4881-native.json'
    feed=read(feed_path)
    native=read(raw_path)
    cases=[]
    minute_receipts=[]
    for market,data in feed['markets'].items():
        chart, children=data['chart'],data['children']
        assert len(chart)==720 and len(children)==2880 and data['disagreements']==[]
        variants=native[market]
        assert 'E_PARSE_EXPR' in variants['literal']['error']
        assert 'E_LEGACY_RSI_OVERLOAD' in variants['wallet20_rsi_original']['error']
        for tag in ('','_confirmed'):
            left=variants['wallet20'+tag]['broker']
            for other in ('wallet50','wallet20_risk50'):
                right=variants[other+tag]['broker']
                assert left['orders']==right['orders'] and left['trades']==right['trades']
        safe=variants['wallet20_confirmed']
        trades,orders,callbacks,bounds=model(chart,children,safe['broker'],safe['plots'])
        quarter_index={row[0]:row for row in children}
        extremes=[]
        for (pnl,stamp,price),column in zip(bounds,(3,2),strict=True):
            minutes=minutes_for(market,stamp,15,work.parent,monthly,minute_receipts)
            assert aggregate(minutes,15)[0][:5]==tuple(quarter_index[stamp][:5])
            extremes.append({'pnl':pnl,'minute':next(r[0] for r in minutes if r[column]==price),
                             'open_of_quarter_hour':stamp,'price':price})
        original=variants['wallet20']['broker']
        difference=[(a,b) for a,b in zip(original['trades'],safe['broker']['trades'],strict=True) if a!=b]
        if market=='BTCUSDT':
            assert len(difference)==1
            ((invalid,valid),)=difference
            assert invalid['entryBarIndex']==invalid['exitBarIndex']==valid['entryBarIndex']==300
            assert valid['exitBarIndex']==301
            assert (invalid['exitPrice'],valid['exitPrice'])==(27291.8,27178.8)
            assert chart[300][1]>chart[299][3]>=chart[300][4]
            minute_route=minutes_for(market,chart[300][0],61,work.parent,monthly,minute_receipts)
            assert minute_route[0][1]==27291.8 and minute_route[-1][1]==27178.8
            assert aggregate(minute_route[:60],60)[0][:5]==tuple(chart[300][:5])
        else:
            assert difference==[]
        assert len(trades)==(17 if market=='BTCUSDT' else 8)
        assert all(not c['diagnostics'] and not c['broker']['diagnostics'] for c in variants.values() if 'broker' in c)
        cases.append({'market':market,'trades':trades,'orders':orders,'opening_callbacks':callbacks,
                      'risk_exposure_bounds':extremes,'unverified_full_bar_callback_difference':difference,
                      'explicit_capital_interpretations_compared':[[20000,20000],[50000,50000],[20000,50000]]})
    isolation=read(work/'round3-isolation-python.json')
    assert set(isolation)=={'file_error','network_error'} and all(v[0]=='PermissionError' for v in isolation.values())
    attrs={'id':4881,'group':'FMZ Pine v4 · capital-invariant causal historical callback',
           'exit':'Source Vortex close and reconstructed earliest opening callback',
           'period':'Binance USD-M · 2023-08-19 to 2023-09-18 UTC exclusive',
           'interval':'1h','archive_interval':'15m','currency':'USDT'}
    scenarios=[(c['market'],c['trades'],1) for c in cases]
    scenarios.append(('BTCUSDT + ETHUSDT',[t for c in cases for t in c['trades']],2))
    normalized=[]
    results=[]
    for market,trades,accounts in scenarios:
        wallet20=ledger_metrics(trades,float(accounts*ORDER_CASH),0)
        wallet50=ledger_metrics(trades,50_000.0*accounts,0)
        assert all(math.isclose(wallet20[k],wallet50[k],abs_tol=1e-8,rel_tol=0)
                   for k in wallet20 if k!='net_dd_pct')
        normalized.append({'market':market,'declared_20k_dd_pct':wallet20['net_dd_pct'],
                           'alternate_50k_dd_pct':wallet50['net_dd_pct']})
        results.append({**attrs,'market':market,**wallet20})
    write(out,{'schema':'FMZ #4881 causal historical replay with initial-capital invariance',
               'source_url':'https://www.fmz.com/strategy/427311','source_revision':'7853bb2bf262c4567ac238d3552d97f0e50cb801',
               'source_sha256':SOURCE,'engine_sha256':ENGINE,'feed_sha256':sha256(feed_path),'native_sha256':sha256(raw_path),
               'market_receipts':feed['receipts'],'minute_extremes_and_callback_receipts':minute_receipts,
               'source_fee_per_side':float(FEE),'isolation':isolation,
               'capital_sensitivity':normalized,'cases':cases,
               'coverage':[[4881,'Tested · capital-invariant archived events with causal callbacks',
                            'Read-only capital write is ambiguous but inert in this sample. Firm risk bounds, all opening callbacks and the exact deprecated RSI ratio are verified. A native full-bar callback was not causal, so only the reconstructed original market chronology is scored.']],
               'results':results})


if __name__=='__main__':
    main(*map(Path,sys.argv[1:]))
