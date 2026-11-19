"""Estimate a long timed exit only where captured bids and mark evidence cover it."""
from decimal import Decimal as D
from math import isfinite

from .delta_candidate_capture import MAX_QUOTE_AGE
from .delta_plan import TRADE1_CONTRACTS

HOLD_SECONDS = 600


def book_midpoint(book):
    bid=max(D(str(level['price'])) for level in book['buy'])
    ask=min(D(str(level['price'])) for level in book['sell'])
    if not (bid.is_finite() and ask.is_finite() and 0<bid<=ask):
        raise ValueError('Invalid same-book spread')
    return (bid+ask)/2


def minute_index(bars, start, end, stop, target):
    """Return the first possible hosted trigger over a fully observed interval."""
    indexed = {row['time']:row for row in bars}
    if len(indexed)!=len(bars):
        raise ValueError('Duplicate mark candle')
    for t in range(start//60*60,end//60*60+1,60):
        row = indexed[t]
        op, hi, lo, cl = (D(str(row[key])) for key in ('open','high','low','close'))
        if not 0 < lo <= min(op, cl) <= max(op, cl) <= hi:
            raise ValueError('Invalid mark candle')
        stop_hit, target_hit = lo<=stop, hi>=target
        if stop_hit or target_hit:
            kind = 'ambiguous' if stop_hit and target_hit else ('stop_loss' if stop_hit else 'take_profit')
            return dict(trigger_type=kind, trigger_minute=t,
                        partial_boundary=t<start or t+60>end)
    return None


def bid_proceeds(bids, quantity):
    levels=[]
    for bid in bids:
        px, size = D(str(bid['price'])), D(str(bid['size']))
        if not px.is_finite() or px<=0 or not size.is_finite() or size<0 or size%1:
            raise ValueError('Invalid displayed bid')
        levels.append((px,int(size)))
    if len({p for p,_ in levels})!=len(levels):
        raise ValueError('Duplicate bid')
    proceeds=D(0)
    for price, visible in sorted(levels,reverse=True):
        filled=min(quantity,visible)
        proceeds+=filled*price
        quantity-=filled
        if not quantity:
            return proceeds
    raise ValueError('Displayed bids do not cover the full close')


def timed_exit(trade, mark_bars, exit_quotes, *, exit_fee_rate, funding_usd, stress=False,
               protective_books=None, zero_funding_through=None):
    """Keep unknown funding, ambiguous bracket touches and underfilled closes unscored."""
    try:
        opened=float(trade['first_fill_at'])
        if not isfinite(opened) or opened < 0:
            raise ValueError('Invalid modeled first fill time')
        deadline=opened+HOLD_SECONDS
        quotes=[q for q in exit_quotes if 0 <= float(q['time'])-deadline < MAX_QUOTE_AGE]
        if not quotes and protective_books is None:
            raise ValueError('Missing captured bids after the exact deadline')
        quote=min(quotes,key=lambda q:float(q['time']),default=None)
        closed=float(quote['time']) if quote is not None else deadline
        quantity=trade['filled']
        if type(quantity) is not int or not 0 < quantity <= TRADE1_CONTRACTS:
            raise ValueError('Invalid filled contract quantity')
        entry, stop, target, multiplier, entry_rate, exit_rate = [
            D(str(v)) for v in (trade['entry_price'],trade['stop'],trade['target'],
                                trade['contract_value'],trade['entry_fee_rate'],exit_fee_rate)]
        if not (0 < stop < entry < target and multiplier > 0 and
                0 <= entry_rate < 1 and 0 <= exit_rate < 1):
            raise ValueError('Invalid fees, protective brackets or contract value')
        touch = minute_index(mark_bars,int(opened),int(closed),stop,target)
        protective = {}
        if touch:
            unresolved = dict(touch,status='protective_exit_unresolved',deadline_at=deadline)
            proof = protective_books(touch,opened,deadline,stop,target) if protective_books else None
            if not proof or zero_funding_through is None:
                return unresolved
            samples = proof['quotes']
            closed = samples[-1]['time']
            if not zero_funding_through(closed):
                return unresolved
            prices = []
            try:
                for sample in samples:
                    book_midpoint({'buy':sample['bids'],'sell':[{'price':sample['best_ask']}]})
                    prices.append((bid_proceeds(sample['bids'],quantity),sample))
            except (ArithmeticError, KeyError, TypeError, ValueError):
                return unresolved
            _, quote = min(prices,key=lambda sample:sample[0])
            funding_usd = '0'
            protective = dict(touch,trigger_window_us=proof['trigger_window_us'],book_samples=len(samples),
                              funding_source='observed_schedule_no_event')
        if quote is None:
            raise ValueError('Missing captured bids after the exact deadline')
        if funding_usd is None:
            raise ValueError('Funding across the exposure window is unverified')
        funding = D(str(funding_usd))
        if not funding.is_finite():
            raise ValueError('Invalid funding cashflow')
        sale = bid_proceeds(quote['bids'],quantity)
        gross = (sale-entry*quantity)*multiplier
        fees = (entry*quantity*entry_rate+sale*exit_rate)*multiplier
        extra = D(0)
        if stress:
            entry_mid = D(str(trade['entry_midpoint']))
            exit_mid = book_midpoint({'buy':quote['bids'],'sell':[{'price':quote['best_ask']}]})
            if not 0<entry_mid<=entry:
                raise ValueError('Invalid entry midpoint for modeled spread cost')
            extra = ((entry-entry_mid)*quantity + max(D(0),exit_mid*quantity-sale))*multiplier
        return dict(status='modeled_exit',close_time=closed,deadline_at=deadline,
                    exit_price=str(sale/quantity),gross_usd=str(gross),fees_usd=str(fees),
                    funding_usd=str(funding),extra_execution_usd=str(extra),
                    net_usd=str(gross-fees+funding-extra),**protective)
    except (ArithmeticError, KeyError, TypeError, ValueError) as error:
        return dict(status='unavailable',reason=str(error))
