"""Check #197 original rules, actual depth sweeps and independent funded ledgers."""

import argparse
from collections import Counter
from decimal import Decimal as D, localcontext
import gzip
import itertools
import json
from pathlib import Path

from fmz_native_round20_880_capture import sha
from verify_r34_btc_random_book import drawdown, random_sequence, sum_path

INITIAL=D(10_000)
TAKER=D('0.0004')
ZERO=D(0)
STEP=200
CAP_AGE=5_000_000
N=1000
PRECISION=100
LEVERAGE=20


def dec(x):
    return D(str(x))


def close(x,want):
    assert abs(dec(x)-want)<D('0.00000001'),(x,want)


def book(spec,t):
    i=(t-spec['begin_ms'])//STEP
    assert spec['begin_ms']+i*STEP==t and 0<=i<len(spec['depth'])
    arrive,venue,ask,bid=spec['depth'][i]
    assert venue<=arrive<=t*1000
    if isinstance(ask,str):
        def pairs(values):
            nums=list(map(int,values.split(',')))
            return [list(r) for r in zip(nums[0::2],nums[1::2],strict=True)]
        ask,bid=pairs(ask),pairs(bid)
    q=spec['quotes'][i]
    assert [bid[0][0],ask[0][0],bid[0][1],ask[0][1]]==q[2:6]
    return t*1000-arrive,ask,bid


def market(spec,t):
    row=spec['marks'][(t-spec['begin_ms'])//STEP]
    assert row[1]<=row[0]<=t*1000
    return D(row[2])/100,dec(row[3])


def price_quantity(spec,t,label,units):
    age,ask,bid=book(spec,t)
    assert age<=CAP_AGE
    take=ask if label in ('buy','closesell') else bid
    remains=units
    choices=[]
    for px,capacity in take:
        actual=min(capacity,remains)
        choices.append([px,actual])
        remains-=actual
        if not remains:
            break
    assert all(q>0 and px>0 for px,q in choices)
    value=sum(px*q for px,q in choices)
    return remains,D(value)/100_000,choices,age


def check_host(control):
    checks=control['checks']
    ops={row['k']:row for row in checks}
    for see in ('GetAccount','GetDepth','GetPosition','Buy','Sell'):
        row=ops[see]
        assert row['at']-row['before']==200
    assert ops['GetAccount']['result']['Balance']==10_000 and ops['SetMarginLevel']['arg']==[20]
    assert [r['arg'] for r in checks if r['k']=='SetDirection']==[['buy'],['closebuy']]
    depth=ops['GetDepth']['result']
    buy,sell=ops['GetHistoryOrders']['result']
    assert buy['AvgPrice']==depth['topAsk']['Price'] and sell['AvgPrice']==depth['topBid']['Price']
    assert buy['Offset']==0 and sell['Offset']==1 and buy['DealAmount']==sell['DealAmount']==.015


def expected_action(pos,profit,bits):
    if not pos and bits!=2**31:
        return ('buy' if bits<2**31 else 'sell'),15
    if pos and profit>1:
        return ('closebuy' if pos>0 else 'closesell'),abs(pos)
    if pos and profit<-1:
        return ('buy' if pos>0 else 'sell'),15
    return None


def replay_rule(run,spec):
    found=iter(run['orders'])
    draws=iter(run['draws'])
    random=random_sequence(run['seed'],run['mirror'])
    pos=0
    basis=ZERO
    clock=spec['begin_ms']+400
    cutoff=spec['end_ms']
    abort=run['unsupported']
    failed_order=False
    for at,units,gain,basis_price,margin in run['decisions']:
        assert clock==at<cutoff and units==pos
        last,_=market(spec,at)
        average=basis/(D(abs(pos))/N) if pos else ZERO
        profit=D(pos)/N*(last-average)
        close(gain,profit); close(basis_price,average); close(margin,basis/LEVERAGE)
        bits=None if pos else next(random)
        if not pos:
            assert next(draws)==[at,bits,0]
        decision=expected_action(pos,profit,bits)
        if decision:
            tag,qty=decision
            clock+=STEP+run['delay']
            if clock>=cutoff or (abort and abort['clock']<clock):
                break
            remaining,notional,portions,age=price_quantity(spec,clock,tag,qty)
            if abort and abort['clock']==clock:
                assert abort['direction']==tag and abort['units']==qty
                if remaining:
                    assert abort['reason']=='market order exceeds the observed levels'
                    assert abort['availableUnits']==qty-remaining
                else:
                    assert abort['reason']=='first new order fails modeled initial margin' and tag in ('buy','sell')
                    assert abort['available']<=abort['required']
                    close(abort['required'],notional*(D(1)/LEVERAGE+TAKER))
                failed_order=True
                break
            assert remaining==0
            o=next(found)
            assert (o['clock'],o['direction'],o['units'],o['portions'],o['age'])==(clock,tag,qty,portions,age)
            assert o['api']==('Buy' if tag in ('buy','closesell') else 'Sell')
            close(o['executedNotional'],notional)
            if tag.startswith('close'):
                assert abs(pos)==qty
                pos=0
                basis=ZERO
            else:
                pos+=qty if tag=='buy' else -qty
                basis+=notional
        clock+=1400
    end=run['ending']
    assert next(found,None) is None and next(draws,None) is None
    assert (end['clock']==cutoff and clock>=cutoff) or (abort and end['clock']==abort['clock'])
    if abort and abort['reason'] in ('market order exceeds the observed levels','first new order fails modeled initial margin'):
        assert failed_order
    assert end['posUnits']==pos
    close(end['basis'],basis)


def accounting(run,spec):
    by_time={o['clock']:o for o in run['orders']}
    assert len(by_time)==len(run['orders'])
    final=run['ending']
    scheduled=spec['funding']
    due=scheduled['exchange_settlement_ms']
    settling=((due+STEP-1)//STEP)*STEP
    point=scheduled['prior_mark']
    before,after=[dec(v) for v in scheduled['official_two_minute_mark_price_bounds_USDT']]
    assert before<=dec(point[3])<=after and point[1]<=point[0]<=scheduled['boundary_ms']*1000
    funds=run['funding']
    assert len(funds)==(settling<=final['clock'])
    wallet=INITIAL
    qty=basis=carry=fees=all_fees=all_funding=ZERO
    close_trades=[]
    peak=INITIAL
    low_buffer=INITIAL
    dd=dd_pct=ZERO
    total_sweeps=0
    max_levels=max_age=0
    for now in range(spec['begin_ms'],final['clock']+1,STEP):
        last,mark=market(spec,now)
        if now==settling:
            [detail]=funds
            prior,rate=dec(point[3]),dec(scheduled['rate'])
            cashflow=-qty*prior*rate
            assert detail['clock']==settling and detail['venueClock']==due
            close(detail['notional_BTC'],qty);close(detail['mark'],prior);close(detail['rate'],rate);close(detail['value'],cashflow)
            carry+=cashflow
            all_funding+=cashflow
            wallet+=cashflow
        unrealized=qty*(mark-basis/abs(qty)) if qty else ZERO
        cur_buffer=wallet+unrealized-abs(qty)*mark/LEVERAGE
        low_buffer=min(low_buffer,cur_buffer)
        order=by_time.get(now)
        if order:
            n=order['units']
            size=D(n)/N
            label=order['direction']
            leftover,sum_value,amts,delay=price_quantity(spec,now,label,n)
            assert not leftover and amts==order['portions'] and delay==order['age']
            close(order['mark'],mark);close(order['last'],last);close(order['executedNotional'],sum_value)
            order_fee=sum_value*TAKER
            close(order['fee'],order_fee)
            all_fees+=order_fee
            level_count=len(amts)
            total_sweeps+=int(level_count>1)
            max_levels=max(max_levels,level_count)
            max_age=max(max_age,delay)
            if label.startswith('close'):
                assert abs(qty)==size
                gross=(sum_value-basis)*(1 if qty>0 else -1)
                close(order['pnl'],gross)
                fee_total=fees+order_fee
                close_trades.append({'at':now,'gross':gross,'fees':fee_total,'funding':carry,
                                     'after_fees':gross-fee_total,'net':gross-fee_total+carry})
                wallet+=gross-order_fee
                qty=basis=fees=carry=ZERO
            else:
                assert wallet-basis/LEVERAGE>sum_value/LEVERAGE+order_fee
                close(order['pnl'],ZERO)
                qty+=size if label=='buy' else -size
                wallet-=order_fee
                basis+=sum_value
                fees+=order_fee
            close(order['wallet'],wallet)
            assert order['posUnits']==qty*N
        unrealized=qty*(mark-basis/abs(qty)) if qty else ZERO
        equity=wallet+unrealized
        if not (run['unsupported'] and now==final['clock']):
            assert equity>abs(qty)*mark/LEVERAGE
        peak=max(peak,equity)
        dd=max(dd,peak-equity)
        dd_pct=max(dd_pct,(peak-equity)/peak)
    assert final['posUnits']==qty*N
    close(final['basis'],basis);close(final['wallet'],wallet);close(final['floating'],unrealized)
    close(final['mark'],mark);close(final['last'],last);close(run['minimumInitialMarginBuffer'],low_buffer)
    if run['unsupported'] and run['unsupported']['reason']=='first new order fails modeled initial margin':
        close(run['unsupported']['available'],wallet-basis/LEVERAGE)
    exposure={'orders':len(by_time),'multi_level_orders':total_sweeps,'levels_in_largest_sweep':max_levels,'max_book_age_us':max_age,
        'decision_steps':len(run['decisions']),'rng_draws':len(run['draws']),
        'receipt_order_and_draw_path_sha256':sha(json.dumps([run['orders'],run['draws']],separators=(',',':')).encode())}
    if run['unsupported']:
        return None,exposure
    metrics={k:sum((o[k] for o in close_trades),ZERO) for k in ('gross','fees','after_fees','funding','net')}
    close(equity-INITIAL,metrics['net']-fees+carry+unrealized)
    row={k:float(v) for k,v in metrics.items()}
    for alias,name in (('gross','gross'),('fee','after_fees'),('net','net')):
        d,p=drawdown(sum_path(t[name] for t in close_trades))
        row[alias+'_dd']=float(d)
        row[alias+'_dd_pct']=float(p)
        row[alias+'_wins']=sum(t[name]>ZERO for t in close_trades)
    row.update(trades=len(close_trades),unsettled=int(bool(qty)),starting_equity=float(INITIAL),execution=0,
               remaining_unrealized=float(unrealized),mark_to_market_net=float(equity-INITIAL))
    exposure.update(marked_drawdown_USDT=dd,marked_drawdown_fraction=dd_pct,ending_open_BTC=qty,
                    funding_cash_total_USDT=all_funding,fee_total_USDT=all_fees,
                    minimum_pre_order_initial_margin_buffer_USDT=low_buffer,verified_closes=len(close_trades))
    return row,exposure


def produce(rows,job):
    performance=[]
    diagnostics=[]
    scopes=job['scope']
    expected=set(itertools.product(scopes,(1,42,20201120),(False,True),(0,200)))
    assert expected=={(r['day'],r['seed'],r['mirror'],r['delay']) for r in rows} and len(rows)==24
    for r in rows:
        day,seed,mirror,delay=(r[k] for k in ('day','seed','mirror','delay'))
        spec=scopes[day]
        replay_rule(r,spec)
        outcome,evidence=accounting(r,spec)
        label={'day':day,'seed':seed,'mirrored':mirror,'extra_delay_ms':delay}
        diagnostics.append({**label,**evidence,'completed':outcome is not None,'stop':r['unsupported']})
        if outcome is not None:
            outcome.update(id=197,name='Commodity martingale tutorial, archived BTC futures configuration',
                           group=f'FMZ archived source / Binance recorded depth +{delay}ms',
                           market='Binance USD-M BTCUSDT perpetual',currency='USDT',quote_currency='USDT',currency_decimal_places=8,
                           source=job['sources']['197']['archive_url'],period=f'{day} 06:00-10:00 UTC / seed {seed}'+(' mirror' if mirror else ''),
                           interval='1d archived chart and base; 200ms causal host',exit='Source P&L close thresholds and book-level sweeps')
            performance.append((delay,outcome))
    return performance,diagnostics


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ('input','top5-input','first','repeat','top5-receipt','native-control','control-code','worker','top5-stage','top25-stage','output'):
        ap.add_argument('--'+key,type=Path,required=True)
    a=ap.parse_args()
    raw=a.input.read_bytes(); raw5=a.top5_input.read_bytes()
    inp=json.loads(gzip.decompress(raw));inp5=json.loads(gzip.decompress(raw5));
    run=a.first.read_bytes(); assert run==a.repeat.read_bytes()
    small=a.top5_receipt.read_bytes(); r=json.loads(run); r5=json.loads(small)
    assert sha(raw)==r['input_sha256'] and sha(raw5)==r5['input_sha256']==inp['full_depth_input_parent_sha256']
    assert r['runner_sha256']==r5['runner_sha256']==sha(a.worker.read_bytes()) and r['depth_levels']==25 and r5['depth_levels']==5
    control=a.native_control.read_bytes();check_host(json.loads(control))
    assert inp['sample_step_ms']==inp5['sample_step_ms']==STEP and inp['starting_cash_USDT']==inp5['starting_cash_USDT']==INITIAL
    assert dec(inp['commission_rate'])==dec(inp5['commission_rate'])==TAKER
    assert inp['sources']==inp5['sources'] and list(inp['sources'])==['197']
    [s]=inp['sources'].values();assert sha(s['source'].encode())==s['source_sha256']
    assert 'basePeriod: 1d' in s['source'] and 'MarginLevel =20' in s['source'] and 'unit =0.015' in s['source']
    for day,full in inp['scope'].items():
        top5=inp5['scope'][day]
        assert full['top25_proof']['matched_top5_replay_grid_rows']==top5['depth_proof']['BBO_match_rows']==72001
        assert all(full[k]==top5[k] for k in ('marks','quotes','funding','begin_ms','end_ms','depth_proof'))
        assert len(full['depth'])==len(top5['depth'])==72001
    with localcontext() as ctx:
        ctx.prec=37
        perf,tested=produce(r['results'],inp)
        small_perf,ablation=produce(r5['results'],inp5)
    assert len(perf)==24 and len(small_perf)==2
    main=[p for ms,p in perf if not ms]; alternate=[p for ms,p in perf if ms]
    assert len(main)==len(alternate)==12 and all(x['trades'] for x in main+alternate)
    for ms,match in small_perf:
        [ref]=[p for delay,p in perf if delay==ms and p['period']==match['period']]
        assert ref==match
    out={'coverage':[[197,'Tested \u00b7 original BTC futures strategy on recorded top-25 depth',
        'All twelve primary and twelve delayed BTCUSDT historical paths completed. Every market order was fully covered by contemporaneous observed order-book levels. Source predicates, settings, fees, funding, cash, risk and marks were independently reconciled.']],
        'results':main,'delayed_market_fill_sensitivity':alternate,'path_checks':tested,
        'top_five_control':ablation,'source':{k:v for k,v in s.items() if k!='source'},
        'market':{day:{k:spec[k] for k in ('begin_ms','end_ms','depth_proof','top25_proof','quote_ref','mark_ref','funding')} for day,spec in inp['scope'].items()},
        'proof':{'top25_input_sha256':sha(raw),'top5_input_sha256':sha(raw5),'previous_source_and_market_r34_sha256':inp['parent_input_sha256'],
            'runner_sha256':sha(a.worker.read_bytes()),'top25_repeat_receipt_sha256':sha(run),'top5_receipt_sha256':sha(small),
            'native_control_receipt_sha256':sha(control),'control_code_sha256':sha(a.control_code.read_bytes()),
            'top5_stage_sha256':sha(a.top5_stage.read_bytes()),'top25_stage_sha256':sha(a.top25_stage.read_bytes()),
            'verifier_sha256':sha(Path(__file__).read_bytes())},
        'method':{'source':'The document discusses a commodity example. Its embedded executable configuration explicitly names Binance BTC futures with 1d chart and base periods. Both recorded BTC dates are inside that saved historical range. The exercised code reads depth and positions without consuming chart bars, enters at 0.015 BTC and retains the source 20x leverage setting. The native fixture confirms 10,000 USDT default capital and 200ms operation on GetDepth, GetPosition and market orders.',
            'randomness':'Independent four-hour cold starts at 06:00 UTC on 2021-05-01 and 2021-06-01. Preserve the three externally specified seed streams and their antithetic complements for both initial directions. The original Math.random seeds are unspecified and these are explicit stochastic benchmarks.',
            'book':'Use the price-ordered Binance futures snapshots published by Tardis. Every permitted market order matches full requested base size by sweeping known visible ask or bid volume at a snapshot with capture-local time no later than completion. Prices use integer cents and quantity uses thousandths of BTC. All 144,002 recorded grid rows match the prior five-level snapshots and separately captured best quotes. Displayed size and price are the execution bounds.',
            'timing':'Primary calls take 200ms as observed in the FMZ native fixture. A full parallel sensitivity adds 200ms to each market order, and re-evaluates every changed future order and account state. Delayed rows are separate. The five-level control preserves 22 early stops and 2 complete paths. These repeat exactly under top-25. Report performance only for complete runs.',
            'economics':'Current-position profit uses captured last trades, while marked performance and drawdown use recorded derivatives marks. Financing is applied at the first replay clock at or after the exact recorded venue settlement. Use the historical 0.04% taker fee, exact weighted average of observed accepted market sweep prices, signed official funding and allocated entry fees. Independent Decimal reconciliation verifies each order and ending cash. Test requires positive equity beyond initial margin throughout.',
            'limits':'All fills are modeled market sweeps of observed quantities. The benchmark assumes fixed observed books and the stated call delays. Venue impact, hidden liquidity and other market dates are outside the evidence. The 12 primary and 12 delayed benchmarks share data and are statistically dependent.'},
        'references':['https://docs.tardis.dev/downloadable-csv-files/data-types','https://docs.tardis.dev/historical-data-details/binance-futures',
            'https://github.com/binance/binance-public-data','https://www.binance.com/en/blog/futures/421499824684900660']}
    a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8',newline='\n')
    counter=Counter((p['extra_delay_ms'],p['completed']) for p in tested)
    print('complete magnitudes',dict(counter),'top5',sum(o['completed'] for o in ablation),'report',sha(a.output.read_bytes()),flush=True)
    for output in (main,alternate):
        print('closes',sum(o['trades'] for o in output),'wins',sum(o['net_wins'] for o in output),'closed net range',
              (min(o['net'] for o in output),max(o['net'] for o in output)),'marked range',
              (min(o['mark_to_market_net'] for o in output),max(o['mark_to_market_net'] for o in output)),flush=True)


if __name__=='__main__':
    main()
