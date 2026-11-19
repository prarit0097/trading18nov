"""Delta demo long-entry arithmetic, separate from spot execution approval."""
from decimal import Decimal as D
from datetime import timedelta, timezone
from itertools import combinations, product as leverage_combinations
from .trade import long_levels


CRYPTO_DEMO_SYMBOLS = ('BTCUSD', 'SOLUSD', 'ETHUSD', 'DOGEUSD', 'XRPUSD')
MIN_BATCH_COINS = 4
TARGET_CLOSED_TRADES = 10_000
LEGACY_CONTRACTS = 10
TRADE1_CONTRACTS = 3


def eligible_completed_trade(row):
    trade1 = row.get('campaign_id') == 'trade1'
    required = TRADE1_CONTRACTS if trade1 else LEGACY_CONTRACTS
    return (row['status'] == 'closed' and row.get('symbol') in CRYPTO_DEMO_SYMBOLS
            and row.get('filled_contracts') == required and row.get('net_pnl') is not None
            and (not trade1 or (row.get('classification') == 'strategy'
                 and row.get('contracts') == required and row.get('exited_contracts') == required))
            and D(str(row['net_pnl'])).is_finite())


def next_batch_size(completed):
    # A partial batch can leave fewer than four trades to reach the exact target.
    return min(MIN_BATCH_COINS, max(0, TARGET_CLOSED_TRADES - completed))


def campaign_state(rows, positions, orders, now, *, other_account_trades=()):
    """Report the entry gate from reconciled trades and account inventory."""
    from datetime import datetime
    ist = timezone(timedelta(hours=5, minutes=30))
    today = now.astimezone(ist).date()
    closed = [row for row in rows if row['status'] == 'closed']
    completed = sum(eligible_completed_trade(row) for row in closed)
    daily_net = sum(
        (D(row['net_pnl']) for row in (*closed, *other_account_trades)
         if row['status'] == 'closed' and datetime.fromisoformat(row['closed_at']).astimezone(ist).date() == today),
        D(0),
    )
    if not daily_net.is_finite():
        raise ValueError('Daily net P&L must be finite')
    daily_loss = max(D(0), -daily_net)
    reasons = []
    if any(D(str(position['size'])) != 0 for position in positions) or orders:
        reasons.append('Account has an open position or pending order')
    if any(row['status'] != 'closed' for row in (*rows, *other_account_trades)):
        reasons.append('A registered trade has not finalized')
    if daily_loss >= 30:
        reasons.append('Daily loss limit reached')
    if completed >= TARGET_CLOSED_TRADES:
        reasons.append('Campaign trade count reached')
    return dict(trading_day_ist=today.isoformat(), completed=completed,
                daily_loss_usd=str(daily_loss),
                remaining_planned_risk_usd=str(max(D(0), min(D(10), 30-daily_loss))),
                blocked=bool(reasons), reasons=reasons)


def plan(product,ticker,now_seconds,available_cash,daily_loss,open_positions,
         environment='india_testnet', *, batch=False, contracts=LEGACY_CONTRACTS):
    """Reject unsafe or unsupported inputs; return a proposal, never submit it."""
    def require(condition,message):
        if not condition: raise ValueError(message)
    def number(value):
        result=D(str(value))
        require(result.is_finite(),'Non-finite numeric input')
        return result
    require(environment=='india_testnet','Only india_testnet is authorized')
    supported_sizes = (LEGACY_CONTRACTS, TRADE1_CONTRACTS) if batch else (LEGACY_CONTRACTS,)
    require(type(contracts) is int and contracts in supported_sizes,'Unsupported contract size')
    require(open_positions==0,'Account already has an open position')
    symbols = CRYPTO_DEMO_SYMBOLS if batch else ('BTCUSD','ETHUSD','SOLUSD')
    require(product['symbol'] in symbols,'Unsupported symbol')
    require(product['contract_type']=='perpetual_futures' and product['notional_type']=='vanilla'
            and product['is_quanto'] is False,'Only linear non-quanto perpetuals')
    require(product['contract_unit_currency']==product['underlying_asset']['symbol']==product['symbol'][:-3]
            and product['quoting_asset']['symbol']==product['settling_asset']['symbol']=='USD',
            'Contract units are incompatible')
    require(product['trading_status']=='operational','Product unavailable')
    require(ticker['product_id']==product['id'],'Ticker identity mismatch')
    age=number(now_seconds)-number(ticker['timestamp'])/1000000
    require(0<=age<=15,'Ticker is stale or future-dated')
    cash,loss=map(number,(available_cash,daily_loss))
    require(cash>=0 and loss>=0,'Invalid cash or daily loss')
    bid,ask=(number(ticker['quotes'][k]) for k in ('best_bid','best_ask'))
    require(0<bid<=ask and (ask-bid)/bid*10000<=30,'Invalid or wide spread')
    tick=number(product['tick_size']); value=number(product['contract_value'])
    raw_fee=number(product['taker_commission_rate'])
    require(0<=raw_fee<D('.01'),'Invalid raw commission rate')
    fee=max(D('.001'),raw_fee*D('1.18')+D('.0001'))
    require(tick>0 and value>0 and 0<=fee<D('.01'),'Invalid contract metadata')
    # Marketable limit bounds entry price; the stop-market cannot bound exit slippage.
    limit=(ask/tick).to_integral_value(rounding='ROUND_CEILING')*tick+tick*10
    stop,target=long_levels(limit,1,2,tick)
    quantity=value*contracts
    fee_buffer=(limit+target)*quantity*fee
    funding_buffer=D('.50')
    planned=(limit-stop)*quantity+fee_buffer+funding_buffer
    require(planned<=10,f'{contracts} contracts exceed $10 planned risk')
    require(loss+planned<=30,'Daily loss plus reserved trade risk exceeds $30')
    notional=limit*quantity
    leverage=next((n for n in (1,2,5) if notional/n+fee_buffer<=cash*D('.80')),None)
    require(leverage is not None,'Insufficient margin at maximum 5x')
    return dict(environment=environment,symbol=product['symbol'],product_id=product['id'],
                contracts=contracts,side='buy',leverage=leverage,quantity=str(quantity),
                limit=str(limit),stop=str(stop),target=str(target),planned_loss=str(planned),
                fee_buffer=str(fee_buffer),funding_buffer=str(funding_buffer),
                strategy_qualified=False,loss_cap_guaranteed=False)


def plan_batch(markets, now, available_cash, daily_loss, *, completed=0, contracts=LEGACY_CONTRACTS):
    """Select a feasible cohort of distinct crypto coins in turnover order."""
    cash, loss = D(str(available_cash)), D(str(daily_loss))
    if not cash.is_finite() or not loss.is_finite() or min(cash, loss) < 0 or type(completed) is not int or completed < 0:
        raise ValueError('Invalid batch cash, loss or campaign count')
    count = next_batch_size(completed)
    if count == 0:
        return dict(status='target_reached', entries=[])
    capacity = (cash * D('.80'), max(D(0), 30 - loss))
    possible = {}
    rejected = {}
    for product, ticker, signal in markets:
        symbol = product['symbol']
        try:
            turnover = D(str(ticker['turnover_usd']))
            if not turnover.is_finite() or turnover <= 0:
                raise ValueError('Missing positive USD traded turnover')
            entry = plan(product, ticker, now, cash, loss, 0, batch=True, contracts=contracts)
        except (ValueError, ArithmeticError, KeyError, TypeError) as error:
            rejected[symbol] = str(error)
            continue
        margin = D(entry['limit']) * D(entry['quantity']) / entry['leverage'] + D(entry['fee_buffer'])
        risk = D(entry['planned_loss'])
        possible[symbol] = (dict(entry, signal=dict(signal), margin_reserve=str(margin),
                                 turnover_usd=str(turnover)), margin, risk, turnover)
    ranked = sorted(possible, key=lambda symbol:(-possible[symbol][3], symbol))
    output = dict(entries=[], requested_entries=count, minimum_distinct_symbols=count,
                  margin_budget=str(capacity[0]), daily_risk_budget=str(capacity[1]),
                  eligible_symbols=ranked, rejected=rejected)
    if len(ranked) < count:
        return dict(output, status='insufficient_distinct_coins')

    minimum_margin = None
    for selection in combinations(ranked, count):
        risk = sum(possible[s][2] for s in selection)
        if risk > capacity[1]:
            continue
        entries = [possible[s][0] for s in selection]
        notionals = [D(e['limit']) * D(e['quantity']) for e in entries]
        fees = sum(D(e['fee_buffer']) for e in entries)
        floor = sum(value / 5 for value in notionals) + fees
        minimum_margin = floor if minimum_margin is None else min(minimum_margin, floor)
        if floor > capacity[0]:
            continue
        options = [tuple(level for level in (1,2,5) if level >= e['leverage']) for e in entries]
        combinations_by_leverage = sorted(leverage_combinations(*options),
                                          key=lambda levels: (sum(levels), levels))
        for levels in combinations_by_leverage:
            reserves = [value / level + D(entry['fee_buffer'])
                        for entry,value,level in zip(entries,notionals,levels)]
            margin = sum(reserves)
            if margin <= capacity[0]:
                entries = [dict(entry, lot_number=i, leverage=level, margin_reserve=str(reserve))
                           for i,(entry,level,reserve) in enumerate(zip(entries,levels,reserves),1)]
                return dict(output, status='planned', entries=entries, planned_loss=str(risk),
                            margin_reserve=str(margin), distinct_symbols=count)
    return dict(output, status='budget_blocked',
                minimum_margin_at_5x=None if minimum_margin is None else str(minimum_margin))
