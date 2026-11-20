"""Reconcile the pinned #4899 native fill path, funding and marked risk in Decimal."""

import argparse
from bisect import bisect_right
from collections import Counter
from decimal import Decimal as D, localcontext
import gzip
import json
from pathlib import Path

from fmz_native_round20_880_capture import sha

START=D(100_000)
ZERO=D(0)
MAKER=D('0.0002')
TAKER=D('0.0004')
TICK=D('0.01')
EPSILON=D('0.0000001')
STEP=900_000


def d(v):
    return D(str(v))


def near(actual,expected):
    assert abs(d(actual)-expected)<=EPSILON,(actual,expected)


def drawdown(points):
    peak=START
    loss=percent=ZERO
    for cumulative in points:
        equity=START+cumulative
        peak=max(peak,equity)
        loss=max(loss,peak-equity)
        percent=max(percent,(peak-equity)/peak)
    return loss,percent


def quote_price(quote,sell):
    return d(quote[2 if sell else 3])


def price_crosses(quote,sell,limit):
    px=quote_price(quote,sell)
    return px>=limit if sell else px<=limit


def order_path(run,spec):
    m=run['model']
    prices=run['chart']['prices'][:-1]
    times=[p[0] for p in prices]
    begin,end=spec['begin'],spec['end']
    candles={r[0]:r for r in spec['market']['swap']['data']}
    assert times==sorted(set(times)) and times[0]==begin and times[-1]==end==m['stop_ms']
    assert prices[-1]==m['ticker'] and m['checked_clock_ms']<run['chart']['prices'][-1][0]
    for at,last,bid,ask in prices:
        _,_,high,low,*_=candles[at//STEP*STEP]
        assert low<=d(last)*100<=high and d(ask)-d(last)==d(last)-d(bid)==TICK
    originals={x['id']:x for x in m['put']}
    history={o['Id']:o for o in m['history']+m['pending']}
    cancellations={c['id']:c for c in m['cancellations']}
    assert len(originals)==len(m['put'])==len(history) and originals.keys()==history.keys()
    assert all(originals) and cancellations.keys()=={i for i,o in history.items() if o['Status']==2}
    brackets={}
    for poll in m['changes']:
        assert 0<poll['after']-poll['before']<=200
        for seen in poll['open']:
            o=history[seen['Id']]
            assert not seen['Status'] and not seen['DealAmount'] and o['Time']<=poll['after']
            assert all(seen[k]==o[k] for k in ('Id','Time','Price','Amount','Type','Offset','Symbol','ContractType'))
        for i,last in poll['unseen']:
            assert i not in brackets
            brackets[i]=(last,poll['after'])
    fills=[]
    for i,o in history.items():
        sub=originals[i]
        posted=o['Time']
        sell=o['Type']==1
        limit=d(o['Price'])
        amount=d(o['Amount'])
        assert o['Symbol']=='ETH_USDT.swap' and o['ContractType']=='swap'
        assert begin<=sub['start']<=posted==sub['end']<end and sell==(sub['side']=='Sell')==bool(o['Offset'])
        assert sub['direction']==('closebuy' if sell else 'buy') and abs(amount-d(sub['size']))<=D('0.0005')
        step=bisect_right(times,posted)
        prev=prices[step-1]
        market=sub['limit']==-1
        assert market or abs(limit-d(sub['limit']))<=TICK/2
        immediate=market or price_crosses(prev,sell,limit)
        hit=None if immediate else next((q for q in prices[step:] if price_crosses(q,sell,limit)),None)
        if o['Status']==2:
            cancel=cancellations[i]
            assert cancel['result'] and posted<cancel['before']<=cancel['after']<end
            assert not immediate and not o['DealAmount'] and (hit is None or hit[0]>cancel['after'])
            continue
        if o['Status']==0:
            assert not immediate and hit is None and not o['DealAmount']
            continue
        assert o['Status']==1 and (immediate or hit is not None)
        at,price=(posted,quote_price(prev,sell)) if immediate else (hit[0],limit)
        assert posted<=at<end and price==d(o['AvgPrice']) and amount==d(o['DealAmount'])>ZERO
        if not immediate and i in brackets:
            assert brackets[i][0]<=at<=brackets[i][1]
        fills.append({'at':at,'id':i,'qty':amount,'price':price,'close':sell,'posted':posted,'limit':limit,
              'fee':amount*price*(TAKER if immediate else MAKER), 'type':'taker' if immediate else 'maker',
              'source_pending_bracket':brackets.get(i)})
    assert len({f['at'] for f in fills})==len(fills)
    return sorted(fills,key=lambda x:x['at']),prices


def without_funding(fills):
    states=[]
    qty=basis=net=ZERO
    for f in fills:
        size,price=f['qty'],f['price']
        net-=f['fee']
        if f['close']:
            assert ZERO<size<=qty
            allocated=basis*size/qty
            net+=size*price-allocated
            basis-=allocated
            qty-=size
        else:
            qty+=size
            basis+=size*price
        states.append((qty,net))
    return states


def settlement_events(model,spec,fills):
    before,after=spec['begin'],spec['end']
    times=[f['at'] for f in fills]
    states=without_funding(fills)
    official={t:D(r)/10**8 for t,r,*_ in spec['market']['funding']['data'] if before+100<t<=after+100}
    assert len(official)==3
    bars={k:{r[0]:r for r in spec['market'][k]['data']} for k in ('swap','index')}
    tail=model['account']
    observations=model['observations']+[{**model['terminalAccount'],'wallet':d(tail['Equity'])-d(tail['UPnL'])}]
    settled={}
    book_cashflow=ZERO
    for obs in observations:
        observed_time=obs['at']
        sampled=bisect_right(times,observed_time)
        unfunded=states[sampled-1][1] if sampled else ZERO
        difference=d(obs['wallet'])-START-unfunded
        cashflow=difference-book_cashflow
        if abs(cashflow)<=EPSILON:
            continue
        [at]=[t for t in official if obs['previous_account_ms']<t<=observed_time]
        assert at not in settled and at not in times
        boundary=round(at/STEP)*STEP
        qty=states[bisect_right(times,at)-1][0]
        rate=official[at]
        environment=[market[t] for market in bars.values() for t in (boundary-STEP,boundary)]
        low=min(D(r[3])/100 for r in environment)
        high=max(D(r[2])/100 for r in environment)
        implied=-cashflow/(qty*rate)
        assert low<=implied<=high,(model['day'],at,implied,low,high)
        settled[at]={'cash_flow_USDT':cashflow,'rate':rate,'venue_time_ms':at,'pre_settlement_ETH':qty,
            'modeled_mark_USDT':implied,'public_bar_price_bounds_USDT':[low,high],
            'native_account_bracket_ms':[obs['previous_account_ms'],observed_time]}
        book_cashflow=difference
    assert settled.keys()==official.keys()
    return settled


def accounting(m,spec,fills,quotes,funding):
    native_quotes={p[0]:d(p[1]) for p in quotes}
    orders={v['at']:v for v in fills}
    assert not orders.keys() & funding.keys()
    times=sorted(native_quotes.keys() | orders.keys() | funding.keys())
    assert times[0]==spec['begin'] and times[-1]==max(funding)
    cash=START
    qty=basis=held_fees=held_funding=maker=taker=all_funding=ZERO
    curves={k:[] for k in ('gross','after_fees','net')}
    observations=[]
    closed=[]
    for at in times:
        if at in native_quotes:
            price=native_quotes[at]
        if at in funding:
            event=funding[at]
            assert qty==event['pre_settlement_ETH']
            carry=event['cash_flow_USDT']
            cash+=carry
            held_funding+=carry
            all_funding+=carry
        if at in orders:
            row=orders[at]
            size,px,fee=(row[k] for k in ('qty','price','fee'))
            cash-=fee
            if row['type']=='maker':
                maker+=fee
            else:
                taker+=fee
            if row['close']:
                assert ZERO<size<=qty
                ratio=size/qty
                trade_basis=basis*ratio
                opening=held_fees*ratio
                funding_share=held_funding*ratio
                gross=px*size-trade_basis
                fees=fee+opening
                cash+=gross
                qty-=size
                basis-=trade_basis
                held_fees-=opening
                held_funding-=funding_share
                closed.append({'id':row['id'],'at':at,'gross':gross,'fees':fees,'funding':funding_share,
                               'after_fees':gross-fees,'net':gross-fees+funding_share})
            else:
                qty+=size
                basis+=size*px
                held_fees+=fee
        assert qty>ZERO or at<spec['begin']+2000
        unrealized=qty*price-basis
        net=cash-START+unrealized
        assert cash+unrealized>qty*price/10
        curves['gross'].append(net-all_funding+maker+taker)
        curves['after_fees'].append(net-all_funding)
        curves['net'].append(net)
        observations.append((cash,unrealized))
    [tail]=m['positions']
    assert d(tail['Amount'])==qty and tail['Type']==0 and tail['MarginLevel']==10
    near(tail['Price'],basis/qty)
    near(tail['Margin'],basis/10)
    near(m['account']['Equity'],cash+unrealized)
    near(m['account']['UPnL'],unrealized)
    for o in m['observations']:
        obs_cash,obs_mark=observations[bisect_right(times,o['at'])-1]
        near(o['wallet'],obs_cash)
        near(o['account']['UPnL'],obs_mark)
    metrics=('gross','fees','net','after_fees','funding')
    totals={k:sum((r[k] for r in closed),ZERO) for k in metrics}
    near(curves['net'][-1],totals['net']-held_fees+held_funding+unrealized)
    result={k:float(v) for k,v in totals.items()}
    details={'marked_drawdown':{k:list(drawdown(v)) for k,v in curves.items()},
             'closed_drawdown':{},'final_wallet_USDT':cash,'final_equity_USDT':cash+unrealized,'last_mark_USDT':price,
             'remaining_qty_ETH':qty,'remaining_fees_USDT':held_fees,'remaining_funding_USDT':held_funding,
             'fees_USDT_total':maker+taker,'maker_fees_USDT_total':maker,'taker_fees_USDT_total':taker,
             'funding_USDT_total':all_funding,'closed_reductions_sha256':sha(json.dumps(closed,default=str).encode()),
             'close_examples':closed[:1]+closed[-1:]}
    for prefix,metric in (('gross','gross'),('fee','after_fees'),('net','net')):
        value=ZERO
        points=[]
        for row in closed:
            value+=row[metric]
            points.append(value)
        loss,fraction=drawdown(points)
        details['closed_drawdown'][metric]=[loss,fraction]
        result[prefix+'_dd']=float(loss)
        result[prefix+'_dd_pct']=float(fraction)
        result[prefix+'_wins']=sum(r[metric]>ZERO for r in closed)
    result.update(trades=len(closed),unsettled=1,starting_equity=float(START),execution=0,
                  mark_to_market_net=float(curves['net'][-1]),remaining_unrealized=float(unrealized))
    return result,details


def verify(run,spec,source):
    m=run['model']
    fills,quotes=order_path(run,spec)
    funding=settlement_events(m,spec,fills)
    measures,detail=accounting(m,spec,fills,quotes,funding)
    physical={x[0]:x for x in spec['trade_minute_reference']['rows']}
    diagnostics=Counter()
    for row in fills:
        r=physical[row['at']//60_000*60_000]
        diagnostics[row['type']+'_modeled_fills']+=1
        diagnostics[row['type']+'_simulated_price_inside_observed_minute_range']+=int(r[3]<=row['price']*100<=r[2])
    detail.update({'day':m['day'],'cancelled_orders':len(m['cancellations']),'stress_checks':dict(diagnostics),
        'pending_at_cutoff':m['pending'],'settlements':list(funding.values()),
        'native_source_stop_ms':m['stop_ms'],'native_terminal_account_ms':m['terminalAccount']['at'],
        'first_excluded_quote_ms':run['chart']['prices'][-1][0],
        'native_order_path_sha256':sha(json.dumps(fills,default=str).encode()),'fill_examples':fills[:2]+fills[-2:]})
    measures.update(id=4899,name='ETH long-only USDT / coin balancing grid',group='FMZ Native \u00b7 Archived quote model',
        source=source,market='Binance USD-M ETHUSDT perpetual',period=m['day']+' 24h UTC',currency='USDT',
        quote_currency='USDT',currency_decimal_places=8,interval='30m / 15m native simulated ticks',
        exit='Archived market and limit reductions. Open inventory marked at cutoff.')
    return measures,detail


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('input','first','second','stage','worker','output'):
        parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args()
    data,canonical=args.input.read_bytes(),args.first.read_bytes()
    assert canonical==args.second.read_bytes()
    job,receipt=json.loads(gzip.decompress(data)),json.loads(canonical)
    assert receipt['input_sha256']==sha(data) and job['source_sha256']==receipt['source_sha256']==sha(job['source'].encode())
    assert job['fees_pct']==[0.02,0.04] and job['starting_cash_USDT']==START
    assert job['parameters']=={'pricePrecision':2,'amountPrecision':3,'linjie':30,'leverage':10}
    results,diagnostics=[],[]
    with localcontext() as ctx:
        ctx.prec=42
        for run in receipt['windows']:
            output,detail=verify(run,job['scope'][run['model']['day']],job['source_url'])
            results.append(output)
            diagnostics.append(detail)
    assert [r['day'] for r in diagnostics]==['2021-05-01','2021-05-19','2021-05-31']
    assert [r['stress_checks']['maker_modeled_fills'] for r in diagnostics]==[370,521,412]
    assert [r['stress_checks']['taker_modeled_fills'] for r in diagnostics]==[112,185,156]
    assert [r['cancelled_orders'] for r in diagnostics]==[402,477,449]
    out={'coverage':[[4899,'Tested \u00b7 archived ETH balance grid with FMZ modeled fills',
        'Three prespecified May 2021 UTC days using the original ETHUSDT settings. An independent native quote trace verifies every modeled order and cancellation. A separate Decimal ledger reconciles closed P&L, marked equity, fees, funding and cutoff inventory.']],
        'results':results,'diagnostics':diagnostics,
        'source':{'url':job['source_url'],'sha256':job['source_sha256'],'document_sha256':job['archive_document_sha256'],
                  'publisher':'https://www.fmz.com/strategy/339698','parameters':job['parameters']},
        'proof':{'input_sha256':sha(data),'receipt_sha256':sha(canonical),'engine_sha256':receipt['engine_sha256'],
            'stage_sha256':sha(args.stage.read_bytes()),'worker_sha256':sha(args.worker.read_bytes()),
            'verifier_sha256':sha(Path(__file__).read_bytes())},
        'venue_bindings':{day:{k:v['references'] for k,v in spec['market'].items()} |
            {'observed_1m':spec['trade_minute_reference']['reference']} for day,spec in job['scope'].items()},
        'definitions':{'scope':'Three independently restarted 24h UTC sessions inside the archived 2019 to 2024 author horizon. Flat initial position, 100,000 USDT available, 10x initial leverage and 30m / 15m FMZ chart and base settings.',
        'matching':'The exact archived JavaScript runs in the original FMZ simulated-tick engine. A separate native tape verifies bid/ask touch, the first eligible tick and full simulated size. Initial market and marketable limit executions charge 0.04% taker. Resting modeled fills execute at their limit price and charge 0.02% maker. Additional fixed slippage is zero.',
        'cutoff':'The strategy stops trading at the scheduled cutoff and no fill reaches the last scheduled tick. The final account includes the cutoff quote and the same boundary settlement, timestamped up to 10ms after UTC midnight. The next simulated quote is excluded from the final balance and marks.',
        'settlement':'Each native funding cash posting is reconstructed from consecutive account snapshots and an independently computed no-funding ledger. The signed rate and exact pre-settlement inventory imply a modeled mark inside the checksum-verified adjacent venue index and contract candles. One funding rate in the FMZ feed differs from the official archived rate by 1e-8. The replay uses the exact venue rate.',
        'drawdown':'Each reduction counts as a closed trade with prorated weighted basis, opening fee and held funding. Closed drawdown uses these reductions alone. Marked equity drawdown includes the open long position, funding and all fees at the modeled ticks and executed order times.',
        'observed_market_sensitivity':'Checksummed Binance 1m OHLC independently checks whether the modeled execution price appears within the observed low-high interval of that minute. This is only a price plausibility diagnostic. Historical queues, executable size and strategy paths under recorded order books remain unknown.'},
        'references':['https://www.fmz.com/strategy/339698','https://github.com/binance/binance-public-data',
            'https://www.fmz.com/user-guide/backtesting-system/backtest-modes-and-order-matching',
            'https://www.binance.com/en/blog/futures/421499824684900660'],
        'reproduction':'Stage the fixed three market windows and exact archive source. Invoke native worker twice in a fresh offline isolated process, copying the first receipt aside. Use this verifier with both receipts, which must be byte identical.'}
    args.output.write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8',newline='\n')
    print([(r['period'],r['trades'],r['net'],r['mark_to_market_net'],d['marked_drawdown']['net'],d['stress_checks']) for r,d in zip(results,diagnostics)])
    print(sha(args.output.read_bytes()))


if __name__=='__main__':
    main()
