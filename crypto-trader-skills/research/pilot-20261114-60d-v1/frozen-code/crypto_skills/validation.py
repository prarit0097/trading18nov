"""Bounded public-history research; frozen chronological selection, never orders."""
import argparse,copy,json,random,time
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from .core import Workspace,SkillError,require,decimal,utc,iso,digest
from .cli import DEFAULT
from .market import _get_json
from .research import backtest,_bars

ROOT=Path(__file__).resolve().parents[1]
SYMBOLS=('BTCUSDT','ETHUSDT','SOLUSDT')
VARIANTS={'baseline':{'lookback':20,'min_rvol':'0'},
          'longer':{'lookback':40,'min_rvol':'0'},
          'volume':{'lookback':20,'min_rvol':'1.5'},
          'longer_volume':{'lookback':40,'min_rvol':'1.5'}}

def code_hash():
    return digest({p.name:digest(p.read_text(encoding='utf-8')) for p in
                   [Path(__file__),ROOT/'crypto_skills/research.py',ROOT/'crypto_skills/trade.py',ROOT/'crypto_skills/core.py']})

def specification(end,days):
    end=utc(end)
    require(end.hour==end.minute==end.second==end.microsecond==0,'End must be a completed UTC day boundary')
    require(type(days) is int and 12<=days<=60 and days%4==0,'Days must be a multiple of4, between12and60')
    require(end<=utc(),'History cannot extend into the future')
    return {'end':iso(end),'start':iso(end-timedelta(days=days)),'days':days,'bars_per_asset':days*288,
            'symbols':list(SYMBOLS),'interval_seconds':300,'variants':VARIANTS,'code_hash':code_hash(),
            'split':'50%train/25%validation/25%test; flat boundaries; forced final liquidation',
            'selection_min_trades':30,'validation_min_trades':20,'test_min_trades':30,
            'bootstrap':{'replays':1000,'block_days':3,'seed':19},
            'config':dict(DEFAULT,venue='binance',initial_cash='10000',risk_budget='25',max_notional='2000',
                          max_total_exposure='4000',max_daily_loss='100')}

def partition(market):
    n=len(market['bars']);require(n>=8 and n%4==0,'History must allow exact chronological halves/quarters')
    parts={}
    for name,start,end in [('train',0,n//2),('validation',n//2,3*n//4),('test',3*n//4,n)]:
        m=copy.deepcopy(market);m['bars']=m['bars'][start:end]
        m['as_of']=iso(utc(m['bars'][-1]['time'])+timedelta(seconds=m['interval_seconds']))
        m['health']=dict(valid=True,gaps=[],closed_bars=len(m['bars']));parts[name]=m
    return parts

def metrics(result):
    m=dict(result['metrics']);trades=result['trades'];n=len(trades)
    pnls=[decimal(t['net_pnl']) for t in trades];wins=sum(p>0 for p in pnls);losses=sum(p<0 for p in pnls)
    positive=sum((p for p in pnls if p>0),Decimal(0));negative=-sum((p for p in pnls if p<0),Decimal(0))
    m.update(win_count=wins,loss_count=losses,flat_count=n-wins-losses,
             win_rate=str(Decimal(wins)/n) if n else None,
             net_expectancy=str(decimal(m['net_pnl'])/n) if n else None,
             profit_factor=str(positive/negative) if negative else None,
             return_fraction=str(decimal(m['net_pnl'])/decimal(m['initial_cash'])),
             entry_turnover=str(sum((decimal(t['entry_price'])*decimal(t['quantity']) for t in trades),Decimal(0))))
    return m

def _mean(results,key):
    return sum((decimal(r['metrics'][key]) for r in results),Decimal(0))/len(results)

def choose(training):
    eligible={k:r for k,r in training.items() if _mean(r,'net_pnl')>0 and sum(x['metrics']['trade_count'] for x in r)>=30}
    pool=eligible or training
    selected=sorted(pool,key=lambda k:(-_mean(pool[k],'net_pnl'),k))[0]
    return {'id':selected,'training_pass':bool(eligible),'training_mean_net':str(_mean(training[selected],'net_pnl'))}

def comparison(candidate,baseline,min_trades):
    return (sum(r['metrics']['trade_count'] for r in candidate)>=min_trades and
            _mean(candidate,'net_pnl')>0 and _mean(candidate,'net_pnl')>_mean(baseline,'net_pnl') and
            _mean(candidate,'max_drawdown_quote')<=_mean(baseline,'max_drawdown_quote'))

def block_interval(series,seed=19):
    values=list(map(decimal,series));require(len(values)>=3,'Need at least3daily observations')
    rng=random.Random(seed);means=[]
    for _ in range(1000):
        sample=[]
        while len(sample)<len(values):
            start=rng.randrange(len(values)-2);sample.extend(values[start:start+3])
        means.append(sum(sample[:len(values)])/len(values))
    means.sort()
    return {'lower':str(means[24]),'upper':str(means[974]),'observations':len(values),'replays':1000,
            'block_days':3,'seed':seed,'quantity':'mean pooled daily realized PnL, independent research accounts',
            'limit':'Conditional short-sample bootstrap, not a future win probability.'}

def reserve_holdout(root,start,end,fingerprint,seen_start=None):
    w=Workspace(root)
    with w.lock():
        data=w.read('registry')['data'] if (w.state/'registry.json').exists() else {'reservations':[]}
        rows=data['reservations']
        reused=any(r['fingerprint']!=fingerprint and start<r['end'] and r.get('seen_start',r['start'])<end for r in rows)
        row={'start':start,'end':end,'fingerprint':fingerprint,'seen_start':seen_start or start}
        if row not in rows:rows.append(row);w.write('registry',data)
        return reused

def promotion(train_ok,val_ok,test,baseline,stress,interval,reused):
    return (train_ok and val_ok and not reused and comparison(test,baseline,30) and
            sum(decimal(r['metrics']['net_pnl'])>0 for r in test)>=2 and
            _mean(stress,'net_pnl')>0 and decimal(interval['lower'])>0)

def completed(workspace,fingerprint,inputs=None):
    if not (workspace.state/'qualification.json').exists():return None
    previous=workspace.read('qualification')
    require(previous['data'].get('fingerprint')==fingerprint,'Completed experiment inputs changed; never retune an inspected holdout')
    if inputs is not None:
        require(all(previous['inputs'].get(k)==v for k,v in inputs.items()),'Completed experiment lineage changed')
    return previous

def download(root,end,days=60):
    w=Workspace(root);spec=specification(end,days)
    with w.lock():
        if (w.state/'experiment_spec.json').exists():
            require(w.read('experiment_spec')['data']==spec,'Pinned experiment specification/code changed')
        else:w.write('experiment_spec',spec)
        for symbol in SYMBOLS:
            kind='history_'+symbol.lower()
            if (w.state/(kind+'.json')).exists():
                cached=w.read(kind)['data'];_bars(cached['market'],cached['config']);continue
            raw=Workspace(w.root/'raw'/symbol)
            if (raw.state/'metadata.json').exists():item=raw.read('metadata')['data']['symbol']
            else:
                info=_get_json('/api/v3/exchangeInfo',{'symbol':symbol})
                require(len(info.get('symbols',[]))==1,'Missing symbol metadata');item=info['symbols'][0]
                require(item.get('symbol')==symbol and item.get('quoteAsset')=='USDT','Metadata identity mismatch')
                raw.write('metadata',{'symbol':item,'captured_at':iso()})
            filters={f['filterType']:f for f in item['filters']}
            meta={'qty_step':filters['LOT_SIZE']['stepSize'],'price_tick':filters['PRICE_FILTER']['tickSize'],
                  'min_notional':filters.get('NOTIONAL',filters.get('MIN_NOTIONAL',{}))['minNotional']}
            cfg=dict(spec['config'],symbol=symbol,**meta);bars=[];page_digests=[]
            start_ms=int(utc(spec['start']).timestamp())*1000;end_ms=int(utc(spec['end']).timestamp())*1000
            for offset in range(0,spec['bars_per_asset'],1000):
                limit=min(1000,spec['bars_per_asset']-offset)
                request={'symbol':symbol,'interval':'5m','startTime':start_ms+offset*300000,'endTime':end_ms-1,'limit':limit}
                key=f'page-{offset}'
                if (raw.state/(key+'.json')).exists():page=raw.read(key);require(page['data']['request']==request,'Cached request mismatch')
                else:
                    w.write('download_checkpoint',{'status':'requesting','symbol':symbol,'offset':offset,'request':request})
                    rows=_get_json('/api/v3/klines',request)
                    page=raw.write(key,{'request':request,'rows':rows,'captured_at':iso()});time.sleep(.1)
                rows=page['data']['rows'];require(isinstance(rows,list) and len(rows)==limit,'Incomplete historical page')
                for i,row in enumerate(rows):
                    require(isinstance(row,list) and len(row)>=7 and row[0]==request['startTime']+i*300000 and
                            row[6]==row[0]+299999,'Duplicate, gapped or malformed historical candle')
                    bars.append(dict(time=iso(utc('1970-01-01T00:00:00Z')+timedelta(milliseconds=row[0])),
                                     open=row[1],high=row[2],low=row[3],close=row[4],volume=row[5],closed=True))
                page_digests.append(page['digest'])
                print(f'{symbol}: {len(bars)}/{spec["bars_per_asset"]} closed bars',flush=True)
            market={'symbol':symbol,'venue':'binance','product_type':'spot','interval_seconds':300,'as_of':spec['end'],
                    'bars':bars,'metadata':meta,'health':{'valid':True,'gaps':[],'closed_bars':len(bars)},
                    'source':{'mode':'public_rest','base_url':'https://data-api.binance.vision','price_unit':'USDT',
                              'volume_unit':item['baseAsset'],'purpose':'historical research only; no bid/ask execution quote',
                              'metadata_limit':'Current exchange filters; historical changes unavailable.'}}
            _bars(market,cfg)
            w.write(kind,{'market':market,'config':cfg,'bars_sha256':digest(bars),'raw_page_digests':page_digests},
                    inputs={'experiment_spec':w.read('experiment_spec')['digest']})
        w.write('download_checkpoint',{'status':'complete','symbols':list(SYMBOLS),'bars_per_asset':spec['bars_per_asset']})
    return w.read('download_checkpoint')

def _run(market,config,variant):
    return backtest(market,dict(config,**variant))

def _daily(results,market):
    start=utc(market['bars'][0]['time']).date();end=utc(market['as_of']).date();days={}
    while start<end:days[start.isoformat()]=Decimal(0);start+=timedelta(days=1)
    for result in results:
        for t in result['trades']:
            day=utc(t['exit_time']).date().isoformat();days[day]=days.get(day,Decimal(0))+decimal(t['net_pnl'])
    return {k:str(v) for k,v in sorted(days.items())}

def hold_benchmark(market,config):
    first,last=decimal(market['bars'][0]['open']),decimal(market['bars'][-1]['close'])
    fee=decimal(config['fee_rate']);slip=decimal(config['slippage_bps'])/10000
    qty=decimal(config['max_notional'])/(first*(1+slip))
    net=qty*(last*(1-slip)*(1-fee)-first*(1+slip)*(1+fee))
    return {'cash_net_pnl':'0','capped_buy_and_hold_net_pnl':str(net),'notional_cap':config['max_notional'],
            'limits':'Different exposure/time in market; analytical fractional quantity, no tick/lot rounding.'}

def evaluate(root):
    w=Workspace(root)
    with w.lock():
        spec=w.read('experiment_spec');require(spec['data']['code_hash']==code_hash(),'Code changed since precommit')
        histories={s:w.read('history_'+s.lower()) for s in SYMBOLS};parts={};inputs={'experiment_spec':spec['digest']}
        for s,h in histories.items():
            require(h['inputs'].get('experiment_spec')==spec['digest'],'Historical spec lineage changed')
            require(digest(h['data']['market']['bars'])==h['data']['bars_sha256'],'Historical bars hash mismatch')
            _bars(h['data']['market'],h['data']['config']);parts[s]=partition(h['data']['market']);inputs[h['kind']]=h['digest']
        windows=[(p['test']['bars'][0]['time'],p['test']['as_of']) for p in parts.values()];require(len(set(windows))==1,'Asset dates differ')
        fingerprint=digest({'spec':spec['data'],'data':{s:{'bars':h['data']['bars_sha256'],
            'config':h['data']['config'],'metadata':h['data']['market']['metadata'],'source':h['data']['market']['source']}
            for s,h in histories.items()}})
        cached=completed(w,fingerprint,inputs)
        if cached:return cached
        trials={name:[_run(parts[s]['train'],histories[s]['data']['config'],variant) for s in SYMBOLS]
                for name,variant in spec['data']['variants'].items()}
        selected=choose(trials)
        w.write('selection',dict(selected,fingerprint=fingerprint,train_trials={k:[metrics(r) for r in rs] for k,rs in trials.items()}),inputs)
        variant=spec['data']['variants'][selected['id']]
        reused=reserve_holdout(ROOT/'research-registry',windows[0][0],windows[0][1],fingerprint,
                               seen_start=spec['data']['start'])
        output={};full={}
        for split in ('validation','test'):
            candidate=[];baseline=[];stress=[];per_asset={}
            for s in SYMBOLS:
                cfg=histories[s]['data']['config'];m=parts[s][split]
                a=_run(m,cfg,variant);b=_run(m,cfg,VARIANTS['baseline']);candidate.append(a);baseline.append(b)
                per_asset[s]={'candidate':metrics(a),'baseline':metrics(b),'benchmarks':hold_benchmark(m,cfg),
                              'candidate_trades':a['trades'],'baseline_trades':b['trades']}
                if split=='test':
                    stressed=dict(cfg,fee_rate=str(decimal(cfg['fee_rate'])*2),slippage_bps=str(decimal(cfg['slippage_bps'])*2))
                    st=_run(m,stressed,variant);stress.append(st);per_asset[s]['double_cost']=metrics(st)
            full[split]=(candidate,baseline,stress);output[split]=per_asset
        val_ok=comparison(*full['validation'][:2],20)
        daily=_daily(full['test'][0],parts[SYMBOLS[0]]['test']);interval=block_interval(list(daily.values()))
        qualified=promotion(selected['training_pass'],val_ok,*full['test'],interval,reused)
        data={'status':'research_qualified_for_forward_pilot' if qualified else 'rejected','fingerprint':fingerprint,
              'selection':selected,'validation_pass':val_ok,'holdout_reused_exploratory':reused,
              'periods':{k:{'start':p['bars'][0]['time'],'end':p['as_of'],'bars':len(p['bars'])} for k,p in parts[SYMBOLS[0]].items()},
              'results':output,'daily_test_net_pnl':daily,'bootstrap':interval,
              'mean_test_candidate_net':str(_mean(full['test'][0],'net_pnl')),
              'mean_test_baseline_net':str(_mean(full['test'][1],'net_pnl')),
              'mean_test_double_cost_net':str(_mean(full['test'][2],'net_pnl')),
              'live_defaults_changed':False,'orders_submitted':0,
              'limits':['60-day pilot; limited regimes, current filters and analytical bar fills.',
                        'Independent asset accounts are not the shared paper portfolio.',
                        'No spread/depth/queue/partial fill/latency or market-impact qualification.',
                        'Manual execution tests excluded; no claimed calibrated win probability.',
                        'Research qualification permits only a further forward-paper experiment.']}
        return w.write('qualification',data,dict(inputs,selection=w.read('selection')['digest']))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['download','evaluate']);p.add_argument('--workspace',required=True)
    p.add_argument('--end',default='2026-11-14T00:00:00Z');p.add_argument('--days',type=int,default=60);args=p.parse_args()
    try:
        result=download(args.workspace,args.end,args.days) if args.action=='download' else evaluate(args.workspace)
        print(json.dumps(result,ensure_ascii=True));return 0
    except (SkillError,OSError,ValueError,KeyError,TypeError) as exc:
        print(json.dumps({'status':'error','error':str(exc)}));return 2

if __name__=='__main__':raise SystemExit(main())
