"""Independently verify the two archived BTC native KDJ/risk-study replays."""

import argparse
from bisect import bisect_left,bisect_right
from decimal import Decimal,ROUND_HALF_UP,localcontext
from hashlib import sha256
from pathlib import Path
import gzip
import json

D=Decimal
ZERO=D(0)
EPS=D('0.000001')
ONE_TICK=D('0.1')
CASH=D('10000')
MAKER=D('0.0002')
TAKER=D('0.0004')
HOUR=3_600_000


def sha(raw):
    return sha256(raw).hexdigest()


def dec(x):
    return D(str(x))


def near(a,b):
    assert abs(dec(a)-b)<EPS,(a,b)


def wallet(r):
    return dec(r[3])-dec(r[4])


def cumulative(values):
    total=ZERO
    for v in values:
        total+=v
        yield total


def drawdown(start,changes):
    high=start
    value=ratio=ZERO
    for change in changes:
        equity=start+change
        high=max(high,equity)
        value=max(value,high-equity)
        ratio=max(ratio,(high-equity)/high)
    return value,ratio


def quote(market,t):
    return market[(t//HOUR)*HOUR]


def check_prices(job,r,market):
    spec=job['source'][r['id']]
    bars=r['maxRecords']
    assert len(bars)>100
    assert r['counts']['candles']>=r['counts']['tickCalls']
    for when,active,size,t,o,h,l,c in bars:
        step=spec['record_hours']*HOUR
        assert when>=active and active-t==step and size>=300
        used=[market[x] for x in range(t,t+step,HOUR)]
        reference=[used[0][1],max(z[2] for z in used),min(z[3] for z in used),used[-1][4]]
        assert [dec(x)*10 for x in (o,h,l,c)]==reference
    for t,last,bid,ask in r['prices']:
        _,_,hi,lo,_,_=quote(market,t)
        last,bid,ask=map(dec,(last,bid,ask))
        assert D(lo)/10<=last<=D(hi)/10
        assert ask-last==last-bid==ONE_TICK
    ending=r['ending']
    assert ending['ticker']['Time']==r['end'] and ending['now']<r['end']+10000


def funding_envelope(rates,market,index,entries,exit_stamp):
    lo=hi=mid=ZERO
    start=entries[0]['fill_ms']
    count=0
    for at,rate in rates.items():
        if not start<=at<exit_stamp: continue
        pos=sum((f['qty'] for f in entries if f['fill_ms']<at),ZERO)
        normalized=round(at/(8*HOUR))*8*HOUR
        bids=(min(market[normalized][3],index[normalized][3]),max(market[normalized][2],index[normalized][2]))
        amounts=[-pos*rate*D(price)/10 for price in bids]
        lo+=min(amounts);hi+=max(amounts)
        mid-=pos*rate*D(market[normalized][1])/10
        count+=1
    return lo,hi,mid,count


def verify(job,r):
    market={row[0]:row for row in job['market']['swap']['data']}
    index={row[0]:row for row in job['market']['index']['data']}
    rates={row[0]:D(row[1])/10**8 for row in job['market']['funding']['data']}
    check_prices(job,r,market)
    prices=r['prices']; price_stamps=[p[0] for p in prices]
    marks=r['marks']; mark_stamps=[m[0] for m in marks]
    flats=[p[0] for p in r['positions'] if not p[1]]
    flat_records=[marks[bisect_right(mark_stamps,f)-1] for f in flats]
    assert all(f[4]==0 for f in flat_records) and wallet(flat_records[0])==CASH
    submit={p['id']:p for p in r['submits'] if p['id']}
    pending=r['ending']['pending']
    obs={f[1]:f for f in r['filledStates']}
    cancel={x[1] for x in r['cancels'] if x[2]}
    assert len(submit)==len(r['submits'])==len(r['history'])+len(pending)
    assert {x['Id'] for x in r['history']}|{x['Id'] for x in pending}==set(submit)
    assert all(p['Status']==0 and p['DealAmount']==0 for p in pending)
    assert all(r['begin']<=p['before']<=p['after']<=r['end'] for p in submit.values())
    charges=[]; entries=[]; traces=[]
    bet=dec(job['source'][r['id']]['bet'])
    n=0; makers=0; takers=0; cancelled=0
    for o in r['history']:
        key=o['Id']; s=submit[key]; t=o['Time']; typ=o['Type']; offset=o['Offset']
        assert s['after']==t or o['Status']==2
        assert o['Symbol']=='BTC_USDT.swap' and o['ContractType']=='swap'
        assert (typ,offset)==(0,0) if s['direction']=='buy' else (typ,offset)==(1,1)
        p=dec(s['price']); q=dec(o['Amount'])
        assert q==dec(s['amount']).quantize(D('0.001'),rounding=ROUND_HALF_UP)
        if o['Status']==2:
            assert key in cancel and o['DealAmount']==0 and p>0
            cancelled+=1
            continue
        assert o['Status']==1 and o['DealAmount']==o['Amount']
        fill=dec(o['AvgPrice'])
        native_at=prices[bisect_right(price_stamps,t)-1]
        if p==-1:
            assert o['Price']==0 and q>0
            assert fill==dec(native_at[3 if typ==0 else 2])
            at=t; latest=t; cost=TAKER*q*fill; benchmark=dec(native_at[1]); takers+=1
            if not offset and not s['position']:
                near(s['amount'],bet*20/dec(s['ticker'][3]))
            if not offset and s['position']:
                [prev]=s['position']
                pnl=dec(prev[4]); margin=dec(prev[3]); size=dec(prev[1]); ratio=(-pnl)/margin
                if r['id']=='4834':
                    expected=size*(ratio if ratio>D('0.4') else D('0.2')) if margin/bet<D('2.5') else size*2
                else:
                    expected=size*ratio if margin/bet<D('2.5') else size*2
                near(s['amount'],expected)
        else:
            assert offset==1 and typ==1 and fill==dec(o['Price'])
            assert dec(native_at[2])<fill and key in obs
            found=obs[key]
            assert found[2]==1 and dec(found[3])==q and dec(found[4])==fill
            latest=found[0]
            crossings=prices[bisect_left(price_stamps,t):bisect_right(price_stamps,latest)]
            at,next_price=next((a,b) for a,_,b,_ in crossings if dec(b)>=fill)
            assert t<at<=latest and ((at//HOUR)==(latest//HOUR) or latest-at<20000)
            assert p==dec(s['position'][0][2])*D('1.01') or abs(p-dec(s['position'][0][2])*D('1.01'))<D('0.00002')
            cost=MAKER*q*fill; benchmark=fill; makers+=1
        assert at<r['end'] and q>0
        trace={'id':key,'fill_ms':at,'latest_observed_fill_ms':latest,'qty':q,'price':fill,'benchmark':benchmark,'fee':cost,'maker':p!=-1}
        if offset==0:
            entries.append(trace)
            continue
        n+=1
        assert n<len(flat_records) and at<=flats[n] and q==sum((a['qty'] for a in entries),ZERO)
        buying=sum((a['qty']*a['price'] for a in entries),ZERO)
        nominal=sum((a['qty']*a['benchmark'] for a in entries),ZERO)
        gross=benchmark*q-nominal
        gross_at_fill=fill*q-buying
        execution=gross-gross_at_fill
        fees=cost+sum((a['fee'] for a in entries),ZERO)
        changes=wallet(flat_records[n])-wallet(flat_records[n-1])
        carried=changes-gross_at_fill+fees
        funding_lower,funding_upper,mid,num=funding_envelope(rates,market,index,entries,at)
        assert funding_lower-EPS<=carried<=funding_upper+EPS,(r['id'],n,carried,funding_lower,funding_upper)
        assert abs(gross-fees-execution+carried-changes)<EPS
        traces.append({'entries':entries,'exit':trace,'gross':gross,'gross_at_fills':gross_at_fill,'fees':fees,
            'execution':execution,'after_fees':gross-fees,'funding':carried,'net':changes,
            'official_funding_schedule_count':num,'funding_price_envelope_USDT':[str(funding_lower),str(funding_upper)]})
        entries=[]
    assert n==len(flat_records)-1==len(traces)
    [open_position]=r['ending']['position']
    open_qty=sum((a['qty'] for a in entries),ZERO)
    assert dec(open_position['Amount'])==open_qty and open_position['MarginLevel']==20
    open_price=sum((a['qty']*a['price'] for a in entries),ZERO)/open_qty
    near(open_position['Price'],open_price)
    end_acc=r['ending']['account']
    end_mark=dec(r['ending']['ticker']['Last'])
    pending_qty=sum((dec(p['Amount']) for p in pending),ZERO)
    assert pending_qty==dec(open_position['FrozenAmount'])
    marked_net=dec(end_acc['Equity'])-CASH
    ending_wallet=dec(end_acc['Equity'])-dec(end_acc['UPnL'])
    opening_fees=sum((a['fee'] for a in entries),ZERO)
    last_wallet=wallet(flat_records[-1])
    open_funding=ending_wallet-last_wallet+opening_fees
    lower,upper,mid,num=funding_envelope(rates,market,index,entries,r['ending']['now'])
    assert lower-EPS<=open_funding<=upper+EPS,(r['id'],'tail',open_funding,lower,upper)
    open_unrealized=dec(end_acc['UPnL'])
    assert abs((end_mark-open_price)*open_qty-open_unrealized)<=D('0.000051')
    near(ending_wallet,dec(end_acc['Balance'])+dec(open_position['Margin'])+dec(end_acc['FrozenBalance']))
    sums={key:sum((t[key] for t in traces),ZERO) for key in ('gross','gross_at_fills','after_fees','net','fees','execution','funding')}
    near(sums['net']+open_funding-opening_fees+open_unrealized,marked_net)
    near(sums['after_fees']-sums['execution']+sums['funding'],sums['net'])
    val={k:float(v) for k,v in sums.items() if k!='gross_at_fills'}
    for label,text in (('gross','gross'),('fee','after_fees'),('net','net')):
        a,b=drawdown(CASH,cumulative(z[text] for z in traces))
        val[label+'_dd']=float(a); val[label+'_dd_pct']=float(b)
        val[label+'_wins']=sum(t[text]>0 for t in traces)
    dd,dp=drawdown(CASH,[*[dec(z[3])-CASH for z in marks],marked_net])
    assert min(dec(r[3]) for r in marks)>0
    spec=job['source'][r['id']]
    periods={'4834':'2021-05-01–2021-05-28 UTC','4835':'2021-05-01–2021-08-28 UTC'}
    names={'4834':'测试-关于使用kdj与vol量筛选可能会涨的币种','4835':'测试-关于马丁长期效果'}
    val.update(id=int(r['id']),market='Binance USD-M BTCUSDT perpetual',group='FMZ Native · KDJ and martingale',
        name=names[r['id']],source=spec['url'],period=periods[r['id']],interval=f"{spec['record_hours']}h chart · native 1h simulation base",
        exit='Archived profit/recovery rules · marked open tail',trades=n,unsettled=1,currency='USDT',quote_currency='USDT',
        currency_decimal_places=8,starting_equity=float(CASH),mark_to_market_net=float(marked_net),remaining_unrealized=float(open_unrealized))
    detail={'id':int(r['id']),'executed_taker':takers,'executed_maker':makers,'canceled_unfilled':cancelled,
        'opened_size_BTC_at_cutoff':str(open_qty),'pending_reduce_only_size_BTC_at_cutoff':str(pending_qty),
        'marked_drawdown_USDT':str(dd),'marked_drawdown_fraction':str(dp),'native_cutoff':r['ending'],
        'actual_closed_gross_at_fills_USDT':str(sums['gross_at_fills']),'native_marked_wallet_USDT':str(ending_wallet),
        'open_funding_USDT':str(open_funding),'open_funding_bound_USDT':[str(lower),str(upper)],
        'open_entry_fee_USDT':str(opening_fees),'open_entries':entries,'closed_cycles':traces,
        'warm_record_windows_independently_matched':len(r['maxRecords']),
        'native_price_points_crosschecked':len(prices),'account_mark_samples':len(marks)}
    return val,detail


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('job','receipt','repeat-receipt','worker','stage','output'):
        p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    raw=a.job.read_bytes(); receipt=a.receipt.read_bytes()
    assert receipt==a.repeat_receipt.read_bytes()
    job=json.loads(gzip.decompress(raw)); native=json.loads(receipt)
    assert sha(raw)==native['input_sha256']
    assert job['balance']==int(CASH) and job['fee_pct']==[0.02,0.04]
    coverage=[]; results=[]; diagnostics=[]
    with localcontext() as ctx:
        ctx.prec=42
        for r in native['results']:
            spec=job['source'][r['id']]
            assert spec['code_sha256']==sha(spec['source'].encode()) and spec['end']==r['end'] and job['start']==r['begin']
            assert all('q.fmz.com/data/history' in x['url'] for x in r['requests'])
            row,info=verify(job,r); results.append(row); diagnostics.append(info)
            coverage.append([row['id'],'Tested · exact archived Binance BTCUSDT source in native simulated ticks',
              f"Full authored date range. Native broker matched {row['trades']} closed cycles, one marked open long, reconciled execution, fees and funding, and deterministically repeated."])
    assert [x['trades'] for x in results]==[41,13]
    report={'coverage':coverage,'results':results,'diagnostics':diagnostics,
            'source':{k:{x:y for x,y in v.items() if x!='source'} for k,v in job['source'].items()},
            'market':{k:v['refs'] for k,v in job['market'].items()},
            'proof':{'input_sha256':sha(raw),'deterministic_native_receipt_sha256':sha(receipt),
                'native_engine_sha256':native['engine_sha256'],'worker_sha256':sha(a.worker.read_bytes()),
                'stage_sha256':sha(a.stage.read_bytes()),'verifier_sha256':sha(Path(__file__).read_bytes()),
                'native_requests':{r['id']:r['requests'] for r in native['results']}},
          'method':{'scope':'Exact original BTCUSDT perpetual, chart/backtest dates interpreted as UTC, and archived published numeric parameters. Both start flat with 10,000 USDT benchmark equity because the archive omits starting capital. Inputs set leverage to the published 20x. Each source uses its original native Sleep/candle access and initial empty offline state. #4834 exercises the published single-symbol virtual mode. #4835 uses the source in which the live scanner call is already commented out.',
            'market_data':'Checksummed Binance USD-M historical trade and index candles and original eight-hour funding rates, with exact FMZ overlap after excluding one known partial terminal request row. FMZ uses a native 1h synthetic base tick model built from observed OHLC. All observed synthetic Last values remain inside the matching exchange candle. Native chart prior candles are checked separately. Broker output does not provide an historical maker queue or true fill guarantees.',
            'execution':'Full-quantity native simulated broker orders. All marketable orders cross exactly one native 0.1 USDT tick relative to reference Last, with contemporaneous 0.04% taker fee. #4834 resting sell exits first cross the simulated bid after placement, with native validation of full size and 0.02% maker fee. Canceled limits remain zero-filled. The broker applies its native BTC market precision of 0.001 quantity and 0.1 price tick to the archived order requests.',
            'settlement':'Each closed cycle is assigned independent cash changes at adjacent source-observed flat states. Observed native funding is isolated from gross realized fill P&L and both sides’ fees and independently tested against historical position size, signed rate schedules and contemporaneous contract and index price envelopes. Terminal unrealized values, open fees and open funding remain separate from closed results. No forced terminal exit.',
            'drawdown':'Gross, after-fee and net workbook columns are realized from complete cycles. The marked drawdown separately uses all source-observed changing account equity values and terminal equity. Open inventory materially changes the apparent profitability of #4835.'},
          'references':['https://www.fmz.com/strategy/313036','https://github.com/binance/binance-public-data',
            'https://www.fmz.com/user-guide/backtesting-system/backtest-modes-and-order-matching',
            'https://www.binance.com/en/blog/futures/421499824684900660'],
          'reproduction':'Stage the pinned FMZ strategy ZIP and reuse the shared R29 Binance market binding helpers. Run the worker twice in the network-denied FMZ AppContainer. Pass both equal receipts and staged input to this Decimal verifier.'}
    def encode(x):
        if isinstance(x,D):return str(x)
        raise TypeError(type(x))
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=encode)+'\n',encoding='utf-8',newline='\n')
    print('Verified',[(r['id'],r['trades'],r['net_wins'],r['gross'],r['after_fees'],r['net'],r['mark_to_market_net']) for r in results],sha(a.output.read_bytes()))


if __name__=='__main__':
    main()
