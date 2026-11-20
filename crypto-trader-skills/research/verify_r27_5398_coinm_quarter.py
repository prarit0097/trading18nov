"""Verify archived strategy #5398 on the dated ETHUSD COIN-M benchmark."""

import argparse
from collections import defaultdict
from decimal import Decimal, localcontext
from hashlib import sha256
from math import fsum, isclose, sqrt
from pathlib import Path
import gzip
import json

D=Decimal
ZERO=D(0)
ONE=D(1)
FEE=D("0.0005")
FACE=D(10)
HOUR=3600
US=1_000_000
EPS=D("0.00000000000001")


def sha(raw):
    return sha256(raw).hexdigest()


def d(x):
    return D(str(x))


def near(found,expected):
    assert abs(d(found)-expected)<=EPS,(found,expected)


def drawdown(cash,deltas):
    peak=cash
    worst=relative=ZERO
    for delta in deltas:
        eq=cash+delta
        peak=max(peak,eq)
        worst=max(worst,peak-eq)
        relative=max(relative,(peak-eq)/peak)
    return worst,relative


def std(values):
    center=fsum(values)/len(values)
    return sqrt(fsum((x-center)**2 for x in values)/len(values))


def verify_signals(job,spec,replay):
    settings=job['author']['settings']
    assert (settings['EmaLength'],settings['EmaCoefficient'],settings['StddevLength'],settings['StddevDeviations'])==(90,0.004,33,1)
    assert settings['RunInKLinePeriod'] and settings['UseRecordsMiddleValue']
    assert all(not settings[k] for k in ('UseStopLoss','UseTakeProfit','UseTrackingTakeProfit','OnlyTrendJudgment'))
    h=[[r[0],r[2],r[3],r[4]] for r in spec['history']]
    assert len(h)==500 and spec['start']//HOUR*HOUR-h[-1][0]==HOUR
    assert all(b[0]-a[0]==HOUR for a,b in zip(h,h[1:]))
    clock=list(range(spec['start'],spec['end']+1,5))
    assert [row[0] for row in spec['samples']]==clock
    signals=iter(replay['signals'])
    old=0
    cross=position=0
    expected=[]
    for t,tr,q,mark in spec['samples'][:-1]:
        assert t*US>=max(tr[:2]) and t*US>=max(mark[:2])
        active=[tr[2],tr[4],tr[5],tr[6]]
        if active[0]>h[-1][0]:
            assert active[0]-h[-1][0]==HOUR
            h.append(active)
        else:
            assert active[0]==h[-1][0]
            h[-1]=active
        if old==active[0]:
            continue
        old=active[0]
        closes=[x[3] for x in h[:-1]]
        assert len(closes)>=500
        ema=fsum(closes[:90])/90
        for value in closes[90:]:
            ema+=(value-ema)*2/91
        latest=closes[-1]
        if cross==0:
            cross=-1 if latest<=ema else 1
        elif (cross==-1 and latest>=ema) or (cross==1 and latest<=ema):
            cross=2
        middle=[(x[1]+x[2])/2 for x in h[-34:]]
        before=std(middle[:-1]); after=std(middle[1:])
        actual=next(signals)
        assert [t,active[0]*1000,latest,cross,active[1],active[2]]==[actual[k] for k in
            ('time','bar','previous_close','ema_cross','active_high','active_low')]
        assert isclose(actual['ema'],ema,rel_tol=0,abs_tol=1e-9),(actual['ema'],ema)
        assert isclose(actual['std'],after,rel_tol=0,abs_tol=1e-7),(actual['std'],after)
        assert isclose(actual['previous_std'],before,rel_tol=0,abs_tol=1e-7)
        assert abs(before-after)>1e-7 and abs(latest-ema)>1e-9
        direction=1 if latest>ema*1.004 else -1 if latest<ema*0.996 else 0
        if after<=before or not direction or direction==position or (position==0 and cross!=2):
            continue
        if position:
            expected.append((t,'closebuy' if position==1 else 'closesell'))
        expected.append((t,'buy' if direction==1 else 'sell'))
        position=direction
    assert next(signals,None) is None and len(replay['signals'])==24
    assert [(o['at'],o['direction']) for o in replay['orders']]==expected
    assert replay['settingsEvents']==[['contract','quarter'],['leverage',5],['precision',2,0]]
    return expected


def verify_ledger(job,spec,replay):
    assert replay['counts']['sleep']==replay['counts']['record']==17_160
    assert spec['direct_market']['derivative_ticker']['populated_funding_events']==0
    cash=balance=d(job['starting_cash_eth'])
    remaining=0
    old_entry=old_last=entry_fee=entry_execution=fees=ZERO
    exits=[]
    curve=defaultdict(list)
    by_time=defaultdict(list)
    minimum_excess=None
    min_depth=None
    for o in replay['orders']:
        by_time[o['at']].append(o)
    for r,v in zip(spec['samples'],replay['path'],strict=True):
        t,tr,q,m=r
        last=d(tr[6])
        used=defaultdict(int)
        for o in by_time[t]:
            buy=o['side']==1
            amount=o['amount']
            idx=int(buy)
            used[idx]+=amount
            depth=q[6+idx]-used[idx]
            min_depth=depth if min_depth is None else min(min_depth,depth)
            assert depth==o['remainingDepth'] and depth>=0 and q[8+idx]
            assert q==o['quote'] and 0<=t*US-max(q[:2])<=job['age_max_us']
            assert q[2]<q[3] and q[2+idx]==o['fill']
            execution_price=d(o['fill'])
            fee=d(amount)*FACE/execution_price*FEE
            executed=o['side']*d(amount)*FACE*(ONE/last-ONE/execution_price)
            near(o['fee'],fee); near(o['execution'],executed)
            fees+=fee
            cash-=fee
            if o['open']:
                assert remaining==0 and amount==int(balance*d('0.5')*5*last/FACE)
                remaining=o['side']*amount
                old_entry,old_last=execution_price,last
                entry_fee,entry_execution=fee,executed
                near(o['gross'],ZERO)
            else:
                assert remaining==-o['side']*amount
                gross_at_fill=remaining*FACE*(ONE/old_entry-ONE/execution_price)
                gross_at_last=remaining*FACE*(ONE/old_last-ONE/last)
                costs=entry_execution+executed
                fees_roundtrip=entry_fee+fee
                assert abs(gross_at_last-costs-gross_at_fill)<D('1e-39')
                near(o['gross'],gross_at_fill)
                exits.append({'gross':gross_at_last,'gross_at_fills':gross_at_fill,'after_fees':gross_at_last-fees_roundtrip,
                    'fees':fees_roundtrip,'execution':costs,'net':gross_at_fill-fees_roundtrip,'funding':ZERO})
                cash+=gross_at_fill
                remaining=0
                old_entry=old_last=entry_fee=entry_execution=ZERO
            near(o['cash'],cash)
            assert o['qty']==remaining
        mark=d(m[2]); unrealized=remaining*FACE*(ONE/old_entry-ONE/mark) if remaining else ZERO
        excess=cash+unrealized-abs(remaining)*FACE/mark*(D('0.004')+FEE)
        minimum_excess=excess if minimum_excess is None else min(minimum_excess,excess)
        assert excess>D('0.0165')
        assert v[0]==t and v[2]==remaining and d(v[3])==old_entry and d(v[4])==mark
        near(v[1],cash); near(v[5],unrealized)
        curve['net'].append(cash+unrealized-balance)
        curve['gross'].append(curve['net'][-1]+fees)
    near(replay['minimumExcess'],minimum_excess)
    assert replay['criticalDepth']==min_depth
    near(replay['ending']['cash'],cash); near(replay['ending']['unrealized'],unrealized)
    assert abs(sum((x['net'] for x in exits),ZERO)-entry_fee+unrealized-curve['net'][-1])<EPS
    closed={k:float(sum((x[k] for x in exits),ZERO)) for k in ('gross','after_fees','fees','execution','net','funding')}
    assert abs(d(closed['after_fees'])-d(closed['execution'])+d(closed['funding'])-d(closed['net']))<EPS
    for label,metric in (('gross','gross'),('fee','after_fees'),('net','net')):
        cumulative=[]
        for x in exits:
            cumulative.append(x[metric]+(cumulative[-1] if cumulative else ZERO))
        amount,fraction=drawdown(balance,cumulative)
        closed[label+'_dd']=float(amount); closed[label+'_dd_pct']=float(fraction)
        closed[label+'_wins']=sum(x[metric]>0 for x in exits)
    if replay['day']=='2021-11-01':
        assert len(exits)==1 and remaining==22 and closed['net']<0
        assert min_depth==9
    else:
        assert not exits and not remaining and not replay['orders']
    closed.update(id=5398,market='Binance ETHUSD_211231 inverse quarterly [ETH settlement]',
        period=replay['day']+' 00:05–23:55 UTC',group='FMZ Native · Quarterly ETH trend',name='趋势策略V10-公开',
        source=job['source_url'],trades=len(exits),unsettled=int(bool(remaining)),currency='ETH',quote_currency='ETH',
        currency_decimal_places=12,interval='1h chart · 5s poll',exit='Archived EMA and volatility reversal',
        mark_to_market_net=float(curve['net'][-1]),remaining_unrealized=float(unrealized),starting_equity=float(balance))
    info={'day':replay['day'],'orders':replay['orders'],'closed_trade_ETH':[ {k:str(v) for k,v in x.items()} for x in exits],
        'candle_receipts':spec['historical_bars'],'same_day_capture_check':spec['ohlc_tape_check'],
        'official_trade_hour':spec['official_trade_hour'],'official_mark_minute':spec['official_mark_minute'],
        'market_receipts':spec['direct_market'],'evaluated_hourly_signals':len(replay['signals']),
        'startup_cross_seen':any(x['ema_cross']==2 for x in replay['signals']),
        'smallest_equity_excess_ETH':str(minimum_excess),'smallest_remaining_top_depth_contracts':min_depth,
        'wallet_ETH':str(cash),'terminal_position_contracts':remaining,'terminal_entry_fee_ETH':str(entry_fee),
        'terminal_unrealized_ETH':str(unrealized),'observed_marked_net_ETH':str(curve['net'][-1]),
        'observed_marked_drawdown':{k:{'ETH':str(a),'fraction':str(b)} for k,v in curve.items() for a,b in [drawdown(balance,v)]}}
    info['observed_marked_drawdown']['after_fees']=info['observed_marked_drawdown']['net'].copy()
    return closed,info


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('job','receipt','stage','worker','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    a=parser.parse_args()
    input_raw=a.job.read_bytes(); receipt_raw=a.receipt.read_bytes()
    job=json.loads(gzip.decompress(input_raw)); receipt=json.loads(receipt_raw)
    assert sha(input_raw)==receipt['input_sha256'] and sha(job['source'].encode())==receipt['source_sha256']==job['source_sha256']
    assert receipt['requests']==0 and D(job['fee'])==FEE
    assert [s['day'] for s in receipt['results']]==list(job['scope'])
    results=[]; diagnostics=[]
    with localcontext() as precision:
        precision.prec=44
        for source in receipt['results']:
            spec=job['scope'][source['day']]
            verify_signals(job,spec,source)
            result,details=verify_ledger(job,spec,source)
            results.append(result); diagnostics.append(details)
    report={'coverage':[[5398,'Tested · archived EMA/volatility ETH quarterly benchmark',
        'Three predeclared 23h50m Binance ETH inverse-delivery windows ran the exact source and typed published settings. October and December had no entries. November closed one losing short and kept a marked long. The publisher did not specify an exchange, so figures are for this compatible named benchmark.']],
        'results':results,'diagnostics':diagnostics,
        'author':job['author'],'archive':{'url':job['source_url'],'document_sha256':job['document_sha256'],'source_sha256':job['source_sha256']},
        'proof':{'input_sha256':sha(input_raw),'native_receipt_sha256':sha(receipt_raw),
                 'native_engine_sha256':receipt['native_engine_sha256'],'stage_sha256':sha(a.stage.read_bytes()),
                 'worker_sha256':sha(a.worker.read_bytes()),'verify_sha256':sha(Path(__file__).read_bytes())},
        'method':{'settings':'Exact published parameters use typed public settings, including 0 whole-contract precision and STDDEV multiplier 1. The archived offline ETH_USD branch selects quarter; the article gives no venue, starting collateral, or reproducible original backtest dates. Benchmark the contemporaneous Binance ETHUSD_211231, inverse $10 face, 0.02 ETH flat startup, 5x leverage and the author’s 50% initial collateral sizing.',
            'scope':'Predeclared first-of-month Oct/Nov/Dec 2021, 00:05–23:55 UTC each. Starts each replay cold with empty saved state, no interactive commands, and 500 preceding complete 1h bars for the EMA. Only sandboxed exact source executes orders and uses native FMZ EMA/_N and native TA-Lib STDDEV.',
            'causality':'5-second source clock. Trade and mark observations must be available by decision time. Each new 1h candle decision uses the source’s closed-bar EMA and volatility including the real partial current hour. Public Binance and Tardis all-source aggregation agreed on 71 of 72 complete OHLC bars. The one October 23:00 mismatch is a final close after the cutoff. Mark observations matched official minute mark ranges on 51,462 of 51,483 samples. The recorded mark tape remains the equity source.',
            'fills':'Source market orders fill only at observed stable directional top-of-book for 100ms with no more than two seconds of quote age and full displayed capacity. Same-side close and reversal share displayed depth. Executions are historically quoted simulated fills under that model. Position capacity, 5x initial margin, and modeled maintenance plus taker reserve are checked.',
            'settlement':'Contemporaneous Binance basic taker fee of 0.05% in ETH. This dated inverse contract carries no periodic funding. Put quote impact in execution cost against the last-trade reference. Actual fill-price gross, fees, net realized, terminal unrealized, and observed five-second marked drawdown are separately available. No forced exit at data cutoff or delivery simulation.'},
        'references':['https://www.fmz.com/strategy/320782','https://www.fmz.com/bbs-topic/5447',
          'https://www.binance.com/en/support/announcement/detail/18a3602534d744e4966673b953b55257',
          'https://www.binance.com/en-AE/support/faq/detail/85eac2bba0b342819122dc9bd4745e9b',
          'https://www.binance.com/en-BH/blog/futures/421499824684902618',
          'https://www.binance.com/en/support/faq/detail/a3401595e1734084959c61491bc0dbe3'],
        'reproduction':'Use the published R20 archive helper alongside the stage file. Stage the gzip job with --archive and --output and optionally the locally captured public --author-page. Execute the worker in the existing offline FMZ WASM AppContainer. Verify the resulting receipt with --job --receipt --stage --worker --output.'}
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print('verified',len(results),'scopes',sum(x['trades'] for x in results),'closed trades',sha(a.output.read_bytes()))
    print([(x['period'],x['gross'],x['fees'],x['net'],x['mark_to_market_net']) for x in results])


if __name__=='__main__':
    main()
