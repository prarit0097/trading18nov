"""Verify the #4618 seeded strategy clock, fills and BTC inverse ledger independently."""

import argparse
from collections import defaultdict
from decimal import Decimal, localcontext
from hashlib import sha256
from pathlib import Path
import gzip
import json

D=Decimal
ZERO=D(0)
ONE=D(1)
TAKER=D('0.001')
VENUE_TAKER=D('0.00075')
EPS=D('1e-14')
US=1_000_000
MASK=2**32-1


def sha(v):
    return sha256(v).hexdigest()


def d(v):
    return D(str(v))


def near(found,expected):
    assert abs(d(found)-expected)<=EPS,(found,expected)


def uniform_digits(seed):
    while True:
        seed ^= (seed<<13)&MASK
        seed ^= seed>>17
        seed ^= (seed<<5)&MASK
        yield 10*seed//(MASK+1)


def drawdown(start,changes):
    peak=start
    worst=worst_pct=ZERO
    for change in changes:
        equity=start+change
        peak=max(peak,equity)
        worst=max(worst,peak-equity)
        worst_pct=max(worst_pct,(peak-equity)/peak)
    return worst,worst_pct


def cumulative(seq):
    total=ZERO
    for v in seq:
        total+=v
        yield total


def verify(job,spec,replay):
    start=cash=d(job['cash_btc'])
    prev_cash=cash
    position=0
    entry=entry_last=fee_entry=venue_fee_entry=execution_entry=ZERO
    fees=funding=carry=ZERO
    min_excess=start
    trades=[]
    curves=defaultdict(list)
    orders={o[0]:o for o in replay['orders']}
    draws={v[0]:v for v in replay['draws']}
    assert len(orders)==len(replay['orders']) and len(draws)==len(replay['draws'])
    rng=uniform_digits(replay['seed'])
    skipped=False
    absent_horizon=[]
    probed_depth=None
    max_quote_age=0
    f_at=spec['today']+4*3600
    [cash_flow]=replay['cashflow']
    assert cash_flow['at']==f_at
    funding_candidates=[p for p in spec['funding'] if p[0]<=f_at*US and p[5]==f_at*US]
    prior=funding_candidates[-1]
    rolled=next(p for p in spec['funding'] if p[5]>f_at*US)
    assert all(r[6]==prior[6] for r in funding_candidates)
    assert cash_flow['mark']==prior[2] and cash_flow['alternateMark']==rolled[2]
    assert cash_flow['rate']==float(prior[6])
    assert [r[0] for r in spec['tape']]==list(range(spec['start'],spec['end']+1,job['interval_sec']))
    for i,(r,q,point) in enumerate(zip(spec['tape'],spec['quote_horizons'],replay['path'],strict=True)):
        t=r[0]
        last,mark=d(r[6]),d(r[15])
        assert r[2]<=r[1]<=t*US and r[8]<=r[7]<=t*US and r[14]<=r[13]<=t*US
        if t==f_at:
            assert cash_flow['position']==position
            funding=-position/d(prior[2])*d(prior[6]); cash+=funding; carry+=funding
            near(cash_flow['balance'],cash); near(cash_flow['amount'],funding)
        o=orders.get(t)
        draw=draws.get(t)
        expected=None
        if skipped or t in (spec['start'],spec['end']):
            assert draw is None and o is None
            skipped=False
        else:
            digit=next(rng)
            assert draw==[t,digit,position]
            if position==0:
                expected='buy' if digit>5 else 'sell' if digit<4 else None
            elif position>0 and digit<1:
                expected='closebuy'
            elif position<0 and digit>8:
                expected='closesell'
            if expected is None and position:
                assert (last<=entry+last*d(job['params']['tp_first']) if position>0 else last>=entry-last*d(job['params']['tp_first']))
                assert (last>=entry-last*d(job['params']['st']) if position>0 else last<=entry+last*d(job['params']['st']))
            assert (o[1] if o else None)==expected
        if o:
            assert o[0]==t and o[1]==expected
            label,qty=o[1:3]
            buy=label in ('buy','closesell')
            side=1 if buy else -1
            leg=int(buy)
            px=d(o[3]); depth=d(r[11+leg]); age=t*US-r[7]
            assert px==d(r[9+leg]) and d(r[10])>d(r[9]) and depth>=qty
            assert age<=5*US
            max_quote_age=max(max_quote_age,age)
            excess=depth-qty
            probed_depth=excess if probed_depth is None else min(probed_depth,excess)
            stable=bool(q[2+leg] and q[leg]>=qty)
            assert o[10]==stable
            if not stable:
                absent_horizon.append({'timestamp':t,'direction':label,'requested_contracts':qty,'price_USD':str(px),
                                       'visible_capacity_at_t':str(depth),'minimum_capacity_for_first_100ms':q[leg],
                                       'same_price_for_first_100ms':q[2+leg],'observed_next_updates':q[4]})
            fee=qty/px*TAKER; venue_fee=qty/px*VENUE_TAKER
            execution=side*qty*(ONE/last-ONE/px)
            near(o[4],fee); near(o[5],venue_fee); near(o[6],execution)
            fees+=fee
            cash-=fee
            if label in ('buy','sell'):
                assert position==0 and carry==0
                assert qty==int(D('0.618')*prev_cash*last)
                entry,entry_last,fee_entry,venue_fee_entry,execution_entry=px,last,fee,venue_fee,execution
                assert cash>qty/px
                position=side*qty
                near(o[7],ZERO)
            else:
                assert position==-side*qty
                gross=position*(ONE/entry_last-ONE/last)
                fill_gross=position*(ONE/entry-ONE/px)
                near(o[7],fill_gross)
                costs=execution_entry+execution
                closed_fee=fee_entry+fee
                assert abs(gross-costs-fill_gross)<D('1e-40')
                trades.append({'gross':gross,'gross_at_fills':fill_gross,'fees':closed_fee,'execution':costs,
                    'after_fees':gross-closed_fee,'funding':carry,'net':fill_gross-closed_fee+carry,
                    'net_at_venue_fee_on_same_fills':fill_gross-venue_fee_entry-venue_fee+carry})
                cash+=fill_gross
                position=0
                entry=entry_last=fee_entry=venue_fee_entry=execution_entry=carry=ZERO
                skipped=True
            assert o[9]==position
            near(o[8],cash)
        un=position*(ONE/entry-ONE/mark) if position else ZERO
        excess=cash+un-abs(position)/mark*(D('0.005')+TAKER)
        min_excess=min(min_excess,excess)
        assert excess>D('0.00055')
        assert point[0]==t and point[2]==position and d(point[3])==entry and d(point[4])==mark
        near(point[1],cash); near(point[5],un)
        net_val=cash+un-start
        curves['net'].append(net_val)
        curves['after_fees'].append(net_val-funding)
        curves['gross'].append(net_val+fees-funding)
        prev_cash=cash
    near(replay['minExcess'],min_excess)
    near(replay['ending']['balance'],cash); near(replay['ending']['unrealized'],un)
    expected_rows=len(spec['tape'])-1
    assert replay['count']['ticker']==replay['count']['records']==expected_rows
    assert replay['count']['flag']==len(orders) and replay['count']['plot']==len(draws)
    assert replay['sourceCounts']['entries']==len(trades)+bool(position)
    assert replay['sourceCounts']['closes']==len(trades)
    sums={k:sum((v[k] for v in trades),ZERO) for k in trades[0]}
    assert abs(curves['net'][-1]-(sums['net']+un-fee_entry+carry))<EPS
    assert abs(sums['after_fees']-sums['execution']+sums['funding']-sums['net'])<EPS
    result={k:float(sums[k]) for k in ('gross','fees','after_fees','execution','funding','net')}
    for prefix,key in (('gross','gross'),('fee','after_fees'),('net','net')):
        a,b=drawdown(start,cumulative(x[key] for x in trades))
        result[prefix+'_dd']=float(a); result[prefix+'_dd_pct']=float(b)
        result[prefix+'_wins']=sum(x[key]>0 for x in trades)
    assert result['net']<0
    result.update(id=4618,market='BitMEX XBTUSD perpetual [BTC settlement]',
        period=f"{replay['day']} 02:00–10:00 UTC · seed {replay['seed']}",
        group='FMZ Native · Seeded coin-flip, 0 ms replay',name='抛硬币策略',source=job['source_url'],
        currency='BTC',quote_currency='BTC',currency_decimal_places=12,
        trades=len(trades),unsettled=int(bool(position)),interval='15m chart · 5s quote grid',
        exit='Archived random exits and trailing / stop predicates',starting_equity=float(start),
        remaining_unrealized=float(un),mark_to_market_net=float(curves['net'][-1]))
    info={'day':replay['day'],'seed':replay['seed'],'rng_draw_count':len(draws),'engine_entry_and_close_counts':replay['sourceCounts'],
          'ordered_fills':len(orders),'closed_count':len(trades),'net_wins':result['net_wins'],
          'archived_fee_btc':str(sums['fees']),'closed_gross_at_fills_btc':str(sums['gross_at_fills']),
          'minimum_quote_size_after_fill_contracts':str(probed_depth),'maximum_source_quote_age_us':max_quote_age,
          'funding_settlement_mark_observations':cash_flow,'terminal_position':position,'terminal_fee_btc':str(fee_entry),
          'terminal_funding_btc':str(carry),'terminal_unrealized_btc':str(un),
          'closed_actual_fee_net_btc':str(sums['net_at_venue_fee_on_same_fills']),
          'quote_horizon_failed_bound_count':len(absent_horizon),'failed_100ms_quote_bound_observations':absent_horizon,
          'five_second_equity_drawdown':{k:{'BTC':str(a),'fraction':str(b)} for k,c in curves.items() for a,b in [drawdown(start,c)]}}
    return result,info


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('job','receipt','stage','worker','output'):
        p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    raw=a.job.read_bytes(); saved=a.receipt.read_bytes()
    job=json.loads(gzip.decompress(raw)); replay=json.loads(saved)
    assert sha(raw)==replay['input_sha256'] and sha(job['source'].encode())==replay['source_sha256']==job['source_sha256']
    assert replay['external_requests']==0
    assert job['published_fees_pct']==[0.008,0.1] and job['quote_latency_us']==0 and job['depth_bound_window_us']==100_000
    combos=[(day,n) for day in job['scopes'] for n in job['seeds']]
    assert [(s['day'],s['seed']) for s in replay['results']]==combos
    with localcontext() as precision:
        precision.prec=45
        pairs=[verify(job,job['scopes'][s['day']],s) for s in replay['results']]
    rows=[r for r,_ in pairs]; diagnostics=[d for _,d in pairs]
    assert sum(r['trades'] for r in rows)==2884 and sum(d['ordered_fills'] for d in diagnostics)==5772
    assert [d['quote_horizon_failed_bound_count'] for d in diagnostics]==[1,0,3,12,15,10]
    report={'coverage':[[4618,'Tested · archived BitMEX coin-flip strategy, six prespecified 0 ms bench scopes',
        'Exact XBTUSD source, settings and fee override ran on two captured 8-hour dates with three seeded paths per date. All 5,772 orders met the observed full-quantity instantaneous quote gate. The study counts 2,884 simulated closes. The independent 100 ms bound is separately documented.']],
        'results':rows,'diagnostics':diagnostics,
        'source':{'url':job['source_url'],'publisher':'https://www.fmz.com/strategy/201007','archive_sha256':job['archive_sha256'],
                  'source_sha256':job['source_sha256'],'parameters':job['params'],'fees_pct':job['published_fees_pct']},
        'capture':{d:{'receipts':s['capture_receipts'],'full_day_market_ohlc':s['full_day_ohlc']} for d,s in job['scopes'].items()},
        'proof':{'stage_sha256':sha(a.stage.read_bytes()),'worker_sha256':sha(a.worker.read_bytes()),
            'verification_sha256':sha(Path(__file__).read_bytes()),'input_sha256':sha(raw),'execution_receipt_sha256':sha(saved),
            'native_engine_sha256':replay['engine_sha256'],'r20_capture_sha256':job['r20_capture_sha256']},
        'method':{'scope':'Two direct BitMEX XBTUSD February 1 and August 1 2020 02:00–10:00 UTC slices inside the authored range. Three prespecified xorshift32 seeds (1, 42, 20201120) replace only the randomness source. Independent flat starting wallet 0.001 BTC and 1x, which the publisher did not specify. The original source has 15m chart/5m base and unseeded draws. Benchmark 5s observed quote grid samples are chosen in advance, distinct from the original author FMZ synthetic-tick path.',
            'clock':'Exact JavaScript runs under approved offline isolation. Each market getter can read the current captured time once. Repeated reads advance by one market snapshot, in line with the published FMZ real-tick mechanism. The review uses zero extra request delay as an explicit simulation setting. GetRecords resamples the observed trade path for chart output only. Seeded source math and market-access clock jointly specify the replay; dashboard counters were checked but metrics come from the order ledger.',
            'fills':'The archived strategy submits crossing limits at the current observed bid or ask. Each 0 ms order must fit the full displayed quantity at that time and use only a causal quote that is at most five seconds old. This is a historical model and no orders are externally transmitted. Relative to observed last-trade samples, separate execution cost includes the full direction-dependent quote difference.',
            'delay_sensitivity':'Independently re-stream each full quote capture. Compare the 100 ms minimum available quantity at the same crossing price for each winning gate, with exact timestamps. Only February seed 42 kept the same full-capacity crossing bound for every order. A lost bound leaves the delayed outcome unknown. Keep all six predetermined zero-delay benchmarks as reported, and never infer delayed P&L from a failed observation.',
            'exits':'Independent decision verification matches all seeded digits, order types, amounts and the skipped market tick introduced by each account refresh after a close. Neither the trailing activation nor stop branch triggered on the observed retained paths. Open positions at the fixed boundary are marked without forcing a close.',
            'accounting':'The author sets 0.008% maker and 0.100% taker. All instantaneous simulated executions use the authored taker rate. Market funding at 04:00 UTC uses captured XBTUSD funding, proportional to the signed open position and last observable settlement mark. All values use BTC. A same-fill 0.075% historical fee diagnostic changes only accounting, since it cannot reconstruct new quantities that depend on cash. The independently reconciled marked equity drawdown includes still-open exposure and all debits.'},
        'references':['https://www.fmz.com/strategy/201007','https://www.fmz.com/user-guide/backtesting-system/backtest-modes-and-order-matching',
            'https://www.fmz.com/user-guide/backtesting-system/overview-and-starting-a-backtest',
            'https://docs.tardis.dev/historical-data-details/bitmex','https://www.bitmex.com/blog/why-we-revamped-our-fee-structure'],
        'reproduction':'Stage with the pinned source ZIP and R20 BitMEX SAR capture produced by fmz_native_round20_880_capture.py. Keep the R26 quote-horizon helper beside the stage. Run the worker in the existing network-denied AppContainer, and use this verifier to independently rebuild the report.'}
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print('verified',len(rows),'scopes',sum(r['trades'] for r in rows),'closes',sum(r['net_wins'] for r in rows),'net wins',sha(a.output.read_bytes()))
    print([(r['period'],r['trades'],r['gross'],r['after_fees'],r['net'],r['net_dd_pct']) for r in rows])


if __name__=='__main__':
    main()
