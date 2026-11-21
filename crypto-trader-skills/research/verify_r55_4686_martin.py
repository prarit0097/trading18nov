"""Reconcile FMZ ETHUSDT Martingale fills, carry and account values for the author's May stress."""
import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
from decimal import Decimal as D
import gzip
import json
from pathlib import Path

from fmz_native_round20_880_capture import sha

ZERO=D(0)
MINUTE5=300_000
MAKER=D('.00008')
TAKER=D('.00010')
INITIAL=D(10_000)


def equal(a,b,tolerance='1e-8'):
    assert abs(D(str(a))-D(str(b)))<D(tolerance),(a,b)


def decode(p):
    return json.loads(gzip.decompress(p.read_bytes()))


def history(job,base,packet):
    seen={}
    removed={}
    previous=set()
    for at,orders in base['listedChanges']:
        current={o['Id'] for o in orders}
        for oid in current:seen.setdefault(oid,at)
        for oid in previous-current:
            removed.setdefault(oid,at)
        previous=current
    order_by_id={o['Id']:o for _,o in packet['audited']}
    assert Counter(x['Status'] for x in order_by_id.values())=={0:2,1:111,2:111}
    assert {x[1] for x in base['cancels']}=={i for i,x in order_by_id.items() if x['Status']==2}
    assert previous=={223,224}
    assert not {i for i,x in order_by_id.items() if x['Status']!=1 and x['DealAmount']}
    trades=job['feeds']['swap']['data']
    trade_clock=[x[0] for x in trades]
    fill_events=[]
    for n,(submitted,method,direction,wanted,quantity,oid,ticker) in enumerate(base['orders'],1):
        order=order_by_id[oid]
        assert order['Time']==submitted and order['Amount']==quantity and order['Id']==oid==n
        assert order['Type']==int(method=='Sell') and order['Offset']==int(direction.startswith('close'))
        assert order['ContractType']=='swap' and order['Symbol']=='ETH_USDT.swap'
        equal(order['Price'],wanted,'.00500001')
        if order['Status']!=1:
            continue
        assert order['Amount']==order['DealAmount']
        q=D(str(quantity));p=D(str(order['AvgPrice']));limit=D(str(order['Price']))
        immediate=oid not in seen
        if immediate:
            assert oid==4 and p>limit and method=='Sell'
            assert ticker['Time']<=submitted and p==D(str(ticker['Buy']))
            observed=submitted;fee=q*p*TAKER
        else:
            assert p==limit and oid in removed
            observed=removed[oid]; fee=q*p*MAKER
        begin=bisect_left(trade_clock,submitted//MINUTE5*MINUTE5)
        end=bisect_right(trade_clock,observed//MINUTE5*MINUTE5)
        assert any(D(x[3])/100-D('.01')<=p<=D(x[2])/100+D('.01') for x in trades[begin:end]),(oid,observed,p)
        fill_events.append((observed,submitted,oid,direction,q,p,fee))
    assert len(fill_events)==111 and len({x[2] for x in fill_events})==111
    assert fill_events==sorted(fill_events)
    return fill_events


def carry_events(job,base,events):
    nominal={x[0]:x for x in job['feeds']['funding']['data'] if base['start']<=x[0]<base['end']}
    assert len(nominal)==3
    marks={row[0]:row for row in job['independent_mark_5m']}
    index={row[0]:row for row in job['feeds']['index']['data']}
    old=ZERO;posted={}
    previous_snapshot=None
    for snap_time,[snap] in base['snapshots']:
        fresh=D(str(snap['Assets'][0].get('Funding',0)))
        if fresh==old:
            previous_snapshot=snap
            continue
        [event]=[x for x in nominal if snap_time-MINUTE5<x<=snap_time]
        qty={'Long':ZERO,'Short':ZERO}
        for observed,submitted,_,side,q,_,_ in events:
            if observed>event:break
            leg='Long' if side in ('buy','closebuy') else 'Short'
            qty[leg]+=(-q if side.startswith('close') else q)
        assert qty['Long']>0 and qty['Short']==0
        for sample in (previous_snapshot,snap):
            side=sample['Symbols']['ETH_USDT.swap']
            assert D(str(side['Long']['Amount']))==qty['Long']
            assert side.get('Short',{}).get('Amount',0)==0
        amount=fresh-old
        rate=D(nominal[event][1])/D(100_000_000)
        inferred=-amount/(qty['Long']*rate)
        bucket=event//MINUTE5*MINUTE5
        assert D(index[bucket][3])/100<=inferred<=D(index[bucket][2])/100
        assert D(marks[bucket][3])/100<=inferred<=D(marks[bucket][2])/100
        posted[event]={'native_snapshot_ms':snap_time,'native_funding_USDT':amount,'funding_rate':rate,
                       'native_cash_implied_reference_USDT':inferred,'exposed_long_ETH':qty['Long'],
                       'official_index_open_USDT':D(index[bucket][1])/100,'official_mark_open_USDT':D(marks[bucket][1])/100}
        old=fresh
        previous_snapshot=snap
    assert len(posted)==2
    return posted


def settle(base,events,funding):
    legs={k:[ZERO,ZERO,ZERO,ZERO] for k in ('Long','Short')}
    closed=[]
    receipts=[]
    accounts=list(funding.items())
    for at,submitted,oid,side,q,p,trade_fee in events:
        while accounts and accounts[0][0]<at:
            _,receipt=accounts.pop(0)
            assert legs['Long'][0]==receipt['exposed_long_ETH']
            legs['Long'][3]+=receipt['native_funding_USDT']
        tag='Long' if side in ('buy','closebuy') else 'Short'
        leg=legs[tag]
        receipt={'id':oid,'submission_ms':submitted,'status_observed_by_ms':at,'direction':side,
                 'dealt_ETH':q,'price_USDT':p,'fee_USDT':trade_fee}
        if side.startswith('close'):
            size,notional,opening_fees,carrying=leg
            assert ZERO<q<=size
            fraction=q/size
            basis=notional*fraction
            gain=(p*q-basis)*(1 if tag=='Long' else -1)
            allocated=opening_fees*fraction
            attributed=carrying*fraction
            closed.append([gain,allocated+trade_fee,attributed,tag])
            for i in range(4):leg[i]*=(1-fraction)
            receipt.update(realized_gross_USDT=gain,allocated_entry_fee_USDT=allocated,attributed_funding_USDT=attributed)
        else:
            leg[0]+=q
            leg[1]+=q*p
            leg[2]+=trade_fee
        receipts.append(receipt)
    assert not accounts
    assert legs['Long'][0]==D('.205') and legs['Short'][0]==ZERO
    assert len(closed)==26
    native=base['snapshots'][-1][1][0]
    symbol=native['Symbols']['ETH_USDT.swap']
    final=legs['Long'];marked_price=D(str(symbol['Last']))
    equal(final[1]/final[0],symbol['Long']['Price'])
    netunreal=final[0]*marked_price-final[1]
    equal(netunreal,symbol['Long']['Profit'])
    for leg in legs:
        equal(sum(q[0] for q in closed if q[3]==leg),symbol[leg]['CloseProfit'])
    allfees=sum(x[-1] for x in events)
    equal(allfees,native['Assets'][0]['Commission'])
    gross=sum(x[0] for x in closed);fees=sum(x[1] for x in closed);carry=sum(x[2] for x in closed)
    equal(fees+final[2],allfees)
    equal(carry+final[3],native['Assets'][0]['Funding'])
    equity=gross-allfees+netunreal+carry+final[3]
    equal(equity,native['PnL'])
    return {'closed':closed,'gross':gross,'closed_fees':fees,'closed_funding':carry,'allfees':allfees,
            'equity':equity,'inventory':final[0],'unrealized':netunreal,'unallocated_funding':final[3],
            'unallocated_open_fee':final[2],'receipts':receipts}


def drawdown(points):
    equity=peak=INITIAL; amount=fraction=ZERO
    for delta in points:
        equity+=delta
        peak=max(peak,equity)
        amount=max(amount,peak-equity);fraction=max(fraction,(peak-equity)/peak)
    return amount,fraction


def marks(base):
    points=[]
    for expected,(t,[s]) in enumerate(base['snapshots']):
        assert t==base['start']+expected*MINUTE5
        asset=s['Assets'][0]
        assert asset['Initial']==INITIAL and asset['Currency']=='USDT'
        symbols=s['Symbols'].get('ETH_USDT.swap',{})
        held=[symbols[k] for k in ('Long','Short') if k in symbols]
        balance=D(str(asset['Amount']))+D(str(asset['FrozenAmount']))+sum(D(str(x['Margin']))+D(str(x['Profit'])) for x in held)
        equal(balance-INITIAL,s['PnL'])
        points.append([t,balance])
    assert len(points)==289 and points[-1][0]==base['end']
    deltas=[points[i][1]-points[i-1][1] for i in range(1,len(points))]
    return points,drawdown(deltas)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for n in ('input','base','audit','halfyear','worker','stage','output'):
        parser.add_argument('--'+n,type=Path,required=True)
    a=parser.parse_args();job,base,audited,halfyear=[decode(p) for p in (a.input,a.base,a.audit,a.halfyear)]
    for x in (base,audited,halfyear):
        assert x['input_sha256']==sha(a.input.read_bytes())
        assert x['engine_sha256']=='10759660cb8d8979176908703326e8e2a83d9f25edc31e11e0b22330f7d3b483'
        assert x['worker_sha256']==sha(a.worker.read_bytes())
    assert base['scope']==audited['scope']=='may19' and base['stop']==audited['stop']=='EOF'
    assert halfyear['scope']=='halfyear' and halfyear['stop']=='同时有多空持仓'
    assert halfyear['exitClock']==1614092700200
    time,position=halfyear['positions'][-1]
    assert len(position)==2 and time==halfyear['exitClock']<halfyear['end']
    assert {x['Type'] for x in position}=={0,1} and all(x['Amount']==.005 for x in position)
    assert {k:v for k,v in base.items() if k!='audited'}=={k:v for k,v in audited.items() if k!='audited'}
    assert not base['audited'] and all(x[0]>base['orders'][-1][0] for x in audited['audited'])
    assert base['completion']['Finished'] and base['completion']['Time']==base['end']
    assert base['contracts']==[['swap',{'InstrumentID':'ETHUSDT','LotTick':.001,'PriceTick':.01,'VolumeMultiple':1}]]
    events=history(job,base,audited)
    funding=carry_events(job,base,events)
    roll=settle(base,events,funding)
    points,(mdd,mdp)=marks(base)
    g,f,n=([x[0] for x in roll['closed']],[x[0]-x[1] for x in roll['closed']],
           [x[0]-x[1]+x[2] for x in roll['closed']])
    gdd,gp=drawdown(g);fdd,fp=drawdown(f);ndd,np=drawdown(n)
    metric={'id':4686,'name':'Futures martingale ETH May 19 stress','market':'Binance USD-M perpetual ETHUSDT',
            'period':'2021-05-19 UTC+08:00, 24h','interval':'1d chart, FMZ 5m generated ticks',
            'source':job['source_url'],'group':'Original archived 2023 JS / author May 19 stress',
            'exit':'Completed day. Original target reductions and separate still-open long.',
            'currency':'USDT','quote_currency':'USDT','starting_equity':INITIAL,'gross':sum(g),'fees':roll['closed_fees'],
            'after_fees':sum(f),'net':sum(n),'funding':roll['closed_funding'],'execution':0,
            'gross_dd':gdd,'gross_dd_pct':gp,'fee_dd':fdd,'fee_dd_pct':fp,'net_dd':ndd,'net_dd_pct':np,
            'gross_wins':sum(x>0 for x in g),'fee_wins':sum(x>0 for x in f),'net_wins':sum(x>0 for x in n),
            'trades':len(n),'unsettled':1,'mark_to_market_net':roll['equity'],'remaining_unrealized':roll['unrealized'],
            'marked_dd':mdd,'marked_dd_pct':mdp,'all_fees':roll['allfees']}
    report={'coverage':[[4686,'Tested \u00b7 May 19 ETH martingale stress completed',
                         'Original archived code completes the author-named May 19 market day. The separate six-month attempt aborts on February 23 when both sides fill. Only the completed day contributes performance rows.']],
            'results':[metric],
            'source':{'catalogue_url':job['source_url'],'catalogue_document_sha256':job['document_sha256'],
                      'javascript_sha256':job['source_sha256'],'author_design':job['publisher'],
                      'author_setup_screenshot':job['author_settings'],'author_2021_result_screenshot':job['author_old_result'],
                      'applied_parameters':job['parameters']},
            'venue':job['browsed_files'],
            'proof':{'input_sha256':sha(a.input.read_bytes()),'base_run_sha256':sha(a.base.read_bytes()),
                     'audited_run_sha256':sha(a.audit.read_bytes()),'incomplete_halfyear_run_sha256':sha(a.halfyear.read_bytes()),
                     'stage_sha256':sha(a.stage.read_bytes()),'worker_sha256':sha(a.worker.read_bytes()),
                     'verifier_sha256':sha(Path(__file__).read_bytes()),'pinned_fmz_wasm':base['engine_sha256'],
                     'primary_order_and_financial_states_match_tail_audit':True,'position_account_snapshots':len(points)},
            'completed_scope':{'terminal_ETH':roll['inventory'],'terminal_pending_order_ids':[223,224],
                               'total_paid_funding_USDT':sum(v['native_funding_USDT'] for v in funding.values()),
                               'unallocated_open_order_fee_USDT':roll['unallocated_open_fee'],
                               'unallocated_funding_USDT':roll['unallocated_funding'],'funding_receipts':funding,
                               'five_minute_marked_equity':points,'receipts':roll['receipts']},
            'incomplete_scope':{'begin_ms':halfyear['start'],'configured_end_ms':halfyear['end'],
                                'source_abort_ms':time,'source_exact_diagnostic':halfyear['stop'],
                                'dual_side_inventory':position,'orders_before_abort':len(halfyear['orders']),
                                'execution_marking':'After source error, the engine still emits final marks. Do not treat those as completed strategy execution.'},
            'scope':{'dates':'Author prototype design names May 19. This independently completed 24-hour cohort uses a UTC+08:00 calendar, starts flat at 10,000 USDT and keeps terminal positions marked. The original six-month author screenshot is for an older revision.',
                     'model':'Current official FMZ local WASM supports generated tick mode. 200 ms default latency, 1d chart, 5m base, zero slippage, and author settings of 0.008% maker/0.01% taker. The local scope uses depth 5 and disabled fault injection. The author screenshot contains depth 20 and tolerance field 0.1. No historical order-book fills are claimed.',
                     'settlement':'Closed reductions are counted individually and funded amounts are allocated to average-price inventory. Independently validates all modeled fills against official bar ranges, native resting status, fees and P&L, and both funding rates against official index and mark ranges.',
                     'limitations':'May 19 provides one stress scenario for execution risk. The study does not estimate median performance. Open long drawdown materially changes the result relative to closed trade win rate.'},
            'references':[job['publisher'],'https://github.com/binance/binance-public-data',
                          'https://www.fmz.com/user-guide/backtesting-system/local-backtesting-engine']}
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=float)+'\n',encoding='utf-8',newline='\n')
    print({key:metric[key] for key in ('trades','gross','fees','funding','net','net_wins','mark_to_market_net','marked_dd_pct')},
          sha(a.output.read_bytes()),flush=True)


if __name__=='__main__':main()
