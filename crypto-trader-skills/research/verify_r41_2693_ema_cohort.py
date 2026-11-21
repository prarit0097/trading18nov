"""Certify the unchanged #2693 host schedule, native closed EMA and recorded fills."""
import argparse
from bisect import bisect_right
from collections import Counter,defaultdict
from decimal import Decimal as D, ROUND_CEILING, localcontext
import gzip
import json
from pathlib import Path

from fmz_native_round20_880_capture import sha
from verify_r35_197_recorded_depth import book,close
from verify_r37_5774_eth_book import route
from verify_r34_btc_random_book import drawdown,sum_path

HOUR=3_600_000
STEP=200
START=D(10_000)
ZERO=D(0)


class End(Exception):
    pass


def d(v):return D(str(v))


def ema_checked(spec, at, period=60):
    now=at//HOUR*HOUR
    stored=spec['bars']
    i=(now-stored[0][0])//HOUR
    closes=[d(r[4]) for r in stored[i-4999:i]]
    assert len(closes)==4999 and stored[i-1][0]==now-HOUR
    value=sum(closes[:period])/period
    alpha=D(2)/(period+1)
    for v in closes[period:]:value+=(v-value)*alpha
    return value, stored[i-1][0]


def schedule(run,spec,placements,fills,cancels,native_limits):
    observed=iter(run['emaProof']);reported=iter(run['poll'])
    commands=iter(placements.values());delete=iter(cancels.values())
    at=start=spec['begin_ms'];end=spec['end_ms'];tape=spec['tape']
    clocks=[x[0] for x in tape]; fclock=sorted((e['t'],i) for i,e in fills.items())
    ft=[t for t,_ in fclock]
    read=Counter();old=();counter=1;locked=False
    def call(name,ms=STEP):
        nonlocal at
        read[name]+=1;at=min(at+ms,end)
        if at==end:raise End
    def idle():call('sleep',3000)
    def current():
        i=bisect_right(ft,at)-1
        if i<0:return [0,0],[ZERO,ZERO]
        e=fills[fclock[i][1]]
        return e['qty'],list(map(d,e['basis']))
    def pending():
        nonlocal old
        call('orders')
        seen=tuple(i for i,p in placements.items() if p['t']<at and (i not in fills or fills[i]['t']>at)
                   and (i not in cancels or cancels[i]['t']>at))
        if seen!=old:
            assert next(reported)==[at,list(seen)];old=seen
        return seen
    def clear():
        while True:
            values=pending()
            if not values:return
            for i in values:
                call('cancel')
                got=next(delete)
                assert got['t']==at and got['id']==i
                assert got['was_resting']==(i not in fills or fills[i]['t']>at)
                idle()
            idle()
    wanted=None
    def place(side,price,units,tick):
        call('submit')
        e=next(commands)
        assert e['t']==at and e['direction']==side and e['n']==units and e['sourceTicker']==tick and e['latestEMA']==wanted
        close(e['desired'],price);close(e['amount'],D(units)/1000)
        assert e['limit']==(0 if price==-1 else native_limits[e['desired']]), (run['day'],e['desired'],price,e['limit'])
        assert e['offset']==side.startswith('close')
        if not e['offset']:assert D(units*e['limit'])/100_000>=20
        q,basis=current();assert e['qty']==q
        for got,want in zip(e['basis'],basis,strict=True):close(got,want)
        return e['id']
    def units(price):return int((D(20_200)/price).to_integral_value(rounding=ROUND_CEILING))
    try:
        while True:
            call('ticker')
            i=bisect_right(clocks,at*1000)-1
            spot=tape[i][2] if i>=0 else spec['marks'][(at-start)//STEP][2]
            last=D(spot)/100; tick=[at,float(last)]
            call('position');q,basis=current()
            call('records');wanted=next(observed)
            anchor,prior=ema_checked(spec,at)
            assert wanted['at']==at and wanted['hour']==prior and wanted['usedRecords']==5000
            close(wanted['ema'],anchor);close(wanted['last'],last)
            gap=abs(last-anchor)/anchor
            close(wanted['deviation'],gap)
            if gap>D('.03'):
                clear()
                locked=True
            if gap<D('.02'):
                locked=False
            if locked:
                call('records');idle();continue
            call('account')
            assert not all(q)
            if counter>10:
                if any(q):
                    clear()
                    side=0 if q[0] else 1
                    place('closebuy' if side==0 else 'closesell',D(-1),q[side],tick)
                    counter=1
                continue
            if not any(q):
                buy=place('buy',last-4,units(last-4),tick)
                sell=place('sell',last+4,units(last+4),tick)
                counter=1
            elif q[0]:
                buy=place('buy',last-20,units(last-20),tick)
                sell=place('closebuy',basis[0]*1000/q[0]+20,q[0],tick)
                counter+=1
            else:
                buy=place('closesell',basis[1]*1000/q[1]-20,q[1],tick)
                sell=place('sell',last+20,units(last+20),tick)
                counter+=1
            while True:
                current_ids=pending()
                if not {buy,sell}.issubset(current_ids):
                    clear()
                    break
                call('account');call('records');idle()
            idle()
    except End:assert at==end
    assert read==run['reads'] and next(delete,None) is None and next(commands,None) is None
    assert next(reported,None) is None and next(observed,None) is None
    assert run['tail']['kv']==[['addCounter',counter]]
    return clocks


def proofs(run,spec,ps,fs,cs,clocks):
    witnesses=set()
    periods=defaultdict(list); used=defaultdict(lambda:defaultdict(int))
    for id,p in ps.items():
        _,ask,bid=book(spec,p['t'])
        buy=p['direction'] in ('buy','closesell')
        limit=p['limit'];top=(ask if buy else bid)[0][0]
        clipped=not limit or (top<=limit if buy else top>=limit)
        assert p['clipped']==clipped
        if clipped:
            assert id in fs
            f=fs[id]
            value,levels,_,arrival=route(spec,p['t'],p['direction'],p['n'],used)
            if limit: assert all(px<=limit if buy else px>=limit for px,_ in levels)
            assert f['fill_type']=='taker' and f['us']==p['t']*1000
            assert f['proof']['local']==arrival and f['proof']['used']==levels
            close(f['value'],value)
            continue
        stop=fs[id]['us'] if id in fs else cs[id]['t']*1000 if id in cs else spec['end_ms']*1000
        begin=p['t']*1000
        periods[buy].append((begin,stop))
        left=p['n']*run['mode'];seen=[]
        for clock,raw,px,qty,side,venue,arrive in spec['tape'][bisect_right(clocks,begin):bisect_right(clocks,stop)]:
            assert clock==max(venue,arrive)
            if side==int(not buy) and (px<limit if buy else px>limit):
                valid=min(qty,left);left-=valid
                seen.append([raw,clock,px,valid,side]);
                if not left:break
        if id in fs:
            f=fs[id]
            assert not left and f['fill_type']=='maker' and f['proof']==seen and f['us']==seen[-1][1]
            assert f['t']==(f['us']+STEP*1000-1)//(STEP*1000)*STEP
            close(f['value'],D(p['n']*limit)/100_000)
            witnesses.update(w[0] for w in seen)
        else:assert left>0
    assert all(a[1]<=b[0] for arm in periods.values() for a,b in zip(arm,arm[1:]))
    return witnesses


def cash_marks(run,spec,ps):
    q=[0,0];cost=[ZERO,ZERO];open_fees=[ZERO,ZERO];carry=[ZERO,ZERO]
    wallet=peak=margin=START
    fees=funding=dd=pct=ZERO
    fills=[];points=defaultdict(list)
    for p in run['events']:
        if p['kind'] in ('funding','fill'):points[p['t']].append(p)
    settled=0
    for i,line in enumerate(spec['marks']):
        t=spec['begin_ms']+i*STEP
        mark=d(line[3]);assert line[1]<=line[0]<=t*1000
        for e in points[t]:
            if e['kind']=='fill':
                p=ps[e['id']];v=d(e['value']);n=p['n']
                side=0 if p['direction'] in ('buy','closebuy') else 1
                fee=v*(D('.0002') if e['fill_type']=='maker' else D('.0004'))
                close(e['fee'],fee);fees+=fee;wallet-=fee
                if p['offset']:
                    assert q[side]>=n
                    part=D(n)/q[side]
                    prior=cost[side]*part
                    combined=fee+open_fees[side]*part
                    flow=carry[side]*part
                    g=(v-prior)*(1 if side==0 else -1)
                    close(e['gross'],g)
                    fills.append({'gross':g,'fees':combined,'after_fees':g-combined,'funding':flow,'net':g-combined+flow})
                    q[side]-=n;cost[side]-=prior;open_fees[side]-=combined-fee;carry[side]-=flow
                    wallet+=g
                else:
                    close(e['gross'],ZERO)
                    cost[side]+=v;q[side]+=n;open_fees[side]+=fee
                assert e['qty']==q
                for row,k in zip(e['basis'],cost,strict=True):close(row,k)
            else:
                assert e['us']==spec['funding']['exchange_settlement_ms']*1000 and e['qty']==q
                m=d(spec['funding']['prior_mark'][3]);rate=d(spec['funding']['rate'])
                close(e['mark'],m);close(e['rate'],rate)
                for s in (0,1):
                    got=D(q[s])*m*rate/1000*(-1 if not s else 1)
                    close(e['signed'][s],got);wallet+=got;funding+=got;carry[s]+=got
                settled+=1
            close(e['wallet'],wallet)
        floating=D(q[0]-q[1])*mark/1000-cost[0]+cost[1]
        equity=wallet+floating
        if not any(e.get('fill_type')=='taker' for e in points[t]):
            margin=min(margin,equity-D(sum(q))*mark/10_000)
        assert margin>0 and equity>D(sum(q))*mark/10_000
        peak=max(peak,equity);dd=max(dd,peak-equity);pct=max(pct,(peak-equity)/peak)
    tail=run['tail'];assert tail['qty']==q and settled==1
    close(tail['wallet'],wallet);close(tail['equity'],equity);close(run['minMargin'],margin);close(tail['mark'],mark)
    for x,y in zip(tail['basis'],cost,strict=True):close(x,y)
    sums={k:sum((r[k] for r in fills),ZERO) for k in ('gross','fees','after_fees','funding','net')}
    close(equity-START,floating+sums['net']-sum(open_fees)+sum(carry))
    row={k:float(v) for k,v in sums.items()}
    for key,metric in [('gross','gross'),('fee','after_fees'),('net','net')]:
        raw,ratio=drawdown(sum_path(r[metric] for r in fills));row[key+'_dd']=float(raw);row[key+'_dd_pct']=float(ratio)
        row[key+'_wins']=sum(r[metric]>ZERO for r in fills)
    row.update(trades=len(fills),execution=0,unsettled=sum(bool(n) for n in q),starting_equity=float(START),
               mark_to_market_net=float(equity-START),remaining_unrealized=float(floating))
    return row,{'paid_fees_USDT':fees,'net_funding_USDT':funding,'conservative_margin_buffer_USDT':margin,
                'marked_drawdown_USDT':dd,'marked_drawdown_fraction':pct,'ending_ETH_qty_by_side':[str(D(n)/1000) for n in q],
                'ending_wallet_USDT':wallet,'ending_equity_USDT':equity,'closed_lot_details':fills}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('input','first','repeat','official','worker','stage','cross-code','rounding','rounding-code','output'):
        p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    raw=a.input.read_bytes();bound=a.first.read_bytes();venue=a.official.read_bytes()
    assert bound==a.repeat.read_bytes()
    rounding_bytes=a.rounding.read_bytes()
    rounding=json.loads(rounding_bytes)
    assert rounding['virtual'] and rounding['default_balance']==10_000 and rounding['replay_receipt_sha256']==sha(bound)
    native_limits={f['desired']:int(d(f['native'])*100) for f in rounding['calls']}
    assert native_limits[3304.3149999999996]==330432

    j=json.loads(gzip.decompress(raw));s=json.loads(bound);x=json.loads(venue)
    assert s['input_sha256']==x['input_sha256']==sha(raw) and x['receipt_sha256']==sha(bound)
    assert s['worker_sha256']==sha(a.worker.read_bytes()) and j['source_sha256']==sha(j['source'].encode())
    assert j['opening_notional_minimum_USDT']==20 and j['initial_cash_USDT']==10000
    assert j['archived_overrides']=={'targetProfit':20,'amount':20,'amountPrecision':3,'isAmountForUSDT':True}
    assert j['author_args_with_overrides']['marginLevel']==10 and j['author_args_with_overrides']['ratio']==1
    rows=[];strong=[];summary=[];official_checks=defaultdict(set)
    with localcontext() as ctx:
        ctx.prec=37
        for r in s['results']:
            day=r['day'];spec=j['scope'][day];mode=r['mode']
            assert not r['error'] and r['tail']['clock']==spec['end_ms'] and r['consumedTapeRows']==len(spec['tape'])
            assert not any(e['kind']=='exchange_notional_reject' for e in r['events'])
            places={o['id']:o for o in r['events'] if o['kind']=='placement'}
            fills={o['id']:o for o in r['events'] if o['kind']=='fill'}
            cancels={o['id']:o for o in r['events'] if o['kind']=='cancel'}
            assert set(places)==set(fills)|set(cancels)|set(r['tail']['remaining'])
            clocks=schedule(r,spec,places,fills,cancels,native_limits)
            witness=proofs(r,spec,places,fills,cancels,clocks)
            official_checks[day].update(witness)
            row,diag=cash_marks(r,spec,places)
            row.update(id=2693,name='EMA-filtered layered entries',market='Binance USD-M ETHUSDT perpetual',period=f'{day} 06:00-10:00 UTC',
                       group=f'FMZ archived source / observed through-volume {mode}x',source=j['url'],
                       currency='USDT',quote_currency='USDT',currency_decimal_places=8,interval='1h / 1m archive with causal completed EMA',
                       exit='Archived maker reductions and cutoff mark' if row['trades'] else 'No close. Open inventory marked at cutoff.')
            (rows if mode==1 else strong).append(row)
            summary.append({'day':day,'threshold':mode,'maker_fills':sum(e['fill_type']=='maker' for e in fills.values()),'taker_fills':sum(e['fill_type']=='taker' for e in fills.values()),'order_cancels':len(cancels),
                'original_ema_readings':r['emaProof'],'raw_witness_ids':sorted(witness),'events':r['events'],'source_call_counts':r['reads'],
                'cutoff_open_orders':r['tail']['remaining'],**diag})
    for day,needed in official_checks.items():assert needed=={r['raw_id'] for r in x['reports'][day]['all_witnesses']}
    assert len(rows)==len(strong)==4 and [o['trades'] for o in rows]==[0,2,0,0]
    assert [o['trades'] for o in strong]==[0,2,0,0]
    report={'coverage':[[2693,'Tested \u00b7 exact ETH source across four consecutive dated windows',
                 'Native FMZ EMA and recorded ETH quote and signed-trade liquidity reproduce four complete archived-scope paths. February includes two verified modeled closed reductions. Maker entries and marked cutoff positions exist in all paths.']],
       'results':rows,'strict_double_volume_sensitivity':strong,'verification':summary,
       'source':{'url':j['url'],'archive_sha256':j['document_sha256'],'source_sha256':j['source_sha256'],
                 'author_form_sha256':j['author_form_sha256'],'archive_overrides':j['archived_overrides'],'author_args':j['author_args_with_overrides'],'selected_windows':j['scope_selection']},
       'data':{k:{'proof':v['proof'],'funding':v['funding'],'binance_trade_crosswalk':x['reports'][k]} for k,v in j['scope'].items()},
       'provenance':{'input_sha256':sha(raw),'receipt_sha256':sha(bound),'official_witness_map_sha256':sha(venue),
             'native_TA_engine_sha256':s['native_engine_sha256'],'native_rounding':rounding, 'native_rounding_receipt_sha256':sha(rounding_bytes),'original_Jan_Apr_input_sha256':j['original_Jan_Apr_input_sha256'],
             **{k+'_sha256':sha(getattr(a,k).read_bytes()) for k in ('worker','stage','cross_code','rounding_code')},'verifier_sha256':sha(Path(__file__).read_bytes())}}
    report['method']={
       'scope':'Exact Binance USD-M ETHUSDT settings from the archive and checksum-bound public parameter form. Cold simulation uses the native 10,000 USDT default, 10x leverage and the four saved source overrides. Four consecutive first-of-month four-hour UTC windows inside the author horizon. January and April were preselected initially. February and March fill the calendar gap and all four outcomes remain present. February supplies two closed outcomes. All windows leave modeled inventory and outstanding orders at cutoff.',
       'ema':'Give the original code native FMZ TA.EMA on 4,999 confirmed hourly bars and the evolving current bar. Independent Decimal arithmetic verifies each selected previous completed-hour EMA. The 3% lock guard did not trigger. The source recalculates on each outer loop. A separate native fixture verifies the exact two-decimal placement prices, including near-half-cent values from weighted entry.',
       'fill':'Use known recorded signed trade prints strictly through each resting price and after posting, supported by another Binance checksummed archive keyed by raw fills. The primary threshold is the full order size and the sensitivity requires double. No maker queue or historical account identity is inferred. Use the contemporaneous book for marketability and verified historical 20 USDT opening minimum.',
       'accounting':'Track the captured funding settlement and marks with exact independent Decimal arithmetic. Maker fees are 0.02%; taker fees are 0.04%, and these scoped paths did not use taker. All fees, closed and open funding allocations, valuations, margin buffer and marked drawdown are listed separately.'}
    report['references']=['https://www.fmz.com/strategy/492116','https://www.fmz.com/lang/en/syntax-guide/fun/market/exchange.getrecords',
       'https://www.fmz.com/lang/en/syntax-guide/fun/ta/ta.ema','https://www.binance.com/en/support/announcement/detail/e4384cba297a4bd2a154be644d5d76f9',
       'https://docs.tardis.dev/downloadable-csv-files/data-types']
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8',newline='\n')
    print([(m['period'],m['trades'],m['mark_to_market_net']) for m in rows],sha(a.output.read_bytes()),flush=True)


if __name__=='__main__':main()
