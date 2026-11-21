"""Independently replay every EMA decision and reconcile author notebook P&L."""
import argparse
from collections import defaultdict
import csv
from datetime import datetime
from decimal import Decimal as D
import gzip
import io
import json
from pathlib import Path

from fmz_native_round20_880_capture import sha
from verify_r48_4427_hedge import ZERO, BASE, RATE, LOT, near, curve, relative_pnl


def verify_ema(case,data,source):
    inputs=list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))
    excluded={'LINK','XTZ','BCH','ETH'} if case['cell']==22 else set()
    selected=sorted(set(source['alt_symbols'])-excluded)
    assert case['symbols']==selected and 'BTC' not in selected
    ewm_numerator={v:ZERO for v in selected}
    ewm_weight=dict(ewm_numerator)
    positions={s:ZERO for s in selected}
    entry=dict(positions)
    carried_fee=dict(positions)
    carried_funding=dict(positions)
    total_gross=dict(positions)
    collateral_history=[]
    gross_history=[]
    after_history=[]
    net_history=[]
    marked=[]
    costs=ZERO
    count=defaultdict(int)
    funding=ZERO
    markets_by_bar=defaultdict(list)
    for order in case['orders']:markets_by_bar[order[0]].append(order)
    rate=D(str(case['fee_rate']))
    assert rate in (D('.0005'),ZERO)
    final_prices={s['symbol']:D(s['terminal_official_close']) for s in source['proof']}
    trace=iter(case['marks'])
    for offset,data in enumerate(inputs):
        dt=data['0']
        levels={s:D(data[s]) for s in selected if data[s]}
        if offset==len(inputs)-1 and case['case']=='official terminal candle':
            levels={v:final_prices[v] for v in selected}
        benchmark=final_prices['BTC'] if offset==len(inputs)-1 and case['case']=='official terminal candle' else D(data['BTC'])
        ratios={}
        for ticker in selected:
            ewm_numerator[ticker]*=D('.95')
            ewm_weight[ticker]*=D('.95')
            if ticker in levels:
                rel=levels[ticker]/benchmark
                ewm_numerator[ticker]+=rel
                ewm_weight[ticker]+=1
                ratios[ticker]=rel*ewm_weight[ticker]/ewm_numerator[ticker]
        market_index=sum(ratios.values())/len(ratios)
        schedule=datetime.fromisoformat(dt).hour in (0,8,16)
        flows=ZERO
        if schedule:
            for symbol,p in levels.items():
                happening=-positions[symbol]*p*RATE
                carried_funding[symbol]+=happening
                flows+=happening
        funding+=flows
        mtm=sum((p-entry[s])*positions[s] for s,p in levels.items())
        margin=sum(abs(positions[s])*entry[s]/20 for s in selected)
        realised=sum(total_gross.values())-costs+funding
        balance=BASE+realised+mtm
        native=next(trace)
        assert dt==native[0]
        for observed,wanted in zip(native[1:],[realised,margin,mtm,balance,flows],strict=True):near(observed,wanted)
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
            exposure=-300*D(str(round(float(displacement/D('.01')),1)))
            gap=exposure-previous*price
            if abs(gap)<=20:
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
                payment=carried_funding[symbol]*share
                gross=(price-entry[symbol])*gone*(-side)
                fee=establish+price*gone*rate
                gross_history.append(gross)
                after_history.append(gross-fee)
                net_history.append(gross-fee+payment)
                carried_fee[symbol]-=establish
                carried_funding[symbol]-=payment
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
            if positions[symbol]:near(entry[symbol],source_basis)
            near(gross-charge,reported_delta)
        if declared:
            mtm=sum((p-entry[s])*positions[s] for s,p in levels.items())
            margin=sum(abs(positions[s])*entry[s]/20 for s in selected)
            marked.append(BASE+sum(total_gross.values())-costs+funding+mtm)
            collateral_history.append(marked[-1]-margin)
    assert next(trace,None) is None
    summary=case['final_account']
    for symbol in selected:
        native=summary[symbol]
        near(native['amount'],positions[symbol]);near(native['realised_profit'],total_gross[symbol]);
        if positions[symbol]:near(native['hold_price'],entry[symbol])
    total=sum(total_gross.values())
    native=summary['USDT']
    near(native['realised_profit'],total-costs+funding)
    near(native['margin'],sum(abs(positions[s])*entry[s]/20 for s in selected))
    assert len(gross_history)>0
    unreal=sum(D(str(summary[k]['unrealised_profit'])) for k in selected)
    gross=sum(gross_history)
    allocated=gross-sum(after_history)
    funding_realised=sum(net_history)-sum(after_history)
    near(allocated+sum(carried_fee.values()),costs)
    near(funding_realised+sum(carried_funding.values()),funding)
    marked_net=marked[-1]-BASE
    near(marked_net,gross-costs+funding+unreal)
    before=gross_history;after=after_history;net=net_history
    gdd,gp=curve(BASE,relative_pnl(BASE,before));fdd,fp=curve(BASE,relative_pnl(BASE,after));ndd,np=curve(BASE,relative_pnl(BASE,net))
    mdd,mp=curve(BASE,marked)
    row={'id':4428,'name':'Author notebook multi-asset EMA relative value','market':'Binance USD-M, '+str(len(selected))+' altcoins versus BTC index','group':case['case'],
         'source':source['source']['url'],'period':inputs[0]['0']+' to '+inputs[-1]['0']+' UTC',
         'interval':'Authored 1h Binance prices and close-based notebook execution',
         'exit':'Directional reductions use average-cost basis and allocate entry commissions and modeled carry.',
         'currency':'USDT','quote_currency':'USDT','currency_decimal_places':8,'starting_equity':BASE,
         'gross':gross,'fees':allocated,'after_fees':sum(after),'execution':ZERO,'funding':funding_realised,'net':sum(net),
         'gross_dd':gdd,'gross_dd_pct':gp,'fee_dd':fdd,'fee_dd_pct':fp,'net_dd':ndd,'net_dd_pct':np,
         'gross_wins':sum(v>0 for v in before),'fee_wins':sum(v>0 for v in after),'net_wins':sum(v>0 for v in net),
         'trades':len(before),'unsettled':sum(v!=0 for v in positions.values()),'mark_to_market_net':marked_net,
         'remaining_unrealized':unreal,'marked_dd':mdd,'marked_dd_pct':mp,'all_costs':costs,'all_funding':funding}
    audit={'case':case['case'],'open_legs':row['unsettled'],'order_quantity':len(case['orders']),'closed_reductions_by_leg':dict(count),
           'gross_by_leg':total_gross,'native_terminal_chart_pre_trade_equity':case['marks'][-1][4],
           'min_research_margin_headroom_USDT':min(collateral_history)}
    return row,audit


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('first','repeat','ordinary','market','proof','stage','worker','output'):
        p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args()
    raw=a.first.read_bytes()
    assert raw==a.repeat.read_bytes()
    studied=json.loads(gzip.decompress(raw))
    legacy=a.ordinary.read_bytes()
    replay=json.loads(gzip.decompress(legacy))
    evidence=a.proof.read_bytes()
    source=json.loads(evidence)
    market=a.market.read_bytes()
    assert source['source']['csv_sha256']==sha(market)
    assert replay['proof_sha256']==sha(evidence)==studied['proof_sha256']
    assert replay['worker_sha256']==studied['worker_sha256']==sha(a.worker.read_bytes())
    assert replay['ordinary_set'] and not studied['ordinary_set']
    listed,other=studied['results'][0],replay['results'][0]
    assert listed['symbols']!=other['symbols'] and set(listed['symbols'])==set(other['symbols'])
    key=lambda r:(r[0],r[1],r[2])
    for record,ordinary in zip(sorted(listed['orders'],key=key),sorted(other['orders'],key=key),strict=True):
        assert record[:3]==ordinary[:3]
        for l,r in zip(record[3:],ordinary[3:],strict=True):near(l,r)
    for record,ordinary in zip(listed['marks'],other['marks'],strict=True):
        assert record[0]==ordinary[0]
        for l,r in zip(record[1:],ordinary[1:],strict=True):near(l,r)
    cuts=[verify_ema(r,market,source) for r in studied['results']]
    assert [o[:8] for o in listed['orders']]==[o[:8] for o in studied['results'][2]['orders']]
    primary,filtered,fee_free,official=[r for r,_ in cuts]
    doc={'coverage':[[4428,'Tested \u00b7 authored USD-M EMA relative-value notebook',
                     'The author’s second-strategy EMA optimization cells ran on all vetted Binance BTC-index and alt prices. ETH trades in the 23-alt primary basket. BTC supplies normalization, and there is no direct BTC leg. Active live-minute risk rules remain outside the authored research scope.']],
         'results':[primary],'author_filter_sensitivity':[filtered],'zero_commission_sensitivity':[fee_free],
         'official_finalized_terminal_sensitivity':[official],
         'source_and_data':source,'diagnostics':[d for _,d in cuts],
         'verification':{'binding_sha256':sha(evidence),'byte_identical_native_runs_sha256':sha(raw),
                         'ordinary_set_control_sha256':sha(legacy),'stage_sha256':sha(a.stage.read_bytes()),
                         'worker_sha256':studied['worker_sha256'],'verifier_sha256':sha(Path(__file__).read_bytes())},
         'scope':{'rules':'Author notebook 5364 cells 16 and 22. One-hour adjusted EMA alpha .05, $300 notional per 1% relative deviation, $20 rebalance gate. BTC drives the coin ratios. This is the specifically published historical EMA study. The archived JS runtime uses its own 60-second Alpha .001 rule and real-quote risk gates.',
                  'price_binding':'All finalized populated observations independently match checksummed Binance hourly files. Keep author terminal partial-observation prices in baseline and rerun official finalized closes as a terminal sensitivity.',
                  'fees_and_funding':'Author’s original 0.05% commission and scheduled 0.01% fixed proxy funding per open leg, in USDT. Original strategy decisions repeat with zero commissions. Applied fees and proxy funding are separately reconciled at every step.',
                  'execution':'Authored strategy signals and fills share the same bar price. Historical order book, latency, market impact and cross-margin liquidation are outside this model. All trade counts are portfolio position reductions on alt legs, not independent bets. Drawdown fields are fractions.'},
         'references':[source['source']['author_page'],source['source']['part1'],source['source']['part2'],'https://github.com/binance/binance-public-data']}
    a.output.write_text(json.dumps(doc,ensure_ascii=False,indent=2,default=float)+'\n',encoding='utf-8',newline='\n')
    print([(r['group'],r['trades'],r['net'],r['mark_to_market_net']) for r,_ in cuts],sha(a.output.read_bytes()),flush=True)


if __name__=='__main__':main()
