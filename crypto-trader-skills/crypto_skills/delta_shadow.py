"""Paired 15/30-minute research observations for settled Trade 1 entries."""
import asyncio
from datetime import datetime
from decimal import Decimal as D
import json
from operator import itemgetter

from .delta_plan import eligible_completed_trade
CAPS = (15, 30)
# Apply identical assumptions to both horizons. A candle is a price proxy.
EXIT_COST = D('.0005')
KEYS = ('first_fill_at', 'closed_at', 'exit_reason', 'exit', 'entry', 'filled_contracts',
        'contract_value', 'position', 'stop_loss', 'target', 'actual_commission',
        'entry_commission', 'funding', 'net_pnl', 'symbol')


def seconds(stamp):
    dt = datetime.fromisoformat(stamp)
    if dt.utcoffset() is None:
        raise ValueError('UTC offset missing')
    return dt.timestamp()


def minute(t):
    return int(t // 60) * 60


def _deadline_book_price(row, capture, end):
    from .delta_candidate_capture import MAX_QUOTE_AGE
    from .delta_candidate_exit import bid_proceeds, book_midpoint

    if capture['status'] != 'valid':
        raise ValueError('No valid depth snapshot at the modeled deadline')
    book = capture['book']
    observed = capture['book_observed_at']
    stamp = int(book['last_updated_at'])
    exchange = stamp / 1_000_000
    if (book['symbol'] != row['symbol'] or not end <= exchange <= observed + 2
            or not end <= observed < end + MAX_QUOTE_AGE
            or minute(exchange) != minute(end) or minute(observed) != minute(end)):
        raise ValueError('Displayed bid depth does not cover the modeled deadline minute')
    book_midpoint(book)
    size = row['filled_contracts']
    if type(size) is not int or size <= 0:
        raise ValueError('Invalid close quantity')
    return bid_proceeds(book['buy'], size) / size, stamp


def replay(row, marks, trades, closed, end, *, deadline_book=None):
    stop, target = D(row['stop_loss']), D(row['target'])
    if row['position'] != 'long' or not 0 < stop < target:
        raise ValueError('Unsupported position or bracket')
    px = None
    end_bar = minute(end) - 60
    for t in range(minute(closed), int(end) + 1, 60):
        if t >= end:
            break
        bar = marks[t]
        op, lo, hi, cl = (D(str(bar[k])) for k in ('open','low','high','close'))
        if not 0 < lo <= min(op, cl) <= max(op, cl) <= hi:
            raise ValueError('Invalid mark candle')
        if lo <= stop or hi >= target:
            if t < closed or t + 60 > end:
                raise ValueError('Bracket touched in a partial boundary minute')
            if lo <= stop and hi >= target:
                raise ValueError('Both brackets touched in one minute')
            px = min(op, stop) if lo <= stop else target
            end = t + 60
            break
    if int(closed // 3600) != int(end // 3600):
        raise ValueError('Additional funding unverified across UTC hour')
    reference = 'last completed trade close'
    source = {}
    if px is None:
        last = trades.get(end_bar)
        if last is not None and D(str(last['volume'])) > 0:
            px = D(str(last['close']))
        elif deadline_book is not None:
            px, stamp = _deadline_book_price(row, deadline_book, end)
            reference = 'captured displayed bid depth'
            source = dict(reference_exchange_us=stamp)
        elif last is None:
            raise KeyError(end_bar)
        else:
            raise ValueError('No traded volume in deadline reference minute')
    if px <= 0:
        raise ValueError('Invalid reference price')
    px *= 1 - EXIT_COST
    size = D(str(row['filled_contracts'])) * D(str(row['contract_value']))
    entry_fee = D(row['entry_commission'])
    exit_rate = (D(row['actual_commission']) - entry_fee) / (D(row['exit']) * size)
    if not 0 <= exit_rate < 1:
        raise ValueError('Invalid exchange exit commission rate')
    fees = entry_fee + px * size * exit_rate
    funding = D(row['funding'])
    return dict(status='estimated', exit_price=str(px), fees=str(fees), funding=str(funding),
                net_pnl=str((px - D(row['entry'])) * size - fees + funding),
                method=f'1m mark brackets / {reference}, 5bp exit slippage, actual fee rate, zero incremental funding assumed',
                **source)


async def estimate(call, row, closed, end, *, deadline_book=None):
    args = dict(resolution='1m', start=minute(closed), end=minute(end))
    try:
        marks, trades = await asyncio.gather(*(
            call('get_candles', dict(args, symbol=prefix + row['symbol'])) for prefix in ('MARK:', '')))
        def index(candles):
            result = {int(b['time']): b for b in candles}
            if len(result) != len(candles):
                raise ValueError('Duplicate candle')
            return result
        return replay(row, index(marks['result']), index(trades['result']), closed, end,
                      deadline_book=deadline_book)
    except (KeyError, TypeError, ValueError, ArithmeticError) as err:
        return dict(status='unavailable', reason='Incomplete or ambiguous price/cost history: ' + str(err))
    except (OSError, RuntimeError, TimeoutError):
        return dict(status='pending', reason='Price history request needs retry')


async def refresh_trade1_shadows(call, rows, path, as_of):
    from .delta_ledger import atomic_json
    saved = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    dirty = False
    now = seconds(as_of)
    fetch_budget = 0 if any(r.get('status') == 'open' for r in rows) else 8
    for row in rows:
        if row.get('campaign_id') != 'trade1' or not eligible_completed_trade(row):
            continue
        order = str(row['order_id'])
        signature = [row.get(k) for k in KEYS]
        old = saved.get(order, {})
        results = {r['minutes']:r for r in old.get('results', [])} if old.get('signature') == signature else {}
        for cap in CAPS:
            previous = results.get(cap, {})
            if previous.get('status') in ('estimated','actual_early_exit','unavailable'):
                continue
            value = previous.copy() or dict(status='pending')
            if not row.get('first_fill_at') or not row.get('closed_at'):
                value = dict(status='unavailable', reason='Exchange fill timestamp missing')
            else:
                end = seconds(row['first_fill_at']) + cap * 60
                closed = seconds(row['closed_at'])
                if closed <= end and row.get('exit_reason') in ('stop_loss', 'take_profit'):
                    value = dict(status='actual_early_exit', exit_price=row['exit'], fees=row['actual_commission'],
                                 funding=row['funding'], net_pnl=row['net_pnl'], method='Same exchange bracket fill')
                elif row.get('exit_reason') != 'ten_minute' or closed >= end:
                    value = dict(status='unavailable', reason='Actual exit timing or reason prevents paired replay')
                elif now >= max(minute(end) + 60, previous.get('retry_after', 0)) and fetch_budget:
                    fetch_budget -= 1
                    value = await estimate(call, row, closed, end)
                    if value['status'] == 'pending':
                        attempts = previous.get('attempts', 0) + 1
                        value.update(attempts=attempts, retry_after=now+60)
                        if attempts >= 3:
                            value = dict(status='unavailable', reason='Three history requests failed across separate refreshes')
            value['minutes'] = cap
            if value['status'] != 'pending':
                value['observed_at'] = as_of
            results[cap] = value
        row['shadow_exits'] = sorted(results.values(), key=itemgetter('minutes'))
        current = dict(signature=signature, results=row['shadow_exits'])
        if current != old:
            saved[order] = current
            dirty = True
    if dirty:
        atomic_json(path, saved)
