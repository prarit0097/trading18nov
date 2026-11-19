"""Review actual ten-lot batches and select prospective validation cohorts."""

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json

from .delta_plan import LEGACY_CONTRACTS

BATCH_SIZE = 10
SIGNAL_STATUSES = ('ready', 'waiting', 'unavailable')
ENTRY_FIELDS = (
    'batch_id', 'batch_slot', 'order_id', 'symbol', 'entry_policy_version',
    'entry_observed_at', 'signal_status_at_entry', 'opened_at',
)


def _timestamp(value):
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError('Batch timestamps must include an offset')
    return result.astimezone(timezone.utc)


def _net_metrics(values):
    return dict(lots=len(values), net_pnl_usd=str(sum(values, Decimal(0))),
                wins=sum(value > 0 for value in values),
                losses=sum(value < 0 for value in values),
                breakevens=sum(value == 0 for value in values))


def review_batch(rows, *, expected_entry_fingerprint=None, contracts=LEGACY_CONTRACTS):
    """Report descriptive P&L for a batch of ten fully settled, same-sized lots."""
    rows = sorted(rows, key=lambda row: row['batch_slot'])
    slots = [row['batch_slot'] for row in rows]
    if any(type(slot) is not int for slot in slots) or slots != list(range(1, BATCH_SIZE + 1)):
        raise ValueError('A complete review requires ten distinct batch slots')
    batch_ids = {row['batch_id'] for row in rows}
    policies = {row['entry_policy_version'] for row in rows}
    if len(batch_ids) != 1 or len(policies) != 1 or not all(batch_ids | policies):
        raise ValueError('Batch ID and entry policy must be consistent')
    if len({row['order_id'] for row in rows}) != BATCH_SIZE:
        raise ValueError('Orders in a batch must be distinct')
    values = []
    by_status = defaultdict(list)
    opened_times = []
    closed_times = []
    for row in rows:
        if row['status'] != 'closed' or row.get('filled_contracts') != contracts:
            raise ValueError(f'A complete review requires ten finalized {contracts}-contract lots')
        opened = _timestamp(row['opened_at'])
        closed = _timestamp(row['closed_at'])
        if _timestamp(row['entry_observed_at']) > opened or closed < opened:
            raise ValueError('Entry evidence must predate or coincide with the fill, and close must follow')
        status = row['signal_status_at_entry']
        if status not in SIGNAL_STATUSES:
            raise ValueError('Unknown recorded signal status')
        pnl = Decimal(row['net_pnl'])
        if not pnl.is_finite():
            raise ValueError('Non-finite batch net P&L')
        values.append(pnl)
        by_status[status].append(pnl)
        opened_times.append(opened)
        closed_times.append(closed)

    evidence = [[row[field] for field in ENTRY_FIELDS] for row in rows]
    fingerprint = hashlib.sha256(json.dumps(evidence, separators=(',', ':')).encode()).hexdigest()
    if expected_entry_fingerprint is not None and fingerprint != expected_entry_fingerprint:
        raise ValueError('Saved batch entry evidence changed')
    return dict(
        batch_id=rows[0]['batch_id'], entry_policy_version=rows[0]['entry_policy_version'],
        first_opened_at=min(opened_times).isoformat(), last_closed_at=max(closed_times).isoformat(),
        entry_fingerprint=fingerprint, order_ids=[row['order_id'] for row in rows],
        by_signal_status={status:_net_metrics(nums) for status, nums in sorted(by_status.items())},
        **_net_metrics(values),
    )


def validation_batches(rows, *, frozen_at, policy_version=None, contracts=LEGACY_CONTRACTS):
    """Select complete post-freeze cohorts with disjoint exposure windows.

    Pass rows for all policies. Overlaps across policies are excluded before
    the optional policy filter is applied. Disjoint windows do not establish
    independence or remove selection bias.
    """
    frozen = _timestamp(frozen_at)
    groups = defaultdict(list)
    seen_orders = set()
    for row in rows:
        if not row.get('batch_id'):
            continue
        if row['order_id'] in seen_orders:
            raise ValueError('Order is registered in more than one batch row')
        seen_orders.add(row['order_id'])
        groups[row['batch_id']].append(row)
    exposure = []
    for batch_id, group in groups.items():
        opened = min(_timestamp(row['opened_at']) for row in group)
        closed = (max(_timestamp(row['closed_at']) for row in group)
                  if all(row['status'] == 'closed' for row in group)
                  else datetime.max.replace(tzinfo=timezone.utc))
        exposure.append((opened, closed, batch_id))

    eligible = []
    # An overlap cluster can include different policies and unfinished batches.
    # Retain only singleton windows, so overlapping lots cannot inflate the sample.
    exposure.sort()
    previous_max_close = datetime.min.replace(tzinfo=timezone.utc)
    for index, (opened, closed, batch_id) in enumerate(exposure):
        overlaps_earlier = opened < previous_max_close
        previous_max_close = max(previous_max_close, closed)
        overlaps_later = index + 1 < len(exposure) and exposure[index + 1][0] < closed
        if overlaps_earlier or overlaps_later:
            continue
        group = groups[batch_id]
        if (opened <= frozen or len(group) != BATCH_SIZE
                or any(row['status'] != 'closed' or row.get('filled_contracts') != contracts
                       for row in group)
                or any(_timestamp(row['entry_observed_at']) <= frozen for row in group)):
            continue
        report = review_batch(group, contracts=contracts)
        if policy_version is None or report['entry_policy_version'] == policy_version:
            eligible.append(report)
    return eligible
