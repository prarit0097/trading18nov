"""Verify the legacy OKCoin Dual Thrust inverse fills and marked equity."""
import argparse
from bisect import bisect_right
from decimal import Decimal as D
import gzip
import json
from pathlib import Path

from fmz_native_round20_880_capture import sha
from verify_r51_4850_quarter import INITIAL, ZERO, RATE, VALUE, LEV, HOUR, close, curve, relative_pnl


def market_proof(t,price,bars,clocks):
    k=bisect_right(clocks,t)-1
    assert k>=0
    return any(D(r[3])/100-D('.01')<=price<=D(r[2])/100+D('.01') for r in bars[max(0,k-1):k+1])


def observation(packet,market):
    bars=market['data']
    clocks=[r[0] for r in bars]
    events=[]
    for issued,side,direction,requested,qty,native_id in packet['orders']:
        [observed]=packet['order_observations'][str(native_id)]
        seen,order,flags=observed
        assert order['Time']==issued and order['Id']==native_id
        assert flags[0]==order['Status']==1 and flags[2]==order['DealAmount']==qty==1
        assert order['ContractType']=='this_week' and order['Symbol']=='BTC_USD.this_week'
        assert order['Type']==int(side=='sell') and order['Offset']==int(direction.startswith('close'))
        assert issued<seen
        p=D(str(order['AvgPrice']))
        assert (p<D(str(order['Price']))) if side=='buy' else p>D(str(order['Price']))
        assert market_proof(issued,p,bars,clocks)
        events.append((issued,native_id,direction,qty,p))
    assert len(events)==len(packet['order_observations'])
    return events


def audit(fill,job):
    history=job['market']['data']
    timestamps=[r[0] for r in history]
    opens=[r for r in fill['first_records'] if r['Time']+HOUR<=job['begin_ms']]
    assert len(opens)==6 and {r['Time']%HOUR for r in fill['first_records']}=={0}
    hourly={}
    for r in history:
        ms=r[0]; bucket=ms//HOUR*HOUR
        if bucket not in hourly:hourly[bucket]=[r[1],r[2],r[3],r[4],1]
        else:
            old=hourly[bucket];hourly[bucket]=[old[0],max(old[1],r[2]),min(old[2],r[3]),r[4],old[4]+1]
    verified_warm=0
    for r in opens:
        values=hourly[r['Time']]
        assert 1<=values[-1]<=60
        verified_warm+=1
        for a,b in zip((r[k] for k in ('Open','High','Low','Close')),values[:4],strict=True):close(a,D(b)/100)
    assert verified_warm==6
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
    for row in fill['snapshots']:
        t,[snapshot]=row
        assert snapshot['Id']=='Futures_OKCoin' and snapshot['MarginCurrency']=='BTC'
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
        status=snapshot['Symbols']['BTC_USD.this_week']
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
        quote_tick=D('.01')
        permitted=max(D('1e-12'),VALUE*sum(shares.values())*quote_tick/(raw-quote_tick)**2)
        largest_mark_residual=max(largest_mark_residual,abs(D(str(snapshot['PnL']))-(equity-INITIAL)))
        close(snapshot['PnL'],equity-INITIAL,permitted)
        marked.append(equity)
        headroom.append(equity-margin)
    assert native_clock==list(range(job['begin_ms'],job['end_ms']+300_000,300_000))
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
    outcome={'id':1116,'name':'Python Dual Thrust on legacy OKCoin weekly',
             'market':'OKEX dated BTC-USD-190906 inverse current-week',
             'period':'2019-09-01 06:00–22:00 UTC','interval':'1h decision bars and 1m FMZ simulated subticks',
             'source':job['source_url'],'group':'Original Python / dated OKCoin weekly',
             'exit':'Native Dual Thrust reversals and terminal remaining BTC inverse inventory.',
             'currency':'BTC','quote_currency':'BTC','currency_decimal_places':10,'starting_equity':INITIAL,
             'gross':sum(gross),'fees':settled_fees,'after_fees':sum(net),'net':sum(net),'execution':ZERO,'funding':ZERO,
             'gross_dd':gdd,'gross_dd_pct':gp,'fee_dd':ndd,'fee_dd_pct':np,'net_dd':ndd,'net_dd_pct':np,
             'gross_wins':sum(x>0 for x in gross),'fee_wins':sum(x>0 for x in net),'net_wins':sum(x>0 for x in net),'trades':len(net),
             'unsettled':sum(q>0 for q in shares.values()),'mark_to_market_net':marked[-1]-INITIAL,'remaining_unrealized':unsettled,
             'marked_dd':mdd,'marked_dd_pct':mp,'all_fees':charged}
    detail={'closing_reductions':len(net),'native_orders':len(executed),'portfolio_snapshot_count':len(marked),
            'matching_closed_prior_hourly_bars_count':verified_warm,'min_5m_observed_headroom_BTC':min(headroom),
            'ending_contracts':shares,'ending_coin_equity_BTC':str(marked[-1]),'receipts':witnesses,
            'maximum_native_aggregate_display_residual_BTC':str(largest_mark_residual),
            'five_minute_portfolio_marks':[[k,str(v)] for k,v in zip(native_clock,marked,strict=True)]}
    return outcome,detail


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for x in ('input','first','repeat','worker','stage','output'):
        p.add_argument('--'+x,type=Path,required=True)
    a=p.parse_args()
    raw=a.input.read_bytes();original=a.first.read_bytes();other=a.repeat.read_bytes()
    data,run,control=[json.loads(gzip.decompress(x)) for x in (raw,original,other)]
    assert sha(raw)==run['input_sha256']==control['input_sha256']
    assert sha(data['script'].encode())==data['source_sha256']
    assert sha(a.worker.read_bytes())==run['worker_sha256']==control['worker_sha256']
    assert run['engine_sha256']=='504c312b9b4b410e84c9812298964becc7ae669f253fa0790480330661b212c0'
    assert run['ending_ms']==data['end_ms'] and run['outcome']=='finished'
    first_requests=run.pop('market_request_receipts')
    repeat_requests=control.pop('market_request_receipts')
    assert first_requests and all(x[0]=='Futures_OKCoin' for x in first_requests)
    assert repeat_requests in (first_requests,[])
    assert run==control
    [contract]=run['native_market_choice'];assert contract['InstrumentID']==data['named_market']=='BTC-USD-190906'
    assert contract['LotTick']==1 and contract['PriceTick']==.01 and contract['VolumeMultiple']==100
    assert len(run['rate_proof'])==1 and run['rate_proof'][0][2]==1
    assert data['params']=={'NPeriod':4,'Ks':.5,'Kx':.5,'AmountOP':1,'Interval':2000,'LoopInterval':3,
                            'PeriodShow':500,'ContractTypeIdx':0,'MarginLevelIdx':0}
    metrics,audit_trail=audit(run,data)
    r={'coverage':[[1116,'Tested \u00b7 authored Python Dual Thrust on legacy weekly BTC',
               'A named dated legacy current-week BTC contract runs the original Python code with verified published defaults. The author omitted calendar and starting wallet. This selected native scenario is independent of the old generic rolled q symbols.']],
       'results':[metrics],'diagnostics':audit_trail,
       'source':{'url':data['source_url'],'publisher':data['publisher'],'github_archive_sha256':data['archive_sha256'],
                 'python_sha256':data['source_sha256'],'publisher_form_sha256':data['publisher_snapshot_sha256'],'parameters':data['params']},
       'venue':data['trade_proof'],
       'proof':{'alias_bound_to_named_contract':contract,'input_sha256':sha(raw),'original_run_sha256':sha(original),
                'repeat_run_sha256':sha(other),'matched_financial_and_execution_state_excluding_optional_local_cache_fetch':True,
                'first_offline_data_fetch':first_requests,'repeat_feed_fetch':repeat_requests,
                'runtime_expected_engine_sha256':run['engine_sha256'],'worker_sha256':run['worker_sha256'],
                'stage_sha256':sha(a.stage.read_bytes()),'verifier_sha256':sha(Path(__file__).read_bytes())},
       'scope':{'data':'Actual OKEX BTC-USD-190906 recorded signed prints produce 1-minute historical OHLC. All 54 empty minute buckets remain absent. Six market hours warm the source’s four-bar range, then 06:00–22:00 runs with a flat 0.1 BTC wallet. Both calendar and wallet are explicit scenario choices.',
                'execution':'Native FMZ generated intraminute subticks and depth approximate the dated contract. Actual published lot, cent increments and 100 USD size are bound. All official native alpha-related actions are retained and all modeled fills settle immediately within their marketable limit. This does not verify real historical L2 queue.',
                'fees':'Use explicit model .02% maker/.05% taker; actual model fills all pay taker, with each fee independently reconciled in BTC. The author’s separate informational .03% logger is not the broker statement. No funding applies to this dated-contract model.',
                'risk':'Keep the open terminal inverse holding, recognize closed win rate separately, and use 5-minute observed native marks for sampled drawdown. All settlements and marked values remain denominated in BTC.'},
       'references':[data['publisher'],'https://www.fmz.com/syntax-guide/exchanges/cex/okx',
                     'https://www.okx.com/en-gb/help/expiry-futures','https://docs.tardis.dev/historical-data-details/okex-futures']}
    a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2,default=float)+'\n',encoding='utf-8',newline='\n')
    print({f:metrics[f] for f in ('trades','gross','fees','net','mark_to_market_net','marked_dd_pct')},sha(a.output.read_bytes()),flush=True)


if __name__=='__main__':main()
