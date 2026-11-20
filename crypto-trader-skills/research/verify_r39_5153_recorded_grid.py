"""Independently verify #5153 source state machine, maker witnesses and filled cash flow."""
import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
from decimal import Decimal as D, ROUND_HALF_UP, localcontext
import gzip
import json
from pathlib import Path

from fmz_native_round20_880_capture import sha
from verify_r34_btc_random_book import sum_path
from verify_r37_5774_eth_book import route
from verify_r35_197_recorded_depth import book, close

STEP=200
LEV=20
CASH=D(2500)
ZERO=D(0)
TAKER=D('.0004')
MAKER=D('.0002')


class Boundary(Exception):
    pass


def native_check(abi):
    seq=abi['probe']
    assert seq[0]['result']['PriceTick']==.1 and seq[0]['result']['LotTick']==.001
    assert seq[1]['args']==[20] and seq[2]['result']['Equity']==2500
    assert all(s['end']-s['before']==(0 if s['method'].startswith('Set') else 200) for s in seq)
    assert seq[8]['result'][0]['Price']==36944.4 and seq[12]['result'][0]['Price']==36944.5
    assert seq[9]['result'] and seq[13]['result'] and seq[-2]['result'][0]['Amount']==.030


def predict_orders(run,spec,tape):
    rows=run['events']
    placements={e['id']:e for e in rows if e['kind']=='placement'}
    fills={e['order_id']:e for e in rows if e['kind']=='fill'}
    cancels={e['order_id']:e for e in rows if e['kind']=='cancel'}
    pending_ids=run['ending']['resting']
    terminal_keys=set(fills)|{i for i,x in cancels.items() if x['was_resting']}
    assert set(placements)==terminal_keys|set(pending_ids) and not terminal_keys&set(pending_ids)
    seen=iter(placements.values()); c_events=iter(cancels.values()); polls=iter(run['pending_order_polls'])
    q={x['t']:x['qty'] for x in fills.values()}
    assert len(q)==len(fills)
    q_times=sorted(q)
    times=[r[0] for r in tape]
    assert times==sorted(times) and max(r[2] for r in tape)<6_000_000
    start,end=spec['begin_ms'],spec['end_ms']
    clock=start
    counts=Counter()
    last_ids=None
    def inc(kind):
        nonlocal clock
        clock+=STEP
        counts[kind]+=1
        if clock>=end:raise Boundary
    def ticker():
        inc('ticker')
        i=bisect_right(times,clock*1000)-1
        p=tape[i][2] if i>=0 else spec['marks'][(clock-start)//STEP][2]
        return [clock,p]
    def pos():
        inc('position')
        i=bisect_right(q_times,clock)-1
        v=q[q_times[i]] if i>=0 else [0,0]
        assert not v[1]
        return [clock,v]
    def open_ids():
        nonlocal last_ids
        inc('orders')
        live=[i for i,o in placements.items() if o['t']<clock and (i not in fills or fills[i]['t']>clock)
              and (i not in cancels or cancels[i]['t']>clock)]
        if live!=last_ids:
            types=[int(placements[i]['direction'] not in ('buy','closesell')) for i in live]
            assert next(polls)==[clock,live,types]
            last_ids=live
        return live
    def place(label,units,raw_limit,quote,positions):
        inc('submit')
        actual=next(seen)
        assert (clock,label,units)==(actual['t'],actual['direction'],actual['q'])
        close(actual['raw_limit'],raw_limit)
        close(actual['requested_qty'],D(units)/1000)
        assert actual['source_tick']==quote and actual['source_positions']==positions
        rounded=0 if raw_limit==-1 else int((raw_limit*10).to_integral_value(rounding=ROUND_HALF_UP))*10
        assert actual['limit_cent']==rounded
    try:
        anchor=ticker()
        central=D(anchor[1])/100
        lo,hi=central-300,central+300
        keys=[a for a in rows if a['kind']=='key']
        assert [(x['key'],x['write'],x['t']) for x in keys]==[('buyp',False,start),('buyp',True,anchor[0]),('sellp',True,anchor[0])]
        assert keys[0]['value'] is None
        close(keys[1]['value'],lo);close(keys[2]['value'],hi)
        while True:
            inc('account')
            spot=ticker();holding=pos();open_ids()
            if not holding[1][0]:
                place('buy',30,D(-1),spot,holding)
            else:
                live=open_ids()
                if not live:
                    place('buy',1,lo,spot,holding)
                    place('closebuy',1,hi,spot,holding)
                elif len(live)==1:
                    original=placements[live[0]]
                    for i in open_ids():
                        inc('cancel')
                        observed=next(c_events)
                        assert (observed['t'],observed['order_id'])==(clock,i)
                        assert observed['was_resting']==(i not in fills or fills[i]['t']>clock)
                    step=300 if original['direction']=='buy' else -300
                    lo+=step;hi+=step
    except Boundary:
        assert clock==end
    assert counts==run['call_counts'] and sum(counts.values())==(end-start)//STEP
    assert next(seen,None) is None and next(c_events,None) is None and next(polls,None) is None
    return placements,fills,cancels,times


def witnesses(run,spec,tape,placements,fills,cancels,times):
    used=defaultdict(lambda:defaultdict(int))
    windows=defaultdict(list)
    witnessed=set()
    for i,p in placements.items():
        init=p['t'];label=p['direction'];limit=p['limit_cent'];q=p['q'];buy=label in ('buy','closesell')
        _,asks,bids=book(spec,init)
        top=(asks if buy else bids)[0][0]
        active=limit==0 or (top<=limit if buy else top>=limit)
        assert p['marketable']==active
        if active:
            assert i in fills and fills[i]['liquidity']=='taker' and fills[i]['event_us']==init*1000
            a,stack,_,arrival=route(spec,init,label,q,used)
            if limit:assert all(px<=limit if buy else px>=limit for px,_ in stack)
            assert fills[i]['proof']['side']==stack and fills[i]['proof']['snapshot_us']==arrival
            close(fills[i]['value'],a)
            continue
        terminal=(fills[i]['event_us'] if i in fills else cancels[i]['t']*1000 if i in cancels else spec['end_ms']*1000)
        windows[buy].append((init*1000,terminal))
        start=bisect_right(times,init*1000);stop=bisect_right(times,terminal)
        left=q*run['multiple']; proof=[]
        for seen,id,px,avail,was_buy,raw,local in tape[start:stop]:
            assert seen==max(local,raw)
            if was_buy==int(not buy) and (px<limit if buy else px>limit):
                volume=min(left,avail);left-=volume
                proof.append([id,seen,px,volume,was_buy])
                if not left:break
        if i in fills:
            f=fills[i]
            assert not left and f['liquidity']=='maker' and f['proof']==proof and proof[-1][1]==f['event_us']
            assert f['t']==(f['event_us']+STEP*1000-1)//(STEP*1000)*STEP
            close(f['value'],D(q*limit)/100_000)
            witnessed.update(k[0] for k in proof)
        else:assert left>0, (i,'resting order has an omitted fill')
    assert all(middle[1]<=later[0] for side in windows.values() for middle,later in zip(side,side[1:]))
    return witnessed


def d(v):return D(str(v))


def risk_drawdown(values):
    peak=CASH
    worst=ratio=ZERO
    for increment in values:
        equity=CASH+increment
        peak=max(peak,equity)
        worst=max(worst,peak-equity)
        ratio=max(ratio,(peak-equity)/peak)
    return worst,ratio


def check_metrics(run,spec,placements):
    ordered=defaultdict(list)
    for e in run['events']:
        if e['kind'] in ('fill','funding'):ordered[e['t']].append(e)
    q=[0,0]; basis=[ZERO,ZERO]; opening_fee=[ZERO,ZERO]; carry=[ZERO,ZERO]
    wallet=lowest=CASH
    paid_fee=paid_funding=ZERO
    mark_to_mark=[];fills=[];one=0
    funding=spec['funding'];target=funding['exchange_settlement_ms']*1000
    rate,raw_mark=d(funding['rate']),d(funding['prior_mark'][3])
    low,high=map(d,funding['official_two_minute_mark_price_bounds_USDT'])
    assert low<=raw_mark<=high
    for idx,point in enumerate(spec['marks']):
        clock=spec['begin_ms']+idx*STEP
        mark=d(point[3]);assert point[1]<=point[0]<=clock*1000
        events=ordered[clock]
        assert [ev['event_us'] for ev in events]==sorted(ev['event_us'] for ev in events)
        for e in events:
            if e['kind']=='funding':
                one+=1
                assert e['qty']==q and e['event_us']==target
                close(e['mark'],raw_mark);close(e['rate'],rate)
                for i,size in enumerate(q):
                    signed=(1 if i else -1)*D(size)*raw_mark*rate/1000
                    close(e['cash_flows'][i],signed);carry[i]+=signed;wallet+=signed;paid_funding+=signed
            else:
                p=placements[e['order_id']]
                size=p['q'];label=p['direction'];index=0 if label in ('buy','closebuy') else 1
                amount=d(e['value'])
                fee=amount*(TAKER if e['liquidity']=='taker' else MAKER)
                close(e['fee'],fee);close(e['avg'],amount*1000/size)
                paid_fee+=fee
                wallet-=fee
                if label.startswith('close'):
                    assert q[index]>=size
                    portion=D(size)/q[index]
                    cost=basis[index]*portion
                    covered_fee=opening_fee[index]*portion
                    fee_pair=covered_fee+fee
                    spent=carry[index]*portion
                    gross=(amount-cost)*(1 if index==0 else -1)
                    close(e['pnl'],gross)
                    wallet+=gross
                    fills.append({'gross':gross,'fees':fee_pair,'funding':spent,'after_fees':gross-fee_pair,'net':gross-fee_pair+spent})
                    q[index]-=size
                    basis[index]-=cost
                    opening_fee[index]-=covered_fee
                    carry[index]-=spent
                else:
                    assert amount>=5
                    close(e['pnl'],ZERO)
                    basis[index]+=amount;q[index]+=size;opening_fee[index]+=fee
                assert e['qty']==q
                for observed,expected in zip(e['basis'],basis,strict=True):close(observed,expected)
            close(e['wallet'],wallet)
        unreal=(D(q[0]-q[1])*mark/1000)-basis[0]+basis[1]
        eq=wallet+unreal
        assert eq>D(sum(q))*mark/1000/LEV
        # The runtime's risk check precedes immediate order callbacks at this grid point.
        if not any(ev['kind']=='fill' and ev['liquidity']=='taker' for ev in events):
            lowest=min(lowest,eq-D(sum(q))*mark/1000/LEV)
        mark_to_mark.append(eq-CASH)
    tail=run['ending']
    assert one==1 and tail['quantities']==q and tail['clock']==spec['end_ms']
    close(tail['cash'],wallet);close(tail['eq'],eq);close(tail['quote_mark'],mark);close(run['minimum_buffer_USDT'],lowest)
    for observed,expected in zip(tail['basis'],basis,strict=True):close(observed,expected)
    totals={k:sum((o[k] for o in fills),ZERO) for k in ('gross','fees','funding','after_fees','net')}
    close(mark_to_mark[-1],totals['net']-sum(opening_fee)+sum(carry)+unreal)
    row={k:float(v) for k,v in totals.items()}
    for pref,key in (('gross','gross'),('fee','after_fees'),('net','net')):
        dd,pct=risk_drawdown(sum_path(x[key] for x in fills));row[pref+'_dd']=float(dd);row[pref+'_dd_pct']=float(pct)
        row[pref+'_wins']=sum(x[key]>0 for x in fills)
    row.update(trades=len(fills),unsettled=sum(bool(x) for x in q),starting_equity=float(CASH),execution=0,
               mark_to_market_net=float(mark_to_mark[-1]),remaining_unrealized=float(unreal))
    marked_dd,marked_pct=risk_drawdown(mark_to_mark)
    trace={'mark_drawdown_USDT':marked_dd,'mark_drawdown_fraction':marked_pct,'min_initial_margin_buffer_USDT':lowest,
           'cash_USDT':wallet,'marked_equity_USDT':eq,'sum_execution_fees_USDT':paid_fee,'funding_total_USDT':paid_funding,
           'remaining_position_BTC':[str(D(size)/1000) for size in q],'pending_order_ids':tail['resting'],
           'all_cutoff_carry_USDT':carry,'all_cutoff_entry_fee_USDT':opening_fee,'closed_leg_evidence':fills}
    return row,trace


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('book','input','first','repeat','fixture','official','worker','stage','fixture-code','cross-code','output'):
        p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    raw=a.input.read_bytes();b=a.book.read_bytes();first=a.first.read_bytes()
    assert first==a.repeat.read_bytes()
    job=json.loads(gzip.decompress(raw));book_data=json.loads(gzip.decompress(b));model=json.loads(first)
    assert model['input_sha256']==sha(raw) and model['book_sha256']==sha(b)==job['books_sha256']
    assert model['worker_sha256']==sha(a.worker.read_bytes()) and sha(job['source_py'].encode())==job['source_sha256']
    assert job['settings']=={'H':30,'n1':.001,'grid':300,'xia':50000,'M':20,'shang':60000}
    assert job['starting_cash_USDT']==2500 and job['fees_pct']==[0.02,0.04]
    abi=a.fixture.read_bytes();native_check(json.loads(abi))
    official=a.official.read_bytes();audit=json.loads(official)
    assert audit['input_sha256']==sha(raw) and audit['receipt_sha256']==sha(first)
    assert [(r['day'],r['multiple']) for r in model['results']]==[(d,m) for d in book_data['scope'] for m in (1,2)]
    rows=[];strong=[];details=[]
    used=defaultdict(set)
    with localcontext() as ctx:
        ctx.prec=37
        for r in model['results']:
            day,m=r['day'],r['multiple'];spec=book_data['scope'][day];t=job['tapes'][day]['tape']
            assert r['consumed_tape_rows']==len(t)
            placements,fills,cancels,clocks=predict_orders(r,spec,t)
            trades=witnesses(r,spec,t,placements,fills,cancels,clocks)
            used[day].update(trades)
            v,proof=check_metrics(r,spec,placements)
            v.update(id=5153,name='Simple arithmetic BTC futures grid',market='Binance USD-M BTCUSDT perpetual',
                     source=job['source_url'],group=f'FMZ archived source / recorded strict trade-through {m}x',
                     period=f'{day} 06:00-10:00 UTC',interval='1m original chart and base; 200ms calls',
                     exit='Archived grid partial reductions and mark of remaining inventory',
                     currency='USDT',quote_currency='USDT',currency_decimal_places=8)
            (rows if m==1 else strong).append(v)
            proof.update(day=day,witness_multiple=m,authored_poll_counts=r['call_counts'],
                modeled_taker_fills=sum(x['liquidity']=='taker' for x in fills.values()),
                modeled_maker_fills=sum(x['liquidity']=='maker' for x in fills.values()),
                confirmed_cancels=len(cancels), raw_unique_witnesses=sorted(trades),
                order_trace_sha256=sha(json.dumps(r['events'],separators=(',',':')).encode()),
                order_lifecycle=r['events'])
            details.append(proof)
    for day,w in used.items():assert w=={x['raw_id'] for x in audit['reports'][day]['all_witnesses']}
    assert [x['trades'] for x in rows]==[2,0] and [x['trades'] for x in strong]==[2,0]
    assert [{k:v for k,v in w.items() if k!='group'} for w in rows]==[{k:v for k,v in w.items() if k!='group'} for w in strong]
    report={'coverage':[[5153,'Tested \u00b7 original BTC grid on recorded quotes and strict trade-through',
             'Both exact archived-settings market windows completed. Separate stricter 2x signed volume produced identical metrics. All signed maker witnesses matched checksummed Binance aggregate-trade IDs, while queue outcomes remain modeled.']],
            'results':rows,'strict_double_volume_sensitivity':strong,'diagnostics':details,
            'source':{'url':job['source_url'],'source_sha256':job['source_sha256'],'archive_sha256':job['archive_sha256'],
                'publisher':'https://www.fmz.com/strategy/330440','archived_parameters':job['settings']},
            'data':{day:{'trades':job['tapes'][day]['reference'],'book':q['top25_proof'],'settlement':q['funding'],
                    'official_binance_trade_binding':audit['reports'][day]} for day,q in book_data['scope'].items()},
            'proof':{'input_sha256':sha(raw),'book_sha256':sha(b),'receipt_sha256':sha(first),
                 'native_python_fixture_sha256':sha(abi),'independent_exchange_crosswalk_sha256':sha(official),
                 **{key+'_sha256':sha(getattr(a,key).read_bytes()) for key in ('worker','stage','fixture_code','cross_code')},
                 'independent_verifier_sha256':sha(Path(__file__).read_bytes())}}
    report['method']={
        'archive_scope':'Original active Python and unchanged saved BTCUSDT market, 2,500 USDT, 20x, 30 initial units of 0.001 BTC, 300-USDT grid, 50,000 lower and 60,000 upper side bands. Two prescribed four-hour UTC cold starts use empty native storage. Prices stayed below 60,000 in both scopes and exercised the long side.',
        'timing_and_quotes':'Native Python fixture proves 200ms account, ticker, position, order and cancel calls, 0.001 lot and nearest 0.1 limit tick. Use recorded BTC last-trade prints when available, and observed order-book levels at marketable placement. Every source poll, grid re-anchoring and cancel is independently reconstructed.',
        'maker_model':'A resting order is eligible only after posting. Require same-aggressor signed executed quantity strictly beyond its price while open and before any cancel completes. Each maker order executes in full once the modeled threshold is met, at its own limit. Distinct evidence prices and times are checked against the venue archive by exact raw trade ID, price, size capacity and aggressor side. The primary threshold is one posted quantity. The stricter sensitivity requires twice that executed quantity. Both are counterfactual fills using recorded prints; historical account queue position is outside the evidence.',
        'costs_and_exposure':'Historical 0.02% maker and 0.04% taker apply to their separate legs. Account cash, weighted partial-reduction basis, allocated opening fees, positive collateral, and signed funding at the actual settlement are independently reconciled. Use recorded derivative marks to value open inventory. A no-close window has no closed win-rate estimate.',
        'model_limits':'Observed trades and quotes are fixed. Real exchange queue, response delays, market impact and the source short-side branch are outside these windows. The sensitivity reruns the full source under stricter volume and shares the same market sample.'}
    report['references']=['https://www.fmz.com/strategy/330440','https://docs.tardis.dev/downloadable-csv-files/data-types',
       'https://github.com/binance/binance-public-data','https://www.binance.com/en/blog/futures/421499824684900660']
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8',newline='\n')
    print([(o['period'],o['trades'],o['net'],o['mark_to_market_net']) for o in rows],flush=True)
    print(sha(a.output.read_bytes()),flush=True)


if __name__=='__main__':main()
