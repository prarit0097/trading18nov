"""Reconcile #3717's complete native simulated-tick month and matched calendar day."""
import argparse
from collections import Counter
from decimal import Decimal as D
import gzip
import json
from pathlib import Path

from fmz_native_round20_880_capture import sha

INITIAL=D(1_000_000)


def close(a,b):
    assert abs(D(str(a))-D(str(b)))<D('0.0000005'),(a,b)


def read(path):
    raw=path.read_bytes()
    return json.loads(gzip.decompress(raw)),sha(raw)


def decode_snapshot(row):
    t,[snap]=row
    assert snap['Id']=='Binance' and snap['BaseCurrency']=='BTC' and snap['QuoteCurrency']=='USDT'
    assets={x['Currency']:x for x in snap['Assets']}
    assert set(assets)<= {'BTC','USDT'} and 'USDT' in assets
    btc=assets.get('BTC',{'Amount':0,'FrozenAmount':0,'Commission':0,'Initial':0})
    quote=assets['USDT']
    assert all(D(str(a[k]))>=0 for a in (btc,quote) for k in ('Amount','FrozenAmount','Commission'))
    assert btc['Initial']==0 and quote['Initial']==float(INITIAL) and btc['Commission']==0
    symbol=snap['Symbols']['BTC_USDT']
    balance=D(str(quote['Amount']))+D(str(quote['FrozenAmount']))
    inventory=D(str(btc['Amount']))+D(str(btc['FrozenAmount']))
    mark=D(str(symbol['Last']))
    assert mark>0
    stats=symbol['TradeStatus']
    close(inventory,D(str(stats['BuyDealAmount']))-D(str(stats['SellDealAmount'])))
    equity=balance+inventory*mark
    close(equity-INITIAL,snap['PnL'])
    return {'timestamp_ms':t,'cash_USDT':str(balance),'BTC':str(inventory),'mark_USDT':str(mark),
            'equity_USDT':str(equity),'cumulative_fees_USDT':str(quote['Commission']),
            'buy_order_count':stats['BuyOrderCount'],'sell_order_count':stats['SellOrderCount']}


def reconcile(receipt,spec,stride):
    assert receipt['outcome']=='end_of_backtest' and receipt['reason']=='StopError'
    ref=receipt['report']
    assert ref['Progress']==100 and ref['Finished'] and ref['TaskStatus']==1 and ref['Status']==''
    t0,t1=receipt['begin']*1000,receipt['end']*1000
    assert ref['Time']==t1
    native=ref['Task']; options=native['Options']; [venue]=native['Exchanges']
    assert options['NetDelay']==200 and options['Period']==60_000 and venue['BasePeriod']==60_000
    assert (venue['FeeMaker'],venue['FeeTaker'],venue['FeeDenominator'])==(600,750,6)
    assert native['Options']['SnapshotPeriod']==stride
    assert 1000*options['TimeBegin']==t0 and 1000*options['TimeEnd']==t1
    assert t0==spec['begin']*1000 and venue['Balance']==float(INITIAL) and venue['Stocks']==0
    assert ref['LogsCount']==len(ref['RuntimeLogs'])==receipt['counts']['buy']+receipt['counts']['sell']
    orders=[q for q in receipt['tape'] if q[0]=='order']
    assert len(orders)==ref['LogsCount']
    census=Counter(q[2] for q in orders)
    for row,log in zip(orders,ref['RuntimeLogs'],strict=True):
        _,at,act,limit,qty,order=row
        assert (at,order)==(log[1],log[4]) and log[2]==int(act=='sell')
        assert (log[5],log[6])==(0 if limit==-1 else limit,qty)
    assert all(t0<=x[1]<=t1 for x in receipt['tape'])
    pause_start,pause_end=(k*1000 for k in spec['proof']['maintenance_utc_unix_s'])
    assert not any(pause_start<=q[1]<pause_end for q in orders)
    original=[decode_snapshot(q) for q in ref['Snapshots']]
    observed=[q['timestamp_ms'] for q in original]
    nominal=list(range(t0,t1+1,stride))
    assert all(x in nominal for x in observed) and observed==sorted(set(observed))
    assert observed[0]==t0 and observed[-1]==t1
    missing=sorted(set(nominal)-set(observed))
    assert all(pause_start<=q<=pause_end for q in missing),missing
    tail=original[-1]
    assert census['buy']==tail['buy_order_count'] and census['sell']==tail['sell_order_count']
    fees=[D(q['cumulative_fees_USDT']) for q in original]
    assert fees==sorted(fees) and fees[0]==0
    cash=D(tail['equity_USDT'])
    initial=D(original[0]['equity_USDT'])
    close(initial,INITIAL)
    peak=initial
    drawdown=pct=D(0)
    for row in original:
        e=D(row['equity_USDT'])
        peak=max(e,peak)
        drawdown=max(drawdown,peak-e)
        pct=max(pct,(peak-e)/peak)
    value={'begins_ms':t0,'ends_ms':t1,'snapshot_count':len(original),'snapshot_spacing_ms':stride,
           'missing_snapshot_times_during_official_maintenance_ms':missing,'terminal_equity_USDT':str(cash),
           'marked_net_USDT':str(cash-initial),'marked_gross_on_executed_path_USDT':str(cash-initial+fees[-1]),
           'fees_paid_USDT':str(fees[-1]),'sampled_drawdown_USDT':str(drawdown),'sampled_drawdown_ratio':str(pct),
           'ending_BTC':tail['BTC'],'ending_mark_USDT':tail['mark_USDT'],'source_buy_orders':census['buy'],
           'source_sell_orders':census['sell'],'market_buy_orders':receipt['counts']['market_order'],
           'market_data_files':receipt['offline_requests']}
    return value,original


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('input','minute','hourly','first-day','recorded','stage','worker','output'):
        p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    spec,input_sha=read(a.input)
    minute,minute_sha=read(a.minute)
    hourly,hourly_sha=read(a.hourly)
    day,day_sha=read(a.first_day)
    worker_sha=sha(a.worker.read_bytes())
    assert sha(spec['script'].encode())==spec['script_sha256']
    assert input_sha==minute['input_sha256']==hourly['input_sha256']==day['input_sha256']
    assert hourly['worker_sha256']==day['worker_sha256']==worker_sha
    assert minute['tape']==hourly['tape'] and minute['counts']==hourly['counts']
    assert minute['report']['RuntimeLogs']==hourly['report']['RuntimeLogs']
    assert minute['report']['Snapshots'][-1]==hourly['report']['Snapshots'][-1]
    late={k:nextvalue for k,nextvalue in minute['report']['Snapshots']}
    both={k for k,nextvalue in hourly['report']['Snapshots'] if k in late}
    assert len(both)>10
    for k,nextvalue in hourly['report']['Snapshots']:
        if k in both:assert nextvalue==late[k]
    month,month_path=reconcile(hourly,spec,3_600_000)
    same_day,day_path=reconcile(day,spec,120_000)
    assert (month['ends_ms']-month['begins_ms'])//86_400_000==31
    assert (same_day['ends_ms']-same_day['begins_ms'])==86_400_000
    recorded_file=a.recorded.read_bytes()
    approved=json.loads(recorded_file)['results'][0]
    assert approved['id']==3717 and approved['period']=='2021-08-01 UTC'
    matched={'native_simulated_marked_net_USDT':same_day['marked_net_USDT'],
             'recorded_depth_model_marked_net_USDT':str(approved['mark_to_market_net'])}
    compared=D(matched['native_simulated_marked_net_USDT'])-D(matched['recorded_depth_model_marked_net_USDT'])
    matched['modeled_difference_USDT']=str(compared)
    data={'coverage':[],'results':[],'schema':'Native FMZ simulated tick research supplement / provenance and marked P&L',
          'id':3717,'comparison':matched,'original_saved_month_simulated_ticks':month,'matched_launch_day_simulated_ticks':same_day,
          'monthly_hourly_mark_path':month_path,'launch_day_two_minute_mark_path':day_path,
          'data':spec['proof'],'published_source':spec['source_url'],'source_sha256':spec['script_sha256'],
          'source_config':spec['settings'],'source_parameters':spec['params'],
          'verification':{'input_sha256':input_sha,'original_full_minute_capture_sha256':minute_sha,
                          'full_hourly_capture_sha256':hourly_sha,'launch_day_capture_sha256':day_sha,
                          'recorded_evidence_sha256':sha(recorded_file),'stage_sha256':sha(a.stage.read_bytes()),
                          'worker_sha256':worker_sha,'verifier_sha256':sha(Path(__file__).read_bytes()),
                          'matched_final_snapshot':True,'identical_full_order_status_and_account_tapes':True,
                          'crosschecked_minute_hourly_tail_snapshots':len(both)},
          'scope':{'month':'Original Aug 2021 Binance BTC/USDT no-leverage saved scope is interpreted as UTC. The isolated official VM simulates ticks and depth from FMZ candles. OHLC is cross-checked against official Binance. The exchange maintenance gap is explicit.',
                   'matched_day':'The 1 August comparison keeps the archived starting wallet, symbol, fees and source. The recorded adapter starts when the first usable book is seen, around six seconds after 00:00 UTC. Observability and fill rules differ.',
                   'metrics':'Marked equity is available plus frozen quote and all BTC valued at the final last price. Before-fee marked P&L adds reported commissions back on the same executed path. The sampled worst drawdown is a lower bound. Both drawdown ratios have fractional units. No win rate or closed-trade P&L can be derived from native aggregate snapshots.',
                   'limits':'These are comparative diagnostic receipts. Real order queue, execution impact and exact native fill-by-fill attribution remain outside this supplement.'},
          'references':['https://www.fmz.com/strategy/316809','https://www.fmz.com/user-guide/backtesting-system/backtest-modes-and-order-matching',
                        'https://github.com/binance/binance-public-data',spec['proof']['maintenance_notice'],spec['proof']['maintenance_complete_notice']]}
    a.output.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print({name:{k:row[k] for k in ('snapshot_count','marked_net_USDT','fees_paid_USDT','sampled_drawdown_ratio')} for name,row in (('month',month),('matched day',same_day))},sha(a.output.read_bytes()))


if __name__=='__main__':
    main()
