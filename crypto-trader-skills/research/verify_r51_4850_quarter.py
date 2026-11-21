"""Independently reconstitute the verified inverse quarterly Turtle wallet."""
import argparse
from bisect import bisect_right
from decimal import Decimal as D
import gzip
import json
from pathlib import Path

from fmz_native_round20_880_capture import sha
from verify_r48_4427_hedge import curve, relative_pnl

INITIAL=D('.1')
ZERO=D(0)
RATE=D('.0005')
VALUE=D(100)
LEV=D(10)
HOUR=3_600_000
DAY=24*HOUR


def close(left,right,tol=D('1e-12')):
    assert abs(D(str(left))-D(str(right)))<=tol,(left,right)


def market_proof(t,price,hours,at):
    j=bisect_right(at,t)-1
    assert j>=0
    values=hours[max(0,j-1):j+1]
    return any(D(h[3])/10-D('.1')<=price<=D(h[2])/10+D('.1') for h in values)


def observation(fill_orders,market):
    notes=[]
    hours=market['data']
    clocks=[r[0] for r in hours]
    for desired,native in zip(fill_orders['orders'],fill_orders['read_fill_events'],strict=True):
        start,issued,method,direction,limit,qty,oid=desired
        check_time,out_id,record=native
        assert oid==out_id==record['Id'] and isinstance(oid,int)
        assert issued==record['Time']<=check_time and start<=issued and qty>0 and qty==int(qty)
        assert record['ContractType']=='quarter' and record['Symbol']=='BTC_USD.quarter'
        assert record['Amount']==record['DealAmount']==qty and record['Status']==1
        assert record['Type']==int(method=='sell') and record['Offset']==int(direction.startswith('close'))
        p=D(str(record['AvgPrice']))
        assert p>0 and p*10==int(p*10)
        assert (p<D(str(record['Price']))) if method=='buy' else p>D(str(record['Price']))
        close(D(str(limit)).quantize(D('.1')),record['Price'],D('.1'))
        assert market_proof(issued,p,hours,clocks)
        notes.append((issued,oid,direction,int(qty),p))
    assert [k[1] for k in notes]==list(range(1,len(notes)+1))
    return notes


def audit(fill,job):
    history=job['market']['data']
    timestamps=[r[0] for r in history]
    opens=[r for r in fill['first_records'] if r['Time']+DAY<=job['begin_ms']]
    assert len(opens)>=55 and {r['Time']%DAY for r in fill['first_records']}=={16*HOUR}
    daily={}
    for r in history:
        ms=r[0]; bucket=(ms+8*HOUR)//DAY*DAY-8*HOUR
        if bucket not in daily:daily[bucket]=[r[1],r[2],r[3],r[4],1]
        else:
            old=daily[bucket];daily[bucket]=[old[0],max(old[1],r[2]),min(old[2],r[3]),r[4],old[4]+1]
    verified_warm=0
    for r in opens:
        values=daily[r['Time']]
        if values[-1]!=24:
            assert r is opens[0] and values[-1]==16
        else:
            verified_warm+=1
        for a,b in zip((r[k] for k in ('Open','High','Low','Close')),values[:4],strict=True):close(a,D(b)/10)
    assert verified_warm>=55
    executed=observation(fill,job['market'])
    shares={'Long':0,'Short':0}
    reciprocal_cost={'Long':ZERO,'Short':ZERO}
    allocated={'Long':ZERO,'Short':ZERO}
    gross_totals={'Long':ZERO,'Short':ZERO}
    charged=ZERO
    reductions=[]
    marked=[]
    witnesses=[]
    headroom=[]
    index=0
    native_clock=[]
    largest_mark_residual=ZERO
    for row in fill['native_snapshots']:
        t,[snapshot]=row
        assert snapshot['Id']=='Futures_Binance' and snapshot['MarginCurrency']=='BTC'
        native_clock.append(t)
        while index<len(executed) and executed[index][0]<=t:
            ts,oid,direction,q,p=executed[index]
            paid=RATE*VALUE*q/p
            charged+=paid
            leg='Long' if direction in ('buy','closebuy') else 'Short'
            if direction.startswith('close'):
                assert shares[leg]>=q
                fraction=D(q)/shares[leg]
                cost=reciprocal_cost[leg]*fraction
                entryfees=allocated[leg]*fraction
                gain=(cost-D(q)/p)*VALUE*(1 if leg=='Long' else -1)
                reductions.append([gain,paid+entryfees]);gross_totals[leg]+=gain
                reciprocal_cost[leg]-=cost
                allocated[leg]-=entryfees
                shares[leg]-=q
                witnesses.append({'timestamp_ms':ts,'id':oid,'side':direction,'quantity':q,'price':str(p),
                                  'gross_realized_BTC':str(gain),'allocated_fees_BTC':str(paid+entryfees)})
            else:
                shares[leg]+=q
                reciprocal_cost[leg]+=D(q)/p
                allocated[leg]+=paid
                witnesses.append({'timestamp_ms':ts,'id':oid,'side':direction,'quantity':q,'price':str(p),'fee_BTC':str(paid)})
            index+=1
        status=snapshot['Symbols']['BTC_USD.quarter']
        raw=D(str(status['Last']))
        assert raw>0 and market_proof(t,raw,history,timestamps)
        unsettled=margin=ZERO
        for tag,k in (('Long',1),('Short',-1)):
            native=status.get(tag,{'Amount':0,'CloseProfit':0,'Profit':0,'Margin':0,'Price':0})
            assert native['Amount']==shares[tag]
            close(native['CloseProfit'],gross_totals[tag])
            unreal=VALUE*(reciprocal_cost[tag]-D(shares[tag])/raw)*k
            unreal=unreal if shares[tag] else ZERO
            locked=reciprocal_cost[tag]*VALUE/LEV
            close(native['Profit'],unreal)
            close(native['Margin'],locked)
            if shares[tag]:close(native['Price'],shares[tag]/reciprocal_cost[tag],D('0.000001'))
            unsettled+=unreal
            margin+=locked
        [balance]=snapshot['Assets']
        assert balance['Currency']=='BTC' and balance['FrozenAmount']==0 and balance['Initial']==float(INITIAL)
        close(balance['Commission'],charged)
        remaining=INITIAL+sum(gross_totals.values())-charged-margin
        close(remaining,balance['Amount'])
        equity=remaining+margin+unsettled
        quote_tick=D('.1')
        permitted=max(D('1e-12'),VALUE*sum(shares.values())*quote_tick/(raw-quote_tick)**2)
        largest_mark_residual=max(largest_mark_residual,abs(D(str(snapshot['PnL']))-(equity-INITIAL)))
        close(snapshot['PnL'],equity-INITIAL,permitted)
        marked.append(equity)
        headroom.append(equity-margin)
    assert native_clock==list(range(job['begin_ms'],job['end_ms']+DAY,DAY))
    assert index==len(executed)
    assert reductions and all(x[1]>0 for x in reductions)
    gross=[a for a,b in reductions];net=[a-b for a,b in reductions]
    settled_fees=sum(x[1] for x in reductions)
    close(sum(gross),sum(gross_totals.values()))
    close(settled_fees+sum(allocated.values()),charged)
    close(sum(net)+unsettled-sum(allocated.values()),marked[-1]-INITIAL)
    gdd,gp=curve(INITIAL,relative_pnl(INITIAL,gross))
    ndd,np=curve(INITIAL,relative_pnl(INITIAL,net))
    mdd,mp=curve(INITIAL,marked)
    outcome={'id':4850,'name':'Turtle with overwritten 55 and 20 day channels',
             'market':'Binance COIN-M BTCUSD_211231, compatible quarter scenario',
             'period':'2021-10-01 to 2021-12-24 UTC','interval':'UTC+8 daily indicators, 1h FMZ simulated subticks',
             'source':job['source']['url'],'group':'Original Python / source-compatible fixed quarter',
             'exit':'Contract reductions in the unchanged Turtle. Keep open quarter inventory marked.',
             'currency':'BTC','quote_currency':'BTC','currency_decimal_places':10,'starting_equity':INITIAL,
             'gross':sum(gross),'fees':settled_fees,'after_fees':sum(net),'net':sum(net),'execution':ZERO,'funding':ZERO,
             'gross_dd':gdd,'gross_dd_pct':gp,'fee_dd':ndd,'fee_dd_pct':np,'net_dd':ndd,'net_dd_pct':np,
             'gross_wins':sum(x>0 for x in gross),'fee_wins':sum(x>0 for x in net),'net_wins':sum(x>0 for x in net),'trades':len(net),
             'unsettled':sum(q>0 for q in shares.values()),'mark_to_market_net':marked[-1]-INITIAL,'remaining_unrealized':unsettled,
             'marked_dd':mdd,'marked_dd_pct':mp,'all_fees':charged}
    detail={'closing_reductions':len(net),'native_orders':len(executed),'days_with_wallet_observations':len(marked),
            'matching_closed_prior_daily_bars_count':verified_warm,'min_daily_observed_headroom_BTC':min(headroom),
            'ending_contracts':shares,'ending_coin_equity_BTC':str(marked[-1]),'receipts':witnesses,
            'maximum_native_aggregate_display_residual_BTC':str(largest_mark_residual),
            'daily_portfolio_marks':[[k,str(v)] for k,v in zip(native_clock,marked,strict=True)]}
    return outcome,detail


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('input','original','fills','repeat','abi','worker','abi-code','stage','output'):
        p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    data=a.input.read_bytes();a0=a.original.read_bytes();a1=a.fills.read_bytes();abi=a.abi.read_bytes()
    assert a1==a.repeat.read_bytes()
    job,original,fills=[json.loads(gzip.decompress(x)) for x in (data,a0,a1)]
    fixture=json.loads(abi)
    assert not original['with_fills'] and fills['with_fills']
    assert sha(data)==fixture['input_sha256']==original['input_sha256']==fills['input_sha256']
    assert sha(a.worker.read_bytes())==original['worker_sha256']==fills['worker_sha256']
    assert job['historical_market_symbol']==fixture['quarter_result']['InstrumentID']=='BTCUSD_211231'
    for k in ('completion','orders','counts','first_records','native_snapshots','final_ms','progress','native_finished','task'):
        assert original[k]==fills[k]
    assert original['completion']=='end_of_backtest' and original['native_finished'] and original['progress']==100
    assert original['final_ms']==job['end_ms']
    outcome,detail=audit(fills,job)
    result={'coverage':[[4850,'Tested \u00b7 source-compatible BTC inverse quarter scenario',
                'Unchanged archive uses the authored indicator and order logic in independently bound native FMZ. Named 100 USD BTC inverse quarterly data and fees reconcile. Venue, capital and calendar are explicitly the selected research case, with no saved author deployment configuration.']],
            'results':[outcome],'diagnostics':detail,
            'source':{**job['source'],'arguments':job['source_defaults'],'scenario':job['assumptions']},
            'sources':job['archive_rows'],
            'verification':{'inverse_quote_abi_sha256':sha(abi),'source_and_data_sha256':sha(data),'original_uninstrumented_run_sha256':sha(a0),
                            'byte_identical_fill_runs_sha256':sha(a1),'worker_sha256':sha(a.worker.read_bytes()),
                            'abi_code_sha256':sha(a.abi_code.read_bytes()),'stage_sha256':sha(a.stage.read_bytes()),
                            'verifier_sha256':sha(Path(__file__).read_bytes()),'engine_sha256':fixture['engine_sha256']},
            'scope':{'source':'Archive selects generic quarter and sizes against BTC coin collateral with USD 100 inverse contracts. Venue/data dates and 0.1 BTC flat wallet are explicit research choices. Author arguments 20/10/20 retained, but entry channel overwrites to 55 and stop threshold overwrites to 20 in the source.',
                     'engine':'Fixed historical instrument BTCUSD_211231. Native calendar bars begin at 16:00 UTC (UTC+8), independently checked against warmed one-hour exchange series. FMZ generates subticks. The normal run and GetOrder receipt run have identical order times, decisions, daily portfolio snapshots and final state.',
                     'accounting':'A separate one-contract roundtrip proves native inverse settlement mechanics. Every authored order has a fully filled marketable receipt and native .05% taker commission confirmed by independent BTC currency ledger. No funding applies to this dated quarterly model. Drawdown columns are ratios; marked drawdown samples daily native marks and is a lower bound versus intraday risk.',
                     'reproducibility':'Exact original source, canonical data, repeat engine runs and independent quote/fee checks. Source results are simulated within one named market; the native quote range proof does not infer actual historical order queue, liquidity or fill timing.'},
            'references':[job['source']['publisher'],'https://www.fmz.com/lang/en/syntax-guide/fun/ta/ta.highest',
                          'https://www.fmz.com/syntax-guide/fun/futures/exchange.setcontracttype',
                          'https://www.binance.com/en-IN/support/faq/detail/85eac2bba0b342819122dc9bd4745e9b',
                          'https://github.com/binance/binance-public-data']}
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=float)+'\n',encoding='utf-8',newline='\n')
    print({k:outcome[k] for k in ('trades','gross','net','mark_to_market_net','marked_dd_pct')},sha(a.output.read_bytes()),flush=True)


if __name__=='__main__':main()
