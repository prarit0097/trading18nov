"""Cross-check the authored butterfly runs with independent baskets and cash accounting."""
import argparse
from collections import defaultdict
import csv
from decimal import Decimal as D
import gzip
import io
import json
from pathlib import Path

from fmz_native_round20_880_capture import sha
from verify_r45_5094_spot import curve, relative_pnl

ZERO=D(0)
SEED=D(10_000)
TOLERANCE=D('.0000003')


def decimal(x):
    return D(str(x))


def same(a,b,tol=TOLERANCE):
    assert abs(decimal(a)-decimal(b))<=tol,(a,b)


def data_rows(raw,symbols,official):
    rows=[]
    for row in csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))):
        if all(row[s] for s in symbols):
            rows.append((row[''],[D(row[s]) for s in symbols]))
    if official:
        rows[-1]=(rows[-1][0],[D(official[s]) for s in symbols])
    return rows


def reconcile(scope,raw,candle):
    coin=scope['coin']
    assert coin in ('BTC','ETH')
    names=[f'{coin}USD_{key}' for key in ('201225','200925','PERP')]
    assert scope['symbols']==names
    positions=[ZERO]*3
    entry=[ZERO]*3
    fee_alloc=[ZERO]*3
    lev=D(20)
    realized=paid=ZERO
    outcomes=[]
    all_mark=[]
    headroom=[]
    ideal_ema=ZERO
    divisor=ZERO
    cumulative=ZERO
    fees=decimal(scope['fee_rate'])
    listed=scope['transactions']
    by_time=defaultdict(list)
    for e in listed:by_time[e[0]].append(e)
    assert all([e[1] for e in leg]==[names[1],names[0],names[2]] for leg in by_time.values())
    seen=set()
    chart=iter(scope['chart'])
    inspected=0
    holds_float=0
    initial_count=0 if coin=='BTC' else 30
    scope_data=data_rows(raw,names,candle)
    for index,(stamp,prices) in enumerate(scope_data):
        diff=prices[0]+prices[2]-2*prices[1]
        cumulative=diff+D('.999')*cumulative
        divisor=1+D('.999')*divisor
        ideal_ema=cumulative/divisor
        if index<initial_count:
            assert stamp not in by_time
            continue
        t,closed,unreal,margin,charges,reported_equity,prices_received=next(chart)
        assert t==stamp and prices==[decimal(v) for v in prices_received]
        floating=sum((m-p)*q for m,p,q in zip(prices,entry,positions,strict=True))
        tied=sum(abs(n)*p/lev for n,p in zip(positions,entry,strict=True))
        eq=SEED+realized-paid+floating
        same(closed,realized-paid)
        same(unreal,floating)
        same(margin,tied)
        same(charges,paid)
        same(reported_equity,eq,D('.000001'))
        all_mark.append(eq)
        headroom.append(eq-tied)
        inspected+=1
        width=30 if coin=='BTC' else 15*prices[2]*D('.0002')
        aim=-round(float((diff-ideal_ema)/width),1)
        delta=aim-holds_float
        intended=1 if delta>1 else -1 if delta<-1 else 0
        observed=by_time.get(t,[])
        if not intended:
            assert not observed,(coin,t,aim,holds_float,observed)
            continue
        assert observed,(coin,t,aim,holds_float)
        expected=abs(delta) if coin=='BTC' else 1
        old=positions[2]
        gross=costs=covered_qty=ZERO
        seen.add(t)
        for e in observed:
            date,sym,side,observed_px,size,prior,after,post_entry,net_change,observed_fee=e
            leg=names.index(sym)
            weight=-2 if leg==1 else 1
            assert side==intended*(1 if weight>0 else -1)
            price=prices[leg]
            q=decimal(size).quantize(D('.1'))
            same(size,q)
            same(q,expected*abs(weight))
            same(price,observed_px)
            same(prior,positions[leg])
            hold=positions[leg]
            addition=q
            charge=fees*price*q
            settled=ZERO
            if side*hold<0:
                amount=min(abs(hold),q)
                if leg==2:covered_qty=amount
                allocated=fee_alloc[leg]*amount/abs(hold)
                fee_alloc[leg]-=allocated
                costs+=allocated+price*amount*fees
                settled=(price-entry[leg])*amount*(-side)
                gross+=settled
                positions[leg]+=side*amount
                addition-=amount
            if addition>0:
                p=abs(positions[leg])
                entry[leg]=(p*entry[leg]+price*addition)/(p+addition)
                positions[leg]+=side*addition
                fee_alloc[leg]+=price*addition*fees
            elif not positions[leg]:entry[leg]=ZERO
            same(positions[leg],after)
            if positions[leg]:same(entry[leg],post_entry)
            same(charge,observed_fee)
            same(settled-charge,net_change)
            realized+=settled
            paid+=charge
            if leg==2:holds_float=after
        if covered_qty>0:
            assert old*intended<0
            outcomes.append([gross,costs,covered_qty])
        else:
            same(gross,0)
            same(costs,0)
        same(positions[0],positions[2])
        same(positions[1],-2*positions[2])
        post_unreal=sum((m-p)*q for m,p,q in zip(prices,entry,positions,strict=True))
        all_mark.append(SEED+realized-paid+post_unreal)
        headroom.append(all_mark[-1]-sum(abs(n)*p/lev for n,p in zip(positions,entry,strict=True)))
    assert next(chart,None) is None and seen==set(by_time)
    ending=scope['final_account']
    same(realized-paid,ending['realised_profit'])
    same(paid,ending['fee'])
    same(paid,ending['taker_fee'])
    same(0,ending['maker_fee'])
    same(sum(abs(n)*p/lev for n,p in zip(positions,entry,strict=True)),ending['margin'])
    for i,sym in enumerate(names):
        after=scope['final_legs'][sym]
        same(positions[i],after['amount'])
        if positions[i]:same(entry[i],after['hold_price'])
    net=all_mark[-1]-SEED
    tail_unreal=sum((decimal(scope['final_legs'][symbol]['price'])-e)*q for symbol,e,q in zip(names,entry,positions,strict=True))
    same(tail_unreal,sum(q['unrealised_profit'] for q in scope['final_legs'].values()))
    gross_trades=[x[0] for x in outcomes]
    net_trades=[x-y for x,y,z in outcomes]
    gross=sum(gross_trades)
    taken=sum(q[1] for q in outcomes)
    same(realized,gross)
    same(taken+sum(fee_alloc),paid)
    same(gross-taken+tail_unreal-sum(fee_alloc),net)
    gross_dd,gross_pct=curve(SEED,relative_pnl(SEED,gross_trades))
    net_dd,net_pct=curve(SEED,relative_pnl(SEED,net_trades))
    market_dd,market_pct=curve(SEED,all_mark)
    summary={'id':4417,'name':'Binance COIN-M butterfly hedge, author notebook','market':f'Binance COIN-M {coin}, three-leg basket, USDT notebook proxy',
             'group':scope['case'],'period':scope_data[initial_count][0]+' to '+scope_data[-1][0]+' UTC',
             'interval':'Original 5m Binance historical prices, author linear synthetic execution',
             'exit':'Per synchronized three-leg basket reduction. Remaining legs marked at terminal research prices.',
             'currency':'USDT','quote_currency':'USDT','currency_decimal_places':8,
             'starting_equity':SEED,'gross':gross,'fees':taken,'after_fees':sum(net_trades),'net':sum(net_trades),
             'execution':ZERO,'funding':ZERO,'gross_dd':gross_dd,'gross_dd_pct':gross_pct,'net_dd':net_dd,'net_dd_pct':net_pct,
             'fee_dd':net_dd,'fee_dd_pct':net_pct,'gross_wins':sum(x>0 for x in gross_trades),'net_wins':sum(x>0 for x in net_trades),
             'fee_wins':sum(x>0 for x in net_trades),'trades':len(outcomes),'unsettled':int(any(abs(x)>D('.000001') for x in positions)),
             'marked_dd':market_dd,'marked_dd_pct':market_pct,'mark_to_market_net':net,'remaining_unrealized':tail_unreal,
             'total_paid_fees':paid,'open_position_fee_not_allocated':sum(fee_alloc)}
    proof={'coin':coin,'scenario':scope['case'],'fee_rate_decimal':scope['fee_rate'],'num_authored_mark_rows':inspected,
           'basket_adjustment_count':len(by_time),'individual_leg_fills':len(listed),'closed_basket_reductions':len(outcomes),
           'highest_margined_leverage_ratio_before_orders':max(x[3]*20/x[5] for x in scope['chart']),
           'minimum_linear_research_collateral_headroom_USDT':min(headroom),'terminal_per_leg':{name:str(q) for name,q in zip(names,positions,strict=True)},
           'author_chart_final_pre_trade_marked':sum(scope['chart'][-1][1:3]),'active_cell_sha256':scope['active_cell_sha256'],
           'engine_cell_sha256':scope['engine_cell_sha256'],'trade_trace_digest':sha(json.dumps(listed,separators=(',',':')).encode())}
    return summary,proof


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('first','repeat','csv','proof','worker','stage','output'):
        p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    receipt=a.first.read_bytes()
    assert receipt==a.repeat.read_bytes()
    r=json.loads(gzip.decompress(receipt))
    manifest=a.proof.read_bytes()
    verified=json.loads(manifest)
    data=a.csv.read_bytes()
    check=r['verification']
    assert check['csv_sha256']==sha(data)==verified['source']['author_csv_sha256']
    assert check['notebook_sha256']==verified['source']['author_notebook_sha256']
    assert check['official_candle_proof_sha256']==sha(manifest) and check['worker_sha256']==sha(a.worker.read_bytes())
    final={p['symbol']:p['independent_final_candle_close'] for p in verified['prices']}
    assert len(final)==6
    rows=[]
    details=[]
    for q in r['results']:
        use_final=final if q['case']=='official finalized terminal candle' else None
        row,proof=reconcile(q,data,use_final)
        row['source']=verified['source']['source_url']
        rows.append(row)
        details.append(proof)
    for i in (0,3):
        assert r['results'][i]['case']=='authored research'
        assert r['results'][i+1]['case']=='0.04% fixed-grid taker fee'
        assert [e[:8] for e in r['results'][i]['transactions']]==[e[:8] for e in r['results'][i+1]['transactions']]
    report={'coverage':[[4417,'Tested \u00b7 authored BTC/ETH butterfly notebook model',
                         'Both published original historical notebook cases execute on independently verified Binance COIN-M price legs. Results reflect the notebook’s explicitly linear USDT paper engine. The separate live IOC implementation and executable inverse settlement are outside this historical result.']],
            'results':[r for r in rows if r['group']=='authored research'],
            'fixed_grid_higher_fee_sensitivity':[r for r in rows if r['group']=='0.04% fixed-grid taker fee'],
            'official_terminal_price_sensitivity':[r for r in rows if r['group']=='official finalized terminal candle'],
            'proof':{**check,'reproducible_runtime_receipt_sha256':sha(receipt),'stage_sha256':sha(a.stage.read_bytes()),
                     'independent_verifier_sha256':sha(Path(__file__).read_bytes())},
            'source':verified['source'],'price_series_provenance':verified['prices'],'diagnostics':details,
            'scope':{'fills':'Author-linked notebook cells 13, 14 and 18 simulate synchronized three-leg fills at candle observations with a 20x linear USDT engine. Only plot display is omitted. Neither actual inverse coin P&L, funding rates nor IOC leg slippage is implemented in the author model.',
                     'dates':'Use the author CSV timestamps, independently identified as UTC bucket-open labels. ETH starts after the author’s 30-valid-bar warmup. All finalized source prices independently cross-match. Each final saved source price is within its official OHLC range and differs from its finalized close. Preserve it in primary results and rerun with the documented official close.',
                     'fees':'Primary uses the original author research 0.02% taker fees. Alternate fixed-grid reruns use the author-discussed 0.04% rate while leaving signal thresholds fixed. Fee changes produce an identical quantity/price decision trace. Basket-reduction P&L allocates previous open fees pro rata; marked equity counts all fees.',
                     'risk':'Quoted cash plus remaining marked linear legs is research equity. The author engine computes linear margin, without venue liquidation, maintenance rules, collateral valuation dynamics or practical partial-leg ordering. Drawdown fields are fractions and refer only to this model.'},
            'references':['https://www.fmz.com/digest-topic/6102','https://www.fmz.com/strategy/226882','https://github.com/binance/binance-public-data']}
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=float)+'\n',encoding='utf-8',newline='\n')
    print([(v['market'],v['group'],v['trades'],v['net'],v['mark_to_market_net']) for v in rows],sha(a.output.read_bytes()),flush=True)


if __name__=='__main__':main()
