"""Independently validate the archived #4868 Cboe close join and USD marks."""
from bisect import bisect_right
from datetime import UTC, datetime
from decimal import Decimal as D
from math import fsum, isclose, log
from pathlib import Path
from statistics import pstdev
import sys

from research.fmz_round7_magnifier import ledger_metrics, read, sha256, write

HOUR=3_600_000
DAY=24*HOUR
CAPITAL=D(100_000)
FEE=D('.0001')
STEP=D('.001')
SOURCE='8a74f1b585b4236106aa576e00dd76afff0d53f67d7735cb500c5a78eaa3ea42'
ENGINE='6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda'


def close_releases(sessions):
    time_of_close=21*HOUR+15*60_000  # New York 16:15 EST in the complete source scope.
    return [row[0]+time_of_close for row in sessions]


def reference_cron(chart, sessions):
    times=close_releases(sessions)
    indices=[bisect_right(times,bar[0]+HOUR-1)-1 for bar in chart]
    assert min(indices)>=0
    return [sessions[i][4] for i in indices], [times[i] for i in indices]


def indicators(chart, vix):
    close=[row[4] for row in chart]
    typical=[fsum(row[2:5])/3 for row in chart]
    volumes=[row[5] for row in chart]
    log_returns=[log(h)-log(typical[i-1] if i else h) for i,h in enumerate(typical)]
    ranges=[max(row[2]-row[3],abs(row[2]-(close[i-1] if i else row[1])),
                abs(row[3]-(close[i-1] if i else row[1]))) for i,row in enumerate(chart)]
    atr,vfi,vfi10,valid_vcp=[],[],[],[]
    atr_up,vix_up,volatility_ok,volatility_exit,money_exit=[],[],[],[],[]
    for i,row in enumerate(chart):
        atr.append(None if i<14 else fsum(ranges[:15])/15 if i==14 else atr[-1]+(ranges[i]-atr[-1])/15)
        avg=fsum(volumes[i-130:i])/130 if i>=130 else None
        clipped=min(volumes[i],2.5*avg) if avg is not None else None
        threshold=.2*row[4]*pstdev(log_returns[i-29:i+1]) if i>=29 else None
        flow=typical[i]-typical[i-1]
        positive=threshold is not None and flow>threshold
        negative=threshold is not None and flow< -threshold
        contribution=clipped if positive else None if negative and clipped is None else -clipped if negative else 0.
        if contribution is not None:
            valid_vcp.append(contribution)
        raw=fsum(valid_vcp[-130:])/avg if len(valid_vcp)>=130 and avg else 0.
        vfi.append(None if i<2 else 0. if i==2 else .5*(vfi[-1]+raw))
        vfi10.append(fsum(vfi[i-9:i+1])/10 if i>=11 else None)
        atr_up.append((atr[i]/min(x for x in atr[i-25:i] if x is not None)-1)*100 if i>=25 else None)
        vix_up.append((vix[i]/min(vix[i-25:i])-1)*100 if i>=25 else None)
        volatility_ok.append(vfi[i] is not None and vfi[i]>-20 and i>=25 and (atr_up[i]<90 or vix_up[i]<60))
        volatility_exit.append(i>=25 and vix_up[i]>120)
        cross=i>=3 and ((vfi[i]>-20 and vfi[i-1]<=-20) or (vfi[i]<-20 and vfi[i-1]>=-20))
        money_exit.append(cross and i>=12 and vfi10[i]<vfi10[i-1])
    assert all(datetime.fromtimestamp(bar[0]/1000,UTC).month==12 for bar in chart)
    return {'vix':vix,'viu':vix_up,'atru':atr_up,'vfi':vfi,'vfi10':vfi10,
            'long':[False,*volatility_ok[:-1]],'seas':[False]*len(chart),
            'svol':volatility_exit,'crit':money_exit}


def account(chart, children, conditions, rates, native):
    assert native['diagnostics']==[]
    balance=CAPITAL
    holding=None
    pending=0
    orders,trades=[],[]
    for j,(c,observed) in enumerate(zip(chart,native['equity'],strict=True)):
        stamp,price=c[:2]
        today=D(str(rates[str(stamp-stamp%DAY)]))
        fill=D(str(price))
        if pending:
            assert children[4*j][:2]==[stamp,price]
            if pending==1:
                quantity=(balance*D('.1')/(fill*today*(1+FEE)))//STEP*STEP
                fee=quantity*fill*today*FEE
                holding=(stamp,fill,quantity,fee)
                balance-=fee
                order={'id':'L','barIndex':j,'time':stamp,'direction':'strategy.long','qty':float(quantity),'price':price}
            else:
                start,entry,quantity,fee=holding
                exit_fee=quantity*fill*today*FEE
                gross=quantity*(fill-entry)*today
                balance+=gross-exit_fee
                # The broker converts realized quote difference at the exit-day rate.
                trades.append({'dir':1,'qty':float(quantity),'entryPrice':float(entry*today),
                               'exitPrice':float(fill*today),'entryTime':start,'exitTime':stamp,
                               'entry_fill_usdt':float(entry),'exit_fill_usdt':price,'usd_rate_at_exit':float(today),
                               'profit':float(gross-fee-exit_fee),'commission':float(fee+exit_fee)})
                holding=None
                order={'id':'Close entry(s) order L','barIndex':j,'time':stamp,'direction':'strategy.close',
                       'qty':float(quantity),'price':price}
            orders.append(order)
        if holding:
            _,basis,amount,_=holding
            cash=balance-amount*basis*today
            value=amount*D(str(c[4]))*today
        else:
            cash,value=balance,D(0)
        for key,expected in (('cash',cash),('marketValue',value),('equity',cash+value)):
            assert isclose(observed[key],float(expected),abs_tol=1e-7,rel_tol=0),(j,key,observed[key],expected)
        close_now=conditions['seas'][j] or (j>0 and (conditions['svol'][j-1] or conditions['crit'][j-1]))
        pending=-1 if close_now and holding else 1 if conditions['long'][j] and holding is None else 0
    assert orders==native['orders']
    assert len(trades)==1 and len(orders)==3 and holding is not None
    for record,broker in zip(trades,native['trades'],strict=True):
        assert all(record[k]==broker[k] for k in ('qty','entryTime','exitTime'))
        assert (record['entry_fill_usdt'],record['exit_fill_usdt'])==(broker['entryPrice'],broker['exitPrice'])
        assert isclose(record['profit'],broker['profit'],abs_tol=1e-8)
    start,entry,quantity,fee=holding
    mark={'open_time':start,'open_price_usdt':float(entry),'quantity':float(quantity),
          'last_bar':chart[-1][0],'last_usdt_mark':chart[-1][4],
          'terminal_rate':float(today),'open_entry_fee_usd':float(fee),
          'unrealized_usd_less_entry_fee':float((D(str(c[4]))-entry)*quantity*today-fee),
          'closed_and_open_marked_equity_usd':float(cash+value)}
    return orders,trades,mark


def main(work, out):
    assert sha256(work/'source-4868.md')==SOURCE
    assert sha256(work/'priced-runtime/pine_compat/pine_compat.pyd')==ENGINE
    feed_path,native_path=work/'4868-feed.json',work/'4868-native.json'
    feed,native=read(feed_path),read(native_path)
    fixture=read(work/'4868-cross-fixture.json')
    assert fixture['constant first']==[0]*8
    assert fixture['constant second']==fixture['explicit']==[0,1,0,1,0,1,0,1]
    cases=[]
    for market,data in feed['markets'].items():
        assert len(data['chart'])==744 and len(data['children'])==2976 and data['disagreements']==[]
        chart=data['chart']
        original=native[market]['literal']
        clean=native[market]['whitespace']
        raw_aligned=native[market]['causal_vix_close']
        resolved=native[market]['verified']
        assert original==clean
        assert original['broker']==raw_aligned['broker']
        assert all(n.get('diagnostics')==[] for n in (original,raw_aligned,resolved))
        for key in ('long','seas','svol','crit'):
            assert original['plots']['obs '+key]==raw_aligned['plots']['obs '+key]
        differences={key:sum(a!=b for a,b in zip(original['plots']['obs '+key],raw_aligned['plots']['obs '+key],strict=True))
                     for key in ('vix','viu')}
        assert differences=={'vix':40,'viu':47}
        assert native[market]['swapped']==resolved
        assert not any(raw_aligned['plots']['obs crit'])
        critical=[i for i,flag in enumerate(resolved['plots']['obs crit']) if flag]
        assert critical==([260,261] if market=='BTCUSDT' else [292])
        causal,available=reference_cron(chart,feed['vix_sessions'])
        conditions=indicators(chart,causal)
        for k,expected in conditions.items():
            assert all(a==b or (None not in (a,b) and isclose(a,b,abs_tol=1e-8,rel_tol=0))
                       for a,b in zip(expected,resolved['plots']['obs '+k],strict=True)),(market,k)
        assert all(t<=r[0]+HOUR-1 for t,r in zip(available,chart,strict=True))
        orders,trades,mark=account(chart,data['children'],conditions,feed['rates'],resolved['broker'])
        cases.append({'market':market,'orders':orders,'trades':trades,'terminal':mark,
                      'legacy_constant_first_cross_missing_indices':critical,
                      'timing_transport_differences':differences,'valid_entry_signal_bars':sum(conditions['long']),
                      'release_times':list(dict.fromkeys(available))})
    isolation=read(work/'round3-isolation-python.json')
    assert set(isolation)=={'file_error','network_error'} and all(v[0]=='PermissionError' for v in isolation.values())
    attrs={'id':4868,'group':'FMZ Pine v5 · actual CBOE close and USD account',
           'exit':'Source money-flow cross, independently resolved symmetric operation',
           'period':'Binance USD-M · December 2023 UTC','interval':'1h','archive_interval':'15m','currency':'USD'}
    results=[{**attrs,'market':c['market'],**ledger_metrics(c['trades'],float(CAPITAL),1)} for c in cases]
    results.append({**attrs,'market':'BTCUSDT + ETHUSDT',**ledger_metrics(
        [t for c in cases for t in c['trades']],float(2*CAPITAL),2)})
    write(out,{'schema':'FMZ #4868 source-invariant CBOE VIX release-timing verification',
               'source_url':'https://www.fmz.com/strategy/439619','source_revision':'7853bb2bf262c4567ac238d3552d97f0e50cb801',
               'source_sha256':SOURCE,'engine_sha256':ENGINE,'input_sha256':sha256(feed_path),
               'native_sha256':sha256(native_path),'receipts':feed['receipts'],'isolation':isolation,
               'symmetric_cross_fixture':fixture,
               'source_fee_per_side':float(FEE),'cases':cases,
               'coverage':[[4868,'Tested · causal CBOE close and repaired symmetric cross',
                            'Official CBOE close transport and USD accounting are independently verified. Swapped operands and an explicit symmetric cross agree with the ledger. The pinned engine suppresses the constant-first crossing in its literal route, which is excluded from performance.']],
               'results':results})


if __name__=='__main__':
    main(*map(Path,sys.argv[1:]))
