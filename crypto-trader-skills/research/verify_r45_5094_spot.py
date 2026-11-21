"""Independently audit the legacy FMZ #5094 recorded-depth replay and FIFO accounting."""
import argparse
from bisect import bisect_right
from collections import defaultdict, deque
import csv
from decimal import Decimal as D, ROUND_HALF_EVEN
import gzip
import io
import json
from pathlib import Path
from zipfile import ZipFile

from fmz_native_round20_880_capture import request, sha

BTC=100_000_000
DENOM=BTC*100
INITIAL_BTC=3*BTC
INITIAL_CASH=D(10_000)
ZERO=D(0)


def decimals(x):
    return D(str(x))


def close(a,b):
    assert abs(decimals(a)-decimals(b))<=D('.000001'),(a,b)


def price_size(s,unit):
    value=D(s)*unit
    assert value==int(value)
    return int(value)


def check_official(needed):
    label='BTCUSDT-trades-2019-09-01.zip'
    url='https://data.binance.vision/data/spot/daily/trades/BTCUSDT/'+label
    with request(url+'.CHECKSUM') as r:
        verified,f=r.read(200).decode().split()
    assert f==label
    with request(url) as r:
        raw=r.read(60_000_000)
    assert sha(raw)==verified
    linked={}
    with ZipFile(io.BytesIO(raw)) as file:
        [member]=file.namelist()
        with file.open(member) as read:
            for row in csv.reader(io.TextIOWrapper(read,encoding='utf-8')):
                if not row[0].isdigit():continue
                ident=int(row[0])
                if ident not in needed: continue
                assert ident not in linked and row[5].lower() in ('false','true')
                tick=needed[ident]
                assert abs(int(row[4])*1000-tick[1])<1000
                assert int(row[5].lower()=='false')==tick[4]
                assert price_size(row[1],100)==tick[5] and price_size(row[2],BTC)==tick[6]
                linked[ident]=tick
    assert linked.keys()==needed.keys()
    return {'url':url,'sha256':verified,'verified_raw_ids':len(linked),'verified_fields':['ID','time','price','size','aggressor']}


def curve(initial,values):
    peak=initial
    absolute=relative=ZERO
    for value in values:
        peak=max(peak,value)
        absolute=max(absolute,peak-value)
        relative=max(relative,(peak-value)/peak)
    return absolute,relative


def relative_pnl(seed,vals):
    wallet=seed
    for x in vals:
        wallet+=x
        yield wallet


def get_mark_time(mark_path, fills, books, initial_qty, initial_cash):
    ix=0
    cash=initial_cash
    qty=initial_qty
    observed=[]
    stamps=[b[1] for b in books]
    for t,bid,nav in mark_path:
        assert bid==books[bisect_right(stamps,t)-1][4][2]
        while ix<len(fills) and fills[ix][0]<t:
            _,side,vol,v,fee=fills[ix]
            cash+=(v if not side else -v)-fee
            qty+=vol if side else -vol
            ix+=1
        alternatives=[cash+D(qty*bid)/DENOM]
        i=ix
        while i<len(fills) and fills[i][0]==t:
            _,side,vol,v,fee=fills[i]
            cash+=(v if not side else -v)-fee
            qty+=vol if side else -vol
            i+=1
            alternatives.append(cash+D(qty*bid)/DENOM)
        ix=i
        assert any(abs(x-decimals(nav))<=D('.000001') for x in alternatives),(t,bid,nav,alternatives)
        observed.append(min(alternatives,key=lambda x:abs(x-decimals(nav))))
    assert ix==len(fills)
    return observed


def audit(case,spec,trade_by_id):
    pending={}
    pay=decimals(case['style']['fee'])
    multiplier=case['style']['volume']
    available=INITIAL_CASH
    holdings=INITIAL_BTC
    allocated=defaultdict(int)
    depth_used=defaultdict(int)
    mark=case['startMark']
    assert spec['book'][0][4][2]==mark and spec['book'][0][1]==case['first_book_us']
    seed=available+D(mark*holdings)/DENOM
    close(case['initial'],seed)
    inventory=deque([(holdings,seed-available,ZERO)])
    book=spec['book']
    clock=[a[1] for a in book]
    settled={}
    fillproof=[]
    sale_times={}
    spent=ZERO
    count_maker=count_depth=count_cancels=0
    seen=set()
    for step in case['trace']:
        kind,t,*row=step
        assert case['start']<=t<case['end']
        if kind=='reject':
            continue
        i=row[0]
        if kind=='order':
            _,buy,limit,q,raw_limit,raw_size=row
            assert i not in pending
            # Two-stage scaling mirrors floating host precision before its half-even tie gate.
            assert limit==int(D(raw_limit*100).to_integral_value(rounding=ROUND_HALF_EVEN))
            assert q==1000*int(D(raw_size*BTC/1000).to_integral_value(rounding=ROUND_HALF_EVEN))
            assert q>0 and q%1000==0 and D(limit*q)/DENOM>=5
            pending[i]={'t':t,'buy':buy,'limit':limit,'remaining':q,'canceled':False}
            continue
        active=pending[i]
        assert not active['canceled'] and active['remaining']>0
        if kind=='cancel':
            assert active['t']<t
            active['canceled']=True
            count_cancels+=1
            continue
        assert kind=='fill'
        _,buy,q,px,kind,proof,sent_fee=row
        assert buy==active['buy'] and 0<q<=active['remaining'] and q%1000==0
        assert px<=active['limit'] if buy else px>=active['limit']
        active['remaining']-=q
        notional=D(q*px)/DENOM
        fee=notional*pay
        close(fee,sent_fee)
        if kind=='maker':
            assert active['t']<t and px==active['limit'] and sum(x[1] for x in proof)==multiplier*q
            for raw,used in proof:
                record=trade_by_id[raw]
                assert active['t']<record[0]<=t and record[0]==max(record[1],record[2])
                assert record[4]==1-buy and 0<used
                assert record[5]<px if buy else record[5]>px
                allocated[raw]+=used
                assert allocated[raw]<=record[6]
                seen.add(raw)
            assert max(trade_by_id[num][0] for num,n in proof)==t
            count_maker+=1
        else:
            assert kind=='taker' and t==active['t']
            observed,venue,local,prev=proof
            assert observed==max(venue,local) and t>=observed and t-observed<=10_000_000
            sampled=book[bisect_right(clock,t)-1]
            assert sampled[1:4]==[observed,venue,local]
            levels=sampled[4];pick=0 if buy else 2
            depth=dict(zip(levels[pick::4],levels[pick+1::4],strict=True))
            key=(observed,buy,px)
            assert prev==depth_used[key] and q+prev<=depth[px]
            depth_used[key]+=q
            count_depth+=1
        spent+=fee
        if buy:
            inventory.append((q,notional,fee))
            holdings+=q
            available-=notional+fee
        else:
            available+=notional-fee
            holdings-=q
            assert holdings>=0
            sale_times[i]=t
            left=q
            profit=notional
            cost=fee
            while left:
                units,basis,buy_fee=inventory.popleft()
                deal=min(left,units)
                split=D(deal)/units
                fee_used=buy_fee*split
                value_used=basis*split
                profit-=value_used
                cost+=fee_used
                if deal<units:inventory.appendleft((units-deal,basis-value_used,buy_fee-fee_used))
                left-=deal
            past=settled.setdefault(i,[ZERO,ZERO])
            past[0]+=profit
            past[1]+=cost
        assert available>=0
        fillproof.append((t,buy,q,notional,fee))
    resting={k:v for k,v in pending.items() if not v['canceled'] and v['remaining']}
    assert resting.keys()==set(case['pending'])
    close(sum(D(o['limit']*o['remaining'])/DENOM*(1+pay) for o in resting.values() if o['buy']),case['lockedCash'])
    assert sum(o['remaining'] for o in resting.values() if not o['buy'])==case['lockedBTC']
    assert holdings==case['inventory']+case['lockedBTC']==sum(lot[0] for lot in inventory)
    close(available,decimals(case['cash'])+decimals(case['lockedCash']))
    tail=available+D(holdings*case['bidCents'])/DENOM
    assert case['bidCents']==book[-1][4][2]
    close(tail,case['marked'])
    values=get_mark_time(case['markChanges'],fillproof,book,INITIAL_BTC,INITIAL_CASH)
    mark_abs,mark_ratio=curve(seed,values)
    close(mark_ratio,case['markedDrawdownRatio'])
    close(values[-1],tail)
    closed_by_ending=sorted(settled,key=lambda x:(sale_times[x],x))
    gross_list=[settled[k][0] for k in closed_by_ending]
    net_list=[settled[k][0]-settled[k][1] for k in closed_by_ending]
    gross=sum(gross_list)
    closed_fees=sum(q[1] for q in settled.values())
    old_basis=sum(q[1] for q in inventory)
    old_fees=sum(q[2] for q in inventory)
    assert closed_by_ending
    close(closed_fees+old_fees,spent)
    close(gross-closed_fees+D(holdings*case['bidCents'])/DENOM-old_basis-old_fees,tail-seed)
    gross_dd,gross_pct=curve(seed,relative_pnl(seed,gross_list))
    net_dd,net_pct=curve(seed,relative_pnl(seed,net_list))
    row={'id':5094,'name':'OKCoin Leek Harvester FMZ port', 'source':spec['source_url'],
         'market':'Binance spot BTC/USDT','period':'2019-09-01 00:00–22:00 UTC (alternative date)',
         'group':'FMZ exact source / '+case['style']['name'],
         'interval':'1h saved chart and 200 ms native callback delay, one-second causal depth samples',
         'exit':'FIFO inventory reductions counted per sell order with executed units. Remaining BTC marked at observed bid.',
         'currency':'USDT','quote_currency':'USDT','currency_decimal_places':8,
         'gross':gross,'fees':closed_fees,'after_fees':gross-closed_fees,'net':sum(net_list),'funding':ZERO,'execution':ZERO,
         'gross_dd':gross_dd,'gross_dd_pct':gross_pct,'fee_dd':net_dd,'fee_dd_pct':net_pct,'net_dd':net_dd,'net_dd_pct':net_pct,
         'gross_wins':sum(x>0 for x in gross_list),'fee_wins':sum(x>0 for x in net_list),'net_wins':sum(x>0 for x in net_list),
         'trades':len(net_list),'unsettled':int(holdings>0),'remaining_unrealized':D(holdings*case['bidCents'])/DENOM-old_basis,
         'starting_equity':seed,'mark_to_market_net':tail-seed,'marked_dd':mark_abs,'marked_dd_pct':mark_ratio,
         'filled_all_fees':spent,'unallocated_open_fees':old_fees}
    details={'style':case['style'],'source_calls':case['counts'],'order_count':len(pending),'cancellations':count_cancels,
             'recorded_depth_slices':count_depth,'modeled_maker_fills':count_maker,'unique_official_raw_ids':len(seen),
             'signed_trade_ids_sha256':sha(json.dumps(sorted(seen)).encode()),'terminal_cash_USDT':str(available),
             'terminal_quantity_BTC':str(D(holdings)/BTC),'marked_reconciliation_count':len(values),
             'maximum_liquidity_snapshot_age_ms':case['maxQuoteAge']/1000}
    return row,details


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('input','receipt','repeat','worker','abi','abi-code','stage','output'):
        p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    raw=a.input.read_bytes();receipt=a.receipt.read_bytes()
    assert receipt==a.repeat.read_bytes()
    spec=json.loads(gzip.decompress(raw)); result=json.loads(gzip.decompress(receipt));abi=a.abi.read_bytes()
    assert result['input_sha256']==sha(raw) and result['worker_sha256']==sha(a.worker.read_bytes())
    assert result['native_abi_sha256']==sha(abi) and sha(spec['source'].encode())==spec['source_sha256']
    api=json.loads(abi)
    assert (api['deposit']['Balance'],api['deposit']['Stocks'])==(10_000,3)
    assert result['engine_sha256']==api['engine_sha256']
    assert all(r['after']-r['t']==200 for r in api['reads'])
    witnesses={j for c in result['results'] for e in c['trace'] if e[0]=='fill' and e[6]=='maker' for j,_ in e[7]}
    wanted={row[3]:row for row in spec['tape'] if row[3] in witnesses}
    assert wanted.keys()==witnesses
    official=check_official(wanted)
    details=[audit(case,spec,wanted) for case in result['results']]
    primary,strict,fee=[r for r,_ in details]
    report={'coverage':[[5094,'Tested \u00b7 recorded Binance spot alternative day',
                         'Unchanged active source on an authenticated 22-hour same-venue BTCUSDT alternative date. The source-saved Sept 5 depth is unavailable without licensed data and is outside verified coverage.']],
            'results':[primary,fee],'strict_double_volume_sensitivity':[strict],
            'diagnostics':[d for _,d in details],'official_binance_witness_binding':official,'market_data':spec['data'],
            'source':{'archive_sha256':spec['archive_sha256'],'source_sha256':spec['source_sha256'],'source_url':spec['source_url'],
                      'publisher':'https://www.fmz.com/strategy/34388','saved_source_dataset_date':spec['saved_date'],
                      'recorded_replay_alternative_date':spec['recorded_alternate_date'],'source_arguments':spec['args'],
                      'saved_exchange':spec['settings'],'official_native_default_balances':api['deposit']},
            'provenance':{'repeated_runtime_receipt_sha256':sha(receipt),'native_abi_sha256':sha(abi),
                          'worker_sha256':sha(a.worker.read_bytes()),'abi_code_sha256':sha(a.abi_code.read_bytes()),
                          'stage_sha256':sha(a.stage.read_bytes()),'data_input_sha256':sha(raw),
                          'independent_verifier_sha256':sha(Path(__file__).read_bytes())},
            'scope':{'sample':'The documented Tardis first-of-month free dataset covers September 1 with causal L2 and trade IDs. Its September 5 requests return HTTP 401, while FMZ public one-second history returned an empty real tick series. The BTC/USDT spot market, source-authored 22h timeframe and durations are faithfully retained on the explicitly alternate UTC date.',
                     'simulation':'The replay retains the archived author parameters and official engine default wallet of 3 BTC plus 10,000 USDT. Account operations advance 200 ms. Resting maker fills are full-size counterfactual fills with strictly beyond-limit aggressor-volume witnesses before cancellation. Marketable parts use recorded depth at pricing and quantity supported by the chosen book. The 2x threshold reruns all decisions independently.',
                     'costs':'The zero-fee baseline preserves the archived settings. A separate actual-fee schedule sensitivity applies 0.1% per side in quote equivalent, keeping market data fixed while allowing different cash and source decisions. Zero futures funding applies to spot. Initial inherited BTC is booked at the initial observed bid for FIFO P&L attribution.',
                     'metrics':'Count sell orders with executed lots, including reductions from seeded BTC and partial reductions. Inventory is marked at the latest recorded best bid. Marked and closed drawdowns are explicit fractional ratios. Portfolio equity is marked when a sampled bid or position cashflow changes. Same asset and date remain one market scope.'},
            'references':['https://www.fmz.com/strategy/34388','https://docs.tardis.dev/historical-data-details/binance',
                          'https://github.com/binance/binance-public-data','https://www.binance.com/en/support/announcement/detail/360033002011']}
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=float)+'\n',encoding='utf-8',newline='\n')
    print([(r['group'],r['trades'],r['net'],r['mark_to_market_net'],r['marked_dd_pct']) for r,_ in details], sha(a.output.read_bytes()),flush=True)


if __name__=='__main__':main()
