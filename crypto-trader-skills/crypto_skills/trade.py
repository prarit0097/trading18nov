"""Decimal spot-long paper pipeline. The ledger is the authoritative commit.

Portfolio/orders are recoverable projections. Stops are hypothetical gap-free
risk estimates, never a promise of maximum realized loss. No live transport.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from .core import Workspace, SkillError, decimal, digest, iso, require, utc


ZERO = Decimal('0')
ONE = Decimal('1')


def _round(value, step, up=False):
    return (value / step).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR) * step


def long_levels(entry, stop_pct, target_r, tick):
    """Keep a long plan anchored to its known signal, independent of later fills."""
    entry, pct, multiple, tick = map(decimal, (entry, stop_pct, target_r, tick))
    require(entry > 0 and 0 < pct < 100 and multiple > 0 and tick > 0, 'Invalid long plan inputs')
    stop = _round(entry*(ONE-pct/100),tick)
    target = _round(entry+(entry-stop)*multiple,tick,up=True)
    require(0 < stop < entry < target, 'Invalid rounded long plan')
    return stop,target


def _config(ws):
    config = ws.config
    positive = ('initial_cash', 'risk_budget', 'max_notional', 'max_total_exposure',
                'max_daily_loss', 'qty_step', 'price_tick', 'min_notional',
                'max_spread_bps', 'stop_pct', 'target_r')
    for key in positive + ('fee_rate', 'slippage_bps', 'min_rvol'):
        require(key in config, f'Missing required configuration: {key}')
        value = decimal(config[key])
        require(value > 0 if key in positive else value >= 0, f'Invalid {key}')
    require(decimal(config['fee_rate']) < 1 and decimal(config['slippage_bps']) < 10000,
            'Fee or slippage exceeds supported range')
    require(decimal(config['stop_pct']) < 100, 'Stop percentage must be below 100')
    for key in ('risk_ttl_seconds', 'max_market_age_seconds', 'signal_ttl_seconds', 'lookback'):
        require(type(config.get(key)) is int and config[key] > 0, f'Invalid {key}')
    for key in ('symbol', 'venue', 'quote_currency'):
        require(isinstance(config.get(key), str) and config[key], f'Missing {key}')
    require(config.get('product_type') in ('spot', 'linear_perpetual'), 'Unknown product type')
    return config


def _market(ws, config, now):
    envelope = ws.read('market')
    data = envelope['data']
    for key in ('symbol', 'venue', 'product_type'):
        require(data.get(key) == config[key], f'Market {key} mismatch')
    require(isinstance(data.get('as_of'),str), 'Missing market as_of')
    age = (now - utc(data['as_of'])).total_seconds()
    require(0 <= age <= config['max_market_age_seconds'], 'Market is future-dated or stale')
    health = data.get('health', {})
    require(health.get('valid') is True and health.get('gaps') == [], 'Market health is invalid or gapped')
    interval = data.get('interval_seconds')
    require(type(interval) is int and interval > 0, 'Missing interval units')
    bid, ask = decimal(data.get('bid')), decimal(data.get('ask'))
    require(0 < bid <= ask, 'Invalid bid/ask')
    for key in ('qty_step', 'price_tick', 'min_notional'):
        require(decimal(data.get('metadata', {}).get(key)) == decimal(config[key]),
                f'Exchange filter mismatch: {key}')
    source = data.get('source', {})
    require(source.get('mode') in ('fixture', 'import', 'public_rest'), 'Unknown market source')
    require(source.get('price_unit') == config['quote_currency'], 'Missing or incompatible price unit')
    base = source.get('volume_unit')
    require(isinstance(base, str) and base and base + config['quote_currency'] == config['symbol'],
            'Missing or incompatible base-volume unit')
    bars = data.get('bars')
    require(isinstance(bars, list) and len(bars) > 0, 'Missing bars')
    previous = None
    closed = []
    for bar in bars:
        require(isinstance(bar, dict) and 'time' in bar, 'Invalid bar')
        opened = utc(bar['time'])
        require(opened <= utc(data['as_of']), 'Future bar')
        if previous is not None:
            require((opened - previous).total_seconds() == interval, 'Bars have gaps or duplicates')
        previous = opened
        values = [decimal(bar.get(key)) for key in ('open', 'high', 'low', 'close', 'volume')]
        op, high, low, close, volume = values
        require(0 < low <= min(op, close) <= max(op, close) <= high and volume >= 0, 'Invalid OHLCV')
        require(type(bar.get('closed')) is bool, 'Missing closed-bar flag')
        if bar['closed']:
            require(opened + timedelta(seconds=interval) <= utc(data['as_of']), 'Bar not yet closed')
            closed.append(bar)
        else:
            require(bar is bars[-1], 'Unclosed bar before trailing bar')
    require(health.get('closed_bars') == len(closed), 'Closed-bar count mismatch')
    return envelope, closed


def _load(ws, kind, inputs, now, config):
    envelope = ws.read(kind)
    for key, value in inputs.items():
        require(envelope['inputs'].get(key) == value, f'{kind} invalidated by {key}; rebuild downstream artifacts')
    require(utc(envelope['created_at']) <= now, f'{kind} is future-dated')
    if kind in ('proposal', 'plan', 'sizing'):
        require((now - utc(envelope['created_at'])).total_seconds() <= config['signal_ttl_seconds'], f'{kind} expired')
    if kind in ('proposal', 'plan') and envelope['data'].get('status') == 'ready':
        signal_time = envelope['data'].get('signal_time')
        require(signal_time is not None, f'{kind} is missing signal time')
        require(0 <= (now - utc(signal_time)).total_seconds() <= config['signal_ttl_seconds'],
                f'{kind} signal expired or is future-dated')
    return envelope


def _base(ws, config, now):
    market, bars = _market(ws, config, now)
    return {'config': ws.read('config')['digest'], 'market': market['digest']}, market, bars


def _chain(ws, config, now, through):
    inputs, market, bars = _base(ws, config, now)
    artifacts = {}
    for kind in ('proposal', 'plan', 'sizing'):
        if kind == 'sizing':
            inputs['portfolio'] = ws.read('portfolio')['digest']
        artifact = _load(ws, kind, inputs, now, config)
        artifacts[kind] = artifact
        inputs[kind] = artifact['digest']
        if kind == through:
            return inputs, market, bars, artifacts
    raise SkillError('Unknown pipeline stage')


def _account(ws, config, now):
    # Missing files may initialize; damaged existing state must never reset cash.
    if not (ws.state / 'ledger.json').exists():
        ws.write('ledger', dict(cash=str(decimal(config['initial_cash'])), positions=[],
                 realized_pnl='0', daily_realized={}, orders=[], quote_currency=config['quote_currency'],
                 initial_cash=str(decimal(config['initial_cash']))), now=now)
    ledger = ws.read('ledger')
    require(utc(ledger['created_at']) <= now, 'Account state is future-dated; backdated mutation rejected')
    data = ledger['data']
    require(data.get('quote_currency') == config['quote_currency'], 'Account quote currency changed')
    require(decimal(data.get('cash')) >= 0 and isinstance(data.get('positions'), list), 'Invalid account state')
    portfolio = {key: data[key] for key in ('cash', 'positions', 'realized_pnl', 'daily_realized', 'quote_currency')}
    portfolio['account_digest'] = ledger['digest']
    _project(ws, 'portfolio', portfolio, ledger)
    _project(ws, 'orders', {'orders': data['orders'], 'status': 'paper'}, ledger)
    return ledger, ws.read('portfolio')


def _project(ws, kind, data, ledger):
    path = ws.state / (kind + '.json')
    if path.exists():
        old = ws.read(kind)
        if old['inputs'].get('ledger') == ledger['digest']:
            require(old['data'] == data, f'{kind} does not match authoritative ledger')
            return old
        require(old['inputs'].get('ledger') == ledger['inputs'].get('previous_ledger')
                and old['inputs'].get('ledger') is not None,
                f'{kind} was externally changed; refusing account repair')
    return ws.write(kind, data, inputs={'ledger': ledger['digest']}, now=ledger['created_at'])


def breakout_observation(last, history, side):
    level = (max(decimal(b['high']) for b in history) if side == 'long'
             else min(decimal(b['low']) for b in history))
    average = sum((decimal(b['volume']) for b in history), ZERO) / len(history)
    entry = decimal(last['close'])
    rvol = decimal(last['volume']) / average if average > 0 else ZERO
    triggered = entry > level if side == 'long' else entry < level
    return entry, level, rvol, triggered and average > 0


def _entry(ws, config, now, side):
    inputs, market, closed = _base(ws, config, now)
    require(side in ('long', 'short'), 'Unknown side')
    require(side == 'long' or config['product_type'] == 'linear_perpetual', 'Spot short unsupported')
    data = dict(status='waiting', side=side, reasons=[], research_only=config['product_type'] != 'spot')
    lookback = config['lookback']
    if len(closed) <= lookback:
        data['reasons'] = ['Insufficient lagged closed bars']
    else:
        last, history = closed[-1], closed[-lookback-1:-1]
        end = utc(last['time']) + timedelta(seconds=market['data']['interval_seconds'])
        require(0 <= (now - end).total_seconds() <= config['signal_ttl_seconds'], 'Last closed signal bar is stale')
        entry, level, rvol, triggered = breakout_observation(last, history, side)
        data.update(entry=str(entry), breakout_level=str(level), rvol=str(rvol), signal_time=iso(end))
        if triggered and rvol >= decimal(config['min_rvol']):
            data['status'] = 'ready'
        else:
            data['reasons'] = ['No closed-bar breakout with sufficient relative volume']
    return ws.write('proposal', data, inputs=inputs, now=now)


def _plan(ws, config, now):
    inputs, market, bars, artifacts = _chain(ws, config, now, 'proposal')
    proposal = artifacts['proposal']['data']
    data = dict(status='waiting', reasons=proposal.get('reasons', []))
    if proposal['status'] == 'ready':
        entry, tick = decimal(proposal['entry']), decimal(config['price_tick'])
        short = proposal['side'] == 'short'
        distance = entry * decimal(config['stop_pct']) / 100
        if short:
            stop = _round(entry+distance,tick,up=True)
            target = _round(entry-(stop-entry)*decimal(config['target_r']),tick)
        else:
            stop,target=long_levels(entry,config['stop_pct'],config['target_r'],tick)
        require(stop > 0 and target > 0 and stop != entry, 'Invalid rounded stop/target')
        data = dict(status='ready', entry=str(entry), stop=str(stop), target=str(target),
                    side=proposal['side'], signal_time=proposal['signal_time'],
                    research_only=proposal['research_only'], assumptions=['Stops may gap; losses may exceed risk budget'])
    return ws.write('plan', data, inputs=inputs, now=now)


def _size_data(config, market, plan, portfolio):
    if plan['status'] != 'ready':
        return dict(status='waiting', reasons=['Plan is not ready'])
    if plan['side'] != 'long':
        return dict(status='blocked', reasons=['Short sizing requires qualified margin and funding engine'])
    tick, step = decimal(config['price_tick']), decimal(config['qty_step'])
    slip, fee = decimal(config['slippage_bps']) / 10000, decimal(config['fee_rate'])
    fill = _round(decimal(market['ask']) * (ONE + slip), tick, up=True)
    stop_fill = _round(decimal(plan['stop']) * (ONE - slip), tick)
    unit_loss = fill - stop_fill + fee*(fill + stop_fill)
    require(decimal(plan['stop']) < fill < decimal(plan['target']),
            'Executable fill must remain strictly between stop and target')
    require(stop_fill > 0 and unit_loss > 0, 'Invalid executable risk distance')
    exposure = sum((decimal(p['quantity'])*decimal(p['entry_price']) for p in portfolio['positions']), ZERO)
    room = max(ZERO, decimal(config['max_total_exposure']) - exposure)
    quantity = _round(min(decimal(config['risk_budget']) / unit_loss,
                          decimal(config['max_notional']) / fill, room / fill,
                          decimal(portfolio['cash']) / (fill*(ONE+fee))), step)
    notional = quantity * fill
    return dict(status='ready' if quantity > 0 and notional >= decimal(config['min_notional']) else 'blocked',
                quantity=str(quantity), fill_price=str(fill), notional=str(notional), fee=str(notional*fee),
                cash_required=str(notional*(ONE+fee)), worst_case_loss=str(quantity*unit_loss),
                stop_fill_assumption=str(stop_fill), reasons=[] if quantity > 0 and notional >= decimal(config['min_notional']) else ['Quantity below exchange minimum'])


def _size(ws, config, now):
    with ws.lock():
        config = _config(ws)
        ledger, portfolio = _account(ws, config, now)
        inputs, market, bars, artifacts = _chain(ws, config, now, 'plan')
        inputs['portfolio'] = portfolio['digest']
        data = _size_data(config, market['data'], artifacts['plan']['data'], portfolio['data'])
        return ws.write('sizing', data, inputs=inputs, now=now)


def _risk_checks(config, market, plan, sizing, portfolio, now):
    reasons = []
    if config['product_type'] != 'spot':
        reasons.append('Perpetual execution lacks qualified margin and funding engine')
    if plan.get('side') != 'long':
        reasons.append('Only spot long execution is supported')
    expected = _size_data(config, market, plan, portfolio)
    require(sizing == expected, 'Sizing does not match recomputed risk and exchange filters')
    if sizing['status'] != 'ready':
        reasons.extend(sizing.get('reasons', ['Sizing is not ready']))
    spread = (decimal(market['ask'])-decimal(market['bid'])) / decimal(market['bid']) * 10000
    if spread > decimal(config['max_spread_bps']):
        reasons.append('Spread exceeds limit')
    if any(p['symbol'] == config['symbol'] for p in portfolio['positions']):
        reasons.append('An open position already exists for symbol')
    realized = decimal(portfolio['daily_realized'].get(now.date().isoformat(), '0'))
    if realized <= -decimal(config['max_daily_loss']):
        reasons.append('Daily realized loss limit reached')
    return reasons


def _risk(ws, config, now):
    with ws.lock():
        config = _config(ws)
        ledger, portfolio = _account(ws, config, now)
        inputs, market, bars, artifacts = _chain(ws, config, now, 'sizing')
        reasons = _risk_checks(config, market['data'], artifacts['plan']['data'],
                               artifacts['sizing']['data'], portfolio['data'], now)
        return ws.write('risk', dict(status='blocked' if reasons else 'approved', approved=not reasons,
                        reasons=reasons, expires_at=iso(now + timedelta(seconds=config['risk_ttl_seconds'])),
                        account_digest=ledger['digest']), inputs=inputs, now=now)


def settle_close(data,position,fill,fee_rate,now,price_source):
    """Settle one full spot position; caller holds the lock and commits the ledger."""
    fill,rate=decimal(fill),decimal(fee_rate)
    quantity=decimal(position['quantity'])
    require(fill>0 and quantity>0 and 0<=rate<1,'Invalid close price, quantity or fee')
    require(position in data['positions'],'Position not owned')
    fee=quantity*fill*rate;proceeds=quantity*fill-fee
    pnl=proceeds-quantity*decimal(position['entry_price'])-decimal(position['entry_fee'])
    data['cash']=str(decimal(data['cash'])+proceeds)
    data['positions'].remove(position)
    data['realized_pnl']=str(decimal(data['realized_pnl'])+pnl)
    day=now.date().isoformat()
    data['daily_realized'][day]=str(decimal(data['daily_realized'].get(day,'0'))+pnl)
    return dict(id=digest({'position':position['id'],'action':'close'}),action='sell',
                position_id=position['id'],symbol=position['symbol'],quantity=str(quantity),
                price=str(fill),fee=str(fee),realized_pnl=str(pnl),at=iso(now),mode='paper',price_source=price_source)


def _paper(ws, now, action, price):
    with ws.lock():
        config = _config(ws)
        ledger, portfolio = _account(ws, config, now)
        data = ledger['data']
        if action == 'submit':
            risk = ws.read('risk')
            order_id = digest({'risk': risk['digest'], 'action': 'submit'})
            if any(order['id'] == order_id for order in data['orders']):
                return ws.read('orders')
            inputs, market, bars, artifacts = _chain(ws, config, now, 'sizing')
            _load(ws, 'risk', inputs, now, config)
            require(risk['data'].get('approved') is True, 'Risk approval is blocked')
            require(now < utc(risk['data']['expires_at']), 'Risk approval expired')
            require(risk['data'].get('account_digest') == ledger['digest'], 'Risk account snapshot invalidated')
            reasons = _risk_checks(config, market['data'], artifacts['plan']['data'],
                                   artifacts['sizing']['data'], portfolio['data'], now)
            require(not reasons, '; '.join(reasons))
            size, plan = artifacts['sizing']['data'], artifacts['plan']['data']
            quantity, fill, fee = (decimal(size[k]) for k in ('quantity', 'fill_price', 'fee'))
            position = dict(id=order_id, symbol=config['symbol'], quantity=str(quantity),
                            entry_price=str(fill), entry_fee=str(fee), stop=plan['stop'], target=plan['target'],
                            opened_at=iso(now), entry_fee_rate=config['fee_rate'])
            position['exit_model']={key:config[key] for key in
                ('venue','product_type','quote_currency','price_tick','fee_rate','slippage_bps')}
            data['positions'].append(position)
            data['cash'] = str(decimal(data['cash'])-decimal(size['cash_required']))
            order = dict(id=order_id, action='buy', symbol=config['symbol'], quantity=str(quantity),
                         price=str(fill), fee=str(fee), at=iso(now), risk_digest=risk['digest'],
                         price_source='ask_plus_adverse_slippage', mode='paper')
        elif action == 'close':
            require(config['product_type'] == 'spot', 'Perpetual close requires margin and funding engine')
            positions = [p for p in data['positions'] if p['symbol'] == config['symbol']]
            if not positions:
                require(any(o['action'] == 'sell' and o['symbol'] == config['symbol'] for o in data['orders']), 'No inventory to close')
                return ws.read('orders')
            require(len(positions) == 1, 'Ambiguous inventory')
            position = positions[0]
            manual = price is not None
            if manual:
                fill = decimal(price)
                require(fill > 0, 'Close mark must be positive')
                fill = _round(fill, decimal(config['price_tick']))
            else:
                market, bars = _market(ws, config, now)
                fill = _round(decimal(market['data']['bid']) * (ONE-decimal(config['slippage_bps'])/10000), decimal(config['price_tick']))
            require(fill > 0, 'Rounded close price is zero')
            order=settle_close(data,position,fill,config['fee_rate'],now,
                               'manual_hypothetical_mark' if manual else 'bid_minus_adverse_slippage')
        else:
            raise SkillError('Paper action must be submit or close')
        data['orders'].append(order)
        ws.write('ledger', data, inputs={'previous_ledger': ledger['digest'], 'config': ws.read('config')['digest']}, now=now)
        _account(ws, config, now)
        return ws.read('orders')


def run(args):
    ws, now = Workspace(args.workspace), utc(getattr(args, 'now', None))
    if args.command == 'paper':
        return _paper(ws, now, args.action, getattr(args, 'price', None))
    config = _config(ws)
    commands = {'entry': lambda: _entry(ws, config, now, getattr(args, 'side', None) or 'long'),
                'plan': lambda: _plan(ws, config, now), 'size': lambda: _size(ws, config, now),
                'risk': lambda: _risk(ws, config, now)}
    require(args.command in commands, 'Unknown trade command')
    try:
        return commands[args.command]()
    except (KeyError, TypeError, AttributeError) as exc:
        raise SkillError(f'Invalid upstream data: {exc}') from exc
