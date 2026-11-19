"""Model an entry decision from captured public market data and the frozen batch planner."""
from decimal import Decimal

from .delta_plan import CRYPTO_DEMO_SYMBOLS, TRADE1_CONTRACTS, plan_batch

DISPLAYED_LEVELS = 5


def book_fill(asks, contracts, limit):
    """Consume displayed offer levels in price order without assuming hidden liquidity."""
    limit = Decimal(limit)
    if not limit.is_finite() or limit <= 0 or type(contracts) is not int or contracts <= 0:
        raise ValueError('Invalid IOC limit or quantity')
    levels=[]
    for ask in asks:
        price, size = Decimal(str(ask['price'])), Decimal(str(ask['size']))
        if not price.is_finite() or price <= 0 or not size.is_finite() or size < 0 or size % 1:
            raise ValueError('Invalid displayed price or size')
        levels.append((price, int(size)))
    levels.sort()
    if not levels or len({price for price,_ in levels})!=len(levels):
        raise ValueError('Order-book evidence has missing or duplicate asks')

    remaining = contracts
    notional = Decimal(0)
    for price, available in levels:
        if price > limit:
            break
        quantity = min(remaining, available)
        notional += price * quantity
        remaining -= quantity
        if remaining == 0:
            break

    filled = contracts - remaining
    if not remaining:
        state = 'full'
    elif len(levels) >= DISPLAYED_LEVELS and levels[-1][0] < limit:
        state = 'depth_unresolved'
    else:
        state = 'partial' if filled else 'unfilled'
    return dict(state=state,filled=filled,avg_price=str(notional/filled) if filled else None)


def evaluate_entry(snapshot, products, slot, *, cash, day_loss, ready_only):
    """Apply both arms to the same five eligible symbols at a common closed bar."""
    if not snapshot.get('complete'):
        return dict(status='incomplete_market_evidence',fills=[])
    try:
        coins = snapshot['coins']
        captured_at = float(snapshot['captured_at'])
        if not 0 <= captured_at-slot < 15:
            raise ValueError('Snapshot is outside the decision window')
        markets = []
        for symbol in CRYPTO_DEMO_SYMBOLS:
            row = coins[symbol]
            signal = row['signal']
            if (row['status'] != 'valid' or signal['closed_at'] != slot
                    or row['book']['symbol'] != symbol or row['ticker']['symbol'] != symbol
                    or signal['status'] not in ('ready','waiting') or products[symbol]['symbol'] != symbol):
                raise ValueError('Missing or misaligned market evidence')
            if not ready_only or signal['status'] == 'ready':
                markets.append((products[symbol],row['ticker'],signal))
        group = plan_batch(markets,captured_at,cash,day_loss,contracts=TRADE1_CONTRACTS)
        if group['status'] != 'planned':
            return dict(group,fills=[])
        fills=[]
        for entry in group['entries']:
            symbol=entry['symbol']
            row=coins[symbol]
            mark=Decimal(row['ticker']['mark_price'])
            if not Decimal(entry['stop']) < mark < Decimal(entry['target']):
                return dict(group,status='mark_outside_brackets',fills=fills,abandoned_at=symbol)
            fill=book_fill(row['book']['sell'],TRADE1_CONTRACTS,entry['limit'])
            fills.append(dict(fill,symbol=symbol))
            if fill['state']=='depth_unresolved':
                return dict(group,status='incomplete_market_evidence',fills=fills,abandoned_at=symbol)
    except (ArithmeticError, ValueError, KeyError, TypeError) as error:
        return dict(status='incomplete_market_evidence',fills=[],reason=str(error))
    return dict(group,status='modeled_entry',fills=fills,
                full_lots=sum(fill['state']=='full' for fill in fills))
