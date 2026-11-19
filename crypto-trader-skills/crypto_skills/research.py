"""Bounded, offline research: historical fills, block replay and a finite economy."""
import hashlib
import json
import math
import random
import time
from decimal import Decimal, ROUND_DOWN, ROUND_CEILING
from datetime import timedelta

from .core import SkillError, Workspace, decimal, digest, require, utc
from .trade import long_levels


def _integer(value, low, high, label):
    require(type(value) is int and low <= value <= high, f'{label} must be {low}..{high}')
    return value


def _bars(market, config):
    require(market.get('symbol') == config.get('symbol') and
            market.get('product_type') == config.get('product_type') and
            market.get('venue') == config.get('venue'), 'Market/config identity mismatch')
    health = market.get('health', {})
    require(health.get('valid') is True and health.get('gaps') == [], 'Invalid or gapped market')
    metadata = market.get('metadata', {})
    require(all(decimal(metadata.get(k)) > 0 for k in ('qty_step','price_tick','min_notional')),
            'Explicit positive market filter units required')
    require(all(decimal(metadata[k]) == decimal(config.get(k)) for k in metadata
                if k in ('qty_step','price_tick','min_notional')), 'Market/config filter mismatch')
    source = market.get('source', {})
    quote, base = config.get('quote_currency'), source.get('volume_unit')
    require(isinstance(quote,str) and quote and source.get('price_unit') == quote and isinstance(base,str) and
            base and base+quote == market['symbol'], 'Explicit compatible price and base-volume units required')
    require(source.get('mode') in ('fixture','import','public_rest'), 'Unknown market source')
    require(market.get('as_of') is not None, 'Missing market as_of')
    asof = utc(market['as_of'])
    interval = _integer(market.get('interval_seconds'), 1, 86400, 'interval_seconds')
    source = market.get('bars')
    require(isinstance(source, list) and 2 <= len(source) <= 20000, 'Need 2..20000 bars')
    result, previous, unclosed = [], None, False
    for b in source:
        require(isinstance(b,dict) and b.get('time') is not None, 'Explicit bar timestamp required')
        t = utc(b['time'])
        require(t.microsecond == 0 and int(t.timestamp()) % interval == 0 and t <= asof,
                'Future or unaligned bar')
        require(previous is None or (t - previous).total_seconds() == interval,
                'Bars must be chronological and contiguous')
        previous = t
        require(type(b.get('closed')) is bool, 'Bar closed flag required')
        require(not unclosed, 'Only final bar may be unclosed')
        unclosed = not b['closed']
        values = {k: decimal(b.get(k)) for k in ('open','high','low','close','volume')}
        require(values['low'] > 0 and values['low'] <= min(values['open'], values['close'])
                <= max(values['open'], values['close']) <= values['high'] and values['volume'] >= 0,
                'Invalid OHLCV')
        if b['closed']:
            require(t+timedelta(seconds=interval) <= asof, 'Bar close is after snapshot time')
            result.append(dict(values, time=b['time']))
    require(len(result) >= 2, 'Need at least two closed bars')
    require(health.get('closed_bars') == len(result), 'Closed-bar count mismatch')
    return result


def _costs(config):
    fee, slip = decimal(config.get('fee_rate')), decimal(config.get('slippage_bps')) / 10000
    require(0 <= fee < 1 and 0 <= slip < 1, 'Invalid fee or slippage')
    return fee, slip


def _round(value, tick, up=False):
    return (value/tick).to_integral_value(rounding=ROUND_CEILING if up else ROUND_DOWN)*tick


def _exit(bar, stop, target):
    if bar['open'] <= stop:
        return bar['open'], 'stop_gap'
    if bar['open'] >= target:
        return target, 'target'  # Known open precedes unknown intrabar ordering.
    if bar['low'] <= stop:
        return stop, 'stop_first_ambiguous' if bar['high'] >= target else 'stop'
    if bar['high'] >= target:
        return target, 'target'
    return None, None


def backtest(market, config):
    require(config.get('product_type') == 'spot',
            'Perpetual backtest unsupported: funding, margin and liquidation contracts unavailable')
    bars = _bars(market, config)
    lookback = _integer(config.get('lookback'), 1, 1000, 'lookback')
    require(len(bars) >= lookback + 1, 'Insufficient closed history for lookback')
    fee, slip = _costs(config)
    cash = initial = decimal(config.get('initial_cash'))
    budget, cap, step = (decimal(config.get(k)) for k in ('risk_budget','max_notional','qty_step'))
    tick, min_notional, exposure_cap, daily_cap = (decimal(config.get(k)) for k in
        ('price_tick','min_notional','max_total_exposure','max_daily_loss'))
    stop_pct, target_r = decimal(config.get('stop_pct')) / 100, decimal(config.get('target_r'))
    min_rvol = decimal(config.get('min_rvol', '0'))
    require(min_rvol >= 0, 'Invalid relative volume threshold')
    require(min(cash,budget,cap,step,target_r,tick,min_notional,exposure_cap,daily_cap) > 0
            and 0 < stop_pct < 1, 'Invalid backtest limits')
    trades, position, pending, fees = [], None, None, Decimal(0)
    daily_realized = {}
    peak, drawdown = cash, Decimal(0)
    for i, bar in enumerate(bars):
        day = utc(bar['time']).date().isoformat()
        if pending and position is None and daily_realized.get(day,0) > -daily_cap:
            entry = _round(bar['open'] * (1 + slip), tick, up=True)
            stop,target = pending
            stop_fill = _round(stop*(1-slip), tick)
            executable = 0 < stop_fill and stop < entry < target
            unit_loss = entry-stop_fill+fee*(entry+stop_fill)
            qty = (min(budget/unit_loss, cap/entry, exposure_cap/entry, cash/(entry*(1+fee)))
                   if executable and unit_loss > 0 else Decimal(0))
            qty = (qty/step).to_integral_value(rounding=ROUND_DOWN)*step
            if executable and qty > 0 and qty*entry >= min_notional:
                entry_fee = entry * qty * fee
                cash -= entry * qty + entry_fee
                fees += entry_fee
                position = dict(entry_price=entry, stop=stop, target=target, quantity=qty,
                                entry_fee=entry_fee, entry_time=bar['time'])
        pending = None
        if position:
            price, reason = _exit(bar, position['stop'], position['target'])
            if price is None and i == len(bars)-1:
                price, reason = bar['close'], 'end_of_data'
            if price is not None:
                price = _round(price*(1-slip),tick)
                qty = position['quantity']
                exit_fee = price*qty*fee
                cash += price*qty-exit_fee
                fees += exit_fee
                pnl = (price-position['entry_price'])*qty-position['entry_fee']-exit_fee
                daily_realized[day] = daily_realized.get(day,Decimal(0))+pnl
                trades.append({**{k:str(v) for k,v in position.items()}, 'exit_price':str(price),
                               'exit_time':bar['time'], 'exit_fee':str(exit_fee),
                               'net_pnl':str(pnl), 'exit_reason':reason})
                position = None
        equity = cash + (position['quantity']*_round(bar['close']*(1-slip),tick)*(1-fee) if position else 0)
        peak = max(peak, equity)
        drawdown = max(drawdown, peak-equity)
        if position is None and i >= lookback and i < len(bars)-1:
            history = bars[i-lookback:i]
            average = sum(b['volume'] for b in history)/lookback
            if (bar['close'] > max(b['high'] for b in history) and average > 0
                       and bar['volume']/average >= min_rvol):
                pending = long_levels(bar['close'],config['stop_pct'],target_r,tick)
    require(position is None, 'Unsettled backtest inventory')
    return dict(status='complete', metrics=dict(trade_count=len(trades), initial_cash=str(initial),
                final_cash=str(cash), net_pnl=str(cash-initial), total_fees=str(fees),
                max_drawdown_quote=str(drawdown), closed_bars=len(bars)), trades=trades,
                assumptions=['Long spot cash/inventory research baseline; no leverage or shorting.',
                'Signal uses prior closed highs; fill next closed bar open with adverse slippage.',
                'Stops/targets stay anchored to signal close; skip fills outside original plan.',
                'Stop gaps fill at worse open; stop wins same-bar ambiguity; exit adverse slippage.',
                'One position; venue tick/step/minimum filters, cash/notional/total exposure caps.',
                'Normal stop sizing includes both fees and adverse exit slippage; gaps may exceed budget.',
                'Daily realized loss blocks later entries after threshold; force settle at final close.'],
                limits=['Not a perpetual margin/funding/liquidation backtest.',
                        'No order-book liquidity, partial fills, funding, latency or market impact.',
                        'Historical research is not a prediction or calibrated win probability.'])


def simulate(market, config, plan, seed=19, replays=10000, steps=20, block_size=4):
    require(config.get('product_type') == 'spot',
            'Perpetual replay unsupported: funding, margin and liquidation contracts unavailable')
    bars = _bars(market, config)
    _integer(seed, 0, 2**63-1, 'seed'); _integer(replays, 1, 10000, 'replays')
    _integer(steps, 1, 256, 'steps'); _integer(block_size, 1, 256, 'block_size')
    require(plan.get('status') == 'ready' and plan.get('side') == 'long', 'Ready long plan required')
    entry, stop, target = (decimal(plan.get(k)) for k in ('entry','stop','target'))
    require(0 < stop < entry < target, 'Invalid plan entry/stop/target')
    fee, slip = _costs(config)
    returns = [tuple(b[k]/bars[i-1]['close'] for k in ('open','high','low','close'))
               for i,b in enumerate(bars) if i > 0]
    require(block_size <= len(returns), 'Insufficient history for block size')
    rng, pnls, underlying, sequences, sample = random.Random(seed), [], [], set(), []
    outcomes = dict(stop_count=0, target_count=0, timeout_count=0)
    # Identical numerical blocks count as one historical block, not extra observations.
    block_ids = [digest([[str(v) for v in row] for row in returns[i:i+block_size]])
                 for i in range(len(returns)-block_size+1)]
    for path in range(replays):
        ratios, ids = [], []
        while len(ratios) < steps:
            start = rng.randrange(len(block_ids))
            ratios.extend(returns[start:start+block_size]); ids.append(block_ids[start])
        sequences.add(tuple(ids))
        mark, fill, reason = entry, None, None
        for o,h,l,c in ratios[:steps]:
            bar = dict(open=mark*o, high=mark*h, low=mark*l, close=mark*c)
            if fill is None:
                fill, reason = _exit(bar, stop, target)
            mark = bar['close']
        if fill is None:
            fill, reason = mark, 'timeout'
        outcomes['target_count' if reason == 'target' else
                 'timeout_count' if reason == 'timeout' else 'stop_count'] += 1
        buy, sell = entry*(1+slip), fill*(1-slip)
        pnl = sell-buy-fee*(buy+sell)
        pnls.append(pnl); underlying.append(mark/entry-1)
        if path < 10:
            sample.append(dict(net_pnl_per_unit=str(pnl), underlying_return=str(underlying[-1]),
                               settlement=reason))
    ordered = sorted(pnls)
    tail = ordered[:max(1, math.ceil(replays*.05))]
    wins, losses = sum(p > 0 for p in pnls), sum(p < 0 for p in pnls)
    return dict(status='complete', seed=seed, metrics=dict(replays=replays, horizon_bars=steps,
                win_count=wins, loss_count=losses, flat_count=replays-wins-losses, **outcomes,
                mean_net_pnl_per_unit=str(sum(pnls)/replays),
                p05_net_pnl_per_unit=str(ordered[max(0, math.ceil(replays*.05)-1)]),
                expected_shortfall_05_per_unit=str(sum(tail)/len(tail)),
                underlying_positive_count=sum(p > 0 for p in underlying),
                mean_underlying_return=str(sum(underlying)/replays),
                unique_block_sequences=len(sequences), unique_net_pnl=len(set(pnls)),
                historical_return_bars=len(returns), possible_block_starts=len(block_ids),
                distinct_historical_blocks=len(set(block_ids))), path_sample=sample,
                assumptions=['Contiguous OHLC return blocks resampled with replacement; crypto 24/7.',
                'One unit long plan; adverse entry/exit slip, both fees; every path settled.',
                'Underlying horizon return continues after plan exit and is reported separately.',
                'Stops take precedence on ambiguous bars; no favorable target gap improvement.'],
                limits=['Conditional stress replay, not calibrated probabilities or independent observations.',
                'Repeated blocks and paths do not add historical information; no prediction claim.',
                'No spread, liquidity, funding, margin, liquidation or market impact qualification.'])


def world(market, config, seed=19, agents=10000, steps=20):
    bars = _bars(market, config)
    _integer(seed, 0, 2**63-1, 'seed'); _integer(agents, 2, 10000, 'agents')
    _integer(steps, 1, 100, 'steps')
    rng = random.Random(seed)
    tick = decimal(config.get('price_tick'))
    lot = decimal(config.get('qty_step'))
    capital = decimal(config.get('initial_cash'))
    require(min(tick,lot,capital) > 0, 'Invalid synthetic economy units')
    price = max(1, int(bars[-1]['close']/tick))
    unit = tick*lot
    cash = [int(capital/unit)]*agents
    inventory = [1000]*agents
    initial_cash, initial_inventory = sum(cash), sum(inventory)
    require(min(cash) >= price, 'Insufficient initial cash for synthetic order lot')
    ledger, sample, traded = hashlib.sha256(), [], set()
    submitted = matches = volume = 0
    for step in range(steps):
        bids, asks = [], []
        for actor in range(agents):
            buy = bool(rng.getrandbits(1))
            limit = max(1, price+rng.randint(-3,3))
            quantity = min(rng.randint(1,100), cash[actor]//limit if buy else inventory[actor])
            if quantity:
                (bids if buy else asks).append([limit, actor, quantity])
                submitted += 1
        bids.sort(key=lambda x:(-x[0], x[1])); asks.sort(key=lambda x:(x[0],x[1]))
        bi = ai = 0
        while bi < len(bids) and ai < len(asks) and bids[bi][0] >= asks[ai][0]:
            bid, ask = bids[bi], asks[ai]
            price = (bid[0]+ask[0])//2
            qty = min(bid[2], ask[2])
            buyer, seller = bid[1], ask[1]
            payment = price*qty
            require(cash[buyer] >= payment and inventory[seller] >= qty, 'Unfunded synthetic fill')
            cash[buyer] -= payment; cash[seller] += payment
            inventory[buyer] += qty; inventory[seller] -= qty
            event = [step, buyer, seller, price, qty]
            ledger.update(json.dumps(event, separators=(',',':')).encode()+b'\n')
            if len(sample) < 20:
                sample.append(dict(step=step,buyer=buyer,seller=seller,price=str(price*tick),
                                   quantity=str(qty*lot),quote_transferred=str(payment*unit)))
            traded.update((buyer,seller)); matches += 1; volume += qty
            bid[2] -= qty; ask[2] -= qty
            bi += bid[2] == 0; ai += ask[2] == 0
        require(sum(cash) == initial_cash and sum(inventory) == initial_inventory and
                min(cash) >= 0 and min(inventory) >= 0, 'Synthetic ledger conservation failed')
    return dict(status='complete', seed=seed, metrics=dict(participant_count=agents, steps=steps,
                submitted_orders=submitted, matched_trades=matches, participants_traded=len(traded),
                matched_quantity=str(volume*lot), last_price=str(price*tick),
                initial_cash_units=initial_cash, final_cash_units=sum(cash),
                initial_inventory_lots=initial_inventory, final_inventory_lots=sum(inventory),
                all_balances_nonnegative=min(cash) >= 0 and min(inventory) >= 0),
                units=dict(cash_unit=str(unit), inventory_lot=str(lot), price_tick=str(tick)),
                ledger_sample=sample, ledger_digest=ledger.hexdigest(),
                final_balances_digest=digest(list(zip(cash,inventory))),
                assumptions=['Actual lightweight synthetic participants each submit at most one limit order per step.',
                'Finite initial cash per participant from demo config; each starts with 1000 inventory lots.',
                'Price-time matching, midpoint execution; unmatched orders expire each step; zero fees.',
                'Cash and inventory conservation and nonnegative balances checked each step.'],
                limits=['Synthetic closed economy; not real people, MiroFish/OASIS, LLM agents or a prediction.',
                'Random order policies, no calibrated behavior, external flow, latency or market impact model.',
                'Ledger sample is bounded; full fill stream and final balances have deterministic digests.'])


def _lineage(workspace, artifact, depth=0, seen=None):
    seen = set() if seen is None else seen
    if artifact['digest'] in seen:
        return
    require(depth <= 8 and len(artifact['inputs']) <= 16 and len(seen) < 64,
            'Research lineage exceeds bounded depth/width/size')
    seen.add(artifact['digest'])
    for kind, expected in artifact['inputs'].items():
        current = workspace.read(kind)
        require(current['digest'] == expected, f'{artifact["kind"]} lineage invalidated by {kind}')
        _lineage(workspace,current,depth+1,seen)


def run(args):
    workspace = Workspace(args.workspace)
    kind = {'backtest':'backtest', 'simulate':'simulation', 'world':'world'}.get(args.command)
    require(kind is not None, 'Unknown research command')
    with workspace.lock():
        config = workspace.config
        inputs = {'config':workspace.read('config')['digest']}
        try:
            market = workspace.read('market')
        except SkillError as exc:
            return workspace.write(kind, dict(status='insufficient_data', reason=str(exc)), inputs, args.now)
        inputs['market'] = market['digest']
        _lineage(workspace,market)
        started = time.perf_counter()
        if args.command == 'backtest':
            result = backtest(market['data'], config)
        elif args.command == 'world':
            result = world(market['data'], config, seed=getattr(args,'seed',19),
                           agents=getattr(args,'agents',10000), steps=getattr(args,'steps',20))
        else:
            try:
                plan = workspace.read('plan')
            except SkillError as exc:
                return workspace.write(kind, dict(status='insufficient_data', reason=str(exc)), inputs, args.now)
            require(all(plan['inputs'].get(k) == v for k,v in inputs.items()), 'Plan lineage is stale')
            _lineage(workspace,plan)
            inputs['plan'] = plan['digest']
            result = simulate(market['data'], config, plan['data'], seed=getattr(args,'seed',19),
                              replays=getattr(args,'replays',10000), steps=getattr(args,'steps',20),
                              block_size=getattr(args,'block_size',4))
        result['benchmark'] = dict(elapsed_seconds=round(time.perf_counter()-started,6),
                                   measured_locally=True, capacity_claim=False)
        return workspace.write(kind, result, inputs, args.now)
