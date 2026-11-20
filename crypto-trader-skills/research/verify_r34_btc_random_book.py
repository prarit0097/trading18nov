"""Verify recorded BBO depth, the archived stochastic rules and the cash ledger."""
import argparse
from collections import Counter
from decimal import Decimal as D, localcontext
import gzip
import itertools
import json
from pathlib import Path

from fmz_native_round20_880_capture import sha

ZERO=D(0)
CENT=100
QUANTITY=1000
INITIAL=D(10_000)
TAKER=D('0.0004')
STEP=200
MASK=2**32-1
DURATION={197:400,4692:200,5685:5800}
LEVERAGE={197:20,4692:50,5685:30}


def dec(x):
    return D(str(x))


def near(actual,expected):
    assert abs(dec(actual)-expected)<D('0.000000001'),(actual,expected)


def random_sequence(seed,invert):
    while True:
        seed^=(seed<<13)&MASK
        seed^=seed>>17
        seed^=(seed<<5)&MASK
        yield MASK-seed if invert else seed


def decisions(strategy,position,profit,margin,bits):
    if not position:
        if strategy==197:
            if bits==2**31:
                return []
            order='buy' if bits<2**31 else 'sell'
        elif strategy==4692:
            order='sell' if bits<2**31 else 'buy'
        else:
            if bits==0:
                return []
            order='buy' if bits<=2**31 else 'sell'
        return [('Buy' if order=='buy' else 'Sell',order,D('0.015') if strategy==197 else D('0.001'))]
    amount=abs(position)
    if profit>1:
        close=('Sell','closebuy',amount) if position>0 else ('Buy','closesell',amount)
        return [close] if strategy!=5685 else [close,('Sell','buy' if position>0 else 'sell',D('0.001'))]
    if profit<-(D(1) if strategy==197 else margin):
        return [('Buy','buy',D('0.015') if strategy==197 else D('0.001'))] if position>0 else [
                 ('Sell','sell',D('0.015') if strategy==197 else D('0.001'))]
    return []


def get(spec,key,t):
    start=spec['begin_ms']
    assert start<=t<=spec['end_ms'] and (t-start)%STEP==0
    row=spec[key][(t-start)//STEP]
    assert row[1]<=row[0]<=t*1000
    return row


def quote_guard(spec,t,direction,qty):
    q=get(spec,'quotes',t)
    leg=int(direction in ('buy','closesell'))
    assert q[2]<q[3] and min(q[2:6])>0 and min(q[6:])>=0
    return D(q[2+leg])/CENT,D(q[4+leg])/QUANTITY,D(q[6+leg])/QUANTITY,t*1000-q[0],q


def replay_rule(run,spec):
    strategy=run['id']
    assert run['leverage']==LEVERAGE[strategy]
    observed=iter(run['orders'])
    draws=iter(run['draws'])
    rng=random_sequence(run['seed'],run['mirror'])
    pos=basis=ZERO
    clock=spec['begin_ms']+DURATION[strategy]
    end=spec['end_ms']
    unsupported=False
    for t,recorded_pos,recorded_basis,recorded_profit,recorded_margin in run['decisions']:
        assert t==clock<end
        last=D(get(spec,'marks',t)[2])/100
        average=basis/abs(pos) if pos else ZERO
        profit=pos*(last-average)
        margin=basis/LEVERAGE[strategy]
        near(recorded_pos,pos); near(recorded_basis,average);near(recorded_profit,profit);near(recorded_margin,margin)
        bits=None
        if not pos:
            bits=next(rng)
            assert next(draws)==[t,bits,0]
        waiting=(1000 if strategy==197 else 60_000 if pos else 0)
        expected=decisions(strategy,pos,profit,margin,bits)
        for api,direction,qty in expected:
            clock+=STEP+run['delay']
            if clock>=end:
                break
            price,depth,_,age,book=quote_guard(spec,clock,direction,qty)
            failed=depth<qty or age>5_000_000
            if failed:
                abort=run['unsupported']
                assert abort['time']==clock and abort['api']==api and abort['direction']==direction
                near(abort['qty'],qty)
                near(abort['visible_size'],depth)
                assert abort['book']==book and abort['quote_age_us']==age
                unsupported=True
                break
            o=next(observed)
            assert o[:3]==[clock,api,direction]
            near(o[3],qty);near(o[4],price)
            sign=1 if direction in ('buy','closesell') else -1
            if direction.startswith('close'):
                assert abs(pos)==qty and pos*sign<0
                pos=basis=ZERO
            else:
                assert not pos or pos*sign>0
                pos+=sign*qty
                basis+=qty*price
        if unsupported:
            assert run['ending']['time']==clock
            break
        clock+=waiting+DURATION[strategy]
    assert unsupported==bool(run['unsupported']) and (unsupported or clock>=end==run['ending']['time'])
    assert next(observed,None) is None and next(draws,None) is None
    near(run['ending']['basis'],basis);near(run['ending']['position'],pos)


def sum_path(values):
    total=ZERO
    for v in values:
        total+=v
        yield total


def drawdown(values):
    peak=INITIAL
    largest=ratio=ZERO
    for val in values:
        now=INITIAL+val
        peak=max(peak,now)
        largest=max(largest,peak-now)
        ratio=max(ratio,(peak-now)/peak)
    return largest,ratio


def accounting(run,spec):
    source_orders={o[0]:o for o in run['orders']}
    assert len(source_orders)==len(run['orders'])
    funding=spec['funding']
    [event]=run['funding']
    assert event[0]==funding['boundary_ms']
    assert all(abs(t-funding['exchange_settlement_ms'])>=200 for t in source_orders)
    prior=funding['prior_mark']
    upper,lower=max(funding['official_two_minute_mark_price_bounds_USDT']),min(funding['official_two_minute_mark_price_bounds_USDT'])
    assert lower<=prior[3]<=upper and prior[1]<=prior[0]<=event[0]*1000 and prior[5]==event[0]*1000
    assert abs(float(prior[6])-funding['rate'])<1e-10
    wallet=INITIAL
    qty=basis=entry_fees=entry_carry=fee_total=carry_total=ZERO
    dd=ZERO
    peak=INITIAL
    dd_pct=ZERO
    min_buffer=INITIAL
    max_age=cap_failures=0
    close_rows=[]
    for t in range(spec['begin_ms'],spec['end_ms']+1,STEP):
        mark=d_at(spec,t)
        if t==event[0]:
            carry=-qty*dec(prior[3])*dec(funding['rate'])
            assert event[:1]==[funding['boundary_ms']]
            near(event[1],qty);near(event[2],dec(prior[3]));near(event[3],dec(funding['rate']));near(event[4],carry)
            entry_carry+=carry
            carry_total+=carry
            wallet+=carry
            near(event[5],wallet)
        fill=source_orders.get(t)
        if fill is not None:
            _,api,direction,n,px,fee,gross,post_cash,next_qty,cap,cap100,age,local,last,logged_mark=fill
            size=dec(n)
            price,visible,stable,verified_age,q=quote_guard(spec,t,direction,size)
            assert visible>=size and 0<=verified_age<=5_000_000 and local==q[0] and age==verified_age
            near(px,price);near(cap,visible);near(cap100,stable);near(logged_mark,mark)
            near(last,D(get(spec,'marks',t)[2])/100)
            expected_fee=size*price*TAKER
            near(fee,expected_fee)
            wallet-=expected_fee
            fee_total+=expected_fee
            max_age=max(age,max_age)
            cap_failures+=int(stable<size)
            if direction.startswith('close'):
                edge=qty*(price-basis/abs(qty))
                assert abs(qty)==size
                near(gross,edge)
                wallet+=edge
                charged=entry_fees+expected_fee
                close_rows.append({'at':t,'gross':edge,'fees':charged,'funding':entry_carry,
                    'after_fees':edge-charged,'net':edge-charged+entry_carry})
                qty=basis=entry_fees=entry_carry=ZERO
            else:
                near(gross,ZERO)
                sign=1 if direction=='buy' else -1
                qty+=sign*size
                basis+=price*size
                entry_fees+=expected_fee
            near(post_cash,wallet);near(next_qty,qty)
        floating=qty*(mark-basis/abs(qty)) if qty else ZERO
        equity=wallet+floating
        buffer=equity-abs(qty)*mark/D(run['leverage'])
        assert buffer>0
        min_buffer=min(min_buffer,buffer)
        peak=max(peak,equity)
        dd=max(dd,peak-equity)
        dd_pct=max(dd_pct,(peak-equity)/peak)
    ending=run['ending']
    near(ending['wallet'],wallet);near(ending['position'],qty);near(ending['basis'],basis)
    near(ending['mark'],mark);near(ending['unrealized'],floating)
    v={k:sum((x[k] for x in close_rows),ZERO) for k in ('gross','fees','after_fees','funding','net')}
    near(equity-INITIAL,v['net']-entry_fees+entry_carry+floating)
    result={key:float(value) for key,value in v.items()}
    for alias,column in (('gross','gross'),('fee','after_fees'),('net','net')):
        loss,ratio=drawdown(sum_path(x[column] for x in close_rows))
        result[alias+'_dd']=float(loss)
        result[alias+'_dd_pct']=float(ratio)
        result[alias+'_wins']=sum(x[column]>ZERO for x in close_rows)
    result.update(trades=len(close_rows),unsettled=int(bool(qty)),starting_equity=float(INITIAL),execution=0,
                  mark_to_market_net=float(equity-INITIAL),remaining_unrealized=float(floating))
    return result,{'draws':len(run['draws']),'modeled_full_visible_orders':len(source_orders),'price_size_stable_first_100ms':len(source_orders)-cap_failures,
                   'max_order_quote_age_us':max_age,'fees_total_USDT':fee_total,'funding_total_USDT':carry_total,
                   'min_funded_initial_margin_buffer_USDT':min_buffer,'final_contracts_BTC':qty,
                   'marked_drawdown_USDT':dd,'marked_drawdown_fraction':dd_pct,'ending_wallet_USDT':wallet,
                   'complete_order_and_rng_path_sha256':sha(json.dumps([run['orders'],run['draws']],separators=(',',':')).encode())}


def d_at(spec,t):
    return dec(spec['marks'][(t-spec['begin_ms'])//STEP][3])


def check_host(rows):
    assert rows[1][0]=='GetAccount' and rows[1][4]['Balance']==10_000 and rows[1][4]['Stocks']==3
    uses=[r for r in rows if r[0] in ('GetAccount','GetPosition','GetTicker','Buy','Sell')]
    assert all(r[3]-r[2]==200 for r in uses)
    setters=[x for x in rows if x[0].startswith('Set')]
    assert all(x[3]==x[2] for x in setters)
    assert rows[5][:2]==['SetDirection',['buy']] and rows[6][:2]==['Sell',[-1,0.001]]
    assert rows[7][4][0]['Type']==0
    assert rows[-1][4][0]['Type']==0 and rows[-1][4][0]['Offset']==0
    assert rows[-1][4][0]['AvgPrice']==rows[4][4]['Sell']
    assert rows[-1][4][-1]['AvgPrice']==rows[4][4]['Buy']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('input','first','second','stage','worker','host','host-receipt','output'):
        parser.add_argument('--'+key,type=Path,required=True)
    a=parser.parse_args()
    receipt=a.first.read_bytes(); raw=a.input.read_bytes()
    assert receipt==a.second.read_bytes()
    job=json.loads(gzip.decompress(raw)); proof=json.loads(receipt)
    assert sha(raw)==proof['input_sha256'] and sha(a.worker.read_bytes())==proof['host_sha256']
    host_receipt=a.host_receipt.read_bytes()
    assert sha(host_receipt)==job['control_sha256'] and json.loads(host_receipt)==job['initial_cash_native_control']
    check_host(job['initial_cash_native_control'])
    assert job['starting_cash_USDT']==INITIAL and dec(job['commission_rate'])==TAKER
    for id,source in job['sources'].items():
        assert sha(source['source'].encode())==source['source_sha256']
    keys={(x['id'],x['day'],x['seed'],x['mirror'],x['delay']) for x in proof['results']}
    assert keys==set(itertools.product((197,4692,5685),job['scope'],(1,42,20201120),(False,True),(0,200)))
    assert len(keys)==len(proof['results'])
    results,latency,sensitivity,aborts=[],[],[],[]
    with localcontext() as ctx:
        ctx.prec=35
        for run in proof['results']:
            id,day,seed,delay=(run[k] for k in ('id','day','seed','delay'))
            spec=job['scope'][day]
            replay_rule(run,spec)
            description={'id':id,'day':day,'seed':seed,'mirrored':run['mirror'],'extra_delay_ms':delay}
            if run['unsupported']:
                aborts.append({**description,'reached_cutoff':False,'unsupported_quote':run['unsupported'],
                               'observed_prefix_market_orders':len(run['orders'])})
                continue
            row,detail=accounting(run,spec)
            mirror=' mirror' if run['mirror'] else ''
            row.update(id=id,market='Binance USD-M BTCUSDT perpetual',name='Fibonacci sequence martingale source' if id==4692 else 'Martingale with balance logging source',
                group=f'FMZ source / Binance recorded marketable quotes +{delay}ms', source=job['sources'][str(id)]['archive_url'],
                period=f'{day} 06:00-10:00 UTC / seed {seed}{mirror}', interval='1d / 1h authored; 200ms causal host clock',
                exit='Archived P&L reductions at recorded BBO',currency='USDT',quote_currency='USDT',currency_decimal_places=8)
            (latency if delay else results).append(row)
            sensitivity.append({**description,**detail})
    assert len(results)==len(latency)==len(aborts)==24 and {r['id'] for r in aborts}=={197}
    out={'coverage':[[197,'Pending \u00b7 recorded depth beyond top of book required',
                     'Exact archived Binance BTC source and seeded clock were replayed on recorded quote tapes. Each attempted scope exceeded historical displayed best quote size before cutoff. Replaying valid remainder fills requires genuine depth. No performance metric from incomplete scopes.'],
                    [4692,'Tested \u00b7 original FMZ source on recorded BTC futures BBO',
                     'Twelve complete benchmark paths with full supported marketable top-quote quantity on two 4h dates. Twelve additional 200ms delay paths are provided separately.'],
                    [5685,'Tested \u00b7 original FMZ source on recorded BTC futures BBO',
                     'Twelve complete benchmark paths with full supported marketable top-quote quantity on two 4h dates. Twelve additional 200ms delay paths are provided separately.']],
         'results':results,'delayed_market_fill_sensitivity':latency,'path_evidence':sensitivity,'failed_scope_diagnostics':aborts,
         'source':{i:{k:v for k,v in e.items() if k!='source'} for i,e in job['sources'].items()},
         'market':{d:{k:v[k] for k in ('begin_ms','end_ms','quote_ref','mark_ref','funding')} for d,v in job['scope'].items()},
         'proof':{'input_sha256':sha(raw),'receipt_sha256':sha(receipt),'source_native_semantics_receipt_sha256':sha(host_receipt),
                   **{k+'_sha256':sha(getattr(a,k).read_bytes()) for k in ('worker','stage','host')},'independent_verifier_sha256':sha(Path(__file__).read_bytes())},
         'definitions':{'source':'Byte-pinned original JavaScript in an offline VM. Two first-of-month Binance BTCUSDT scopes start flat at 06:00 UTC and stop at 10:00 UTC. The separate native host fixture shows the omitted default balance 10,000 USDT, 200ms completion for the probed account, position and market order calls and no time advancement for setters. The source direction controls futures side even when the order is sent via the opposite Buy or Sell method. Sources use no K-line reads on their exercised main paths.',
            'random':'Original Math.random seeds were unspecified. The three prespecified xorshift32 seeds produce initial uniforms below 0.5. Each seed and its exact antithetic bit stream are kept, exposing both authored sides. Each path is an explicitly labeled historical stochastic sensitivity.',
            'fill':'At API completion, use the latest recorded bid or ask available by capture-local timestamp and require full order size at top of book. Quotes older than five seconds or size shortfalls stop the entire path. All modeled orders are marketable. The primary model adds no extra delay beyond measured 200ms host calls. An independent repeat reruns the entire causal path with 200ms additional submission delay per market order. Same-price executable size for the next 100ms is reported as a separate diagnostic.',
            'cash':'Use historical 0.04% taker fee, weighted futures cost basis and exchange funding rate. Gross uses observed side prices. Source floating position profit uses observed last trade, consistent with a native last-based position result, while marked drawdown uses recorded Binance derivatives mark prices. Every settlement has an official venue schedule/rate and nearby checksum-bound minute mark.',
            'scope_limits':'0ms and 200ms added delay are benchmark assumptions and do not reproduce queue priority, latency guarantees, market impact or hidden liquidity. Price and quoted size are real recorded observations, while all fills and results are repo-local models. Keep the settings and timing labels attached to each benchmark.'},
         'links':['https://docs.tardis.dev/historical-data-details/binance-futures','https://github.com/binance/binance-public-data',
                   'https://www.binance.com/en/blog/futures/421499824684900660'],
         'reproduction':'Run the native semantics fixture in the restricted offline engine against the pinned #1942 tape. Stage the immutable archive source and timestamped BBO and mark snapshots. Replay twice in separate offline processes and compare byte-identical receipts. Use the independent Decimal verifier to derive all rows.'}
    a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8',newline='\n')
    print('verified',[(i,d,len(l),sum(x['trades'] for x in l),min(x['mark_to_market_net'] for x in l),max(x['mark_to_market_net'] for x in l))
              for i in (4692,5685) for d,l in ((0,[x for x in results if x['id']==i]),(200,[x for x in latency if x['id']==i]))])
    print('unsupported',len(aborts),'sha256',sha(a.output.read_bytes()))


if __name__=='__main__':
    main()
