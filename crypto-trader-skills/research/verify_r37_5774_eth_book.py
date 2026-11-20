"""Verify #5774 source order scheduling and both independently funded hedge sides."""
import argparse
from collections import defaultdict
from decimal import Decimal as D, localcontext
import gzip
import itertools
import json
from pathlib import Path

from fmz_native_round20_880_capture import sha
from verify_r34_btc_random_book import drawdown, random_sequence, sum_path
from verify_r35_197_recorded_depth import book, close, market

STEP=200
TAKER=D('0.0004')
INITIAL=D(10_000)
BASE=1000
LEV=20
ZERO=D(0)
TARGET=D('0.4')
UNIT=500
MID=2**31


def check_native(fixture):
    assert [x['first'] for x in fixture['results']]==['sell','buy']
    for v in fixture['results']:
        assert [r['Type'] for r in v['one']]==[1 if v['first']=='sell' else 0]
        for name,amounts in (('both',[.5,.5]),('increased',[.5,1]),('reopened',[.5,1])):
            assert [r['Type'] for r in v[name]]==[0,1]
            assert [r['Amount'] for r in v[name]]==amounts
        assert [(r['Type'],r['Amount']) for r in v['shortOnly']]==[(1,1)]
        for op in v['trace']:
            assert op['end']-op['start']==(0 if op['call'].startswith('Set') else 200)
        assert v['trace'][2]['got']['Balance']==10_000


def route(spec,clock,tag,units,used):
    age,asks,bids=book(spec,clock)
    assert age<=5_000_000
    i=(clock-spec['begin_ms'])//STEP
    at=spec['depth'][i][0]
    direction=tag in ('buy','closesell')
    found=used[at,direction]
    remain=units
    used_now=[]
    value=0
    for price,size in (asks if direction else bids):
        take=min(remain,size-found[price]);assert take>=0
        if take:
            used_now.append([price,take]);found[price]+=take
            value+=price*take;remain-=take
        if not remain:break
    assert not remain,(tag,units,at,remain)
    return D(value)/100_000, used_now,age,at


def rules(run,spec):
    current=[0,0];weighted=[ZERO,ZERO]
    used=defaultdict(lambda:defaultdict(int))
    randomized=random_sequence(run['seed'],run['mirror']); recorded=iter(run['draws']); history=iter(run['orders'])
    clock=spec['begin_ms']+STEP
    end=spec['end_ms']
    ended=False
    def attempt(tag,size=UNIT):
        nonlocal clock,ended
        if ended:return
        clock+=STEP+run['delay']
        if clock>=end:
            ended=True;return
        o=next(history)
        api='Buy' if tag in ('buy','closesell') else 'Sell'
        assert (o['clock'],o['api'],o['direction'],o['units'])==(clock,api,tag,size)
        value,rows,age,timestamp=route(spec,clock,tag,size,used)
        assert (o['portions'],o['age'],o['snapshot_us'])==(rows,age,timestamp)
        close(o['notional'],value)
        side=0 if tag in ('buy','closebuy') else 1
        if tag.startswith('close'):
            assert size==current[side]
            current[side]=0;weighted[side]=ZERO
        else:
            current[side]+=size;weighted[side]+=value
        assert o['quant']==current
        close(o['basis'][0],weighted[0]);close(o['basis'][1],weighted[1])
    def draw():
        b=next(randomized)
        assert next(recorded)==[clock,b,*current]
        return b
    for tick,positions in run['records']:
        assert clock==tick<end
        last,_=market(spec,tick)
        keys=[i for i,s in enumerate(current) if s]
        assert [p['Type'] for p in positions]==keys
        for i,p in zip(keys,positions,strict=True):
            q=D(current[i])/BASE
            pnl=(1 if i==0 else -1)*(q*last-weighted[i]);margin=weighted[i]/LEV
            close(p['Amount'],q);close(p['Price'],weighted[i]/q);close(p['Profit'],pnl);close(p['Margin'],margin)
        if not keys:
            b=draw()
            attempt('sell');attempt('buy')
            if b>MID:attempt('sell')
            if 0<b<=MID:attempt('buy')
        else:
            i=keys[0];m=weighted[i]
            profit=(1 if i==0 else -1)*(D(current[i])*last/BASE-m)
            if profit>TARGET:
                attempt('closebuy' if i==0 else 'closesell',current[i])
                if not ended:
                    b=draw()
                    if (i==0 and b<MID) or (i==1 and b>MID):
                        attempt('buy' if i==0 else 'sell')
            elif profit<-m/LEV:
                attempt('buy' if i==0 else 'sell')
        if ended:break
        clock+=STEP+(60_000 if keys else 0)
    assert next(recorded,None) is None and next(history,None) is None
    assert run['tail']['clock']==end and clock>=end and not run['unsupported']
    assert [p['size'] for p in run['tail']['positions']]==current
    for p,expected in zip(run['tail']['positions'],weighted,strict=True):close(p['notional'],expected)


def ledger(run,spec):
    q=[0,0]; basis=[ZERO,ZERO]; entry_fee=[ZERO,ZERO]; carry=[ZERO,ZERO]
    cash=INITIAL
    funding_total=[ZERO,ZERO]
    all_fees=ZERO
    peak=min_margin=INITIAL
    max_dd=percentage=ZERO
    goal=spec['funding'];settling=(goal['exchange_settlement_ms']+STEP-1)//STEP*STEP
    assert len(run['funding'])==1
    [posted]=run['funding']
    assert posted['clock']==settling and posted['venue_ms']==goal['exchange_settlement_ms']
    mark0=D(str(goal['prior_mark'][3]));rate=D(str(goal['rate']))
    cap=[D(str(x)) for x in goal['official_two_minute_mark_price_bounds_USDT']]
    assert cap[0]<=mark0<=cap[1]
    assert goal['prior_mark'][1]<=goal['prior_mark'][0]<=goal['boundary_ms']*1000
    trades=[]
    orders={r['clock']:r for r in run['orders']}
    assert len(orders)==len(run['orders'])
    snapshot_position=defaultdict(lambda:defaultdict(int))
    ages=[]; largest=0; multi=0; active=0; peak_exposure=ZERO
    def unreal(m):
        return D(q[0]-q[1])*m/BASE-basis[0]+basis[1]
    for index in range(len(spec['marks'])):
        t=spec['begin_ms']+index*STEP
        if t>spec['begin_ms'] and all(q):active+=1
        _,mark=market(spec,t)
        if t==settling:
            assert posted['quantity']==q
            close(posted['price'],mark0);close(posted['rate'],rate)
            for i in (0,1):
                flow=D(q[i])/BASE*mark0*rate*(-1 if i==0 else 1)
                close(posted['sum'][i],flow)
                carry[i]+=flow
                funding_total[i]+=flow
                cash+=flow
            close(posted['wallet'],cash)
        min_margin=min(min_margin,cash+unreal(mark)-D(sum(q))*mark/BASE/LEV)
        if t in orders:
            o=orders[t];label=o['direction'];size=o['units']
            weight,parts,age,_=route(spec,t,label,size,snapshot_position)
            assert parts==o['portions']
            detail=weight*TAKER
            close(o['fee'],detail);close(o['mark'],mark)
            all_fees+=detail
            ages.append(age);largest=max(largest,len(parts));multi+=len(parts)>1
            cash-=detail
            i=0 if label in ('buy','closebuy') else 1
            if label.startswith('close'):
                assert size==q[i]
                gross=(weight-basis[i])*(1 if i==0 else -1)
                fees=detail+entry_fee[i]
                trades.append({'at':t,'side':i,'gross':gross,'fees':fees,'after_fees':gross-fees,'funding':carry[i],'net':gross-fees+carry[i]})
                cash+=gross
                close(o['gross'],gross)
                q[i]=0
                basis[i]=entry_fee[i]=carry[i]=ZERO
            else:
                assert cash+detail-sum(basis)/LEV>weight/LEV+detail
                q[i]+=size;basis[i]+=weight;entry_fee[i]+=detail
                close(o['gross'],ZERO)
            close(o['wallet'],cash)
            assert o['quant']==q
        peak_exposure=max(peak_exposure,D(sum(q))*mark/BASE)
        un=unreal(mark)
        equity=cash+un
        assert equity>D(sum(q))*mark/BASE/LEV
        peak=max(peak,equity)
        max_dd=max(max_dd,peak-equity)
        percentage=max(percentage,(peak-equity)/peak)
    close(run['marginBuffer'],min_margin)
    t=run['tail'];close(t['mark'],mark);close(t['wallet'],cash);close(t['UPnL'],un)
    assert run['concurrent_hold_steps']==active
    assert q==[s['size'] for s in t['positions']]
    for p,expected in zip(t['positions'],basis,strict=True):close(p['notional'],expected)
    fields=('gross','fees','after_fees','funding','net')
    totals={k:sum((r[k] for r in trades),ZERO) for k in fields}
    close(equity-INITIAL,totals['net']-sum(entry_fee)+sum(carry)+un)
    results={k:float(v) for k,v in totals.items()}
    for p,k in (('gross','gross'),('fee','after_fees'),('net','net')):
        dd,ratio=drawdown(sum_path(r[k] for r in trades))
        results[p+'_dd']=float(dd);results[p+'_dd_pct']=float(ratio);results[p+'_wins']=sum(r[k]>ZERO for r in trades)
    results.update(trades=len(trades),unsettled=sum(bool(x) for x in q),starting_equity=float(INITIAL),execution=0,
                   mark_to_market_net=float(equity-INITIAL),remaining_unrealized=float(un))
    diagnostics={'orders':len(orders),'largest_market_sweep_levels':largest,'multilevel_orders':multi,'max_snapshot_age_us':max(ages),
                 'max_gross_notional_USDT':peak_exposure,'marked_drawdown_USDT':max_dd,'marked_drawdown_fraction':percentage,
                 'min_initial_margin_buffer_USDT':min_margin,'all_fees_USDT':all_fees,'funding_paid_by_side_USDT':funding_total,
                 'long_closed':sum(r['side']==0 for r in trades),'short_closed':sum(r['side']==1 for r in trades),
                 'both_held_seconds':D(active)*STEP/1000,'ending_long_short_ETH':[str(D(x)/BASE) for x in q],
                 'order_path_sha256':sha(json.dumps(run['orders'],separators=(',',':')).encode())}
    return results,diagnostics


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('input','first','second','fixture','fixture-code','stage','runner','output'):
        p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args()
    blob=a.input.read_bytes();r1=a.first.read_bytes()
    assert r1==a.second.read_bytes()
    job=json.loads(gzip.decompress(blob));run=json.loads(r1)
    assert sha(blob)==run['input_sha256'] and sha(a.runner.read_bytes())==run['worker_sha256']
    f=a.fixture.read_bytes();native=json.loads(f);check_native(native)
    assert sha(job['source'].encode())==job['source_sha256']
    assert job['venue']=='Binance USD-M ETHUSDT perpetual' and job['level_count']==5
    assert job['starting_cash_USDT']==INITIAL and D(str(job['taker_rate']))==TAKER and job['leverage']==20
    assert all(w in job['source'] for w in ('"currency":"xxx_USDT"',"['ETH_Usdt'",'if (redom == 0,1,2,3,4,5)',
             'if (redom == 5,6,7,8,9,10)','position[0].Type'))
    expected=set(itertools.product(job['scope'],(1,42,20201120),(False,True),(0,200)))
    assert expected=={(r['day'],r['seed'],r['mirror'],r['delay']) for r in run['results']} and len(run['results'])==24
    assert all(s['proof']['exact_BBO_matches']==72_001 for s in job['scope'].values())
    public=[];delayed=[];validation=[]
    with localcontext() as ctx:
        ctx.prec=37
        for r in run['results']:
            spec=job['scope'][r['day']]
            rules(r,spec)
            metrics,evidence=ledger(r,spec)
            delay=r['delay']; reversed_seed=' mirror' if r['mirror'] else ''
            scope=f"{r['day']} 06:00-10:00 UTC / seed {r['seed']}{reversed_seed}"
            metrics.update(id=5774,name='Dual-sided martingale, named ETH variant',
                           market='Binance USD-M ETHUSDT perpetual',currency='USDT',quote_currency='USDT',currency_decimal_places=8,
                           group=f'FMZ archived ETH source / recorded top-five depth +{delay}ms',source=job['source_url'],
                           period=scope,interval='1d / 1h archived; 200ms causal host',exit='Separate long and short market exits')
            (delayed if delay else public).append(metrics)
            validation.append({'scope':scope,'extra_delay_ms':delay,**evidence})
    assert len(public)==len(delayed)==12
    assert sum(r['trades'] for r in public)==84 and sum(r['trades'] for r in delayed)==83
    report={'coverage':[[5774,'Tested \u00b7 named ETH variant with both futures books isolated',
                          'Original active source used the first expressly named symbol, ETH. Verified native long-first position ordering, paired hedge accounting, visible full market sweeps, fees and funding in twelve complete primary and twelve latency paths.']],
            'results':public,'delayed_market_fill_sensitivity':delayed,'validation':validation,
            'archive_identity':{'url':job['source_url'],'archive_sha256':job['archive_sha256'],'source_sha256':job['source_sha256'],
              'publisher':'https://www.fmz.com/strategy/353904','variant':job['source_variant']},
            'provenance':{'staged_input_sha256':sha(blob),'receipt_sha256':sha(r1),'native_fixture_receipt_sha256':sha(f),
              'native_fixture_engine_sha256':native['engine_sha256'],'native_fixture_market_sha256':native['market_sha256'],
              **{k+'_sha256':sha(getattr(a,k).read_bytes()) for k in ('fixture_code','stage','runner')},
              'verifier_sha256':sha(Path(__file__).read_bytes()),
              'data':{day:{k:s[k] for k in ('begin_ms','end_ms','proof','funding')} for day,s in job['scope'].items()}},
            'method':{'archive_scope':'The saved exchange metadata is a placeholder, while ETH is the first explicit symbol in the archived list. The last and sole main routine uses a single injected exchange. This is an ETH named variant of the unchanged archived rule. Other explicitly listed symbols are outside this evidence.',
              'position_abi':'The native Ethereum fixture confirms independent simultaneous long and short positions. It reports a long first whenever both exist, regardless of submission order or which side reopened. The authored comma expressions open both books while flat, plus a third 0.5 ETH leg selected by seeded RNG. The original source subsequently manages only its first returned position.',
              'market_data':'Two cold-start four-hour windows in May and June 2021. Recorded public normalized top-five Binance ETH order books and separate BBO projection agree in all 144,002 replay grid points. The May capture contained an indicative funding rate that differs from the final Binance archived settlement. Cash uses the archived settlement rate. Both observed boundary marks agree with nearby checksummed venue mark candles.',
              'fills':'Each market order uses displayed ETH bid or ask depth known at the call completion time. Use independent per-snapshot side and price capacity, with prior consumption tracked. The source covers 20x leverage and observed 200ms position/order calls. Benchmark fee is 0.04% taker. The sensitivity adds 200ms to each order and executes a complete causal replay.',
              'settlement':'Keep separate average entry, gross exposure, fees and signed funding for long and short. P&L triggers use captured last trade. Equity and marked drawdown use captured mark prices. Apply funding using the exact venue settlement epoch followed by the first 200ms grid point. Prespecified seeds and antithetic complements keep both sides represented.',
              'limitations':'Observed liquidity is replayed as fixed. Price impact, hidden size and actual queue executions remain outside this model. Results use two historical dates and repeated seeded paths. Closed returns can differ from total returns while either side stays open.'},
            'references':['https://docs.tardis.dev/downloadable-csv-files/data-types','https://github.com/binance/binance-public-data',
                          'https://www.fmz.com/user-guide/backtesting-system/backtest-modes-and-order-matching','https://www.binance.com/en/blog/futures/421499824684900660']}
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8',newline='\n')
    for name,items in (('primary',public),('delayed',delayed)):
        print(name,'closes',sum(x['trades'] for x in items),'wins',sum(x['net_wins'] for x in items),'closed net range',
                 (min(x['net'] for x in items),max(x['net'] for x in items)), 'marked range',
                 (min(x['mark_to_market_net'] for x in items),max(x['mark_to_market_net'] for x in items)),flush=True)
    print(sha(a.output.read_bytes()),flush=True)


if __name__=='__main__':
    main()
