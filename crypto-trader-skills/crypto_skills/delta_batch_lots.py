"""Attribute an exchange-verified long position's fills to its owned lots."""
from collections import deque
from datetime import datetime
from decimal import Decimal, ROUND_DOWN

from .delta_plan import LEGACY_CONTRACTS, TRADE1_CONTRACTS

ZERO = Decimal(0)
USD_TICK = Decimal('0.00000001')


def _timestamp(event):
    stamp = datetime.fromisoformat(event['created_at'])
    if stamp.utcoffset() is None:
        raise ValueError('Batch event has no timezone')
    return stamp


def _number(value):
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError('Batch amount is not finite')
    return number


def _quantity(value):
    quantity = _number(value)
    if quantity <= 0 or quantity != int(quantity):
        raise ValueError('Invalid batch fill quantity')
    return int(quantity)


def _unique(events):
    unique = {}
    for event in events:
        key = event.get('uuid') or event.get('id')
        if key is None or (key in unique and unique[key] != event):
            raise ValueError('Missing or conflicting batch event identity')
        unique[key] = event
    return list(unique.values())


def _allocate(amount, weights):
    """Split a posting at wallet precision and assign the residual once."""
    total = sum(weights.values())
    residual = amount
    items = list(weights.items())
    for key, weight in items[:-1]:
        share = (amount * weight / total).quantize(USD_TICK, rounding=ROUND_DOWN)
        yield key, share
        residual -= share
    if items:
        yield items[-1][0], residual


def allocate_lots(entries, fills, funding=()):
    """Return FIFO attribution for a single product from flat to flat or current."""
    if not entries:
        raise ValueError('A batch product must have owned entries')
    product_id = entries[0]['product_id']
    multiplier = _number(entries[0]['contract_value'])
    contracts = entries[0]['contracts']
    owned = {str(entry['order_id']): entry for entry in entries}
    if (len(owned) != len(entries) or multiplier <= 0
            or type(contracts) is not int or contracts not in (LEGACY_CONTRACTS, TRADE1_CONTRACTS) or any(
            entry['contracts'] != contracts or entry['product_id'] != product_id
            or _number(entry['contract_value']) != multiplier for entry in entries)):
        raise ValueError('Invalid batch product entries')
    lots = {key: dict(filled=0, exited=0, entry_value=ZERO, exit_value=ZERO,
                      entry_fee=ZERO, exit_fee=ZERO, funding=ZERO, fill_ids=[])
            for key in owned}
    events = [(_timestamp(fill), 'fill', fill) for fill in _unique(fills)]
    events += [(_timestamp(post), 'funding', post) for post in _unique(funding)]
    events.sort(key=lambda item: item[0])
    if any(before[0] == after[0] for before, after in zip(events, events[1:])):
        raise ValueError('Batch event timestamps do not establish order')
    fifo = deque()
    remaining = 0
    first_fill = closing_fill = None
    for _, kind, event in events:
        if event['product_id'] != product_id:
            raise ValueError('Batch event product differs from owned entries')
        if closing_fill is not None:
            raise ValueError('Batch event falls after the flat close')
        if kind == 'funding':
            if not remaining:
                raise ValueError('Funding falls outside the open position')
            balances = {key: lot['filled'] - lot['exited'] for key, lot in lots.items()
                        if lot['filled'] > lot['exited']}
            for key, share in _allocate(_number(event['amount']), balances):
                lots[key]['funding'] += share
            continue
        size, price, fee = _quantity(event['size']), _number(event['price']), _number(event['commission'])
        if price <= 0:
            raise ValueError('Invalid batch fill price')
        if first_fill is None:
            first_fill = event
        if event['side'] == 'buy':
            key = str(event['order_id'])
            if key not in lots or any(lot['exited'] for lot in lots.values()):
                raise ValueError('Unowned entry or entry after exits began')
            lot = lots[key]
            lot['filled'] += size
            if lot['filled'] > owned[key]['contracts']:
                raise ValueError('Entry exceeds intended lot size')
            lot['entry_value'] += size * price
            lot['entry_fee'] += fee
            lot['fill_ids'].append(event['id'])
            fifo.append((key, size))
            remaining += size
        elif event['side'] == 'sell':
            if size > remaining:
                raise ValueError('Exit exceeds owned batch quantity')
            units = size
            allocations = {}
            while units:
                key, available = fifo.popleft()
                used = min(units, available)
                allocations[key] = allocations.get(key, 0) + used
                if available > used:
                    fifo.appendleft((key, available - used))
                units -= used
            for key, share in _allocate(fee, allocations):
                lot = lots[key]
                used = allocations[key]
                lot['exited'] += used
                lot['exit_value'] += used * price
                lot['exit_fee'] += share
                lot['fill_ids'].append(event['id'])
            remaining -= size
            if remaining == 0:
                closing_fill = event
        else:
            raise ValueError('Unrecognized batch fill side')
        position = (event.get('meta_data') or {}).get('new_position') or {}
        if position.get('size') != remaining:
            raise ValueError('Batch inventory disagrees with exchange fill')

    rows = {}
    for key, lot in lots.items():
        filled, exited = lot['filled'], lot['exited']
        charges = lot['entry_fee'] + lot['exit_fee']
        gross = ((lot['exit_value'] - lot['entry_value']) * multiplier
                 if closing_fill is not None else None)
        rows[key] = dict(
            filled_contracts=filled, remaining_contracts=filled-exited, exited_contracts=exited,
            entry=str(lot['entry_value']/filled) if filled else None,
            exit=str(lot['exit_value']/exited) if exited else None,
            entry_commission=str(lot['entry_fee']), actual_commission=str(charges),
            funding=str(lot['funding']), gross_pnl=None if gross is None else str(gross),
            net_pnl=None if gross is None else str(gross-charges+lot['funding']),
            fill_ids=lot['fill_ids'],
        )
    return dict(lots=rows, remaining_contracts=remaining,
                first_fill_id=first_fill['id'] if first_fill else None,
                closing_fill_id=closing_fill['id'] if closing_fill else None,
                closed_at=closing_fill['created_at'] if closing_fill else None,
                net_pnl=None if closing_fill is None else str(sum(
                    (Decimal(row['net_pnl']) for row in rows.values()), ZERO)))
