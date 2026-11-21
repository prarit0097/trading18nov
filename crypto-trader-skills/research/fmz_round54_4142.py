"""Validate #4142 against an independent daily signal and FIFO ledger."""
from math import isclose
from decimal import Decimal as D
from pathlib import Path
import sys
from research.fmz_round7_magnifier import date_ms, ledger_metrics, read, sha256, write
from research.fmz_round40_4307 import recurrence
from research.fmz_round49_3749 import wilder


def initial_ema(values, period, alpha):
    assert alpha==2/(period+1)
    out=[values[0]]
    for sample in values[1:]:
        out.append((1-alpha)*out[-1]+alpha*sample)
    return out


def indicator(chart, first_sample_seed=False):
 n=len(chart); closes=[r[4] for r in chart]
 ema = initial_ema if first_sample_seed else recurrence
 em1=ema(closes,12,2/13); em2=ema(closes,26,2/27); raw=[None if b is None else a-b for a,b in zip(em1,em2,strict=True)]
 avg=ema(raw,9,2/10); delta=[None if b is None else a-b for a,b in zip(raw,avg,strict=True)]
 rsi=wilder(closes,45)
 H=[None]*13+[max(r[2] for r in chart[i-13:i+1]) for i in range(13,n)]
 L=[None]*13+[min(r[3] for r in chart[i-13:i+1]) for i in range(13,n)]
 h,l=None,None; hp=[];lp=[]; fib=[]
 for i in range(n):
  if 13<=i<26 or (i>=26 and len(set(H[i-13:i+1]))==1): h=H[i]
  if 13<=i<26 or (i>=26 and len(set(L[i-13:i+1]))==1): l=L[i]
  hp.append(h);lp.append(l)
  f=[None]*7 if None in (h,l) else [(h-l)*w+l for w in (0,.21,.3,.5,.62,.7,1)]
  fib.append(f)
 return {'MACD':delta,'RSI':rsi,'initial high':H,'HPivot':hp,'LPivot':lp}, fib


def cross_up(a,b,c,d):
 return None not in (a,b,c,d) and a>b and c<=d

def cross(a,b,c,d):
 return cross_up(a,b,c,d) or cross_up(b,a,d,c)


def exact_signals(chart, ind, fib):
 close=[r[4] for r in chart]; rsi=ind['RSI']; delta=ind['MACD']
 labels=['Long probe','Short probe','probe last long','probe last short'] + [f'probe {side}{k}' for side in ('long','short') for k in range(10)]
 labels += [f'probe s{k}_{t}' for k in range(4) for t in ('sl','tp')]
 vals={name:[] for name in labels}
 times=[0,0]; last_sig=[[0]*10,[0]*10]; last_input=[[0]*10,[0]*10]; last_open=[0]*4
 recent_in=[False]*4
 for i,r in enumerate(chart):
  stamp,opening,H,L,C,vol=r
  flags=[False,False]; vals_rsi=rsi[i-2:i+1] if i>=2 else []
  m=[False,False]
  if i>=2 and None not in vals_rsi and delta[i] is not None:
   m=[delta[i]>0 and rsi[i]<90 and rsi[i]>rsi[i-1]>rsi[i-2],delta[i]<0 and rsi[i]>10 and rsi[i]<rsi[i-1]<rsi[i-2]]
   flags=[m[s] and cross(C,fib[i][f],close[i-1],fib[i-1][f]) for s,f in enumerate((0,6))]
  old_times=times[:]; times=[stamp if f else 0 for f in flags]
  base_sig=[cross_up(times[s],times[1-s],old_times[s],old_times[1-s]) for s in range(2)]
  short_raw=[flags[1]]+[False]*3
  vals['Long probe'].append(flags[0]); vals['Short probe'].append(flags[1]); vals['probe last long'].append(times[0]); vals['probe last short'].append(times[1]);
  prior=[z[:] for z in last_sig]
  for s in (0,1):

   if base_sig[s]: last_sig[s][0]=stamp
  for s in (0,1):
   side='long' if s==0 else 'short'; fs=(1,2,3) if s==0 else (5,4,3)
   gate=[base_sig[s]]+[False]*9
   for k in range(1,10):
    want= m[s] and i and cross(C,fib[i][fs[k-1]],close[i-1],fib[i-1][fs[k-1]]) if k<=3 else flags[s]
    want=want and prior[s][0]>last_sig[1-s][0]
    if k>=2: want=want and last_sig[s][1]>prior[s][0] and not gate[1]
    if s==1 and k<=3: short_raw[k]=bool(want)
    previous=last_input[s][k]
    if want: last_input[s][k]=stamp
    ctrl={1:(),2:(1,),3:(2,),4:(2,3),5:(3,4),6:(2,4,5),7:(2,4,5,6),8:(2,4,5,6,7),9:(2,4,5,6,7,8)}
    gate[k]=cross_up(last_input[s][k],last_sig[s][k-1],previous,prior[s][k-1]) and not any(gate[z] for z in ctrl[k])
    if gate[k]: last_sig[s][k]=stamp
   for k,v in enumerate(gate): vals[f'probe {side}{k}'].append(v)
  for k,active in enumerate(short_raw):
   if active: last_open[k]=opening
   vals[f'probe s{k}_sl'].append(bool(i and H>=last_open[k]+15 and not recent_in[k]))
   vals[f'probe s{k}_tp'].append(bool(i and L<=last_open[k]-30 and not recent_in[k]))
  recent_in=short_raw
 return vals


SIZES=(1,2,4,8,5,6,7,8,9,10)
IDS={1:('Long',)*10,-1:('Short','Short1','Short2','Short3','Short','Short','Short','Short','Short','Short')}
FEE=D('.00075')

def reconcile(tape,flags,broker,collect=False):
    lots=[]
    orders=[]
    trade=[]
    capital=D(1_000_000)
    cash=capital
    watch=[]
    for i,bar in enumerate(tape):
        t,o,h,l,mark,v=bar
        price=D(str(o))
        marked=D(str(mark))
        j=i-1
        if i:
            previously_open={x[0] for x in lots}
            assert len({a[1] for a in lots})<=1
            exit_ids=[IDS[-1][k] for k in range(4) if IDS[-1][k] in previously_open and
                      (flags[f'probe s{k}_tp'][j] or flags[f'probe s{k}_sl'][j])]
            target=[(side,k) for side in (1,-1) for k in range(10) if flags[f'probe {"long" if side>0 else "short"}{k}'][j]]
            assert len({side for side,k in target})<=1,(i,target)
            target=list({IDS[s][k]:(s,k) for s,k in target}.values())
            assert len(target)<=1,(i,target)
            side,k=target[0] if target else (0,None)
            reversal=lots and side and side!=lots[0][1]
            if reversal:
                assert not exit_ids,(i,exit_ids)
            close_volume=0
            for lot in list(lots):
                name,lotside,at,basis,size=lot
                if reversal or name in exit_ids:
                    if not reversal:
                        assert lots[0][0]==name,(i,lots,name)
                        orders.append({'id':f'Close entry(s) order {name}','barIndex':i,'time':t,'direction':'strategy.close','qty':float(size),'price':float(price)})
                    lots.pop(0)
                    cash+=price*lotside*size
                    settled_gross=(price-basis)*lotside*size
                    extra=(basis+price)*size*FEE
                    trade.append({'id':name,'entryTime':at,'exitTime':t,'entryPrice':float(basis),'exitPrice':float(price),'dir':lotside,'qty':float(size),'original_gross':float(settled_gross),'profit':float(settled_gross-extra),'commission':float(extra)})
                    close_volume+=size
            if side:
                assert len(lots)<10
                name=IDS[side][k]; qty=D(SIZES[k]); cash-=price*side*qty
                lots.append((name,side,t,price,qty))
                orders.append({'id':name,'barIndex':i,'time':t,'direction':'strategy.long' if side>0 else 'strategy.short','qty':float(qty+(close_volume if reversal else 0)),'price':float(price)})
        inv=sum((markld[1]*markld[4]*marked for markld in lots),D(0))
        each=broker['equity'][i]
        if not all(isclose(each[k],float(val),abs_tol=1e-7,rel_tol=0) for k,val in (('cash',cash),('marketValue',inv),('equity',inv+cash))):
            print('cash mismatch',i,each,inv+cash,cash,inv,trade[-2:],orders[-2:]); raise ValueError('account')
    for a,b in zip(orders,broker['orders'],strict=True):
        assert a==b,(a,b)
    for a,b in zip(trade,broker['trades'],strict=True):
        assert all(a[k]==b[k] for k in ('id','entryTime','exitTime','entryPrice','exitPrice')),(a,b)
        assert a['dir']*a['qty']==b['qty'] and isclose(a['original_gross'],b['profit'],abs_tol=1e-8)
    assert not lots
    return trade,orders


SOURCE='b2d0aabf92fdd23d369e59bd613fcdc4e90efba5d9dfa8babc7d2227c39b58fc'
ENGINE='6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda'
DAY=86_400_000


def verification(chart,native):
    trace=native['plots']
    assert native['diagnostics']==native['broker']['diagnostics']==[]
    values,fibs=indicator(chart)
    signals=exact_signals(chart,values,fibs)
    wanted={**signals,**{f'probe {k}':v for k,v in values.items()}}
    for name,expected in wanted.items():
        assert all(a==b or (None not in (a,b) and isclose(a,b,abs_tol=1e-7,rel_tol=0))
                   for a,b in zip(expected,trace[name],strict=True)),name
    alternate,bands=indicator(chart,first_sample_seed=True)
    assert exact_signals(chart,alternate,bands)==signals
    return reconcile(chart,signals,native['broker'])


def floating_discrepancies(chart,literal):
    series={
        'h':[None]*13+[max(r[2] for r in chart[i-13:i+1]) for i in range(13,len(chart))],
        'l':[None]*13+[min(r[3] for r in chart[i-13:i+1]) for i in range(13,len(chart))],
    }
    report={}
    for v,extrema in series.items():
        produced=literal['plots']['probe dev '+v]
        discrepancies=[]
        for i in range(26,len(chart)):
            if len(set(extrema[i-13:i+1]))==1 and produced[i]!=0.0:
                assert 0.0 < produced[i] < 1e-6
                discrepancies.append((chart[i][0],extrema[i],produced[i]))
        assert discrepancies
        report[v]={'count':len(discrepancies),'first':discrepancies[0]}
    return report


def main(work,out):
    assert sha256(work/'source-4142.md')==SOURCE
    assert sha256(work/'priced-runtime/pine_compat/pine_compat.pyd')==ENGINE
    feed_path,native_path=work/'4142-feed.json',work/'4142-native.json'
    feed,native=read(feed_path),read(native_path)
    cases=[]
    for market,chart in feed['markets'].items():
        assert len(chart)==1755 and [r[0] for r in chart]==list(range(date_ms('2019-12-23'),date_ms('2024-10-12'),DAY))
        data=native[market]
        assert data['missing_auxiliary']['error']==f'missing request data for symbol `BINANCE:{market}` timeframe `5`'
        literal=data['literal_observed_5m']
        assert literal==data['remove_unused_requests']==data['dead_rsi_control']
        original_counts=[len(data[k]['broker']['trades']) for k in ('literal_observed_5m','literal_utc_cutoff')]
        assert original_counts==([16,16] if market=='BTCUSDT' else [7,8])
        trades,orders=verification(chart,data['exact_zero_deviation'])
        utc_trades,utc_orders=verification(chart[1:],data['exact_zero_deviation_utc'])
        assert trades==utc_trades
        assert [{k:v for k,v in order.items() if k!='barIndex'} for order in orders]==[
            {k:v for k,v in order.items() if k!='barIndex'} for order in utc_orders]
        assert len(trades)==(18 if market=='BTCUSDT' else 20)
        cases.append({'market':market,'trades':trades,'orders':orders,'clock_and_seed_controls_agree':True,
                      'literal_failed_roundoff_controls':floating_discrepancies(chart,literal),
                      'literal_native_counts_before_utc_controls':original_counts})
    isolation=read(work/'round3-isolation-python.json')
    assert set(isolation)=={'file_error','network_error'} and all(v[0]=='PermissionError' for v in isolation.values())
    attrs={'id':4142,'group':'FMZ Pine v5 · exact zero deviation and daily FIFO',
           'exit':'Source next daily open after market reversal or named short close',
           'period':'Binance USD-M · 2019-12-23 to 2024-10-12 UTC exclusive','interval':'1d',
           'archive_interval':'1d','currency':'USDT'}
    results=[{**attrs,'market':c['market'],**ledger_metrics(c['trades'],1_000_000,0)} for c in cases]
    results.append({**attrs,'market':'BTCUSDT + ETHUSDT',**ledger_metrics(
        [trade for c in cases for trade in c['trades']],2_000_000,0)})
    write(out,{'schema':'FMZ #4142 exact mathematical deviation and next-open FIFO benchmark',
               'source_url':'https://www.fmz.com/strategy/469612',
               'source_revision':'7853bb2bf262c4567ac238d3552d97f0e50cb801',
               'source_sha256':SOURCE,'engine_sha256':ENGINE,'feed_sha256':sha256(feed_path),
               'native_sha256':sha256(native_path),'live_broker_quote_archive_receipts':feed['receipts'],
               'fee_overlay_per_side':float(FEE),'isolation':isolation,'cases':cases,
               'coverage':[[4142,'Tested · exact zero-deviation pivot and clock-invariant daily broker',
                            'Unused lower-timeframe and RSI series were isolated using actual lower quotes. The exact zero-deviation identity reconciles every indicator, FIFO reversal and named market exit on both clocks and EMA seed conventions. Literal emulator roundoff remains disclosed separately.']],
               'results':results})


if __name__=='__main__':
    main(*map(Path,sys.argv[1:]))
