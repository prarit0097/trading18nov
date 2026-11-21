"""Validate the original minute EMA exposure, costs, releases and marked equity."""
import argparse
from collections import defaultdict
import csv
from datetime import datetime, timezone
from decimal import Decimal as D
import gzip
import io
import json
from pathlib import Path

from fmz_native_round20_880_capture import sha
from verify_r48_4427_hedge import BASE, LOT, ZERO, curve, near, relative_pnl


def verify_minute_ema(case,data,source):
    inputs=list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))
    selected=sorted(q['symbol'] for q in source['data'])
    assert case['symbols']==selected and {'BTC','ETH'}<=set(selected)
    ewm_numerator={v:ZERO for v in selected}
    ewm_weight=dict(ewm_numerator)
    positions={s:ZERO for s in selected}
    entry=dict(positions)
    carried_fee=dict(positions)
    total_gross=dict(positions)
    authored_float_positions={q:0.0 for q in selected}
    collateral_history=[]
    gross_history=[]
    after_history=[]
    marked=[]
    costs=ZERO
    boundary_ties=0
    count=defaultdict(int)
    markets_by_bar=defaultdict(list)
    for order in case['orders']:markets_by_bar[order[0]].append(order)
    rate=D(str(case['fee']))
    assert rate in (D('.00075'),ZERO)
    begin=len(inputs)-source['signal_rows']
    start_time=None
    trace=iter(case['marks'])
    for offset,data in enumerate(inputs):
        levels={s:D(data[s]) for s in selected}
        benchmark=levels['BTC']
        ratios={}
        for ticker in selected:
            ewm_numerator[ticker]*=D('.999')
            ewm_weight[ticker]*=D('.999')
            if ticker in levels:
                rel=levels[ticker]/benchmark
                ewm_numerator[ticker]+=rel
                ewm_weight[ticker]+=1
                ratios[ticker]=rel*ewm_weight[ticker]/ewm_numerator[ticker]
        market_index=sum(ratios.values())/len(ratios)
        if offset<begin:continue
        dt=datetime.fromtimestamp(int(data[''])/1000,timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        if start_time is None:start_time=dt
        mtm=sum((p-entry[s])*positions[s] for s,p in levels.items())
        margin=sum(abs(positions[s])*entry[s]/20 for s in selected)
        realised=sum(total_gross.values())-costs
        balance=BASE+realised+mtm
        native=next(trace)
        assert dt==native[0]
        for observed,wanted in zip(native[1:],[realised,margin,mtm,balance],strict=True):near(observed,wanted)
        marked.append(balance)
        collateral_history.append(balance-margin)
        declared={q[1]:q for q in markets_by_bar.get(dt,[])}
        assert len(declared)==len(markets_by_bar.get(dt,[]))
        for symbol in selected:
            if symbol not in levels:
                assert not positions[symbol] and symbol not in declared
                continue
            previous=positions[symbol]
            price=levels[symbol]
            displacement=ratios[symbol]-market_index
            multiple=round(float(displacement/D('.01')),1)
            exposure=-300*D(str(multiple))
            gap=exposure-previous*price
            binary_gap=-300*multiple-authored_float_positions[symbol]*float(price)
            near(gap,binary_gap,D('0.000000001'))
            trigger=abs(binary_gap)>150
            if abs(abs(gap)-150)<=D('1e-10'):
                # Pandas parses decimal text into binary prices. A ULP either way can flip a strict tie.
                boundary_ties+=1
                trigger=symbol in declared
            if not trigger:
                assert symbol not in declared,(dt,symbol,gap)
                continue
            assert symbol in declared,(dt,symbol,gap)
            expected_side=1 if gap>0 else -1
            _,venue,side,x,q,prior,post,source_basis,reported_delta=declared[symbol]
            assert venue==symbol and side==expected_side
            qty=D(str(q)).quantize(LOT)
            near(qty,(abs(gap)/price).quantize(LOT))
            near(price,x)
            near(previous,prior)
            charge=price*qty*rate
            costs+=charge
            gone=min(abs(previous),qty) if side*previous<0 else ZERO
            added=qty-gone
            gross=ZERO
            if gone:
                share=gone/abs(previous)
                establish=carried_fee[symbol]*share
                gross=(price-entry[symbol])*gone*(-side)
                fee=establish+price*gone*rate
                gross_history.append(gross)
                after_history.append(gross-fee)
                carried_fee[symbol]-=establish
                total_gross[symbol]+=gross
                positions[symbol]+=side*gone
                count[symbol]+=1
            if added:
                p=abs(positions[symbol]); carry=entry[symbol]*p
                entry[symbol]=(carry+price*added)/(p+added)
                carried_fee[symbol]+=price*added*rate
                positions[symbol]+=side*added
            elif not positions[symbol]:
                entry[symbol]=ZERO
            near(positions[symbol],post)
            authored_float_positions[symbol]=post
            if positions[symbol]:near(entry[symbol],source_basis)
            near(gross-charge,reported_delta)
        if declared:
            mtm=sum((p-entry[s])*positions[s] for s,p in levels.items())
            margin=sum(abs(positions[s])*entry[s]/20 for s in selected)
            marked.append(BASE+sum(total_gross.values())-costs+mtm)
            collateral_history.append(marked[-1]-margin)
    assert next(trace,None) is None
    summary=case['accounts']
    for symbol in selected:
        native=summary[symbol]
        near(native['amount'],positions[symbol]);near(native['realised_profit'],total_gross[symbol]);
        if positions[symbol]:near(native['hold_price'],entry[symbol])
    total=sum(total_gross.values())
    native=summary['USDT']
    near(native['realised_profit'],total-costs)
    near(native['margin'],sum(abs(positions[s])*entry[s]/20 for s in selected))
    assert len(gross_history)>0
    unreal=sum(D(str(summary[k]['unrealised_profit'])) for k in selected)
    gross=sum(gross_history)
    allocated=gross-sum(after_history)
    near(allocated+sum(carried_fee.values()),costs)
    marked_net=marked[-1]-BASE
    near(marked_net,gross-costs+unreal)
    before=gross_history;after=after_history
    gdd,gp=curve(BASE,relative_pnl(BASE,before));fdd,fp=curve(BASE,relative_pnl(BASE,after))
    mdd,mp=curve(BASE,marked)
    row={'id':5366,'name':'Author notebook minute EMA relative value','market':'Binance USD-M BTC and ETH plus 22 other active perpetuals','group':case['case'],
         'source':source['source']['archive_url'],'period':start_time+' to '+dt+' UTC',
         'interval':'Authored 1m Binance prices and close-based notebook execution',
         'exit':'Directional reductions use average-cost basis and allocate entry commissions and modeled carry.',
         'currency':'USDT','quote_currency':'USDT','currency_decimal_places':8,'starting_equity':BASE,
         'gross':gross,'fees':allocated,'after_fees':sum(after),'execution':ZERO,'funding':ZERO,'net':sum(after),
         'gross_dd':gdd,'gross_dd_pct':gp,'fee_dd':fdd,'fee_dd_pct':fp,'net_dd':fdd,'net_dd_pct':fp,
         'gross_wins':sum(v>0 for v in before),'fee_wins':sum(v>0 for v in after),'net_wins':sum(v>0 for v in after),
         'trades':len(before),'unsettled':sum(v!=0 for v in positions.values()),'mark_to_market_net':marked_net,
         'remaining_unrealized':unreal,'marked_dd':mdd,'marked_dd_pct':mp,'all_costs':costs,'all_funding':ZERO}
    audit={'case':case['case'],'open_legs':row['unsettled'],'order_quantity':len(case['orders']),'closed_reductions_by_leg':dict(count),
           'gross_by_leg':total_gross,'native_terminal_chart_pre_trade_equity':case['marks'][-1][4],
           'min_research_margin_headroom_USDT':min(collateral_history),'native_binary_gate_ties':boundary_ties}
    return row,audit


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('first','repeat','ordinary','market','proof','catalog','stage','worker','output'):
        p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args()
    program=a.first.read_bytes()
    assert program==a.repeat.read_bytes()
    ordinary=a.ordinary.read_bytes()
    src=json.loads(gzip.decompress(program))
    control=json.loads(gzip.decompress(ordinary))
    release=a.proof.read_bytes()
    spec=json.loads(release)
    catalog=a.catalog.read_bytes()
    [prior]=[r for r in json.loads(catalog)['disposition'] if r['id']==5366]
    assert prior['source']==spec['source']['archive_url'] and prior['pinned_document_sha256']==spec['source']['archive_sha256']
    data=a.market.read_bytes()
    assert sha(data)==spec['source']['csv_sha256']
    assert src['input_proof_sha256']==control['input_proof_sha256']==sha(release)
    assert src['worker_sha256']==control['worker_sha256']==sha(a.worker.read_bytes())
    assert control['ordinary_set'] and not src['ordinary_set']
    before,after=src['results']
    [ordered]=control['results']
    assert before['case']=='author minute case' and after['case']=='zero commission sensitivity'
    assert before['symbols']!=ordered['symbols'] and set(before['symbols'])==set(ordered['symbols'])
    assert [t[:8] for t in before['orders']]==[t[:8] for t in after['orders']]
    sort=lambda r:(r[0],r[1],r[2])
    for a_order,b_order in zip(sorted(before['orders'],key=sort),sorted(ordered['orders'],key=sort),strict=True):
        assert a_order[:3]==b_order[:3]
        for x,y in zip(a_order[3:],b_order[3:],strict=True):near(x,y)
    for a_mark,b_mark in zip(before['marks'],ordered['marks'],strict=True):
        assert a_mark[0]==b_mark[0]
        for x,y in zip(a_mark[1:],b_mark[1:],strict=True):near(x,y)
    assert sum(x['matching_closed_prices'] for x in spec['data'])==1_851_840
    assert not any(d['different_observations'] or d['outside_official_candle'] for d in spec['data'])
    original,fee_free=[verify_minute_ema(r,data,spec) for r in src['results']]
    doc={'coverage':[[5366,'Tested \u00b7 authored minute BTC/ETH EMA portfolio model',
                     'The author’s later minute EMA benchmark was executed, including BTC and ETH as real portfolio legs. A portfolio of 24 instruments is preserved. Archived production risk gates and its different default list are outside this research scope.']],
         'results':[original[0]],'zero_commission_sensitivity':[fee_free[0]],'diagnostics':[original[1],fee_free[1]],
         'author_sources_and_data':spec,
         'verification':{'catalogue_sha256':sha(catalog),'source_binding_sha256':sha(release),'byte_identical_source_run_sha256':sha(program),
                         'natural_set_reproducibility_sha256':sha(ordinary),'worker_sha256':sha(a.worker.read_bytes()),
                         'stage_sha256':sha(a.stage.read_bytes()),'verifier_sha256':sha(Path(__file__).read_bytes())},
         'method':{'scope':'Author’s Part4 one-minute executable historical study (cell 8 and its original engine). EMA alpha .001 matches the later live archive’s documented cadence. The model uses 24 original markets, including BTC and ETH, $300 per 1% deviation and a $150 rebalance gate; the active JS starts from a 19-asset default and applies quote, imbalance and risk checks separately.',
                   'observations':'Preserve the author’s full warmup of 69,660 minutes and the 7,500-minute executed segment. All 1,851,840 price observations, including both BTC and ETH, cross-check against independent Binance 1m closed candles. Source floating serialization is compared at 1e-12.',
                   'execution':'Same-candle modeled execution uses the original author notebook’s linear USDT venue approximation and 0.075% commission. Zero commission reruns preserve the same order path. The engine supplies no simulated funding or liquidation. No live websocket, market account, IOC or order book is part of these metrics.',
                   'measurement':'Reconstruct each per-symbol EMA and portfolio state with Decimal arithmetic. At exact $150 rebalance ties, native floating-point source decisions are retained and the side, size, fees and position transition remain independently checked. Count distinct position reductions across one portfolio. Drawdown values are fractions. BTC and ETH gross leg totals are in diagnostics.'},
         'references':[spec['source']['publisher'],spec['source']['linked_predecessor_article'],spec['source']['author_minute_research'],
                       'https://github.com/binance/binance-public-data']}
    a.output.write_text(json.dumps(doc,ensure_ascii=False,indent=2,default=float)+'\n',encoding='utf-8',newline='\n')
    print([(r['case'],r['closed_reductions_by_leg'].get('BTC'),r['closed_reductions_by_leg'].get('ETH')) for r in doc['diagnostics']],sha(a.output.read_bytes()),flush=True)


if __name__=='__main__':main()
