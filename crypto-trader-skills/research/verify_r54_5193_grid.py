"""Audit source-configured one-sided grid orders, inverse reserve and zero fills."""
import argparse
from decimal import Decimal as D
import gzip
import json
from pathlib import Path

from fmz_native_round20_880_capture import sha


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for option in ('input','first','repeat','stage','worker','output'):
        parser.add_argument('--'+option,type=Path,required=True)
    a=parser.parse_args()
    raw,first,second=[p.read_bytes() for p in (a.input,a.first,a.repeat)]
    job,run,control=[json.loads(gzip.decompress(x)) for x in (raw,first,second)]
    assert run==control
    assert run['input_sha256']==sha(raw) and run['worker_sha256']==sha(a.worker.read_bytes())
    assert run['engine_sha256']=='10759660cb8d8979176908703326e8e2a83d9f25edc31e11e0b22330f7d3b483'
    assert sha(job['script'].encode())==job['source_sha256']
    [market,contract]=run['contracts'][0]
    assert len(run['contracts'])==1 and market=='this_week' and contract['InstrumentID']==job['named_market']=='BTC-USD-190906'
    assert contract['LotTick']==1 and contract['PriceTick']==.01 and contract['VolumeMultiple']==100
    assert len(run['leverage'])==1 and run['leverage'][0][1:]==[10,True]
    assert run['finish']==job['end_ms'] and len(run['market_fetches'])==1
    assert run['inspected']>2000 and run['commandChecks']>2000
    assert not run['cancellations']
    assert len(run['outstanding'])==2 and run['outstanding'][0][1]==[]
    initial=D(job['initial_wallet_BTC'])
    boundaries=[row for row in job['market']['data'] if job['begin_ms']<=row[0]<=job['end_ms']]
    price_min=D(min(row[3] for row in boundaries))/100
    price_max=D(max(row[2] for row in boundaries))/100
    assert price_min>9000 and price_max<10000
    assert not job['params']['FirstPriceAuto'] and not job['params']['AutoMove']
    assert job['params']['FirstPrice']==100 and job['params']['PriceGrid']==1 and job['params']['AllNum']==10
    reserved=D(0)
    open_order_receipts=[]
    terminal=run['outstanding'][1][1]
    for i,((t,operation,direction,price,size,oid),state) in enumerate(zip(run['orders'],terminal,strict=True)):
        assert (operation,direction,price,size,oid)==('Buy','buy',100-i,1,i+1)
        assert state==[oid,0,0,price,size]
        assert t<run['outstanding'][1][0] and price<price_min
        margin=D(100)/price/10
        fee_reserve=D(100)/price*D('.0005')
        reserved+=margin+fee_reserve
        open_order_receipts.append({'id':oid,'submitted_ms':t,'limit_USD':price,'contracts':size,'dealt_contracts':0,
                                    'initial_margin_BTC':margin,'unspent_taker_reserve_BTC':fee_reserve})
    assert len(open_order_receipts)==10 and initial>reserved
    count=0
    for t,[snapshot] in run['snapshots']:
        assert t==job['begin_ms']+300_000*count
        assert snapshot['Id']=='Futures_OKCoin' and snapshot['MarginCurrency']=='BTC'
        assert snapshot['PnL']==0 and snapshot['Utilization']==0
        [wallet]=snapshot['Assets']
        assert wallet['Initial']==initial and wallet['Commission']==0
        required=reserved if count else D(0)
        assert abs(D(str(wallet['FrozenAmount']))-required)<D('1e-14')
        assert abs(D(str(wallet['Amount']))+D(str(wallet['FrozenAmount']))-initial)<D('1e-14')
        if count:
            state=snapshot['Symbols']['BTC_USD.this_week']
            assert set(state)=={'Last','TradeStatus'}
            assert state['TradeStatus']=={'BuyDealAmount':0,'BuyOrderCount':10,'SellDealAmount':0,'SellOrderCount':0}
        count+=1
    assert count==193
    result={'id':5193,'name':'One-sided grid with fixed legacy weekly default',
            'market':'OKEX dated BTC-USD-190906 inverse current-week','period':'2019-09-01 06:00–22:00 UTC',
            'interval':'1m native history; source polls at 2s plus latency','source':job['source_url'],
            'group':'Original JavaScript / published fixed-price grid',
            'exit':'No simulated fills through the selected horizon, with ten accepted buy orders still unfilled.',
            'currency':'BTC','quote_currency':'BTC','currency_decimal_places':10,'starting_equity':initial,
            'gross':0,'fees':0,'after_fees':0,'net':0,'execution':0,'funding':0,'gross_dd':0,'gross_dd_pct':0,
            'fee_dd':0,'fee_dd_pct':0,'net_dd':0,'net_dd_pct':0,'gross_wins':0,'fee_wins':0,'net_wins':0,'trades':0,
            'unsettled':0,'mark_to_market_net':0,'remaining_unrealized':0,'marked_dd':0,'marked_dd_pct':0,'all_fees':0}
    report={'coverage':[[5193,'Tested \u00b7 verified zero-fill fixed grid on dated BTC',
                         'The unchanged original grid posts ten correctly funded one-contract bids at its exact author defaults. All remain unfilled over the selected market because the lowest recorded trade is far above every limit. No win rate is defined.']],
            'results':[result],
            'source':{'url':job['source_url'],'publisher':job['publisher'],'github_archive_sha256':job['archive_sha256'],
                      'javascript_sha256':job['source_sha256'],'publisher_form_sha256':job['publisher_snapshot_sha256'],
                      'parameters':job['params']},
            'venue':job['trade_proof'],
            'proof':{'input_sha256':sha(raw),'original_market_input_sha256':job['provenance_input_sha256'],
                     'original_run_sha256':sha(first),'repeat_run_sha256':sha(second),'same_receipts_and_portfolio':True,
                     'worker_sha256':run['worker_sha256'],'stage_sha256':sha(a.stage.read_bytes()),
                     'verifier_sha256':sha(Path(__file__).read_bytes()),'engine_sha256':run['engine_sha256'],
                     'exact_native_contract':contract,'selected_market_range_USD':[price_min,price_max],
                     'resting_bid_reserve_at_end_BTC':reserved,'pending_order_count_end':10,
                     'positions_end':0,'snapshot_count':count,'passing_get_orders_calls':run['inspected'],
                     'empty_external_command_checks':run['commandChecks'],'orders':open_order_receipts},
            'scope':{'calendar':'The publisher omits a backtest calendar and account funding. Use an independently verified, preselected 16-hour BTC weekly history. A flat 2 BTC wallet funds the full ladder without changing order size, price or trading parameters.',
                     'execution':'This historical interval has no BTC prints near the original fixed bid ladder of $100 down to $91. FMZ accepts the ten pending orders and no maker fill is simulated. The study stops before any manual command or shutdown-hook intervention. Optional FirstPriceAuto, automatic move, stop and custom limits were disabled by the publisher.',
                     'risk':'The 1.05330949365 BTC entry-order reserve includes 10x initial margin and a 0.05% fee buffer. It remains part of equity and incurs zero actual fees. Drawdown is zero inside the observed scope and win rate is undefined with no closes. The study gives no expectancy for separately configured grids.'},
            'references':[job['publisher'],'https://www.fmz.com/syntax-guide/exchanges/cex/okx',
                          'https://docs.tardis.dev/historical-data-details/okex-futures']}
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=float)+'\n',encoding='utf-8',newline='\n')
    print(count,reserved,price_min,price_max,sha(a.output.read_bytes()),flush=True)


if __name__=='__main__':main()
