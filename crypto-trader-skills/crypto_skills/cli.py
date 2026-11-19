"""Common command interface used by the independent skill scripts."""
import argparse,json,sys,copy,html
from pathlib import Path
from .core import Workspace,SkillError,require,read_json,decimal,utc,iso

ROOT=Path(__file__).resolve().parents[1]
DEFAULT={
 'mode':'paper','symbol':'BTCUSDT','venue':'fixture','product_type':'spot','quote_currency':'USDT',
 'initial_cash':'10000','fee_rate':'0.001','slippage_bps':'5','risk_budget':None,
 'max_notional':None,'max_total_exposure':None,'max_daily_loss':None,
 'risk_ttl_seconds':30,'max_market_age_seconds':120,'signal_ttl_seconds':300,
 'qty_step':'0.00001','price_tick':'0.01','min_notional':'5','max_spread_bps':'30',
 'stop_pct':'1','target_r':'2','lookback':20,'min_rvol':'0',
 'source_urls':[],'source_min_interval_seconds':60}

def initialize(args,config=None):
    w=Workspace(args.workspace)
    with w.lock():
        require(not (w.state/'config.json').exists(),'Existing workspace config is preserved; choose a new workspace or intentionally edit a versioned config')
        c=dict(DEFAULT)
        if config is not None:c.update(config)
        elif args.input:
            incoming=read_json(args.input);require(isinstance(incoming,dict),'Config input must be an object');c.update(incoming)
        require(c.get('mode')=='paper','Only paper mode is supported; there is no live order connector')
        require(c.get('product_type') in ('spot','linear_perpetual'),'Unsupported product type')
        require(isinstance(c.get('symbol'),str) and c['symbol'].isalnum(),'Invalid symbol')
        for field in ['initial_cash','fee_rate','slippage_bps','stop_pct','target_r','qty_step','price_tick','min_notional']:
            require(decimal(c[field])>=0,'Config numbers must be nonnegative: '+field)
        require(decimal(c['qty_step'])>0 and decimal(c['price_tick'])>0,'Step and tick must be positive')
        return w.write('config',c,now=args.now)

def status(args):
    w=Workspace(args.workspace);artifacts={}
    for p in sorted(w.state.glob('*.json')):
        try:
            a=w.read(p.stem);stale=[]
            for k,v in a['inputs'].items():
                # Previous journal digests name history, not a current artifact file.
                if p.stem=='ledger' and k=='previous_ledger':continue
                try:
                    if w.read(k)['digest']!=v:stale.append(k)
                except SkillError:stale.append(k)
            artifacts[p.stem]={'digest':a['digest'],'status':a['data'].get('status'),'created_at':a['created_at'],'changed_inputs':stale}
        except SkillError as exc:
            artifacts[p.stem]={'error':str(exc)}
    return {'schema_version':1,'kind':'status','data':{'artifacts':artifacts,'limits':['Status is inspection, not authorization to execute a trade.']}}

def chart(w):
    path=w.root/'chart.svg'
    require(not path.is_symlink(),'Symlink chart output rejected')
    path.unlink(missing_ok=True)
    try:market=w.read('market')['data']
    except SkillError:return None
    if market.get('health',{}).get('valid') is not True:return None
    bars=market.get('bars',[])[-80:]
    if not bars:return None
    vals=[float(decimal(x[k])) for x in bars for k in ('high','low')]
    lo,hi=min(vals),max(vals);span=hi-lo or 1
    y=lambda v:300-(float(decimal(v))-lo)/span*235
    step=900/len(bars);maxvol=max(float(decimal(x['volume'])) for x in bars) or 1
    source=market.get('source',{})
    chunks=['<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="480" viewBox="0 0 1000 480" role="img">',
            '<rect width="1000" height="480" fill="#101820"/>',
            '<text x="35" y="22" fill="white">'+html.escape(str(market.get('symbol'))+' '+str(source.get('mode'))+' — observed candles and base volume; not a forecast')+'</text>',
            '<text x="35" y="43" font-size="12" fill="white">'+html.escape(str(source.get('description','Source: '+str(source.get('base_url',source.get('path','explicit import'))))))+'</text>',
            f'<text x="35" y="61" font-size="12" fill="white">High {hi:g} / Low {lo:g} '+html.escape(str(source.get('price_unit')))+'; last 80 bars</text>']
    for i,b in enumerate(bars):
        x=45+i*step;color='#51c4a8' if decimal(b['close'])>=decimal(b['open']) else '#ee7979'
        chunks.append(f'<line x1="{x:.2f}" x2="{x:.2f}" y1="{y(b["high"]):.2f}" y2="{y(b["low"]):.2f}" stroke="{color}"/>')
        top=min(y(b['open']),y(b['close']));height=max(abs(y(b['open'])-y(b['close'])),1)
        vol=65*float(decimal(b['volume']))/maxvol
        chunks.append(f'<rect x="{x-step*.3:.2f}" y="{top:.2f}" width="{step*.6:.2f}" height="{height:.2f}" fill="{color}"/>')
        chunks.append(f'<rect x="{x-step*.3:.2f}" y="{400-vol:.2f}" width="{step*.6:.2f}" height="{vol:.2f}" fill="{color}"/>')
    chunks+=['<text x="35" y="322" font-size="12" fill="white">Base volume ('+html.escape(str(source.get('volume_unit')))+')</text>',
             '<text x="35" y="428" font-size="12" fill="white">'+html.escape(str(bars[0]['time'])+' to '+str(bars[-1]['time'])+'; interval '+str(market.get('interval_seconds'))+' seconds')+'</text>',
             '<text x="35" y="455" font-size="12" fill="white">Check market.json health and as_of for freshness. Historical or synthetic data is not a live quote.</text>','</svg>']
    path.write_text('\n'.join(chunks),encoding='utf-8');return 'chart.svg'

def report(args):
    w=Workspace(args.workspace);st=status(args)['data'];inputs={k:v['digest'] for k,v in st['artifacts'].items() if 'digest'in v and k!='report'}
    summaries={}
    for k in ['market','news','proposal','plan','sizing','risk','orders','portfolio','backtest','simulation','world','qualification','watcher']:
        try:
            a=w.read(k);summaries[k]=a['data']
        except SkillError:pass
    return w.write('report',{'status':'inspection','artifacts':st['artifacts'],'results':summaries,'chart':chart(w),'limits':['Research/paper outputs; not a profit forecast or a live broker record.','Synthetic agents are not real independent people.','Linear-perpetual execution remains blocked unless margin/funding contracts qualify.']},inputs,now=args.now)

def pipeline(args):
    from . import market,trade
    results=[]
    a=copy.copy(args);a.command='market';results.append(market.run(a))
    for command in ['entry','plan','size','risk']:
        a=copy.copy(args);a.command=command;a.input=None;a.fetch=False
        obj=trade.run(a);results.append(obj)
        if obj['data'].get('status') in ('waiting','blocked','error') or obj['data'].get('approved') is False:
            break
    last=results[-1]['data']
    state=last.get('status','complete')
    if last.get('approved') is False:state='blocked'
    return {'schema_version':1,'kind':'pipeline','data':{'status':state,'stages':results,'note':'No paper submission is implicit; run paper submit separately after inspecting risk.'}}

def demo(args):
    from . import market,news,trade,research
    args=copy.copy(args);args.now='2026-11-17T12:00:00Z'
    initialize(args,read_json(ROOT/'examples/paper-config.json'))
    outputs=[]
    for command,file in [('market','market.json'),('news','news.json')]:
        a=copy.copy(args);a.command=command;a.input=str(ROOT/'examples'/file);a.fetch=False
        outputs.append((market if command=='market' else news).run(a))
    for command in ['entry','plan','size','risk']:
        a=copy.copy(args);a.command=command;outputs.append(trade.run(a))
    for command in ['backtest','simulate','world']:
        a=copy.copy(args);a.command=command;outputs.append(research.run(a))
    a=copy.copy(args);a.command='paper';a.action='submit';outputs.append(trade.run(a))
    a.command='report';outputs.append(report(a))
    return {'schema_version':1,'kind':'demo','data':{'provenance':'synthetic offline fixture, fictional limits, pinned simulated clock','stages':[{'kind':x['kind'],'digest':x.get('digest'),'status':x['data'].get('status')} for x in outputs],'workspace':str(Workspace(args.workspace).root),'live_orders_submitted':0}}

def parser():
    p=argparse.ArgumentParser(description='Connected crypto research skills; paper only, no live order connector.')
    p.add_argument('command',choices=['init','market','news','entry','plan','size','risk','paper','backtest','simulate','world','report','status','pipeline','demo'])
    p.add_argument('action',nargs='?',choices=['submit','close','watch'])
    p.add_argument('--workspace',default='.',help='Explicit working directory; artifacts under trader/')
    p.add_argument('--input',help='Plain JSON import/config file')
    p.add_argument('--fetch',action='store_true',help='Explicit public read-only network acquisition')
    p.add_argument('--now',help='ISO8601 aware UTC clock; historical testing only when overridden')
    p.add_argument('--symbol');p.add_argument('--interval',choices=['1m','5m','15m'],default='5m');p.add_argument('--limit',type=int,default=100)
    p.add_argument('--side',choices=['long','short'],default='long');p.add_argument('--price')
    p.add_argument('--duration-seconds',type=int,default=0);p.add_argument('--poll-seconds',type=int,default=15)
    p.add_argument('--seed',type=int,default=19);p.add_argument('--replays',type=int,default=10000);p.add_argument('--agents',type=int,default=10000);p.add_argument('--steps',type=int,default=20);p.add_argument('--block-size',type=int,default=4)
    return p

def main(argv=None):
    args=parser().parse_args(argv)
    try:
        if args.command=='init':obj=initialize(args)
        elif args.command=='status':obj=status(args)
        elif args.command=='report':obj=report(args)
        elif args.command=='pipeline':obj=pipeline(args)
        elif args.command=='demo':obj=demo(args)
        elif args.command=='paper' and args.action=='watch':
            from .watcher import run
            obj=run(args)
        elif args.command in ('market','news'):
            from . import market,news
            obj=(market if args.command=='market' else news).run(args)
        elif args.command in ('backtest','simulate','world'):
            from .research import run
            obj=run(args)
        else:
            require(args.command!='paper' or args.action is not None,'paper requires submit, close or watch')
            from .trade import run
            obj=run(args)
        print(json.dumps(obj,ensure_ascii=True,allow_nan=False))
        data=obj.get('data',{});return 1 if data.get('status') in ('blocked','waiting','error','insufficient_data','degraded') or data.get('approved') is False else 0
    except (SkillError,OSError,ValueError,KeyError,TypeError) as exc:
        print(json.dumps({'status':'error','command':args.command,'error':str(exc)},ensure_ascii=True),file=sys.stderr)
        return 2
