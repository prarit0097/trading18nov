"""Independently reconcile #5148 BTC and ETH market rules and exchange admission."""

import argparse
from collections import defaultdict
from decimal import Decimal as D, ROUND_HALF_UP, localcontext
import gzip
import itertools
import json
from pathlib import Path

from fmz_native_round20_880_capture import sha
from verify_r34_btc_random_book import drawdown, random_sequence, sum_path
from verify_r35_197_recorded_depth import book, close, market
from verify_r37_5774_eth_book import check_native, route

ZERO=D(0)
LEV=50
BASE=1000
MIN=D(5)
TAKER=D('0.0004')
INITIAL=D(10_000)
STEP=200
GAIN=D('0.5')
MID=2**31
S=D('.001')
L=D('.002')


def expected_notional_range(spec,t,tag,n):
    last,mark=market(spec,t)
    _,asks,bids=book(spec,t)
    selected=(asks if tag in ('buy','closesell') else bids)[0]
    values=[D(n)*p/BASE for p in (last,mark,D(selected[0])/100)]
    return min(values),max(values)


def certify_rule(run,spec):
    b,e=spec['begin_ms'],spec['end_ms']
    initial,*history=run['records']
    assert initial==[b+STEP,[]] and run['kvReads']==run['chartCalls']==1 and not run['unsupported']
    clock=b+2*STEP
    draws=iter(run['draws']); gen=random_sequence(run['seed'],run['mirror'])
    events=iter(sorted(run['orders']+run['rejects'],key=lambda x:x['clock']))
    q=[0,0];basis=[ZERO,ZERO];book_use=defaultdict(lambda:defaultdict(int))
    stopped=False
    n=None
    def send(tag,req):
        nonlocal clock,stopped
        if stopped:return
        clock+=STEP+run['delay']
        if clock>=e:
            stopped=True;return
        entry=next(events)
        units=int((req*BASE).to_integral_value(rounding=ROUND_HALF_UP))
        api='Buy' if tag in ('buy','closesell') else 'Sell'
        assert (entry['clock'],entry['units'],entry['direction'],entry['api'])==(clock,units,tag,api)
        close(entry['requested'],req)
        if not tag.startswith('close'):
            low,high=expected_notional_range(spec,clock,tag,units)
            if high<MIN:
                assert run['coin']=='ETH' and units==1
                assert 'notionalBounds_USDT' in entry
                close(entry['notionalBounds_USDT'][0],low);close(entry['notionalBounds_USDT'][1],high)
                return
            assert low>=MIN
        assert 'portions' in entry and 'notionalBounds_USDT' not in entry
        cost,parts,age,arrival=route(spec,clock,tag,units,book_use)
        assert (entry['portions'],entry['age'],entry['snapshot_us'])==(parts,age,arrival)
        close(entry['notional'],cost)
        side=0 if tag in ('buy','closebuy') else 1
        if tag.startswith('close'):
            assert units==q[side]
            q[side]=0;basis[side]=ZERO
        else:
            q[side]+=units;basis[side]+=cost
        assert entry['quant']==q
        for actual,expected in zip(entry['basis'],basis,strict=True):close(actual,expected)
    for t,seen in history:
        assert clock==t<e
        last,_=market(spec,t)
        active=[i for i,size in enumerate(q) if size]
        assert [p['Type'] for p in seen]==active
        for i,p in zip(active,seen,strict=True):
            size=D(q[i])/BASE
            pnl=(size*last-basis[i])*(1 if i==0 else -1)
            close(p['Amount'],size);close(p['Price'],basis[i]/size);close(p['Profit'],pnl);close(p['Margin'],basis[i]/LEV)
        if not active:
            bits=next(gen)
            assert next(draws)==[clock,bits,0,0]
            n=S;send('sell',n)
            n=L;send('buy',n)
            if bits>MID:n=S;send('sell',n)
            if 0<bits<=MID:n=L;send('buy',n)
        else:
            side=active[0]
            profit=(D(q[side])*last/BASE-basis[side])*(1 if side==0 else -1)
            if profit>GAIN:
                send('closebuy' if side==0 else 'closesell',D(q[side])/BASE)
            elif profit<-2*basis[side]/LEV:
                n*=D('1.5');send('buy' if side==0 else 'sell',n)
        if stopped:break
        clock+=STEP+(60_000 if active else 0)
    assert run['tail']['clock']==e and clock>=e and next(events,None) is None and next(draws,None) is None
    assert [p['size'] for p in run['tail']['positions']]==q
    for r,w in zip(run['tail']['positions'],basis,strict=True):close(r['notional'],w)


def settled(run,spec):
    orders={o['clock']:o for o in run['orders']}
    assert len(orders)==len(run['orders'])
    q=[0,0];basis=[ZERO,ZERO];entry_fees=[ZERO,ZERO];carry=[ZERO,ZERO]
    fund=spec['funding'];due=(fund['exchange_settlement_ms']+STEP-1)//STEP*STEP
    [event]=run['funding'];assert event['clock']==due and event['venue_ms']==fund['exchange_settlement_ms']
    fmark,rate=D(str(fund['prior_mark'][3])),D(str(fund['rate']))
    close(event['price'],fmark);close(event['rate'],rate)
    cash=peak=minimum=INITIAL
    marked_loss=marked_pct=fee_total=notional_peak=ZERO
    prior_mark=None;both=multilevel=0;trades=[]
    used=defaultdict(lambda:defaultdict(int))
    def unrl(mark):
        return (D(q[0]-q[1])/BASE)*mark-basis[0]+basis[1]
    for index,z in enumerate(spec['marks']):
        t=spec['begin_ms']+index*STEP
        if index and all(q):both+=1
        if z[3]==prior_mark and t not in orders and t-STEP not in orders and t!=due and index+1<len(spec['marks']):
            continue
        prior_mark=z[3]
        mark=D(str(prior_mark))
        if t==due:
            assert event['quantity']==q
            for i in (0,1):
                flow=D(q[i])*fmark*rate/BASE*(-1 if i==0 else 1)
                close(event['sum'][i],flow)
                carry[i]+=flow;cash+=flow
            close(event['wallet'],cash)
        minimum=min(minimum,cash+unrl(mark)-D(sum(q))*mark/BASE/LEV)
        if t in orders:
            o=orders[t];tag=o['direction'];added=o['units']
            i=0 if tag in ('buy','closebuy') else 1
            price,levels,_,_=route(spec,t,tag,added,used)
            multilevel+=len(levels)>1
            fee=price*TAKER
            close(o['mark'],mark);close(o['fee'],fee)
            fee_total+=fee
            if tag.startswith('close'):
                assert q[i]==added
                profit=(price-basis[i])*(1 if i==0 else -1)
                together=fee+entry_fees[i]
                trades.append({'side':i,'gross':profit,'fees':together,'after_fees':profit-together,
                               'funding':carry[i],'net':profit-together+carry[i]})
                close(o['gross'],profit)
                cash+=profit-fee
                q[i]=0;basis[i]=entry_fees[i]=carry[i]=ZERO
            else:
                assert cash-sum(basis)/LEV>price/LEV+fee
                close(o['gross'],ZERO)
                cash-=fee
                q[i]+=added;basis[i]+=price;entry_fees[i]+=fee
            close(o['wallet'],cash);assert q==o['quant']
        guess=unrl(mark)
        equity=cash+guess
        gross_exposure=D(sum(q))*mark/BASE
        assert equity>gross_exposure/LEV
        notional_peak=max(notional_peak,gross_exposure)
        peak=max(peak,equity)
        marked_loss=max(marked_loss,peak-equity)
        marked_pct=max(marked_pct,(peak-equity)/peak)
    assert both==run['concurrent_hold_steps']
    tail=run['tail'];close(tail['wallet'],cash);close(tail['mark'],mark);close(tail['UPnL'],guess);close(run['marginBuffer'],minimum)
    assert [p['size'] for p in tail['positions']]==q
    for x,want in zip(tail['positions'],basis,strict=True):close(x['notional'],want)
    fields=('gross','fees','after_fees','funding','net')
    sums={k:sum((x[k] for x in trades),ZERO) for k in fields}
    close(equity-INITIAL,sums['net']-sum(entry_fees)+sum(carry)+guess)
    metrics={k:float(v) for k,v in sums.items()}
    for alias,metric in (('gross','gross'),('fee','after_fees'),('net','net')):
        dd,ratio=drawdown(sum_path(x[metric] for x in trades))
        metrics[alias+'_dd']=float(dd);metrics[alias+'_dd_pct']=float(ratio);metrics[alias+'_wins']=sum(x[metric]>ZERO for x in trades)
    metrics.update(trades=len(trades),unsettled=sum(bool(x) for x in q),starting_equity=float(INITIAL),execution=0,
                  mark_to_market_net=float(equity-INITIAL),remaining_unrealized=float(guess))
    evidence={'accepted_orders':len(orders),'multilevel_orders':multilevel,'min_notional_rejections':len(run['rejects']),
        'rejection_examples':run['rejects'][:3], 'ending_long_short_qty':[str(D(x)/BASE) for x in q],
        'max_gross_exposure_USDT':notional_peak,'marked_drawdown_USDT':marked_loss,'marked_drawdown_fraction':marked_pct,
        'minimum_initial_margin_buffer_USDT':minimum,'funding_cashflow_USDT':event['sum'],'fees_USDT_total':fee_total,
        'both_sides_open_seconds':D(both)*STEP/1000,'orders_and_rejects_sha256':sha(json.dumps([run['orders'],run['rejects']],separators=(',',':')).encode())}
    return metrics,evidence


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('input','btc','eth','first','repeat','fixture','control-code','stage','worker','output'):
        p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    raw=a.input.read_bytes();evidence=a.first.read_bytes();fixture=a.fixture.read_bytes()
    assert evidence==a.repeat.read_bytes()
    ctx=json.loads(gzip.decompress(raw));r=json.loads(evidence);abi=json.loads(fixture)
    check_native(abi)
    assert all(v=={'g':'function','dollar':'object','chart':'function','cold':None} for v in abi['ambient'])
    assert all(v['trace'][1]['args']==[50] for v in abi['results'])
    assert sha(raw)==r['input_sha256'] and sha(ctx['code'].encode())==ctx['source_sha256']
    assert sha(a.worker.read_bytes())==r['worker_sha256']
    assert ctx['initial_cash_USDT']==INITIAL and ctx['leverage']==LEV and D(str(ctx['fee_rate']))==TAKER
    assert ctx['minimum_notional_USDT']==MIN
    books={}
    for coin in ('BTC','ETH'):
        raw_book=getattr(a,coin.lower()).read_bytes()
        assert sha(raw_book)==ctx['book_shas'][coin]
        books[coin]=json.loads(gzip.decompress(raw_book))['scope']
    keys={(s['coin'],s['day'],s['seed'],s['mirror'],s['delay']) for s in r['results']}
    assert keys==set(itertools.product(books,books['BTC'],(1,42,20201120),(False,True),(0,200))) and len(r['results'])==48
    rows=[];delayed=[];checks=[]
    with localcontext() as local:
        local.prec=37
        for action in r['results']:
            coin,day,delay=(action[k] for k in ('coin','day','delay'))
            spec=books[coin][day]
            certify_rule(action,spec)
            values,detail=settled(action,spec)
            suffix=' mirror' if action['mirror'] else ''
            window=f"{day} 06:00-10:00 UTC / seed {action['seed']}{suffix}"
            values.update(id=5148,name='Adjusted multiplier martingale, named BTC and ETH variants',
                 source=ctx['archive_url'],market=f'Binance USD-M {coin}USDT perpetual',
                 group=f'FMZ archived source / {coin} observed depth +{delay}ms',period=window,
                 interval='1d / 1h archive; 200ms causal host',exit='Original market-order sides and exact risk thresholds',
                 currency='USDT',quote_currency='USDT',currency_decimal_places=8)
            (delayed if delay else rows).append(values)
            checks.append({'market':coin,'period':window,'extra_delay_ms':delay,**detail})
    summary={}
    for coin in ('BTC','ETH'):
        for delay,selected in ((0,rows),(200,delayed)):
            rr=[x for x in selected if coin+'USDT' in x['market']]
            qq=[x for x in checks if x['market']==coin and x['extra_delay_ms']==delay]
            summary[f'{coin}_{delay}ms']={'scopes':len(rr),'closed_trades':sum(o['trades'] for o in rr),
                'closed_net_wins':sum(o['net_wins'] for o in rr),'full_orders':sum(o['accepted_orders'] for o in qq),
                'notional_rejections':sum(o['min_notional_rejections'] for o in qq),
                'closed_pnl_range_USDT':[min(o['net'] for o in rr),max(o['net'] for o in rr)],
                'marked_pnl_range_USDT':[min(o['mark_to_market_net'] for o in rr),max(o['mark_to_market_net'] for o in rr)],
                'max_marked_drawdown_fraction':max(o['marked_drawdown_fraction'] for o in qq)}
    assert [m['closed_trades'] for m in summary.values()]==[12,8,0,0]
    assert [m['notional_rejections'] for m in summary.values()]==[0,0,18,18]
    report={'coverage':[[5148,'Tested \u00b7 explicitly named BTC and ETH variants with venue admission',
                          'Twenty-four primary and twenty-four latency paths use the unchanged operative source and named BTC and ETH markets. Historical minimum-notional rules preserve ETH opening rejections and marked open exposure.']],
            'results':rows,'delayed_market_fill_sensitivity':delayed,'scope_summary':summary,'scope_checks':checks,
            'source':{'url':ctx['archive_url'],'source_sha256':ctx['source_sha256'],'archive_sha256':ctx['archive_sha256'],
                'published_strategy_url':'https://www.fmz.com/strategy/352037'},
            'provenance':{'input_sha256':sha(raw),'receipt_sha256':sha(evidence),'book_shas':ctx['book_shas'],
                'captured_market_proof':ctx['observed_price_range'],'native_fixture_market_sha256':abi['market_sha256'],
                'native_fixture_engine_sha256':abi['engine_sha256'],'native_fixture_receipt_sha256':sha(fixture),
                **{k+'_sha256':sha(getattr(a,k).read_bytes()) for k in ('stage','worker','control_code')},
                'verifier_sha256':sha(Path(__file__).read_bytes())},
            'method':{'source_scope':'The archived exchange currency is a placeholder. Its source symbol list explicitly includes BTC and ETH and the last main uses one exchange object. Each named market is a standalone variant. Older transfer, network, SetCurrency and chart-helper main declarations are overwritten or dormant. A cold native FMZ fixture confirms the empty _G value, Chart function and $ object. Their initialization does not affect the modeled orders.',
                'position_scope':'The 50x source opens both hedge sides while flat in two always-truthy comma expressions. It then manages the first returned open position. The native fixture returns the long first whenever both exist. The replay preserves original sizes, weighted bases, profit predicates, collateral and marked exposure.',
                'venue_admission':'Archived Binance rules require minimum opening notional of 5 USDT in both 2021 windows. For every ETH scope, observed best price, mark and last trade all place 0.001 ETH above 0 and below 5 USDT and 0.002 ETH above 5 USDT. Pure reductions are exempt. Admitted market sweeps use causally observed displayed price and quantity.',
                'economic_scope':'Use 10,000 USDT initial equity, the historic 0.04% taker fee, observed weighted market sweep prices, and signed funding at the first replay point after the exact venue settlement. Historical quotes are fixed model inputs. Closed and marked drawdown are distinct. Zero closed trades provide no win-rate estimate.',
                'timing_scope':'Operations take 200ms as measured in the native fixture. A separate full replay adds 200ms to each order. Original seeds were unspecified. All chosen seeds and antithetic counterparts are included on the same two dates.'},
            'references':[ctx['minimum_notional_reference'],'https://www.binance.com/en/support/announcement/detail/e4384cba297a4bd2a154be644d5d76f9',
                'https://www.binance.com/en/blog/futures/421499824684900660','https://docs.tardis.dev/downloadable-csv-files/data-types']}
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8',newline='\n')
    print(summary,flush=True)
    print(sha(a.output.read_bytes()),flush=True)


if __name__=='__main__':main()
