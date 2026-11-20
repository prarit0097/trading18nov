"""Verify source and template #4685 decisions and native financial invariants."""

import argparse
from collections import defaultdict
from decimal import Decimal, localcontext
from hashlib import sha256
from math import fsum, isclose
from pathlib import Path
import gzip
import json

D=Decimal
ZERO=D(0)
DAY=86_400_000
HOUR=3_600_000
STEP=900_000
ONE_CENT=D('0.01')
FEE=D('0.0004')
EPS=D('0.000001')


def sha(raw):
    return sha256(raw).hexdigest()


def dec(x):
    return D(str(x))


def near(a,b):
    assert abs(dec(a)-b)<EPS,(a,b)


def drawdown(balance,deltas):
    peak=balance
    value=percent=ZERO
    for change in deltas:
        equity=balance+change
        peak=max(peak,equity)
        value=max(value,peak-equity)
        percent=max(percent,(peak-equity)/peak)
    return value,percent


def cumulative(values):
    amount=ZERO
    for value in values:
        amount+=value
        yield amount


def native_settings(job,mode):
    if mode=='single':
        a=job['source_public_form']['args'];return a['atrPeriod'],a['emaPeriod'],a['trackRatio'],a['stopLoss']
    cfg=json.loads(job['embedded_params']['params']); assert cfg[0]==cfg[1]; a=cfg[0]
    return a['atrPeriod'],a['emaPeriod'],a['trackRatio'],a['stopLoss']


def aggregate(markets,at):
    series=[markets[t] for t in range(at,at+DAY,STEP)]
    return [at,series[0][1]/100,max(r[2] for r in series)/100,min(r[3] for r in series)/100,
            series[-1][4]/100,sum(r[5] for r in series)/1000]


def verify_signal(job,run,coin,book,rates):
    mode=run['mode']
    atr_n,ema_n,mult,stop=native_settings(job,mode)
    bars=book['seed'][:]
    assert len(bars)>=300
    feed=job['feeds'][coin]
    chart={r[0]:r for r in feed['daily']['data']}
    for row in bars:
        if row[0]%DAY==16*HOUR:
            expected=aggregate(rates,row[0])
        else:
            backing=chart[row[0]]
            expected=[backing[0],*[x/100 for x in backing[1:5]],backing[5]/1000]
        assert row[:5]==expected[:5],(coin,row,expected)
    orders=defaultdict(list)
    for order in book['orders']:
        assert order['ticker']['Time']%DAY==16*HOUR
        orders[order['ticker']['Time']].append(order)
    previous=0
    position=0
    price=0
    assert len(book['indicators'])==len(book['balances'])==128
    for index,view in enumerate(book['indicators']):
        active=view['bar']
        last=active-DAY
        assert view['n']==ema_n and active%DAY==16*HOUR
        if index:
            assert active-previous==DAY and bars[-1][0]==last-DAY
            bars.append(aggregate(rates,last))
        else:
            assert bars[-1][0]==last
        typical=[(bar[2]+bar[3]+bar[4])/3 for bar in bars]
        ema=fsum(typical[:ema_n])/ema_n
        for x in typical[ema_n:-1]:
            ema+=(x-ema)*2/(ema_n+1)
        ema_old=ema
        ema+=(typical[-1]-ema)*2/(ema_n+1)
        tr=[max(b[2]-b[3],abs(b[2]-a[4]),abs(b[3]-a[4])) for a,b in zip(bars,bars[1:])]
        atr=fsum(tr[:atr_n])/atr_n
        for x in tr[atr_n:-1]:
            atr=(atr*(atr_n-1)+x)/atr_n
        atr_old=atr
        atr=(atr*(atr_n-1)+tr[-1])/atr_n
        for a,b in zip((ema_old,ema,atr_old,atr),(*view['ema'],*view['atr']),strict=True):
            assert isclose(a,b,rel_tol=0,abs_tol=2e-7),(mode,coin,'indicator',index,a,b)
        earlier,close=bars[-2][4],bars[-1][4]
        up=earlier<ema_old+mult*atr_old and close>ema+mult*atr
        down=earlier>ema_old-mult*atr_old and close<ema-mult*atr
        expected=[]
        if index:
            if position<=0 and up:
                expected=(['closesell'] if position<0 else [])+['buy']
            elif position>=0 and down:
                expected=(['closebuy'] if position>0 else [])+['sell']
            elif position>0 and (close<=price*(1-stop) or close<=ema):
                expected=['closebuy']
            elif position<0 and (close>=price*(1+stop) or close>=ema):
                expected=['closesell']
        actual=orders[active]
        assert expected==[a['direction'] for a in actual],(mode,coin,index,expected,actual)
        for a in actual:
            if a['direction'] in ('buy','sell'):
                position=10 if a['direction']=='buy' else -10
                price=a['order']['AvgPrice']
            else:
                position=price=0
        previous=active
    assert set(orders)=={r['bar'] for r in book['indicators']}


def realized_wallet(snapshot):
    a=snapshot['acc']; pos=snapshot['pos']
    booked=dec(a['Balance'])+sum((dec(p['Margin']) for p in pos),ZERO)+dec(a['FrozenBalance'])
    near(a['Equity'],booked+dec(a['UPnL']))
    assert a['FrozenBalance']==0
    return booked


def verify_money(job,run,coin,book,market):
    starting=D(1000000 if coin=='ETH' else 10000)
    latest=starting
    position=0; entry=mark_entry=entry_fee=before_open=when_open=None
    used=book['orders']
    report=[]
    feed=job['feeds'][coin]
    funding={x[0]:D(x[1])/10**8 for x in feed['funding']['data']}
    index={x[0]:x for x in feed['index']['data']}
    for a in used:
        o=a['order']; side=a['side']=='Buy'; t=a['ticker']['Time']; last=dec(a['last']); qty=dec(o['DealAmount'])
        fill=dec(o['AvgPrice']); closed=a['direction'] in ('closebuy','closesell')
        assert qty==dec(o['Amount'])==D(10)
        assert o['Status']==1 and o['Symbol']==coin+'_USDT.swap' and o['ContractType']=='swap'
        assert t<=o['Time']<t+30_000 and t in market and t%DAY==16*HOUR
        assert last==D(market[t][1])/100 and fill==last+(ONE_CENT if side else -ONE_CENT)
        assert dec(a['limit'])==fill+(D(5) if side else -D(5)) and dec(o['Price'])==dec(a['limit'])
        before=realized_wallet(a['before']); after=realized_wallet(a['after'])
        fees=fill*qty*FEE
        signed=qty if side else -qty
        if not closed:
            assert not position and not a['before']['pos'] and len(a['after']['pos'])==1
            assert int(a['after']['pos'][0]['MarginLevel'])==10
            near(after,before-fees)
            near(before,latest)
            position=signed
            entry,mark_entry,entry_fee,when_open,before_open=fill,last,fees,o['Time'],before
            continue
        assert position==-signed and len(a['before']['pos'])==1 and not a['after']['pos']
        assert before_open is not None
        actual_gross=position*(fill-entry)
        benchmark_gross=position*(last-mark_entry)
        execution=benchmark_gross-actual_gross
        assert execution==qty*D('0.02')
        near(after,before+actual_gross-fees)
        funded=after-before_open-actual_gross+entry_fee+fees
        low=high=price_at_open=ZERO
        stamps=[ts for ts in funding if when_open<ts<=o['Time']]
        for stamp in stamps:
            rate=-position*funding[stamp]
            ranges=(min(market[stamp][3],index[stamp][3]),max(market[stamp][2],index[stamp][2]))
            prices=[rate*D(val)/100 for val in ranges]
            low+=min(prices);high+=max(prices)
            price_at_open+=rate*D(market[stamp][1])/100
        assert low-EPS<=funded<=high+EPS,(run['mode'],coin,when_open,o['Time'],funded,low,high)
        fees+=entry_fee
        report.append({'entry_ms':when_open,'exit_ms':o['Time'],'direction':'long' if position>0 else 'short',
            'gross':benchmark_gross,'gross_at_fills':actual_gross,'after_fees':benchmark_gross-fees,
            'execution':execution,'fees':fees,'funding':funded,'net':actual_gross-fees+funded,
            'official_funding_rate_count':len(stamps),'funding_model_price_envelope_USDT':[str(low),str(high)],
            'funding_at_official_trade_bar_open_USDT':str(price_at_open)})
        latest=after
        position=0
        entry=mark_entry=entry_fee=when_open=before_open=None
    assert not position and not book['ending']['pos'] and len(report)*2==len(used)
    ending=realized_wallet(book['ending'])
    near(ending,latest)
    keys=('gross','gross_at_fills','after_fees','execution','fees','funding','net')
    metrics={k:sum((r[k] for r in report),ZERO) for k in keys}
    near(ending-starting,metrics['net'])
    assert metrics['net']==metrics['after_fees']-metrics['execution']+metrics['funding']
    for b in book['balances']:
        realized_wallet(b)
        assert dec(b['acc']['Equity'])>0
    draw_mark,marked_pct=drawdown(starting,(dec(r['acc']['Equity'])-starting for r in [*book['balances'],book['ending']]))
    val={k:float(v) for k,v in metrics.items() if k!='gross_at_fills'}
    for title,key in (('gross','gross'),('fee','after_fees'),('net','net')):
        d,pct=drawdown(starting,cumulative(r[key] for r in report))
        val[title+'_dd']=float(d);val[title+'_dd_pct']=float(pct)
        val[title+'_wins']=sum(r[key]>0 for r in report)
    name='ETH-only published defaults' if run['mode']=='single' else 'Embedded ETH/LTC two-venue preset'
    val.update(id=4685,market=f'Binance USD-M {coin}USDT perpetual',group='FMZ Native · Archived ATR and native simulated ticks',
        name='数字货币期货多品种ATR策略教学',source=job['source_url'],period='2021-09-01–2022-01-06 UTC · '+name,
        interval='1d FMZ chart · 15m simulation base',exit='Archived ATR/EMA stop or reversal',
        trades=len(report),unsettled=0,starting_equity=float(starting),currency='USDT',quote_currency='USDT',
        currency_decimal_places=8,mark_to_market_net=float(metrics['net']))
    detail={'market':coin,'settings_mode':run['mode'],'native_number_orders':len(used),'closed_round_trips':len(report),
        'actual_gross_at_native_fills_USDT':str(metrics['gross_at_fills']),
        'native_daily_marked_equity_drawdown_USDT':str(draw_mark),'native_daily_marked_equity_drawdown_fraction':str(marked_pct),
        'native_end_account':book['ending']['acc'],
        'each_trade':[ {k:str(v) if isinstance(v,D) else v for k,v in t.items()} for t in report ]}
    return val,detail


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('job','receipt','repeated-receipt','stage','worker','output'):
        p.add_argument('--'+key,type=Path,required=True)
    arg=p.parse_args()
    input_raw=arg.job.read_bytes(); raw=arg.receipt.read_bytes(); repeat=arg.repeated_receipt.read_bytes()
    assert raw==repeat
    job=json.loads(gzip.decompress(input_raw)); native=json.loads(raw)
    assert native['input_sha256']==sha(input_raw) and native['source_sha256']==sha(job['source'].encode())==job['source_sha256']
    assert native['template_sha256']==sha(job['template'].encode())==job['template_sha256']
    runs=native['runs']; assert [r['mode'] for r in runs]==['single','author-two-legs']
    results=[]; diagnostics=[]
    with localcontext() as ctx:
        ctx.prec=44
        for run in runs:
            assert run['start']==job['from_ms'] and run['end']==job['to_ms'] and run['now']>=run['end']
            assert run['sleepCalls']>=160_000
            for coin,s in run['ledgers'].items():
                market={r[0]:r for r in job['feeds'][coin]['swap']['data']}
                verify_signal(job,run,coin,s,market)
                r,d=verify_money(job,run,coin,s,market)
                results.append(r);diagnostics.append(d)
    assert [r['trades'] for r in results]==[7,2,4]
    output={'coverage':[[4685,'Tested · exact FMZ strategy and execution template in both published modes',
        'Full authored dates, Binance USD-M ETH and LTC, exact host scripts and 15m simulated-tick matching. Seven ETH single-mode closes. The authored dual preset had two ETH and four LTC closes. Independent decisions, filled prices, fees, funding bounds and ending wallet reconciliation passed.']],
        'results':results,'diagnostics':diagnostics,
        'dual_mode_combined_realized_net_USDT':str(sum((dec(r['net']) for r in results[1:]),ZERO)),
        'source':{'url':job['source_url'],'publisher':job['source_public_form'],'document_sha256':job['source_doc_sha256'],
          'source_sha256':job['source_sha256'],'embedded_parameters':job['embedded_params'],
          'trade_template':job['template_public_form'],'template_document_sha256':job['template_doc_sha256'],
          'template_code_sha256':job['template_sha256']},
        'market_sources':{c:{kind:data['checks'] for kind,data in f.items()} for c,f in job['feeds'].items()},
        'proof':{'input_sha256':sha(input_raw),'clock_and_ledger_receipt_sha256':sha(raw),'native_engine_sha256':native['engine_sha256'],
            'stage_sha256':sha(arg.stage.read_bytes()),'worker_sha256':sha(arg.worker.read_bytes()),
            'verifier_sha256':sha(Path(__file__).read_bytes()),'repeated_native_sha256':sha(repeat),
            'sleep_calls':{r['mode']:r['sleepCalls'] for r in runs},'q_requests':[r['requests'] for r in runs]},
        'assumptions':{'scope':'Full embedded 2021-09-01 to 2022-01-06 date range interpreted as UTC. The native engine aggregates its daily candles at 16:00 UTC. ETH single uses the source publication defaults EMA10 and band width ATR1. The archived two-exchange object requires onlyOne=false to activate the published JSON argument. It uses EMA20 and ATR2 for both independently traded ETH/LTC legs. Their starting balances are the archived ETH 1,000,000 USDT and a declared 10,000 USDT starting balance for LTC, whose embedded balance was omitted. The two ETH variants use overlapping dates and must be interpreted separately.',
            'price_support':'Stage exchange-published SHA-256 Binance USD-M prices, funding and contract fingerprints, with exact direct FMZ read-only overlap for all checked rows. The native FMZ simulated-tick client takes only disk-backed, checksum-verified market responses. Original strategy and original trade wrapper run internally with their own 500ms sleeps. The native tester creates 15m intrabar tick paths and a one-tick directional spread. The tested crossing limits filled entirely at that synthetic top of book. These are model fills, with no historical depth or actual trade claim.',
            'orders':'Exactly 10 contracts per entry or close. Original template #203258 uses 5 USDT crossing allowance, 500 ms retry and minimum one. No positions remained open. Simulated leverage is 10x. Contemporary exchange fee 0.02% maker and 0.04% taker, with each modeled fill charged taker. The published order set uses actual simulated fill prices, while gross/after-fee reference columns attribute one-tick execution differences separately.',
            'funding':'Every position-level native funding cash flow is isolated from the actual simulated available cash plus margin before/after a closed round trip. Independent signed scheduled Binance charges are constrained by each settlement’s price interval using checksummed contract and index H/L. The native simulator’s actual funding price need not equal either feed’s fixed candle open. Drawdown on closed changes and independent native daily marked equity are both reported.',
            'verification':'A Python shadow calculates Wilder ATR, EMA and order signals on original native seed and independently resampled checksummed closed daily bars. It matches all 384 source decisions, every simulated fill, fee, wallet and available margin movement, and both deterministic repetitions.'},
        'references':['https://www.fmz.com/strategy/339344','https://www.fmz.com/digest-topic/8726',
           'https://www.fmz.com/strategy/203258','https://www.fmz.com/user-guide/backtesting-system/backtest-modes-and-order-matching',
           'https://www.binance.com/en/blog/futures/421499824684900660','https://github.com/binance/binance-public-data'],
        'reproduction':'Stage the pinned FMZ markdown archive and optional locally cached public parameter pages with stage_r29_4685_native.py. Run the worker twice in existing network-denied AppContainer, saving the second output separately. Rebuild results through the independent Python verifier with both receipts.'}
    arg.output.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print('verified',len(results),'scopes',sum(r['trades'] for r in results),'closes',sha(arg.output.read_bytes()))
    print([(r['market'],r['trades'],r['gross'],r['net'],r['net_dd_pct']) for r in results])


if __name__=='__main__':
    main()
