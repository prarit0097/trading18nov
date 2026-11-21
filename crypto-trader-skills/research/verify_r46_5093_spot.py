"""Verify independently decoded orders and balances for the archived FMZ Python port."""
import argparse
from bisect import bisect_right
from collections import defaultdict, deque
from decimal import Decimal as D, ROUND_HALF_EVEN
import gzip
import json
from pathlib import Path

from fmz_native_round20_880_capture import sha
from verify_r45_5094_spot import check_official, close, curve, decimals, get_mark_time, relative_pnl

BTC=100_000_000
DENOM=BTC*100
INITIAL_BTC=0
INITIAL_CASH=D(10_000)
ZERO=D(0)


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
    inventory=deque()
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
    row={'id':5093,'name':'OKCoin Leek Harvester Python port', 'source':spec['source_url'],
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
             'maximum_liquidity_snapshot_age_ms':max((w[1]-w[7][0])/1000 for w in case['trace'] if w[0]=='fill' and w[6]=='taker')}
    return row,details


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('market','source-fixture','first','repeat','worker','abi','abi-code','stage','output'):
        p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    market=a.market.read_bytes()
    source=a.source_fixture.read_bytes()
    receipt=a.first.read_bytes()
    assert receipt==a.repeat.read_bytes()
    cfg=json.loads(source)
    raw=json.loads(gzip.decompress(market))
    data=json.loads(gzip.decompress(receipt))
    abi=a.abi.read_bytes()
    control=json.loads(abi)
    assert (control['balance']['Balance'],control['balance']['Stocks'])==(10_000,0)
    assert all(q['after']-q['before']==200 for q in control['events'])
    assert cfg['market_sha256']==sha(market)==data['market_sha256']
    assert sha(cfg['script'].encode())==cfg['source_sha256'] and data['source_fixture_sha256']==sha(source)
    assert data['worker_sha256']==sha(a.worker.read_bytes())
    assert cfg['settings']=={'eid':'Binance','currency':'BTC_USDT','stocks':0,'fee':[0,0]}
    assert cfg['saved_date']=='2019-09-05' and cfg['compared_date']=='2019-09-01'
    raw['source_url']=cfg['source_url']
    picks={j for c in data['results'] for e in c['trace'] if e[0]=='fill' and e[6]=='maker' for j,_ in e[7]}
    witnesses={r[3]:r for r in raw['tape'] if r[3] in picks}
    assert witnesses.keys()==picks
    linked=check_official(witnesses)
    audits=[audit(q,raw,witnesses) for q in data['results']]
    primary,strict,fees=[r for r,_ in audits]
    out={'coverage':[[5093,'Tested \u00b7 recorded Binance spot alternative day, Python port',
              'The later Python implementation, its published flat BTC wallet and its order timing ran on the separate recorded 2019-09-01 market scope. Original 2019-09-05 depth remains beyond coverage.']],
         'results':[primary,fees],'strict_double_volume_sensitivity':[strict],'diagnostics':[s for _,s in audits],
         'source':{'publisher':cfg['publisher'],'url':cfg['source_url'],'source_sha256':cfg['source_sha256'],'archive_sha256':cfg['archive_sha256'],
                   'saved_market_date':cfg['saved_date'],'recorded_comparison_date':cfg['compared_date'],'saved_exchange':cfg['settings'],
                   'saved_arguments':cfg['params'],'initial_virtual_account':control['balance']},
         'market_data':raw['data'],'official_binance_witness_binding':linked,
         'verification':{'market_packet_sha256':sha(market),'source_fixture_sha256':sha(source),'duplicate_receipt_sha256':sha(receipt),
                        'native_python_abi_sha256':sha(abi),'worker_sha256':sha(a.worker.read_bytes()),'stage_sha256':sha(a.stage.read_bytes()),
                        'abi_code_sha256':sha(a.abi_code.read_bytes()),'verifier_sha256':sha(Path(__file__).read_bytes())},
         'scope':{'original_binding':'Unchanged published Python port uses explicitly flat BTC at launch, 10,000 USDT official loader default and a 400 ms trend-order wait. The older JavaScript port #5094 separately defaults to 3 BTC and 200 ms. Both share the same public 22-hour alternative tape, with separate rule paths.',
                  'tape':'Recorded top-25 Books and signed BTC/USDT Spot trades are captured on September 1, within four days of the authored dates. Original September 5 free provider access excluded the needed depth. Delay gates select only causal feed observations. Source API uses tested 200 ms per call and original virtual Clock.',
                  'execution':'Use recorded displayed depth for each marketable slice and strict through-price signed print allocation for passive remainders. Ex post aggressor volume only supports modeled fills. The model cannot verify placement in the historical queue or real market impact. One- and two-order-volume models use identical source rules.',
                  'accounting':'Count FIFO-matched cash outcomes by each sell order with completed quantity. Initial inventory is zero. Pending and available balances are reconciled exactly. Mark-to-market includes open spot inventory. Separate fee scope charges 0.1% per side in quote equivalent and reruns all decisions. Reported drawdown fields are ratios.'},
         'references':[cfg['publisher'],'https://docs.tardis.dev/historical-data-details/binance','https://github.com/binance/binance-public-data',
                     'https://www.binance.com/en/support/announcement/detail/360033002011']}
    a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2,default=float)+'\n',encoding='utf-8',newline='\n')
    print([(r['group'],r['trades'],r['net'],r['mark_to_market_net']) for r,_ in audits],sha(a.output.read_bytes()),flush=True)


if __name__=='__main__':main()
