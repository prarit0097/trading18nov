"""Reconcile the original fixed-notional basket with independent Decimal arithmetic."""
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
from verify_r45_5094_spot import curve, relative_pnl

ZERO=D(0)
BASE=D(10_000)
RATE=D('.0001')
LOT=D('.000001')


def near(left,right,tol=D('.000001')):
    assert abs(D(str(left))-D(str(right)))<=tol,(left,right)


def verify_replay(case,data,source):
    inputs=list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))
    selected=sorted(source['short_symbols'])+['BTC']
    assert case['iteration']==selected
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
    rate=D(str(case['commission']))
    assert rate in (D('.0005'),ZERO)
    final_prices={s['symbol']:D(s['terminal_official_close']) for s in source['official_market_proof']}
    trace=iter(case['marks'])
    for offset,data in enumerate(inputs):
        dt=data['0']
        levels={s:D(data[s]) for s in selected if data[s]}
        if offset==len(inputs)-1 and case['mode']=='official final candle':
            levels=final_prices
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
            exposure=sum(abs(positions[s])*levels.get(s,ZERO) for s in selected[:-1]) if symbol=='BTC' else D(2000)
            gap=exposure-abs(previous)*price
            if abs(gap)<=20:
                assert symbol not in declared,(dt,symbol,gap)
                continue
            assert symbol in declared,(dt,symbol,gap)
            expected_side=(1 if gap>0 else -1) if symbol=='BTC' else (-1 if gap>0 else 1)
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
    summary=case['accounts']
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
    row={'id':4427,'name':'Author notebook fixed alt-basket shorts, BTC hedge','market':'Binance USD-M, BTC hedge + 14 authored altcoins','group':case['mode'],
         'source':source['source']['archive_url'],'period':inputs[0]['0']+' to '+inputs[-1]['0']+' UTC',
         'interval':'Authored 1h Binance prices and close-based notebook execution',
         'exit':'Directional reductions use average-cost basis and allocate entry commissions and modeled carry.',
         'currency':'USDT','quote_currency':'USDT','currency_decimal_places':8,'starting_equity':BASE,
         'gross':gross,'fees':allocated,'after_fees':sum(after),'execution':ZERO,'funding':funding_realised,'net':sum(net),
         'gross_dd':gdd,'gross_dd_pct':gp,'fee_dd':fdd,'fee_dd_pct':fp,'net_dd':ndd,'net_dd_pct':np,
         'gross_wins':sum(v>0 for v in before),'fee_wins':sum(v>0 for v in after),'net_wins':sum(v>0 for v in net),
         'trades':len(before),'unsettled':sum(v!=0 for v in positions.values()),'mark_to_market_net':marked_net,
         'remaining_unrealized':unreal,'marked_dd':mdd,'marked_dd_pct':mp,'all_costs':costs,'all_funding':funding}
    audit={'case':case['mode'],'open_legs':row['unsettled'],'order_quantity':len(case['orders']),'closed_reductions_by_leg':dict(count),
           'gross_by_leg':total_gross,'native_terminal_chart_pre_trade_equity':case['marks'][-1][4],
           'min_research_margin_headroom_USDT':min(collateral_history)}
    return row,audit


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('market','proof','worker','stage','first','repeat','ordinary','output'):
        p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    receipt=a.first.read_bytes()
    assert receipt==a.repeat.read_bytes()
    native=json.loads(gzip.decompress(receipt))
    proof=a.proof.read_bytes()
    series=a.market.read_bytes()
    stages=json.loads(proof)
    normal=a.ordinary.read_bytes()
    order_control=json.loads(gzip.decompress(normal))
    assert order_control['ordinary_set'] and not native['ordinary_set']
    assert native['input_proof_sha256']==sha(proof)==order_control['input_proof_sha256']
    assert order_control['worker_sha256']==native['worker_sha256']==sha(a.worker.read_bytes())
    assert sha(series)==stages['source']['csv_sha256']
    actual=order_control['results'][0]
    expected=native['results'][0]
    assert set(actual['iteration'])==set(expected['iteration'])
    assert actual['iteration']!=expected['iteration']
    key=lambda o:(o[0],o[1],o[2])
    for earlier,later in zip(sorted(actual['orders'],key=key),sorted(expected['orders'],key=key),strict=True):
        assert earlier[:3]==later[:3]
        for x,y in zip(earlier[3:],later[3:],strict=True):near(x,y)
    for earlier,later in zip(actual['marks'],expected['marks'],strict=True):
        assert earlier[0]==later[0]
        for x,y in zip(earlier[1:],later[1:],strict=True):near(x,y)
    assert [o[:8] for o in native['results'][0]['orders']]==[o[:8] for o in native['results'][1]['orders']]
    rows=[verify_replay(s,series,stages) for s in native['results']]
    report={'coverage':[[4427,'Tested \u00b7 authored fixed-exposure BTC hedge notebook',
                 'Exact author-linked research rules and the archived 14-coin short basket were reproduced on verified Binance USD-M prices. Matched BTC hedge is active. The author excludes ETH from this basket. Native production IOC/live execution remains outside scope.']],
            'results':[rows[0][0]],'no_commission_sensitivity':[rows[1][0]],'official_terminal_candle_sensitivity':[rows[2][0]],
            'details':[proof for _,proof in rows],'source_and_data':stages,
            'proof':{'native_duplicate_sha256':sha(receipt),'unordered_original_set_repeat_sha256':sha(normal),'data_binding_sha256':sha(proof),
                     'worker_sha256':native['worker_sha256'],'stage_sha256':sha(a.stage.read_bytes()),'verifier_sha256':sha(Path(__file__).read_bytes())},
            'method':{'strategy':'First author notebook checks each alt short against its 2,000 USDT research target and rebalances a BTC long to their total. Trade orders use the historical hourly prices and a 20 USDT threshold. These are the author’s notebook settings. Archived live JS has a 50 USDT default and exchange-dependent execution.',
                      'prices':'All finalized BTC and selected alt coin prices match independent checksummed Binance files. Unavailable early listings have no assumed price. Preserve original terminal author snapshot in primary and rerun using all official finalized closes.',
                      'funding_and_fees':'Original notebook charges 0.05% commission. It credits/debits a fixed 0.01% funding proxy on each open leg at 00, 08 and 16 UTC. Historical funding rates, liquidation and actual quoted execution risk are outside the original simulation. Hold the decisions fixed in the no-fee run.',
                      'measurement':'Count each closing reduction from the joint BTC and short-basket portfolio, and allocate opening costs and accrued proxy funding proportionately. Keep BTC hedge and ALT market paths in one portfolio result. Drawdown ratios have fractional units. The native chart and the marked terminal portfolio can differ due to final orders.',
                      'host':'Original code executes in offline native Python with published notebook cells and pandas 2.2.3. Set iteration is sorted deterministically. Same decisions and cash/equity path independently reproduced with native set ordering.'},
            'references':['https://www.fmz.com/strategy/194825','https://www.fmz.com/digest-topic/5294','https://github.com/binance/binance-public-data']}
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=float)+'\n',encoding='utf-8',newline='\n')
    print([(row['group'],row['trades'],row['net'],row['mark_to_market_net']) for row,_ in rows],sha(a.output.read_bytes()),flush=True)


if __name__=='__main__':main()
