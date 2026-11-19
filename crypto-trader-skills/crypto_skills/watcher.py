"""Bounded observation of public quotes; simulated spot exits only."""
import time
from .core import Workspace,SkillError,require,decimal,utc,iso,read_envelope
from .market import _get_json,BASE
from .trade import _config,_account,_round,settle_close

SUPPORTED={'BTCUSDT','ETHUSDT','SOLUSDT'}
MAX_AGE=15

def collect_quote(symbol):
    require(symbol in SUPPORTED,'Unsupported watch symbol')
    started=iso();raw=_get_json('/api/v3/ticker/bookTicker',{'symbol':symbol})
    require(isinstance(raw,dict) and raw.get('symbol')==symbol,'Public quote symbol mismatch')
    return dict(symbol=symbol,venue='binance',bid=raw.get('bidPrice'),ask=raw.get('askPrice'),
                request_started_at=started,received_at=iso(),
                source={'mode':'public_rest','base_url':BASE,'endpoint':'/api/v3/ticker/bookTicker'})

def exit_model(ws,position,quote_currency):
    source='position_snapshot';model=position.get('exit_model')
    if model is None:
        require(position['symbol'] in SUPPORTED,'Unsupported legacy position symbol')
        archive=read_envelope(ws.root/'assets'/position['symbol']/'config.json','config')
        cfg=archive['data'];require(cfg.get('mode')=='paper' and cfg.get('symbol')==position['symbol'],'Legacy symbol/mode mismatch')
        require(utc(archive['created_at'])<=utc(position['opened_at']),'Legacy config was recorded after entry')
        model={k:cfg.get(k) for k in ('venue','product_type','quote_currency','price_tick','fee_rate','slippage_bps')}
        source='verified_archived_entry_config'
    require(isinstance(model,dict),'Missing position exit model')
    require(model.get('venue')=='binance' and model.get('product_type')=='spot' and
            model.get('quote_currency')==quote_currency=='USDT','Unsupported exit model venue/product/currency')
    fee,slip,tick=(decimal(model.get(k)) for k in ('fee_rate','slippage_bps','price_tick'))
    require(0<=fee<1 and 0<=slip<10000 and tick>0,'Invalid exit model costs/tick')
    require(fee==decimal(position.get('entry_fee_rate')),'Exit cost snapshot disagrees with entry fee model')
    return model,source

def observe(ws,position_id,quote,now=None):
    now=utc(now)
    with ws.lock():
        cfg=_config(ws);ledger,_=_account(ws,cfg,now);data=ledger['data']
        positions=[p for p in data['positions'] if p['id']==position_id]
        if not positions:return {'status':'already_closed','position_id':position_id}
        require(len(positions)==1,'Ambiguous position ID');position=positions[0]
        require(position['symbol'] in SUPPORTED,'Unsupported watch symbol')
        model,settings_source=exit_model(ws,position,data['quote_currency'])
        require(isinstance(quote,dict) and quote.get('symbol')==position['symbol'] and quote.get('venue')=='binance','Quote identity mismatch')
        source=quote.get('source',{})
        require(isinstance(source,dict) and source.get('mode')=='public_rest' and source.get('base_url')==BASE and
                source.get('endpoint')=='/api/v3/ticker/bookTicker','Unknown public quote provenance')
        require(isinstance(quote.get('request_started_at'),str) and isinstance(quote.get('received_at'),str),'Missing quote timestamps')
        requested,received=utc(quote['request_started_at']),utc(quote['received_at'])
        require(utc(position['opened_at'])<=requested<=received<=now and (now-requested).total_seconds()<=MAX_AGE,
                'Quote stale, future-dated, out of order or predates position')
        bid,ask=decimal(quote.get('bid')),decimal(quote.get('ask'))
        require(0<bid<=ask,'Invalid bid/ask')
        stop,target=decimal(position['stop']),decimal(position['target']);require(0<stop<target,'Invalid stop/target')
        envelope=ws.write('quote_'+position['symbol'].lower(),quote,now=now)
        reason='stop_loss' if bid<=stop else 'take_profit' if bid>=target else None
        fill=_round(bid*(1-decimal(model['slippage_bps'])/10000),decimal(model['price_tick']))
        require(fill>0,'Rounded observed exit fill is zero')
        quantity=decimal(position['quantity']);require(quantity>0,'Invalid position quantity')
        liquidation=quantity*fill*(1-decimal(model['fee_rate']))
        estimated_pnl=liquidation-quantity*decimal(position['entry_price'])-decimal(position['entry_fee'])
        result={'status':'holding','symbol':position['symbol'],'position_id':position_id,'bid':str(bid),
                'stop':str(stop),'target':str(target),'quote_digest':envelope['digest'],'settings_source':settings_source,
                'observed_at':quote['received_at'],'estimated_exit_fill':str(fill),
                'estimated_liquidation_value':str(liquidation),'estimated_net_pnl':str(estimated_pnl)}
        if reason is None:return result
        order=settle_close(data,position,fill,model['fee_rate'],now,'observed_bid_minus_adverse_slippage')
        order.update(exit_reason=reason,trigger_quote_digest=envelope['digest'],trigger_quote_as_of=quote['request_started_at'],
                     trigger_quote=quote,exit_model=model)
        data['orders'].append(order)
        ws.write('ledger',data,inputs={'previous_ledger':ledger['digest'],'config':ws.read('config')['digest'],
                 envelope['kind']:envelope['digest']},now=now)
        _account(ws,cfg,now)
        return dict(result,status='closed',order=order)

def _watch_loop(args,ws,duration,poll):
    ledger=ws.read('ledger');initial_orders={o['id'] for o in ledger['data']['orders']}
    started=iso();deadline=time.monotonic()+duration
    cycles=checked=0;closed=[];errors=[];recent=[]
    def committed_closes():
        return [o['id'] for o in ws.read('ledger')['data']['orders'] if o['id'] not in initial_orders and
                o.get('action')=='sell' and o.get('trigger_quote_digest')]
    while cycles==0 or time.monotonic()<deadline:
        positions=ws.read('ledger')['data']['positions'];require(len(positions)<=20,'Watcher supports at most20open positions')
        if not positions:break
        cycles+=1
        for p in positions:
            try:
                quote=collect_quote(p['symbol']);result=observe(ws,p['id'],quote);checked+=1
                recent.append(result)
            except (SkillError,OSError,ValueError,KeyError,TypeError) as exc:
                errors.append({'symbol':p.get('symbol'),'position_id':p.get('id'),'at':iso(),'error':str(exc)})
        with ws.lock():
            _account(ws,_config(ws),utc())
            closed=committed_closes()
            ws.write('watcher',{'status':'running','running':True,'started_at':started,'last_checked':iso(),
                     'cycles':cycles,'positions_checked':checked,'closed_order_ids':closed,'recent':recent[-20:],
                     'errors':errors[-20:],'error_count':len(errors),'duration_seconds':duration,'poll_seconds':poll},
                     inputs={'ledger':ws.read('ledger')['digest']})
        left=deadline-time.monotonic()
        if duration==0 or left<=0 or not ws.read('ledger')['data']['positions']:break
        time.sleep(min(poll,left))
    with ws.lock():
        _account(ws,_config(ws),utc())
        closed=committed_closes()
        return ws.write('watcher',{'status':'degraded' if errors else 'complete','running':False,'started_at':started,
                'finished_at':iso(),'cycles':cycles,'positions_checked':checked,'closed_order_ids':closed,
                'recent':recent[-20:],'errors':errors[-20:],'error_count':len(errors),'duration_seconds':duration,'poll_seconds':poll,
                'limits':['Foreground bounded paper watch; no process remains after completion.',
                          'Local request/receipt freshness only; exchange event time unavailable.',
                          'Missed touches between polls or before startup are not reconstructed.',
                          'Entry-time costs/tick, full fills and no market impact are model assumptions.']},
                inputs={'ledger':ws.read('ledger')['digest']})

def run(args):
    require(getattr(args,'now',None) is None and getattr(args,'input',None) is None and
            getattr(args,'price',None) is None and not getattr(args,'fetch',False) and getattr(args,'symbol',None) is None,
            'Public paper watch checks all positions; historical time, input, price, fetch and symbol overrides are rejected')
    duration=getattr(args,'duration_seconds',0);poll=getattr(args,'poll_seconds',15)
    require(type(duration) is int and 0<=duration<=3600,'Duration must be0..3600seconds')
    require(type(poll) is int and 5<=poll<=300,'Poll interval must be5..300seconds')
    ws=Workspace(args.workspace);cfg=_config(ws)
    require(cfg.get('venue')=='binance' and cfg.get('product_type')=='spot','Public watch supports Binance spot only')
    # No lazy account initialization: watching an empty workspace cannot create cash.
    ws.read('ledger')
    with ws.lock('watcher'):
        try:return _watch_loop(args,ws,duration,poll)
        except BaseException as exc:
            with ws.lock():
                ws.write('watcher',{'status':'error','running':False,'finished_at':iso(),'error':str(exc),
                         'note':'Inspect authoritative ledger for any committed exits before retrying.'})
            raise
