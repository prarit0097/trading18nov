"""Check #3717's recorded fill witnesses, FIFO settlement and equity independently."""
import argparse
from bisect import bisect_right
from collections import defaultdict, deque
import csv
from decimal import Decimal as D
import gzip
import io
import json
from pathlib import Path
from zipfile import ZipFile

from fmz_native_round20_880_capture import request, sha

CASH=D(1_000_000)
BTC=100_000_000
UNITS=BTC*100
TAKER=D('.00075')
MAKER=D('.0006')
ZERO=D(0)


def official_trades(needed):
    label='BTCUSDT-trades-2021-08-01.zip'
    url=f'https://data.binance.vision/data/spot/daily/trades/BTCUSDT/{label}'
    with request(url+'.CHECKSUM') as response:
        checksum,filename=response.read(200).decode().split()
    assert filename==label
    with request(url) as response:
        raw=response.read(80_000_000)
    assert sha(raw)==checksum
    found={}
    with ZipFile(io.BytesIO(raw)) as z:
        [csv_file]=z.namelist()
        with z.open(csv_file) as f:
            for record in csv.reader(io.TextIOWrapper(f,encoding='utf-8')):
                if not record[0].isdigit():
                    continue
                n=int(record[0])
                if n not in needed:
                    continue
                buy=record[5].lower()=='false'
                assert record[5].lower() in ('true','false') and n not in found
                p,q=D(record[1])*100,D(record[2])*BTC
                assert p==int(p) and q==int(q)
                found[n]=[int(p),int(q),int(buy),int(record[4])]
    assert set(found)==set(needed)
    return {'archive_url':url,'archive_sha256':checksum,'raw_witnesses':len(found)},found


def eq(a,b):
    assert abs(D(str(a))-D(str(b)))<=D('0.00000000001'),(a,b)


def drawdown(values):
    high=CASH
    abyss=ZERO
    ratio=ZERO
    balance=CASH
    for v in values:
        balance+=v
        high=max(high,balance)
        abyss=max(abyss,high-balance)
        ratio=max(ratio,(high-balance)/high)
    return abyss,ratio


def verify_trial(run,spec,official,trades):
    positions={}
    capacities=defaultdict(int)
    print_use=defaultdict(int)
    bids={}
    clocks={}
    snapshots={r[1]:r for r in spec['book']}
    book_clocks=[r[0] for r in spec['book']]
    outcomes=defaultdict(lambda:[ZERO,ZERO])
    inventory=deque()
    fees=ZERO
    gross=ZERO
    realized_fees=ZERO
    cash=CASH
    native_qty=0
    pending=defaultdict(int)
    maker_events=taker_events=0
    fill_events=[]
    witness_ids=set()
    for e in run['trace']:
        kind,t,*fields=e
        assert run['begin']<=t<run['end']
        if kind=='rejected':
            continue
        oid=fields[0]
        if kind=='order':
            _,buy,limit,size=fields
            assert oid not in positions and size>0 and buy in (0,1)
            positions[oid]=(t,buy,limit,D(str(size)))
            pending[oid]=int(D(str(size))*BTC) if limit else 0
            continue
        assert kind=='fill'
        _,buy,q,price,liquidity,witness,received_fee=fields
        placed,side,limit,quote=positions[oid]
        assert buy==side and q>0 and placed<=t
        value=D(price*q)/UNITS
        expected=value*(MAKER if liquidity=='maker' else TAKER)
        eq(received_fee,expected)
        fees+=expected
        if limit:
            assert price<=limit if buy else price>=limit
            pending[oid]-=q
            assert pending[oid]>=0
        if liquidity=='maker':
            maker_events+=1
            assert price==limit and placed<t and sum(x[1] for x in witness)==run['multiple']*q
            evidence=[]
            for number,used in witness:
                venue=official[number]
                event=trades[number]
                assert venue[:3]==event[2:5] and abs(venue[3]*1000-event[5])<1000
                assert placed<event[0]<=t and event[4]==1-buy
                assert event[2]<price if buy else event[2]>price
                print_use[number]+=used
                assert 0<used and print_use[number]<=event[3]
                evidence.append(event)
                witness_ids.add(number)
            assert max(x[0] for x in evidence)==t
            maker_n=max(x[1] for x in evidence if x[0]==t)
            fill_events.append((t,maker_n,oid,buy,q,value,expected))
        else:
            taker_events+=1
            observed,venue,local,prior=witness
            idx=bisect_right(book_clocks,t//1_000_000)-1
            assert observations_agree(spec['book'][idx],snapshots[observed],venue,local,t)
            depth=snapshots[observed][4]
            side_index=0 if buy else 2
            levels=dict(zip(depth[side_index::4],depth[side_index+1::4],strict=True))
            key=(observed,buy,price)
            assert capacities[key]==prior and q+prior<=levels[price]
            capacities[key]+=q
            fill_events.append((t,2**63-1,oid,buy,q,value,expected))
            if not limit:
                bids[oid]=bids.get(oid,ZERO)+value+expected
                assert bids[oid]<=quote
        if buy:
            cash-=value+expected
            native_qty+=q
            inventory.append([q,value,expected])
        else:
            cash+=value-expected
            native_qty-=q
            assert native_qty>=0
            left=q
            pnl=value
            costs=expected
            while left:
                count, basis, paid=inventory.popleft()
                used=min(left,count)
                portion=D(used)/count
                pnl-=basis*portion
                costs+=paid*portion
                left-=used
                if used!=count:
                    inventory.appendleft([count-used,basis*(1-portion),paid*(1-portion)])
            outcomes[oid][0]+=pnl
            outcomes[oid][1]+=costs
            clocks[oid]=t
            gross+=pnl
            realized_fees+=costs
    end_q=run['free_BTC_units']+run['locked_BTC_units']
    end_cash=D(run['available_USDT'])+D(run['frozen_USDT'])
    eq(cash,end_cash)
    assert native_qty==end_q==sum(x[0] for x in inventory)
    assert sum(pending[n] for n,(_,b,p,_) in positions.items() if not b and p)==run['locked_BTC_units']
    eq(sum(D(pending[n]*p)/UNITS*(1+TAKER) for n,(_,b,p,_) in positions.items() if b and p),run['frozen_USDT'])
    ending_mark=D(run['ending_mark_cents']*end_q)/UNITS
    eq(cash+ending_mark,run['marked_USDT'])
    residual_value=sum(x[1] for x in inventory)
    residual_fees=sum(x[2] for x in inventory)
    eq(realized_fees+residual_fees,fees)
    eq(gross-realized_fees+ending_mark-residual_value-residual_fees,cash+ending_mark-CASH)
    through=sorted(outcomes,key=lambda i:(clocks[i],i))
    gross_trades=[outcomes[x][0] for x in through]
    net_trades=[outcomes[x][0]-outcomes[x][1] for x in through]
    gross_dd,gross_dd_pct=drawdown(gross_trades)
    dd,dd_pct=drawdown(net_trades)
    assert len(through)>0
    eq(verify_marked_drawdown(spec['tape'],fill_events),run['marked_drawdown_pct'])
    metrics={'gross':gross,'fees':realized_fees,'after_fees':gross-realized_fees,'execution':ZERO,'funding':ZERO,
             'net':gross-realized_fees,'gross_dd':gross_dd,'gross_dd_pct':gross_dd_pct,
             'fee_dd':dd,'fee_dd_pct':dd_pct,'net_dd':dd,'net_dd_pct':dd_pct,'gross_wins':sum(v>0 for v in gross_trades),
             'fee_wins':sum(v>0 for v in net_trades),'net_wins':sum(v>0 for v in net_trades),'trades':len(through),
             'unsettled':int(end_q>0),'starting_equity':CASH,'mark_to_market_net':cash+ending_mark-CASH,
             'remaining_unrealized':ending_mark-residual_value,'marked_dd_pct':D(run['marked_drawdown_pct'])/100,
             'paid_fees_all':fees,'unallocated_open_fees':residual_fees}
    audit={'witness_multiple':run['multiple'],'closures':len(through),'orders':len(positions),'witnesses':sorted(witness_ids),
           'taker_slices':taker_events,'maker_fills':maker_events,'ending_inventory_BTC':str(D(end_q)/BTC),
           'ending_cash_USDT':str(cash),'frozen_quote_USDT':run['frozen_USDT'],'source_call_counts':run['calls']}
    return metrics,audit


def observations_agree(a,b,venue,local,t):
    return a==b and a[1:4]==[max(venue,local),venue,local] and a[1]<=t<a[1]+4_000_000


def verify_marked_drawdown(tape,fills):
    trades=iter(sorted(fills,key=lambda x:x[:2]))
    next_fill=next(trades,None)
    qty=0
    cash=CASH
    peak=CASH
    dd=ZERO
    prior_price=tape[0][2]
    for event in tape:
        time,ident,mark,*_=event
        while next_fill and next_fill[:2]<(time,ident):
            fill_key=next_fill[:3]
            while next_fill and next_fill[:3]==fill_key:
                _,_,_,buy,q,value,fee=next_fill
                cash+=(value if not buy else -value)-fee
                qty+=q if buy else -q
                next_fill=next(trades,None)
            equity=cash+D(qty*prior_price)/UNITS
            peak=max(peak,equity)
            dd=max(dd,(peak-equity)/peak)
        while next_fill and next_fill[:2]==(time,ident):
            _,_,_,buy,q,value,fee=next_fill
            cash+=(value if not buy else -value)-fee
            qty+=q if buy else -q
            next_fill=next(trades,None)
        equity=cash+D(qty*mark)/UNITS
        peak=max(peak,equity)
        dd=max(dd,(peak-equity)/peak)
        prior_price=mark
    while next_fill:
        fill_key=next_fill[:3]
        while next_fill and next_fill[:3]==fill_key:
            _,_,_,buy,q,value,fee=next_fill
            cash+=(value if not buy else -value)-fee
            qty+=q if buy else -q
            next_fill=next(trades,None)
        equity=cash+D(qty*prior_price)/UNITS
        peak=max(peak,equity)
        dd=max(dd,(peak-equity)/peak)
    return dd*100


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('input','receipt','repeat','abi','worker','stage','output'):
        p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    raw=a.input.read_bytes()
    native=a.receipt.read_bytes()
    assert native==a.repeat.read_bytes()
    spec=json.loads(gzip.decompress(raw))
    result=json.loads(gzip.decompress(native))
    assert result['input_sha256']==sha(raw) and result['worker_sha256']==sha(a.worker.read_bytes())
    assert sha(spec['script'].encode())==spec['script_sha256']
    ids={num for r in result['results'] for e in r['trace'] if e[0]=='fill' and e[6]=='maker' for num,used in e[7]}
    assert ids
    check,official=official_trades(ids)
    trades={row[1]:row for row in spec['tape'] if row[1] in ids}
    assert set(trades)==ids
    outcomes=[]
    details=[]
    for run in result['results']:
        value,audit=verify_trial(run,spec,official,trades)
        value.update(id=3717,name='Basic grid trading strategy',market='Binance spot BTC/USDT',period='2021-08-01 UTC',
            source=spec['source_url'], group=f'FMZ archived source / observed spot depth, strict through {run["multiple"]}x',
            interval='1m archive, 200ms API delay, one-second depth observations',
            exit='Spot sale proceeds matched to FIFO purchases. Remaining BTC marked at last eligible venue print.',
            currency='USDT',quote_currency='USDT',currency_decimal_places=8)
        outcomes.append(value)
        details.append(audit)
    report={'coverage':[[3717,'Tested \u00b7 verified recorded Binance spot launch day',
             'Unmodified archived Python and saved spot settings ran on the recorded launch day. Verified fills use causal top-25 displayed depth or strict signed print model. The observed month remainder is unavailable in this lane.']],
            'results':outcomes[:1],'strict_double_volume_sensitivity':outcomes[1:],'diagnostics':details,
            'source':{'url':spec['source_url'],'source_sha256':spec['script_sha256'],'archive_sha256':spec['archive_sha256'],
                      'settings':spec['settings'],'parameters':spec['params'],'publisher':'https://www.fmz.com/strategy/316809'},
            'data':{**spec['proof'],'official_spot_witness_binding':check},
            'proof':{'recorded_input_sha256':sha(raw),'repeatable_receipt_sha256':sha(native),
                     'worker_sha256':sha(a.worker.read_bytes()),'stage_sha256':sha(a.stage.read_bytes()),
                     'native_abi_sha256':sha(a.abi.read_bytes()),'verifier_sha256':sha(Path(__file__).read_bytes())},
            'method':{'scope':'Actual top-25 Binance spot launch-day data, fixed UTC interpretation of archived dates. The recorded model starts at the first causally available book around 00:00:06. The archive only specifies BTC; adding ETH is a changed strategy configuration.',
                      'execution':'Displayed depth with per-snapshot consumed-size accounting, market buy sized in quote currency including taker fee. Living orders match only opposite aggressive volume printed strictly through their limits, with no repeated allocation of the same observed volume. Queue fills are counterfactual. Use 2x requirement as sensitivity, not additional independent evidence.',
                      'valuation':'Fees .06% maker, .075% taker from the archived backtest. FIFO allocations assign buy/sell fees to closed trades. Open BTC and its costs remain in the mark. Modeled prices already incorporate depth and price impact. Spot has no funding. Equity drawdown is marked at every recorded print. Drawdown percentage fields store decimal fractions.',
                      'limitations':'We do not know the native order queue, hidden depth or historical counterfactual market impact. No order is placed on a real or demo venue.'},
            'references':['https://www.fmz.com/strategy/316809','https://www.fmz.com/syntax-guide/fun/trade/exchange.buy',
                          'https://www.fmz.com/user-guide/backtesting-system/backtest-configuration-and-saving',
                          'https://github.com/binance/binance-public-data','https://docs.tardis.dev/downloadable-csv-files/data-types']}
    serializer=lambda x:float(x) if isinstance(x,D) else str(x)
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=serializer)+'\n',encoding='utf-8',newline='\n')
    print([(v['trades'],v['gross'],v['net'],v['mark_to_market_net']) for v in outcomes],sha(a.output.read_bytes()),flush=True)


if __name__=='__main__':
    main()
