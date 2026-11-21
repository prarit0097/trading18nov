"""Verify archived JavaScript Dual Thrust on a dated OKEX inverse BTC scenario."""
import argparse
from decimal import Decimal as D
import gzip
import json
from pathlib import Path

from fmz_native_round20_880_capture import sha
from verify_r52_1116_weekly import audit


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('input','first','repeat','control','worker','stage','decimal','output'):
        p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    payload=a.input.read_bytes()
    first=a.first.read_bytes()
    second=a.repeat.read_bytes()
    untouched_raw=a.control.read_bytes()
    job,run,control,untouched=[json.loads(gzip.decompress(x)) for x in (payload,first,second,untouched_raw)]
    assert sha(a.decimal.read_bytes())=='6e99821f8204c5f611b56077e3fce056a1562d22bc341a1f4af01afe7e527d83'
    assert sha(payload)==run['input_sha256']==control['input_sha256']
    assert sha(job['script'].encode())==job['source_sha256']
    assert sha(a.worker.read_bytes())==run['worker_sha256']==control['worker_sha256']
    assert run['engine_sha256']=='10759660cb8d8979176908703326e8e2a83d9f25edc31e11e0b22330f7d3b483'
    result=run.pop('result')
    repeat=control.pop('result')
    bare_result=untouched.pop('result')
    assert untouched.pop('order_observations')=={}
    bare_accounts=untouched.pop('source_account_observations')
    seen_accounts=run['source_account_observations']
    assert [v for _,v in bare_accounts]==[v for _,v in seen_accounts]
    assert [t-u for (t,_),(u,_) in zip(seen_accounts,bare_accounts,strict=True)]==[0,200,200,200,200]
    assert {k:v for k,v in run.items() if k not in ('order_observations','source_account_observations')}==untouched
    assert run==control
    for key in ('Finished','Time','Progress','Snapshots','Profit','Task','Status','BacktestStatus','TaskStatus'):
        assert result[key]==repeat[key]==bare_result[key],key
    assert result['Finished'] and result['Progress']==100 and result['Time']==job['end_ms']
    assert run['ended']==job['end_ms']-800
    assert run['requests'] and all(x[0]=='Futures_OKCoin' and x[4]=='feed' for x in run['requests'])
    [contract]=run['contracts']
    assert contract=={'InstrumentID':'BTC-USD-190906','LotTick':1,'PriceTick':.01,'VolumeMultiple':100}
    assert job['named_market']==contract['InstrumentID']
    assert run['rate']==[['rate',job['begin_ms'],1]]
    outcome,receipts=audit({**run,'snapshots':result['Snapshots']},job)
    outcome.update(id=258,name='Dual Thrust OKCoin weekly (Zero, JavaScript)',
                   group='Original JavaScript / dated OKCoin weekly')
    assert receipts['native_orders']==9 and receipts['closing_reductions']==4
    gross=D(str(outcome['gross']));fees=D(str(outcome['fees']));net=D(str(outcome['net']))
    assert abs(gross-fees-net)<D('1e-18')
    report={'coverage':[[258,'Tested \u00b7 authored JavaScript Dual Thrust on legacy weekly BTC',
                         'Original Zero source and public execution defaults complete an independently reconciled 16-hour dated OKEX BTC native model. Exact selected research window and 1-hour chart are explicit; the publisher describes the daily analogy without providing a reproducible original wallet, calendar or daily trace.']],
            'results':[outcome],'diagnostics':receipts,
            'source':{'url':job['source_url'],'publisher':job['publisher'],'github_archive_sha256':job['archive_sha256'],
                      'javascript_sha256':job['source_sha256'],'publisher_form_sha256':job['publisher_snapshot_sha256'],
                      'parameters':job['params']},
            'venue':job['trade_proof'],
            'proof':{'alias_bound_to_named_contract':contract,'input_sha256':sha(payload),
                     'original_dated_tape_input_sha256':job['proven_input_sha256'],
                     'original_run_sha256':sha(first),'repeat_run_sha256':sha(second),
                     'original_calls_only_control_sha256':sha(untouched_raw),
                     'runtime_expected_engine_sha256':run['engine_sha256'],'worker_sha256':run['worker_sha256'],
                     'stage_sha256':sha(a.stage.read_bytes()),'verifier_sha256':sha(Path(__file__).read_bytes()),
                     'decimal_js_10_6_0_expected_sha256':sha(a.decimal.read_bytes()),
                     'matching_state':'All native order timestamps, fills, start records, portfolio marks and finishing balances match exactly. An additional run without any observational GetOrder calls matches all order timestamps, execution states and 193 portfolio marks. The four post-close logging account reads are 200 ms later with instrumentation, with exactly identical balances. Informational duration counters are excluded.',
                     'offline_data_requests':run['requests']},
            'scope':{'data':'The legacy current-week alias is bound to real dated BTC-USD-190906. The same independently validated 45,240 OKEX signed prints and six hours of complete warm records are used for comparability to the separate Python source. The 54 empty minutes stay absent.',
                     'calendar':'Research interval is 06:00 to 22:00 UTC 2019-09-01 with 0.1 starting BTC, flat. Archived GetRecords() uses an external platform chart period. The study selects 1 hour above 1-minute FMZ native generated subticks. Publisher narrative explains daily bars; this report makes no claim of a daily or expiry-window replay.',
                     'execution':'Original JavaScript is unchanged. FMZ WASM runs official historical simulator; the legacy Decimal method uses decimal.js 10.6.0. Native generator, not the historical order book, determines execution during each minute; all nine marketable limit fills are modeled. Source orchestration and decision logic remain separate from #1116.',
                     'commissions':'Explicit simulated 0.02% maker/0.05% taker. Every executed order takes liquidity. Close fees are both allocated entry plus exit fees, while all-fees includes still-open inventory. Dated simulation config has no funding event.',
                     'risk':'Keep open inventory marked separately from closed metrics; drawdown is sampled at native 5-minute observations in BTC units.'},
            'references':[job['publisher'],'https://github.com/MikeMcl/decimal.js/tree/v10.6.0',
                          'https://www.fmz.com/syntax-guide/exchanges/cex/okx','https://docs.tardis.dev/historical-data-details/okex-futures']}
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=float)+'\n',encoding='utf-8',newline='\n')
    print({k:outcome[k] for k in ('trades','gross_wins','net_wins','gross','fees','net','mark_to_market_net','marked_dd_pct')},
          sha(a.output.read_bytes()),flush=True)


if __name__=='__main__':main()
