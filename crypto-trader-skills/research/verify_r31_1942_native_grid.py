"""Independently verify the #1942 modeled hedge-grid accounting and queue sensitivity."""

import argparse
from bisect import bisect_right
from collections import defaultdict
from decimal import Decimal,localcontext
from hashlib import sha256
from pathlib import Path
import gzip
import json

D=Decimal
ZERO=D(0)
WALLET=D(2000)
MAKER=D('0.0002')
ONE_TICK=D('0.1')
Q=D('0.001')
EPS=D('0.00000001')
M=60_000
H=60*M


def sha(b):
    return sha256(b).hexdigest()


def dec(v):
    return D(str(v))


def near(a,b):
    assert abs(dec(a)-b)<EPS,(a,b)


def wallet(a):
    return dec(a['Equity'])-dec(a['UPnL'])


def drawdown(initial,changes):
    peak=initial
    amount=ratio=ZERO
    for delta in changes:
        value=initial+delta
        peak=max(peak,value)
        amount=max(amount,peak-value)
        ratio=max(ratio,(peak-value)/peak)
    return amount,ratio


def cumulative(v):
    total=ZERO
    for an in v:
        total+=an
        yield total


def fund_rates(book,spec,controls):
    baseline=book['model']
    r={o[0]:D(o[1])/10**8 for o in spec['market']['funding']['data']}
    contracts={x[0]:x[1:5] for x in spec['market']['swap']['data']}
    index={x[0]:x[1:5] for x in spec['market']['index']['data']}
    changes={}
    evidence=[]
    for long,short in zip(book['funding']['long']['settle'],book['funding']['short']['settle'],strict=True):
        t=long['at']; assert short['at']==t
        a=dec(long['after'][1])-dec(long['before'][1])
        b=dec(short['after'][1])-dec(short['before'][1])
        assert abs(a+b)<EPS
        correction=ZERO
        if t in controls:
            compared=controls[t]
            economic_keys=('submitted','history','queries','settled','counts')
            assert all(compared[k]==baseline[k] for k in economic_keys)
            assert all(compared['position'][k]==baseline['position'][k] for k in ('positions','ticker','pending','at'))
            [record]=compared['fundingObservations']
            assert record[0]==t
            near(dec(record[2])-dec(record[1]),b)
            # Both controls split exactly one source Sleep around exactly one funding event.
            # Entire fill and mark paths repeat, so the native terminal wallet change isolates that event.
            correction=wallet(baseline['position']['account'])-wallet(compared['position']['account'])
        src_time,rate=next((k,v) for k,v in r.items() if abs(t-k)<=2000)
        assert rate and a*rate<0 and b*rate>0
        envelope=[D(min(contracts[t][2],index[t][2]))/10,D(max(contracts[t][1],index[t][1]))/10]
        synthetic_price=(b+correction)/(Q*rate)
        assert envelope[0]<=synthetic_price<=envelope[1],(baseline['day'],t,synthetic_price,envelope)
        changes[t]=(a/Q,(b+correction)/Q)
        evidence.append({'settlement_ms':t,'published_rate_timestamp_ms':src_time,'rate':str(rate),
            'native_modeled_mark_bound_USDT':list(map(str,envelope)),'native_long_benchmark_charge_per_001_BTC':str(a),
            'native_short_benchmark_charge_per_001_BTC':str(b),'source_clock_short_correction_USDT':str(correction)})
    return changes,evidence


def orders(book,spec):
    r=book['model']; prices=[p for p in book['chart']['prices'] if p[0]<=spec['end']]; times=[v[0] for v in prices]
    hist={o['Id']:o for o in r['history']}
    sub={o['id']:o for o in r['submitted']}
    market={x[0]:x[1:5] for x in spec['market']['swap']['data']}
    simulated={p[0]:p for p in prices}
    assert len(simulated)==len(prices) and times==sorted(times)
    assert times[0]==spec['begin'] and times[-1]==spec['end']
    assert not r['position']['pending'] and not r['cancel']
    assert len(hist)==len(sub)==len(r['settled'])
    for t,last,bid,ask in prices:
        o,h,l,c=market[(t//M)*M]
        assert l<=dec(last)*10<=h
        assert dec(ask)-dec(last)==dec(last)-dec(bid)==ONE_TICK
    assert all(simulated[p[0]]==p for p in r['queries'])
    result=[]
    for status in r['settled']:
        i=status['id']; o=status['order']; a=sub[i]; assert o==hist[i]
        assert o['Status']==1 and o['Symbol']=='BTC_USDT.swap' and o['ContractType']=='swap'
        t=o['Time']; q=dec(o['DealAmount']); px=dec(o['AvgPrice']); direction=a['direction']
        assert dec(a['price'])==px==dec(o['Price']) and dec(a['qty'])==q==dec(o['Amount'])
        initial=prices[bisect_right(times,t)-1]
        assert o['Type']==(0 if a['side']=='Buy' else 1)
        assert o['Offset']==int(direction in ('closebuy','closesell'))
        assert initial[0]<=a['before']<=t==a['after']
        at=status['first_terminal']['get_ms']
        prev=status['last_pending']['get_ms']
        assert status['first_terminal']['status']==1 and status['last_pending']['status']==0
        assert at-prev==200 and prev>t
        on=times[bisect_right(times,prev)]
        fill=simulated[on]
        assert on<=at and on<spec['end']
        crossed=(lambda p: dec(p[3])<=px) if o['Type']==0 else (lambda p: dec(p[2])>=px)
        assert not crossed(initial)
        eligible=prices[bisect_right(times,t):bisect_right(times,at)]
        assert [p[0] for p in eligible if crossed(p)]==[on] or next(p[0] for p in eligible if crossed(p))==on
        assert crossed(fill)
        side='long' if (direction in ('buy','closebuy')) else 'short'
        result.append({'order_id':i,'direction':direction,'position_side':side,'posted_ms':t,'fill_ms':on,
                    'first_observed_fill_ms':at,'last_observed_pending_ms':prev,'qty':q,'price':px,
                    'closed':bool(o['Offset']),'fee':q*px*MAKER,'queue_model':'native synthetic price-taking at resting limit',
                    'quote_at_placement':initial,'quote_at_fill':fill})
    assert all(a['first_observed_fill_ms']<=b['posted_ms'] for a,b in zip(result,result[1:]))
    return result


def verify(book,spec,controls,background,source_url):
    r=book['model']; fills=orders(book,spec)
    funds,evidence=fund_rates(book,spec,controls)
    prices=[p for p in book['chart']['prices'] if p[0]<=spec['end']]
    qty={k:ZERO for k in ('long','short')}
    basis=qty.copy(); held_fees=qty.copy(); held_funds=qty.copy();
    events_from_fill={a['fill_ms']:a for a in fills}
    assert len(events_from_fill)==len(fills) and not events_from_fill.keys()&funds.keys()
    assert all(abs(t-p)>2000 for t in funds for p in events_from_fill)
    cash=WALLET
    both=0
    curves=defaultdict(list)
    f_paid=c_paid=ZERO
    completed=[]
    for t,last,bid,ask in prices:
        if t in funds:
            a,b=funds[t]
            carry=a*qty['long']+b*qty['short']
            cash+=carry;c_paid+=carry
            held_funds['long']+=a*qty['long']
            held_funds['short']+=b*qty['short']
        if t in events_from_fill:
            order=events_from_fill[t]; side=order['position_side']; short=side=='short'
            amount=order['qty']; px=order['price'];fee=order['fee']; cash-=fee; f_paid+=fee
            if order['closed']:
                assert ZERO<amount<=qty[side]
                fraction=amount/qty[side]
                source_basis=basis[side]*fraction
                alloc_fee=held_fees[side]*fraction
                fund=held_funds[side]*fraction
                gross=(px*amount-source_basis)*(-1 if short else 1)
                charged=fee+alloc_fee
                cash+=gross
                qty[side]-=amount;basis[side]-=source_basis;held_fees[side]-=alloc_fee;held_funds[side]-=fund
                completed.append({'order_id':order['order_id'],'side':side,'amount':amount,'exit_price':px,'gross':gross,
                    'fees':charged,'after_fees':gross-charged,'funding':fund,'net':gross-charged+fund})
            else:
                qty[side]+=amount;basis[side]+=amount*px;held_fees[side]+=fee
        if qty['long'] and qty['short']:both+=1
        mark=dec(last)
        un=qty['long']*mark-basis['long']+basis['short']-qty['short']*mark
        net_equity=cash+un
        assert net_equity>(qty['long']+qty['short'])*mark/10
        curves['net'].append(net_equity-WALLET)
        curves['after_fees'].append(net_equity-WALLET-c_paid)
        curves['gross'].append(net_equity-WALLET-c_paid+f_paid)
    ending=r['position']; end_a=ending['account']
    near(wallet(end_a),cash)
    near(end_a['UPnL'],un)
    near(end_a['Equity'],curves['net'][-1]+WALLET)
    assert ending['ticker']['Time']==spec['end'] and ending['ticker']['Last']==prices[-1][1]
    asserts={p['Type']:p for p in ending['positions']}
    for idx,side in enumerate(('long','short')):
        if qty[side]:
            assert dec(asserts[idx]['Amount'])==qty[side] and asserts[idx]['MarginLevel']==10
            near(asserts[idx]['Price'],basis[side]/qty[side]);near(asserts[idx]['Margin'],basis[side]/10)
        else:
            assert idx not in asserts
    sums={k:sum((x[k] for x in completed),ZERO) for k in ('gross','fees','after_fees','funding','net')}
    assert abs(curves['net'][-1]-(sums['net']-sum(held_fees.values())+sum(held_funds.values())+un))<EPS
    for native,external in zip(fills,background['orders'],strict=True):
        assert native['order_id']==external['order_id'] and native['posted_ms']==external['begin_ms']
        assert native['first_observed_fill_ms']==external['end_ms'] and native['price']==D(external['limit_price'])
    external_success=sum(a['has_full_size_strict_flow_at_native_fill_deadline'] for a in background['orders'])
    out={k:float(v) for k,v in sums.items()}
    for prefix,metric in (('gross','gross'),('fee','after_fees'),('net','net')):
        value,rate=drawdown(WALLET,cumulative(a[metric] for a in completed))
        out[prefix+'_dd']=float(value);out[prefix+'_dd_pct']=float(rate)
        out[prefix+'_wins']=sum(x[metric]>0 for x in completed)
    out.update(id=1942,group='FMZ Native · Two-sided grid with modeled queue',name='Two-sided futures grid v1.0.2',
        source=source_url,market='Binance USD-M BTCUSDT perpetual',period=r['day']+' 24h UTC',currency='USDT',quote_currency='USDT',
        currency_decimal_places=8,interval='1m native simulated-tick base',exit='Archived maker limit closes · inventory marked at cutoff',
        trades=len(completed),unsettled=len(ending['positions']),execution=0,starting_equity=float(WALLET),
        remaining_unrealized=float(un),mark_to_market_net=float(curves['net'][-1]))
    info={'day':r['day'],'native_limit_fills':fills,'closed_grid_reductions':completed,'funding_checks':evidence,
          'simultaneous_long_short_simulated_observation_count':both,'recorded_trade_flow_strictly_through':external_success,
          'physical_market_tape':background,'modeled_cash_wallet_USDT':str(cash),
          'remaining_maker_fee_USDT':sum(held_fees.values()),'remaining_funding_USDT':sum(held_funds.values()),
          'native_account':ending,'marked_drawdown_USDT':{k:[str(p) for p in drawdown(WALLET,values)] for k,values in curves.items()}}
    return out,info


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ('job','receipt','repeat-receipt','observe-eight','observe-sixteen','physical-tape','stage','worker','flow-code','output'):
        ap.add_argument('--'+k,type=Path,required=True)
    a=ap.parse_args()
    raw=a.job.read_bytes(); saved=a.receipt.read_bytes()
    assert saved==a.repeat_receipt.read_bytes()
    job=json.loads(gzip.decompress(raw)); native=json.loads(saved)
    external=a.physical_tape.read_bytes(); physical=json.loads(external)
    assert sha(raw)==native['input_sha256'] and sha(saved)==physical['native_receipt_sha256']
    assert native['source_sha256']==job['source_sha256']==sha(job['source'].encode())
    assert job['fees_pct']==[0.02,0.04] and job['wallet_USDT']==2000
    extra=[a.observe_eight.read_bytes(),a.observe_sixteen.read_bytes()]
    controls={}
    for code in extra:
        x=json.loads(code); assert x['input_sha256']==native['input_sha256']
        row=x['results'][0]['model']; assert row['day']=='2021-01-01'
        [p]=row['fundingObservations'];controls[p[0]]=row
    rows=[]; diagnosis=[]
    with localcontext() as ctx:
        ctx.prec=44
        for run,background in zip(native['results'],physical['scopes'],strict=True):
            day=run['model']['day']; assert background['day']==day
            result,detail=verify(run,job['scope'][day],controls if day=='2021-01-01' else {},background,job['url'])
            rows.append(result);diagnosis.append(detail)
    assert [s['trades'] for s in rows]==[4,2,5]
    assert [s['recorded_trade_flow_strictly_through'] for s in diagnosis]==[8,6,10]
    out={'coverage':[[1942,'Tested · original dual futures grid in three native simulated-tick BTC scopes',
         'Three prespecified first-of-month Binance BTCUSDT sessions, exact source with independent native queue transition bounds, concurrent long/short settlement and funded ledger reconciliation. 25 modeled full maker orders, 11 closed reductions. Historical aggressive tape is separately checked at the modeled deadlines.']],
         'results':rows,'diagnostics':diagnosis,'source':{'url':job['url'],'source_sha256':job['source_sha256'],
         'archive_document_sha256':job['document_sha256'],'publisher':'https://www.fmz.com/strategy/293325'},
         'market_inputs':{d:{k:p['refs'] for k,p in s['market'].items()} for d,s in job['scope'].items()},
         'proof':{'input_sha256':sha(raw),'native_receipt_sha256':sha(saved),'native_engine_sha256':native['emitter_sha256'],
          'historical_trade_flow_sha256':sha(external),'independent_funding_controls_sha256':[sha(s) for s in extra],
          'stage_sha256':sha(a.stage.read_bytes()),'worker_sha256':sha(a.worker.read_bytes()),
          'flow_checker_sha256':sha(a.flow_code.read_bytes()),'verifier_sha256':sha(Path(__file__).read_bytes())},
         'method':{'scope':'Three prespecified complete first-of-month UTC days within the original Jan–Jun 2021 horizon. Each restarts flat with the archived 2,000 USDT on the exact Binance BTCUSDT 1m/1m backtest setting, 10x host default and the archived order quantity ladder. Conclusions apply to these three cold-start simulations.',
             'queue':'The exact archived JavaScript runs in the original FMZ simulated-tick broker. A separately emitted no-strategy quote tape verifies economic crossing, first valid tick, full simulated quantity and a 200 ms source observation bracket for every order. The Binance checksum-bearing aggressive trade tape separately tests whether raw signed flow strictly through each native limit could support its full size within the same native posting and fill deadlines. 24 of 25 pass this sensitivity. Historical queue position and the later causal strategy path remain unresolved. These are modeled orders.',
             'fees':'Every posted limit rested across at least one native order-status observation, then executed at its submitted price. Apply the historically published 0.02% maker rate. Taker schedule 0.04% is configured but unused within the archived strategy path. No fixed spread or synthetic slippage is deducted for these exact limit-price fills. Probe orders are isolated from strategy metrics.',
             'settlement':'Track long and short separately with the native weighted basis and pro-rata fees and funding for partial reductions. A book-specific source-clock funding control adjusts two modeled January funding marks, while preserving every simulated order and quote. Independent funding schedules and price envelopes validate each debit and credit. Marked P&L and equity drawdown include open long/short positions and fees. Closed win rate counts individual closed reductions, including partial close of a side.',
             'proof_limits':'The simulated fill price, close quantity and cash are precise to native ledger rounding. No fees or fill outcomes are inferred from physical maker queue estimates.'},
         'reference_urls':['https://www.fmz.com/strategy/293325','https://github.com/binance/binance-public-data',
           'https://www.fmz.com/user-guide/backtesting-system/backtest-modes-and-order-matching',
           'https://www.binance.com/en/blog/futures/421499824684900660'],
         'reproduction':'Stage the pinned FMZ and checksummed Binance inputs and run the native worker twice. Run the worker with fund-observe8 and fund-observe16 separately for timestamp controls. Run the recorded-flow checker against the unmodified strategy receipt and verify all generated files using Decimal arithmetic.'}
    a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8',newline='\n')
    print('verified',[(r['period'],r['trades'],r['gross'],r['fees'],r['net'],r['mark_to_market_net']) for r in rows],sha(a.output.read_bytes()))


if __name__=='__main__':
    main()
