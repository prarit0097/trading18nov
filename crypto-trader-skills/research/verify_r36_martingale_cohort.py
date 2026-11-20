"""Independently verify the R36 BTC martingale variants and exact native admission case."""
import argparse
from decimal import Decimal as D, ROUND_HALF_UP, localcontext
import gzip
import itertools
import json
from pathlib import Path

from fmz_native_round20_880_capture import sha
from verify_r34_btc_random_book import drawdown, random_sequence, sum_path
from verify_r35_197_recorded_depth import close, market, price_quantity

START=D(10_000)
ZERO=D(0)
SIZE=1000
LEV=50
STEP=200
TAKER=D('0.0004')
TARGET=D('0.05')
UNIT=D('0.001')
MID=2**31


def check_control(control):
    checks=control['checks']
    assert checks[5]['k']=='Sell' and checks[5]['arg']==[-1,100] and checks[5]['result'] is None
    assert checks[6]['result']==[] and checks[7]['result']['Equity']==10_000
    assert checks[1]['arg']==[50]
    assert [v['arg'][1] for v in checks if v['k']=='Buy']==[.001,.0015,.00225,.003375]
    assert [r['DealAmount'] for r in checks[-1]['result']]==[.001,.002,.002,.003]


def check_rules(run,spec):
    id=run['id']
    it=iter(run['orders'])
    seen=iter(run['draws'])
    gen=random_sequence(run['seed'],run['mirror'])
    units=0
    basis=ZERO
    n=UNIT
    clock=spec['begin_ms']+STEP
    end=spec['end_ms']
    cutoff=False
    assert not run['unsupported']
    def draw():
        v=next(gen)
        assert next(seen)==[clock,v,units]
        return v
    def submit(label,requested):
        nonlocal clock,units,basis,cutoff
        clock+=STEP+run['delay']
        if clock>=end:
            cutoff=True
            return
        api='Buy' if label in ('buy','closesell') else 'Sell'
        rounded=int((requested*SIZE).to_integral_value(rounding=ROUND_HALF_UP))
        row=next(it)
        assert (row['clock'],row['direction'],row['api'],row['units'])==(clock,label,api,rounded)
        close(row['requested'],requested)
        left,notional,sweep,age=price_quantity(spec,clock,label,rounded)
        assert not left and row['portions']==sweep and row['age']==age
        close(row['executedNotional'],notional)
        if label.startswith('close'):
            assert rounded==abs(units)
            units=0
            basis=ZERO
        else:
            units+=rounded if label=='buy' else -rounded
            basis+=notional
    for t,pos,profit,price,margin in run['decisions']:
        assert clock==t<end and units==pos
        qty=D(pos)/SIZE
        last,_=market(spec,t)
        basis_price=basis/abs(qty) if pos else ZERO
        un=qty*(last-basis_price)
        close(profit,un);close(price,basis_price);close(margin,basis/LEV)
        if not pos:
            pick=draw()
            if pick<MID:
                n=UNIT;submit('sell',n)
            else:
                n=UNIT if id==5147 else D('.002');submit('buy',n)
        elif un>TARGET:
            submit('closebuy' if pos>0 else 'closesell',abs(qty))
            if not cutoff and id==5149:
                follow=draw()
                if pos>0:
                    n=D('.002')
                    if follow<MID:
                        n=D('.003');submit('sell',n)
                else:
                    n=D('.004')
                    if follow>MID:
                        submit('buy',n)
        elif un<-basis/LEV*(2 if id==5147 else 1):
            n*=D('1.5') if id==5147 else D(1)
            submit('buy' if pos>0 else 'sell',n)
        if cutoff:
            break
        clock+=STEP+(60_000 if pos else 0)
    assert clock>=end==run['ending']['clock'] and next(it,None) is None and next(seen,None) is None
    assert run['ending']['posUnits']==units
    close(run['ending']['basis'],basis)


def funded_ledger(run,spec):
    orders={r['clock']:r for r in run['orders']}
    assert len(orders)==len(run['orders'])
    fund=spec['funding']
    due=((fund['exchange_settlement_ms']+STEP-1)//STEP)*STEP
    [actual]=run['funding']
    assert actual['clock']==due and actual['venueClock']==fund['exchange_settlement_ms']
    position=basis=open_fee=open_carry=all_fees=ZERO
    cash=START
    trough=START
    stock=None
    max_age=largest_sweep=multi=0
    marked_dd=marked_percent=ZERO
    peak=START
    realized=[]
    for index,r in enumerate(spec['marks']):
        t=spec['begin_ms']+STEP*index
        if r[3]==stock and t not in orders and t-STEP not in orders and t!=due and index!=len(spec['marks'])-1:
            continue
        stock=r[3]
        mark=D(str(stock))
        if t==due:
            rate,settlement=D(str(fund['rate'])),D(str(fund['prior_mark'][3]))
            open_carry=-position*settlement*rate
            cash+=open_carry
            close(actual['notional_BTC'],position);close(actual['mark'],settlement);close(actual['rate'],rate);close(actual['value'],open_carry)
        floating=position*(mark-basis/abs(position)) if position else ZERO
        trough=min(trough,cash+floating-abs(position)*mark/LEV)
        if t in orders:
            row=orders[t]
            size=D(row['units'])/SIZE
            side=row['direction']
            _,notional,parts,age=price_quantity(spec,t,side,row['units'])
            max_age=max(max_age,age)
            largest_sweep=max(largest_sweep,len(parts))
            multi+=len(parts)>1
            fee=notional*TAKER
            close(row['fee'],fee);close(row['mark'],mark);close(row['last'],D(r[2])/100)
            all_fees+=fee
            if side.startswith('close'):
                assert abs(position)==size
                gross=(notional-basis)*(1 if position>0 else -1)
                combined_fee=fee+open_fee
                realized.append(dict(gross=gross,fees=combined_fee,funding=open_carry,after_fees=gross-combined_fee,
                                     net=gross-combined_fee+open_carry))
                close(row['pnl'],gross)
                cash+=gross-fee
                position=basis=open_fee=open_carry=ZERO
            else:
                assert cash-basis/LEV>notional/LEV+fee
                close(row['pnl'],ZERO)
                position+=size if side=='buy' else -size
                basis+=notional
                open_fee+=fee
                cash-=fee
            close(row['wallet'],cash);assert position*SIZE==row['posUnits']
        floating=position*(mark-basis/abs(position)) if position else ZERO
        equity=cash+floating
        assert equity>abs(position)*mark/LEV
        peak=max(peak,equity)
        marked_dd=max(marked_dd,peak-equity)
        marked_percent=max(marked_percent,(peak-equity)/peak)
    tail=run['ending'];close(tail['wallet'],cash);close(tail['basis'],basis);close(tail['floating'],floating)
    close(tail['mark'],mark);close(run['minimumInitialMarginBuffer'],trough)
    assert tail['posUnits']==position*SIZE
    values={k:sum((r[k] for r in realized),ZERO) for k in ('gross','fees','funding','after_fees','net')}
    close(equity-START,values['net']-open_fee+open_carry+floating)
    out={k:float(v) for k,v in values.items()}
    for tag,metric in (('gross','gross'),('fee','after_fees'),('net','net')):
        a,b=drawdown(sum_path(r[metric] for r in realized));out[tag+'_dd']=float(a);out[tag+'_dd_pct']=float(b)
        out[tag+'_wins']=sum(r[metric]>0 for r in realized)
    out.update(trades=len(realized),unsettled=int(bool(position)),starting_equity=float(START),execution=0,
               mark_to_market_net=float(equity-START),remaining_unrealized=float(floating))
    detail={'orders':len(orders),'all_fees_USDT':all_fees,'max_book_age_us':max_age,'largest_sweep':largest_sweep,
            'orders_using_multiple_levels':multi,'marked_drawdown_USDT':marked_dd,'marked_drawdown_fraction':marked_percent,
            'ending_open_BTC':position,'opening_margin_buffer_floor_USDT':trough,
            'complete_order_and_random_path_sha256':sha(json.dumps([run['orders'],run['draws']],separators=(',',':')).encode())}
    return out,detail


def native_no_fill(job,depth,execution):
    rows=[]
    mdl=job['sources']['5150']
    args=mdl['defaults']
    assert args['ShortAmount']==100 and args['MarginLevel']==50 and args['short'] is True and args['long'] is False
    assert all(x in mdl['script'] for x in ('redom=0==short','redom=1==long','exchange.Sell(-1, n','"currency":"BTC_USDT"'))
    for day,r in execution.items():
        s=job['native_hourly'][day]
        b=depth['scope'][day]
        assert s['begin']==b['begin_ms'] and s['end']==b['end_ms']
        low_native=D(min(row[3] for row in s['data']['swap']['data'] if s['begin']<=row[0]<=s['end']))/10
        low_recorded=D(min(q[2] for q in b['quotes']))/100
        necessary=min(low_native,low_recorded)*args['ShortAmount']/args['MarginLevel']
        assert necessary>START
        expected=(s['end']-s['begin'])//(2*STEP)
        assert r['short_attempts']==r['empty_positions']==r['draws']==expected==36_000
        assert not r['buy_attempts'] and r['setupCalls']==1
        assert r['firstShortClock']==s['begin']+400 and r['lastShortClock']==r['cutoff']==s['end']
        assert not r['final'] and not r['history'] and r['account']['Balance']==r['account']['Equity']==START and not r['account']['UPnL']
        assert r['requests'] and all(x['key'] in ('swap','index','funding') for x in r['requests'])
        row={v:0 for v in ('gross','fees','after_fees','funding','net','execution','gross_dd','fee_dd','net_dd','gross_dd_pct',
                          'fee_dd_pct','net_dd_pct','gross_wins','fee_wins','net_wins','trades','unsettled','mark_to_market_net','remaining_unrealized')}
        row.update(id=5150,market='Binance USD-M BTCUSDT perpetual',name='Long/short martingale with edited multipliers',
                   group='FMZ original native admission / no fills',source=mdl['url'],period=f'{day} 06:00-10:00 UTC / archived defaults',
                   interval='1d / 1h original native simulation',exit='No filled opening orders',
                   currency='USDT',quote_currency='USDT',currency_decimal_places=8,starting_equity=float(START))
        rows.append((row,{'date':day,'lower_bound_margin_USDT':necessary,'observed_bid_floor_USDT':low_recorded,
                          'native_hourly_low_floor_USDT':low_native,'short_quantity_BTC':100,'native_receipt':r}))
    assert len(rows)==2
    return rows


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ('input','book','variants','variants-repeat','native','native-repeat','stage','variant-worker','native-worker','control','control-code','output'):
        ap.add_argument('--'+k,type=Path,required=True)
    a=ap.parse_args()
    byte_input=a.input.read_bytes(); byte_book=a.book.read_bytes()
    job=json.loads(gzip.decompress(byte_input)); book=json.loads(gzip.decompress(byte_book))
    x=a.variants.read_bytes();n=a.native.read_bytes(); c=a.control.read_bytes()
    assert x==a.variants_repeat.read_bytes() and n==a.native_repeat.read_bytes()
    check_control(json.loads(c))
    vr,nr=json.loads(x),json.loads(n)
    assert sha(byte_input)==vr['input_sha256']==nr['input_sha256'] and sha(byte_book)==vr['book_sha256']==job['recorded_book_sha256']
    assert vr['runner_sha256']==sha(a.variant_worker.read_bytes())
    for k,src in job['sources'].items():
        assert sha(src['script'].encode())==src['script_sha256']
    assert '"currency":"XXX_USDT"' in job['sources']['5147']['script'] and '"BTC_USDT"' in job['sources']['5147']['script']
    assert '"currency":"BTC_USDT","currency":"eth_USDT""currency":"bch_USDT"' in job['sources']['5149']['script']
    native_rows=native_no_fill(job,book,nr['rows'])
    variants=vr['results']
    ids=(5147,5149)
    keys={(r['id'],r['day'],r['seed'],r['mirror'],r['delay']) for r in variants}
    assert len(keys)==len(variants)==48 and keys==set(itertools.product(ids,book['scope'],(1,42,20201120),(False,True),(0,200)))
    main_results=[r for r,_ in native_rows]
    sensitivities=[]
    proof=[]
    with localcontext() as ctx:
        ctx.prec=37
        for run in variants:
            s=book['scope'][run['day']]
            check_rules(run,s)
            result,details=funded_ledger(run,s)
            id,delay=run['id'],run['delay']
            group=f'FMZ archived source BTC variant / recorded depth +{delay}ms'
            result.update(id=id,name='BTC martingale multiplier edit' if id==5147 else 'Long/short martingale, named BTC variant',
                  source=job['sources'][str(id)]['url'],market='Binance USD-M BTCUSDT perpetual',group=group,
                  period=f"{run['day']} 06:00-10:00 UTC / seed {run['seed']}"+(' mirror' if run['mirror'] else ''),
                  interval='1d / 1h archived settings; 200ms causal host',exit='Original market-order P&L conditions',
                  currency='USDT',quote_currency='USDT',currency_decimal_places=8)
            (sensitivities if delay else main_results).append(result)
            proof.append({'scope':result['period'],'id':id,'extra_delay_ms':delay,**details})
    c5147=sum(r['trades'] for r in main_results if r['id']==5147)
    c5149=sum(r['trades'] for r in main_results if r['id']==5149)
    assert (c5147,c5149)==(48,79)
    report={'coverage':[[5147,'Tested \u00b7 explicitly named BTC variant of archived martingale',
                         'The title and source symbol list name BTC, while the embedded exchange currency is a placeholder. Twelve complete BTC benchmarks and twelve latency runs cover the last, sole operative main declaration.'],
                        [5149,'Tested \u00b7 explicitly named BTC variant of archived martingale',
                         'Malformed stored market metadata names BTC, ETH and BCH. The operative main uses a single injected venue object and never rotates or consults other markets. BTC named variant completed twelve benchmarks and twelve latency runs, preserving full source behavior for that market.'],
                        [5150,'Tested \u00b7 original native settings, no fills',
                         'Two native FMZ sessions completed with 72,000 originally authored 100 BTC short attempts rejected, no buy attempts and no fills. Native balance remained 10,000 USDT. Positive lower-bound initial margin exceeds the available wallet in both sessions.']],
            'results':main_results,'delayed_market_fill_sensitivity':sensitivities,'modeled_path_checks':proof,
            'native_admission_diagnostics':[d for _,d in native_rows],
            'archive_sources':{i:{k:v for k,v in item.items() if k!='script'} for i,item in job['sources'].items()},
            'input_provenance':{'bound_source_and_native_hourly_sha256':sha(byte_input),'bound_recorded_book_sha256':sha(byte_book),
                  'recorded_result_receipt_sha256':sha(x),'native_result_receipt_sha256':sha(n),'native_engine_sha256':nr['native_engine_sha256'],
                  'native_fixture_receipt_sha256':sha(c),'native_market_window_matches':{d:{k:b['verification'] for k,b in spec['data'].items()} for d,spec in job['native_hourly'].items()},
                  **{k+'_sha256':sha(getattr(a,k).read_bytes()) for k in ('stage','variant_worker','native_worker','control_code')},
                  'independent_verifier_sha256':sha(Path(__file__).read_bytes())},
            'semantics':{'market_scope':'Two cold-start four-hour dates, 2021-05-01 and 2021-06-01. Both are inside the archived source backtest horizon. The #5147 and #5149 results use the explicitly named BTC variant. ETH, BCH, LTC or EOS configurations remain outside this evidence. The original metadata fields for #5147 and #5149 require a human choice of a named market.',
                'source_scope':'The last declaration of main is the executable entry point under JavaScript function declaration rules. The original JS bytes run unchanged. Older SetCurrency and exchange.IO declarations are overwritten. The sandbox runner exposes no multi-venue, HTTP or source order-mode changing APIs. Native and recorded paths call a single symbol originally named by the publisher.',
                'fees_and_risk':'Use 0.04% historic taker fees and exact observed full-depth sweeps, 50x source leverage, and external Binance funding rates when positions are held. Native control verifies nearest 0.001 BTC quantity handling and the 10,000 USDT default wallet. Snapshot causal support, funding, cash and marked drawdown are checked against independent Decimal accounting.',
                'rng':'Three xorshift32 seeds and their antithetic counterparts are explicit, reproducible draws for the stochastic source. Primary and 200ms delayed paths share the same historical dates. Original random seeds are not recoverable. #5150 overwrites its initial random direction with the published Boolean flags, making all flat attempts identical in side and quantity.',
                'proof_limits':'Native no-fills for #5150 apply to these windows and the archived default cash. Zero trades gives no win rate signal. Recorded-market fills remain modeled, using publicly captured displayed levels and fixed order timing. Delayed paths are full separate causal replays.'},
            'references':['https://docs.tardis.dev/downloadable-csv-files/data-types','https://github.com/binance/binance-public-data',
                         'https://www.fmz.com/user-guide/backtesting-system/backtest-modes-and-order-matching','https://www.binance.com/en/blog/futures/421499824684900660']}
    out=json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n';a.output.write_text(out,encoding='utf-8',newline='\n')
    for ids2,p in ((ids,main_results),(ids,sensitivities)):
        for i in ids2:
            v=[r for r in p if r['id']==i];print(i,len(v),sum(r['trades'] for r in v),sum(r['net_wins'] for r in v),min(r['net'] for r in v),max(r['net'] for r in v),flush=True)
    print('native rejects',sum(x['short_attempts'] for x in nr['rows'].values()),'report',sha(a.output.read_bytes()),flush=True)


if __name__=='__main__':
    main()
