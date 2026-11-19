"""Ten-minute exits for reconciled, independently owned trade1 demo positions."""
from collections import defaultdict
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path

from .core import decimal, iso, read_json, replace_with_windows_retry, utc
from .delta_execution import OrderJournal
from .delta_plan import CRYPTO_DEMO_SYMBOLS, LEGACY_CONTRACTS


_BRACKETS = {'stop_loss_order': 'stop_loss', 'take_profit_order': 'take_profit'}
_TERMINAL = {'closed', 'cancelled', 'rejected'}
_UNKNOWN = (RuntimeError, ConnectionError, TimeoutError)


def _commit(path, records):
    # The encompassing account reconciliation lock serializes snapshots.
    tmp = path.with_suffix('.tmp')
    with tmp.open('w', encoding='utf-8') as stream:
        json.dump(records, stream, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    replace_with_windows_retry(tmp, path)


def _accept(attempt, order):
    if (order.get('client_order_id') != attempt['client_order_id']
            or order.get('product_id') != attempt['product_id']
            or order.get('side') != 'sell' or order.get('reduce_only') is not True
            or decimal(order['size']) != attempt['size'] or not order.get('id')):
        raise ValueError('Time exit acknowledgement does not match its recorded intent')
    unfilled = decimal(order['unfilled_size'])
    if unfilled != int(unfilled) or not 0 <= unfilled <= attempt['size']:
        raise ValueError('Invalid unfilled quantity in timed close')
    if order['state'] == 'rejected' and unfilled != attempt['size']:
        raise ValueError('Rejected timed close claims fills')
    attempt.update(order_id=str(order['id']), state=order['state'],
                   filled=attempt['size']-int(unfilled))


async def _recover(call, attempt):
    try:
        response = await call('get_order_by_id', {'client_order_id':attempt['client_order_id']})
    except _UNKNOWN:
        return
    order = response.get('result')
    if order:
        _accept(attempt, order)


def _resting_protection(order):
    return (order.get('side') == 'sell' and order.get('bracket_order') is True
            and order.get('reduce_only') is True and order.get('state') == 'pending'
            and order.get('stop_order_type') in _BRACKETS)


def _open_exposure(row, observed):
    if row['status'] != 'reconciliation_pending':
        return row
    expected = row.get('expected_filled_contracts')
    if type(expected) is not int or not 1 <= expected <= row.get('contracts', LEGACY_CONTRACTS) or not any(
            p['product_id'] == row['product_id'] and decimal(p['size']) > 0 for p in observed['positions']):
        return row
    # An IOC can report its terminal fill total before the account feed exposes
    # every fill. Only manage units independently proven by the fill chain and
    # current position. Campaign accounting still awaits full reconciliation.
    from .delta_ledger import reconcile_trade
    return reconcile_trade(dict(row, contracts=expected), observed['fills'],
                           observed['transactions'], observed['positions'])


async def _send_due(call, row, timer, exits, clock, save):
    product = row['product_id']
    remaining = row['remaining_contracts']
    if (not 0 < remaining <= row.get('contracts', LEGACY_CONTRACTS)
            or row.get('position') != 'long' or row.get('symbol') not in CRYPTO_DEMO_SYMBOLS):
        raise ValueError('Timed exit does not match the trade1 long position policy')
    attempts = timer['attempts']
    if attempts:
        latest = attempts[-1]
        if latest['state'] not in _TERMINAL:
            return 'awaiting_close_order'
        applied = sum(decimal(f['size']) for f in exits if str(f['order_id']) == latest['order_id'])
        if applied != latest['filled']:
            return 'awaiting_close_fills'

    await OrderJournal._check_environment(call)
    orders = await call('get_open_orders', {'product_ids':[product], 'page_size':100})
    if (orders.get('meta') or {}).get('after') or any(
            not _resting_protection(order) for order in orders['result']):
        return 'awaiting_open_order'
    # A flat position can reopen with the same signed size between snapshots.
    recent = (await call('get_fills', {'product_ids':[product], 'page_size':1}))['result']
    if not recent or recent[0]['id'] not in row['fill_ids']:
        return 'awaiting_position_reconciliation'
    live = (await call('get_positions', {'product_id':product}))['result']
    if decimal(live['size']) != remaining:
        return 'awaiting_position_reconciliation'

    key = f"trade1:{product}:{row['order_id']}:{len(attempts)+1}"
    client_id = 'cts-x-' + hashlib.sha256(key.encode()).hexdigest()[:24]
    intent = dict(client_order_id=client_id, product_id=product, size=remaining,
                  submitted_at=iso(clock()), state='unconfirmed')
    attempts.append(intent)
    save()
    try:
        response = await call('place_order', dict(product_id=product, client_order_id=client_id,
            size=remaining, side='sell', reduce_only=True, order_type='market_order'))
    except _UNKNOWN:
        return 'awaiting_close_order'
    _accept(intent, response['result'])
    save()
    return 'awaiting_close_fills'


async def _verify_exit_type(call, fill, timer):
    order_id = str(fill['order_id'])
    for attempt in timer['attempts']:
        if attempt.get('order_id') == order_id:
            return 'ten_minute'
    if order_id in timer['known_exits']:
        return timer['known_exits'][order_id]
    try:
        order = (await call('get_order_by_id', {'order_id':int(order_id)}))['result']
    except _UNKNOWN:
        return None
    if (not order or str(order.get('id')) != order_id or order.get('product_id') != timer['product_id']
            or order.get('side') != 'sell'):
        return None
    for attempt in timer['attempts']:
        if attempt['client_order_id'] == order.get('client_order_id'):
            _accept(attempt, order)
            return 'ten_minute'
    reason = _BRACKETS.get(order.get('stop_order_type'), 'other_exchange_exit')
    timer['known_exits'][order_id] = reason
    return reason


async def manage_time_exits(call, run, rows, observed, *, execute=False, now=None):
    """Persist deadlines, reconcile order ownership, then close due owned lots in execution mode."""
    path = Path(run)/'time-exits.json'
    if path.parent.name != 'trade1':
        raise ValueError('Timed closes require the trade1 campaign')
    records = read_json(path) if path.exists() else {}
    clock = utc if now is None else lambda: utc(now)
    by_id = {f['id']:f for f in observed['fills']}
    by_entry = defaultdict(list)
    for fill in by_id.values():
        if fill['side'] == 'buy':
            by_entry[(fill['product_id'], str(fill['order_id']))].append(fill)
    dirty = False
    def save():
        nonlocal dirty
        _commit(path, records)
        dirty = False

    for row in rows:
        key = str(row['order_id'])
        product = row['product_id']
        starts = by_entry.get((product, key), ())
        timer = records.get(key)
        if timer is None and not starts:
            continue
        # Earlier confirmed fills win when a delayed fill appears on a subsequent refresh.
        if timer is None:
            timer = records[key] = dict(product_id=product, attempts=[], known_exits={})
            dirty = True
        if timer['product_id'] != product:
            raise ValueError('Timed exit product changed for an existing order')
        times = [utc(f['created_at']) for f in starts]
        if timer.get('first_fill_at'):
            times.append(utc(timer['first_fill_at']))
        first = min(times)
        if timer.get('first_fill_at') != iso(first):
            timer.update(first_fill_at=iso(first), deadline_at=iso(first+timedelta(minutes=10)))
            dirty = True
        row.update(first_fill_at=timer['first_fill_at'], deadline_at=timer['deadline_at'])
        if row['status'] == 'open':
            for order in observed['orders']:
                kind = _BRACKETS.get(order.get('stop_order_type'))
                if (order.get('product_id') == product and kind and order.get('side') == 'sell'
                        and order.get('bracket_order') is True and order.get('reduce_only') is True):
                    if timer['known_exits'].get(str(order['id'])) != kind:
                        timer['known_exits'][str(order['id'])] = kind
                        dirty = True

        attempts = timer['attempts']
        if attempts and attempts[-1]['state'] not in _TERMINAL:
            pending = attempts[-1]
            previous = dict(pending)
            await _recover(call, pending)
            dirty |= previous != pending

        exposure = _open_exposure(row, observed)
        row['timer_exposure_open'] = exposure['status'] == 'open'
        fills = [by_id[i] for i in exposure.get('fill_ids', []) if i in by_id]
        exits = [f for f in fills if f['side'] == 'sell' and f['product_id'] == product]
        deadline = utc(timer['deadline_at'])
        if exposure['status'] == 'open' and clock() >= deadline:
            row['time_exit_state'] = (await _send_due(call, exposure, timer, exits, clock, save)
                                      if execute else 'due_read_only')
        else:
            row['time_exit_state'] = row['status']
        row['exit_order_ids'] = list(dict.fromkeys(str(f['order_id']) for f in exits))
        row['close_submitted_at'] = attempts[0]['submitted_at'] if attempts else None
        row['close_delay_seconds'] = ((utc(row['close_submitted_at'])-deadline).total_seconds()
                                      if attempts else None)
        row['exit_reason'] = None
        if row['status'] == 'closed' and exits:
            kinds = set()
            for fill in exits:
                order_id = str(fill['order_id'])
                missing = order_id not in timer['known_exits']
                reason = await _verify_exit_type(call, fill, timer)
                if reason and missing:
                    timer['known_exits'][order_id] = reason
                    dirty = True
                kinds.add(reason)
            if None not in kinds:
                row['exit_reason'] = next(iter(kinds)) if len(kinds)==1 else 'mixed'
    if dirty:
        save()
