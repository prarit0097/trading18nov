"""Read-only Delta demo reconciliation. This module never places an order."""
import argparse
import asyncio
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal as D
from functools import partial
import json
import time
import hashlib
import math
import os
from pathlib import Path
import tempfile
from .core import Workspace
from .delta_plan import (LEGACY_CONTRACTS, MIN_BATCH_COINS, TRADE1_CONTRACTS,
                         campaign_state, eligible_completed_trade)
from .delta_quota import entry_hold_reason, quota_allows_entry, read_weekly_quota
from .delta_execution import BATCH_POLICY, OrderJournal, execute_batch, execute_entry, verified_protection
from .delta_history_archive import (complete_pages, history_account, publish_verified_history,
                                    read_reconciliation_history, reconciliation_windows, timestamp_us)
from .delta_signal import batch_products, preview, preview_batch, scan
from .delta_research import record_manager_review, refresh_manager_handoffs
from .delta_batch_lots import allocate_lots
from .delta_batch_research import BATCH_SIZE, review_batch


TRADE1_POLICY_SUFFIX = '+trade1-3c-10m-v2'
TRADE1_BASELINE = BATCH_POLICY + TRADE1_POLICY_SUFFIX
TRADE1_PREVIOUS_BASELINE = 'delta-demo-liquid-four-v5+trade1-10m-v1'


class DeltaCallError(RuntimeError):
    """The MCP server reported an exchange or transport error."""


def inclusive_history_start(when):
    """Adapt an inclusive instant to Delta's exclusive start_time_us."""
    return timestamp_us(when)-1


def review(rows):
    closed=[r for r in rows if r['status']=='closed' and r.get('net_pnl') is not None]
    keys=[r['order_id'] for r in closed if 'order_id' in r]
    if len(keys)!=len(set(keys)):
        raise ValueError('Duplicate trade order ID')
    if any(not D(r['net_pnl']).is_finite() for r in closed):
        raise ValueError('Non-finite realized P&L')
    closed.sort(key=lambda r:r.get('closed_at',r.get('opened_at','')))
    strategy=[r for r in closed if r['classification']=='strategy']
    n=len(strategy); wins=sum(D(r['net_pnl'])>0 for r in strategy)
    interval=None
    if n and not any(r.get('batch_id') for r in strategy):
        p=wins/n; z=1.95996398454; divisor=1+z*z/n
        center=(p+z*z/(2*n))/divisor
        radius=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/divisor
        interval=[center-radius,center+radius]
    values=[D(r['net_pnl']) for r in closed]
    positive=sum((v for v in values if v>0),D(0))
    negative=-sum((v for v in values if v<0),D(0))
    equity=peak=drawdown=D(0)
    for v in values:
        equity+=v; peak=max(peak,equity); drawdown=max(drawdown,peak-equity)
    return dict(closed=len(closed),goal=10000,review_batches_due=sum(map(reviewable, closed))//BATCH_SIZE,
                wins=sum(v>0 for v in values),losses=sum(v<0 for v in values),
                breakevens=sum(v==0 for v in values),
                strategy_sample=n,strategy_win_rate=wins/n if n else None,
                wilson_95=interval,net_pnl=str(sum(values,D(0))),
                mean_net_pnl=str(sum(values,D(0))/len(values)) if values else None,
                profit_factor=str(positive/negative) if negative else None,
                max_closed_trade_drawdown=str(drawdown),auto_promote=False)


def reviewable(row):
    if row.get('campaign_id') == 'trade1':
        return eligible_completed_trade(row)
    return (row['status'] == 'closed' and row.get('net_pnl') is not None
            and row.get('filled_contracts', LEGACY_CONTRACTS) == LEGACY_CONTRACTS)


def batch_reviews(rows,processed):
    closed=sorted(filter(reviewable, rows),
                  key=lambda r:(r['closed_at'],r['order_id']))
    output=[]
    for offset in range(0,len(closed)-BATCH_SIZE+1,BATCH_SIZE):
        batch=closed[offset:offset+BATCH_SIZE]
        ids=[r['order_id'] for r in batch]
        key=hashlib.sha256(json.dumps(sorted(ids)).encode()).hexdigest()
        if key in processed: continue
        output.append(dict(batch_id=key,sequence=offset//BATCH_SIZE+1,order_ids=ids,
                           **_review_statistics(batch),status='research_required',auto_promote=False))
    return output


def _review_statistics(batch):
    versions=sorted(set(r['strategy_version'] for r in batch))
    return dict(statistics=review(batch),
                per_version={v:review([r for r in batch if r['strategy_version']==v]) for v in versions})


def refresh_batch_reviews(queue, rows):
    """Keep finalized ten-order membership stable across late postings and revisions."""
    by_order = {row['order_id']:row for row in rows}
    assigned = set()
    batches = queue['batches']
    for batch in batches:
        ids = batch['order_ids']
        assigned.update(ids)
        members = [by_order[key] for key in ids if key in by_order]
        if len(members) == BATCH_SIZE and all(map(reviewable, members)):
            batch.update(_review_statistics(members), settlement_verified=True)
        else:
            batch['settlement_verified'] = False
    for batch in batch_reviews((row for row in rows if row['order_id'] not in assigned), ()):
        batch.update(sequence=len(batches)+1, settlement_verified=True)
        batches.append(batch)


def refresh_campaign_reviews(queue, rows, as_of):
    """Review consecutive settled eligible trades without modifying historic reviews."""
    campaign = queue.setdefault('campaign_reviews', {'batches': []})
    eligible = [row for row in rows if eligible_completed_trade(row)]
    refresh_batch_reviews(campaign, eligible)
    refresh_manager_handoffs(campaign, eligible, as_of, campaign=True)
    return campaign


def settled_net(transactions, gross, commission, *, funding_complete=False):
    """Finalize only when wallet fees and realized settlements reconcile fills."""
    if not funding_complete:
        return None
    allowed={'commission','funding','settlement'}
    if any(t['transaction_type'] not in allowed for t in transactions):
        return None
    if not all(D(v).is_finite() for v in [gross, commission, *(t['amount'] for t in transactions)]):
        return None
    fees=-sum((D(t['amount']) for t in transactions if t['transaction_type']=='commission'),D(0))
    pnl=sum((D(t['amount']) for t in transactions if t['transaction_type']=='settlement'),D(0))
    tolerance=D('.00000001')
    if abs(fees-D(commission))>tolerance or abs(pnl-D(gross))>tolerance:
        return None
    return str(sum((D(t['amount']) for t in transactions),D(0)))


def atomic_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data,indent=2),encoding='utf-8')
    temporary.replace(path)


def _wallet_proves_flat_funding(transactions, wallet, first_fill, closing_fill, *, gross):
    """Verify the product's funding against the shared USD wallet balance chain."""
    def timestamp(row):
        return datetime.fromisoformat(row['created_at'])

    product_postings = sorted(transactions, key=timestamp)
    # Delta can omit the cashflow posting when the realized price difference is exactly zero.
    if len(product_postings) < (2 if gross == 0 else 3):
        return False
    first, last = product_postings[0], product_postings[-1]
    for posting, fill in ((first, first_fill), (last, closing_fill)):
        if (posting['transaction_type'] != 'commission'
                or (posting.get('meta_data') or {}).get('fill_uuid') != fill['id']):
            return False
    try:
        after_close = [posting for posting in product_postings if timestamp(posting)>timestamp(closing_fill)]
        if any(posting['transaction_type']=='funding' for posting in after_close):
            # Delta can post accrued funding immediately before the closing cashflow and fee.
            if (len(after_close)<3 or after_close[-1]!=last
                    or after_close[-2]['transaction_type'] not in ('cashflow','settlement')
                    or any(posting['transaction_type']!='funding' for posting in after_close[:-2])):
                return False
            cashflow = after_close[-2].get('meta_data') or {}
            if (D(str(cashflow.get('exit_price'))) != D(str(closing_fill['price']))
                    or D(str(cashflow.get('position_size'))) != D(str(closing_fill['size']))):
                return False
        start, end = timestamp(first), timestamp(last)
        unique = {}
        for posting in wallet:
            if not start <= timestamp(posting) <= end:
                continue
            key = posting.get('uuid') or posting.get('id')
            if key is None or (key in unique and unique[key] != posting):
                return False
            unique[key] = posting
        chain = sorted(unique.values(), key=timestamp)
        if not chain or chain[0] != first or chain[-1] != last:
            return False
        balances = [D(t['balance']) for t in chain]
        amounts = [D(t['amount']) for t in chain]
    except (ArithmeticError, KeyError, TypeError):
        return False
    return (all(v.is_finite() for v in balances + amounts)
            and all(before + amount == after
                    for before, amount, after in zip(balances, amounts[1:], balances[1:])))


def _event_time(row):
    return datetime.fromisoformat(row['created_at'])


class ReconciliationHistory:
    """Index a single exchange snapshot by product, order and posting time."""

    def __init__(self, fills, wallet):
        unique = defaultdict(dict)
        self.conflicts = set()
        self.fills_by_id = defaultdict(list)
        for fill in fills:
            product = fill['product_id']
            fill_id = fill['id']
            if fill_id in unique[product] and unique[product][fill_id] != fill:
                self.conflicts.add(product)
            unique[product][fill_id] = fill
            self.fills_by_id[fill_id].append(fill)

        self.fills = {}
        self.entry_index = {}
        for product, by_id in unique.items():
            if product in self.conflicts:
                continue
            ordered = sorted(by_id.values(), key=_event_time)
            self.fills[product] = ordered
            for index, fill in enumerate(ordered):
                self.entry_index.setdefault((product, str(fill['order_id'])), index)
        self.wallet = sorted(wallet, key=_event_time)

    def postings(self, start, end=None, *, inclusive=False):
        first = bisect_left(self.wallet, start, key=_event_time)
        if end is None:
            return self.wallet[first:]
        boundary = bisect_right if inclusive else bisect_left
        last = boundary(self.wallet, end, lo=first, key=_event_time)
        return self.wallet[first:last]


def reconcile_trade(trade, fills, wallet, positions, *, entry_contracts=None, indexed=None):
    """Reconcile an owned position against fills and wallet postings."""
    row = dict(trade, status='reconciliation_pending', net_pnl=None, exit=None,
               unrealized_pnl=None)
    for key in ('closed_at', 'provisional_net_pnl', 'reconciliation_reason'):
        row.pop(key, None)

    def pending(reason):
        return dict(row, reconciliation_reason=reason)

    product = trade['product_id']
    history_index = indexed if indexed is not None else ReconciliationHistory(fills, wallet)
    if product in history_index.conflicts:
        return pending('Conflicting fill for the same ID')
    history = history_index.fills.get(product, ())
    allowed = {trade['order_id']:trade['contracts']} if entry_contracts is None else entry_contracts
    by_order = {key:D(0) for key in allowed}
    start = min((history_index.entry_index[(product, key)] for key in allowed
                 if (product, key) in history_index.entry_index), default=None)
    if start is None:
        return pending('Missing entry fill')
    direction = 1 if trade['position'] == 'long' else -1
    entry_side = 'buy' if direction == 1 else 'sell'
    opened = exited = entry_total = exit_total = fees = entry_fees = D(0)
    close_index = None
    for i in range(start, len(history)):
        fill = history[i]
        quantity, price, fee = (D(str(fill[k])) for k in ('size', 'price', 'commission'))
        if (not all(x.is_finite() for x in (quantity, price, fee))
                or quantity <= 0 or quantity != quantity.to_integral_value() or price <= 0):
            return pending('Invalid fill quantity, price or fee')
        if fill['side'] == entry_side:
            key = str(fill['order_id'])
            if key not in allowed or exited:
                return pending('Another entry overlaps the owned position')
            by_order[key] += quantity
            if by_order[key] > allowed[key]:
                return pending('Filled contracts exceed the registered order quantity')
            opened += quantity
            entry_total += quantity * price
            entry_fees += fee
        elif fill['side'] in ('buy', 'sell'):
            exited += quantity
            exit_total += quantity * price
        else:
            return pending('Unknown fill side')
        remaining = opened - exited
        after = (fill.get('meta_data') or {}).get('new_position') or {}
        if remaining < 0 or opened > trade['contracts'] or after.get('size') != direction * remaining:
            return pending('Fill sizes do not match the exchange position lifecycle')
        fees += fee
        if remaining == 0:
            close_index = i
            break
    if entry_contracts is not None and by_order != entry_contracts:
        return pending('Exchange fills have not reached the journaled batch quantities')
    row.update(entry=str(entry_total / opened), filled_contracts=int(opened),
               entry_commission=str(entry_fees), actual_commission=str(fees),
               fill_ids=[f['id'] for f in history[start:(close_index + 1 if close_index is not None else None)]])
    if close_index is None:
        current = [p for p in positions if p['product_id'] == product and D(str(p['size'])) != 0]
        if len(current) != 1 or D(str(current[0]['size'])) != direction * remaining:
            return pending('Open position and fill quantities disagree')
        return dict(row, status='open', remaining_contracts=int(remaining),
                    unrealized_pnl=current[0].get('unrealized_pnl'))

    close = history[close_index]
    start_time = datetime.fromisoformat(history[start]['created_at'])
    next_time = (datetime.fromisoformat(history[close_index + 1]['created_at'])
                 if close_index + 1 < len(history) else None)
    tx = {}
    postings = history_index.postings(start_time, next_time)
    for item in postings:
        if item.get('product_id') != product:
            continue
        key = item.get('uuid') or item.get('id')
        if key is None or (key in tx and tx[key] != item):
            return pending('Wallet transaction identity is missing or inconsistent')
        tx[key] = item
    cashflows = [dict(t, transaction_type='settlement') if t['transaction_type']=='cashflow' else t
                 for t in tx.values()]
    gross = (exit_total - entry_total) * D(trade['contract_value']) * direction
    funding = sum((D(t['amount']) for t in cashflows if t['transaction_type']=='funding'), D(0))
    expected_funding = close['meta_data']['new_position'].get('realized_funding')
    funding_complete = expected_funding is not None and funding == D(expected_funding)
    if not funding_complete and (expected_funding is None or D(expected_funding) == 0):
        funding_complete = _wallet_proves_flat_funding(tx.values(), postings, history[start], close, gross=gross)
    final = settled_net(cashflows, gross, fees, funding_complete=funding_complete)
    row.update(exit=str(exit_total / exited), closed_at=close['created_at'])
    if final is None:
        return pending('Closing fill, commissions or funding do not reconcile with the wallet')
    return dict(row, status='closed', net_pnl=final, funding=str(funding))


def reconcile_batch_position(entries, fills, wallet, positions, orders, *, indexed=None):
    """Reconcile one netted product, then publish its per-order FIFO attribution."""
    def pending(reason):
        return [dict(row, status='reconciliation_pending', net_pnl=None, unrealized_pnl=None,
                     reconciliation_reason=reason) for row in entries]

    first = entries[0]
    if any((e['product_id'], e['stop_loss'], e['target'], e['contract_value'])
           != (first['product_id'], first['stop_loss'], first['target'], first['contract_value'])
           for e in entries):
        return pending('Batch orders disagree about shared product or exit terms')
    expected = {e['order_id']:e['expected_filled_contracts'] for e in entries}
    if len(expected) != len(entries) or any(
            type(e['expected_filled_contracts']) is not int
            or not 1 <= e['expected_filled_contracts'] <= e['contracts'] for e in entries):
        return pending('Batch must contain unique orders with verified positive fill quantities')
    history_index = indexed if indexed is not None else ReconciliationHistory(fills, wallet)
    aggregate = reconcile_trade(dict(first, contracts=sum(expected.values())),
                                fills, wallet, positions, entry_contracts=expected, indexed=history_index)
    if aggregate['status'] not in ('closed', 'open'):
        return pending(aggregate['reconciliation_reason'])

    episode_fills = [fill for fill_id in aggregate['fill_ids']
                     for fill in history_index.fills_by_id[fill_id]]
    closed = aggregate['status'] == 'closed'
    single_closed_lot = closed and len(entries)==1
    funding = []
    if not single_closed_lot:
        start = min(map(_event_time, episode_fills))
        end = datetime.fromisoformat(aggregate['closed_at']) if closed else None
        funding = [tx for tx in history_index.postings(start, end, inclusive=True)
                   if tx.get('product_id') == first['product_id'] and tx.get('transaction_type') == 'funding']
    try:
        allocation = allocate_lots(entries, episode_fills, funding)
    except (ValueError, ArithmeticError, KeyError, TypeError) as error:
        return pending(str(error))
    if single_closed_lot:
        lot = allocation['lots'][first['order_id']]
        lot['funding'] = aggregate['funding']
        lot['net_pnl'] = str(D(lot['net_pnl'])+D(lot['funding']))
        allocation['net_pnl'] = lot['net_pnl']
    if closed and D(allocation['net_pnl']) != D(aggregate['net_pnl']):
        return pending('Allocated lot P&L does not match the exchange wallet')
    covered = not closed and verified_protection(aggregate, orders)
    output = []
    for entry in entries:
        lot = allocation['lots'][entry['order_id']]
        row = dict(entry)
        unrealized = aggregate['unrealized_pnl'] if not closed and len(entries) == 1 else None
        row.update(lot, status=aggregate['status'], unrealized_pnl=unrealized,
                   protection_verified=covered)
        row.pop('reconciliation_reason', None)
        if closed:
            row['closed_at'] = aggregate['closed_at']
        output.append(row)
    return output


def record_cohort_reviews(queue, rows, *, contracts=LEGACY_CONTRACTS):
    """Refresh descriptive reviews without changing saved entry evidence."""
    cohorts = {}
    for row in rows:
        if row.get('batch_id'):
            cohorts.setdefault(row['batch_id'], []).append(row)
    saved = queue.setdefault('execution_cohorts', {})
    for batch_id, cohort in cohorts.items():
        if len(cohort) != BATCH_SIZE or any(row['status'] != 'closed'
                                           or row.get('filled_contracts') != contracts for row in cohort):
            continue
        saved[batch_id] = review_batch(
            cohort, expected_entry_fingerprint=saved.get(batch_id, {}).get('entry_fingerprint'),
            contracts=contracts)


def campaign_paths(root, campaign_id):
    if campaign_id not in ('legacy', 'trade1'):
        raise ValueError('Unknown Delta demo campaign')
    legacy = Path(root)/'runs/delta-demo-loop'
    return (legacy.parent/'trade1' if campaign_id == 'trade1' else legacy), legacy


def initialize_trade1(run):
    """Create the fresh journal once, before permitting the first entry."""
    manifest_path = run/'campaign.json'
    if not manifest_path.exists():
        run.mkdir(parents=True, exist_ok=True)
        if (run/'entries.json').exists() and json.loads((run/'entries.json').read_text()):
            raise ValueError('Existing trade1 journal is missing its original campaign manifest')
        if (run/'ledger.json').exists():
            raise ValueError('Existing trade1 ledger is missing its original campaign manifest')
        (run/'ENTRY_HOLD').write_text('Awaiting owner start.\n', encoding='utf-8')
        atomic_json(run/'entries.json', [])
        atomic_json(manifest_path, dict(campaign_id='trade1', environment='india_testnet',
            started_at=datetime.now(timezone.utc).isoformat(), time_exit_seconds=600,
            strategy_version=TRADE1_BASELINE, contracts=TRADE1_CONTRACTS))
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest['campaign_id'] != 'trade1' or manifest['environment'] != 'india_testnet':
        raise ValueError('Invalid trade1 campaign identity')
    if not (run/'entries.json').exists():
        raise ValueError('The trade1 order journal is missing')
    if 'contracts' not in manifest and manifest['strategy_version'] == TRADE1_PREVIOUS_BASELINE:
        def saved(name, default):
            path = run/name
            return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default

        reviews = saved('reviews.json', {})
        if (not (run/'ENTRY_HOLD').is_file() or saved('entries.json', None) != []
                or saved('ledger.json', {'trades': []}).get('trades') != []
                or any(value for key, value in reviews.items() if key != 'campaign_reviews')
                or any(reviews.get('campaign_reviews', {}).values())
                or saved('time-exits.json', {}) or saved('shadows.json', {})):
            raise ValueError('Only the empty, held Trade1 campaign may switch from ten to three contracts')
        manifest.update(strategy_version=TRADE1_BASELINE, contracts=TRADE1_CONTRACTS)
        atomic_json(manifest_path, manifest)
    if type(manifest.get('contracts')) is not int or manifest['contracts'] != TRADE1_CONTRACTS:
        raise ValueError('The Trade1 manifest must specify three contracts')
    return manifest


def campaign_members(journal_rows, legacy_rows, started_at, previous_rows=()):
    known = {row['order_id'] for row in legacy_rows}
    start = datetime.fromisoformat(started_at)
    current = []
    for row in journal_rows:
        key = row['order_id']
        if (key in known or not row.get('position_episode_id') or datetime.fromisoformat(row['opened_at']) < start
                or type(row.get('contracts')) is not int or row['contracts'] != TRADE1_CONTRACTS):
            raise ValueError('Duplicate, legacy, non-batch or wrong-sized entry in trade1 journal')
        known.add(key)
        strategy_version = row.get('strategy_version', 'unknown') + TRADE1_POLICY_SUFFIX
        current.append(dict(row, campaign_id='trade1', strategy_version=strategy_version,
                            entry_policy_version=strategy_version))
    current_ids = {row['order_id'] for row in current}
    if any(row.get('campaign_id') != 'trade1' or row['order_id'] not in current_ids
           for row in previous_rows):
        raise ValueError('Trade1 journal no longer covers all previously registered entries')
    return current


def _history_arguments(entries):
    return {
        'get_fills': {'product_ids': sorted({row['product_id'] for row in entries}), 'page_size': 50},
        'get_wallet_transactions': {'asset_ids': [3], 'page_size': 200},
    }


def _delta_testnet_parameters():
    from mcp import StdioServerParameters
    return StdioServerParameters(command=str(Path.home()/'.local/bin/uvx.exe'),
        args=['delta-exchange-mcp==0.7.2'], env=dict(os.environ, DELTA_MCP_ENV='india_testnet'))


async def _call_delta(session, name, args):
    raw = (await session.call_tool(name,args)).model_dump(mode='json',by_alias=True)
    if raw.get('isError'):
        raise DeltaCallError('Delta call failed: '+name)
    return raw.get('structuredContent') or json.loads(next(c['text'] for c in raw['content'] if c['type']=='text'))


async def refresh_trade1_history_archive(root):
    """Audit prior settled days independently of the execution snapshot."""
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client
    run, legacy = campaign_paths(root, 'trade1')
    manifest = json.loads((run/'campaign.json').read_text(encoding='utf-8'))
    if manifest['campaign_id'] != 'trade1' or manifest['environment'] != 'india_testnet':
        raise ValueError('Invalid trade1 campaign identity')
    with Workspace(run).lock('history_archive_refresh'):
        previous = json.loads((run/'ledger.json').read_text(encoding='utf-8'))['trades']
        old = json.loads((legacy/'ledger.json').read_text(encoding='utf-8'))['trades']
        entries = campaign_members(OrderJournal(run/'entries.json').trades(), old, manifest['started_at'], previous)
        registered = [row for row in entries if 'product_id' in row and 'contract_value' in row]
        lower = min((inclusive_history_start(datetime.fromisoformat(row['opened_at'])) for row in registered),
                    default=0)
        windows = reconciliation_windows(lower, datetime.now(timezone.utc), registered, previous) if registered else []
        if not windows:
            return {'status': 'no_settled_past_day', 'windows': 0}
        with tempfile.TemporaryFile(mode='w+', encoding='utf-8') as err:
            async with stdio_client(_delta_testnet_parameters(), errlog=err) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    call = partial(_call_delta, session)
                    environment = (await call('get_connection_status', {}))['environment']
                    if environment != 'india_testnet':
                        raise DeltaCallError('Only india_testnet is authorized')
                    account = await history_account(call)
                    counts = await publish_verified_history(call, _history_arguments(registered), lower, windows,
                        archive_path=run/'verified-history.sqlite3', environment=environment, account=account)
        return {'status': 'verified', 'windows': len(windows), 'rows': counts}


async def snapshot(root, *, scan_signals=False, execute_demo=False, batch_preview=False, campaign_id='legacy'):
    root = Path(root)
    run, legacy = campaign_paths(root, campaign_id)
    if campaign_id == 'trade1' and execute_demo and not batch_preview:
        raise ValueError('trade1 execution requires a four-coin batch')
    with Workspace(legacy).lock('reconciliation'):
        data = await _snapshot(root, scan_signals=scan_signals or execute_demo or batch_preview,
                               execute_demo=execute_demo, batch_preview=batch_preview, campaign_id=campaign_id)
        execution = data.get('execution', {})
        if execution.get('status') == 'filled' or execution.get('filled_lots'):
            # Refresh fills, wallet, and protections after the journal has committed ownership.
            result = await _snapshot(root, campaign_id=campaign_id)
            result.update(execution=data['execution'], signals=data['signals'],
                          entry_preview=data['entry_preview'], worker_mode='demo_execution',
                          autonomous_entries_enabled=True)
            result['limits'] = data['limits']
            atomic_json(run/'ledger.json', result)
            return result
        return data


async def _snapshot(root, *, scan_signals=False, execute_demo=False, batch_preview=False, campaign_id='legacy'):
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client
    root=Path(root)
    run, legacy = campaign_paths(root, campaign_id)
    fresh = campaign_id == 'trade1'
    ledger_path = run/'ledger.json'
    legacy_path = legacy/'ledger.json'
    if fresh and not legacy_path.is_file():
        raise ValueError('The previous account ledger is required to carry forward daily risk')
    legacy_rows = json.loads(legacy_path.read_text(encoding='utf-8'))['trades'] if legacy_path.exists() else []
    if fresh:
        manifest = initialize_trade1(run)
        contracts = manifest['contracts']
        previous_rows = json.loads(ledger_path.read_text(encoding='utf-8'))['trades'] if ledger_path.exists() else []
        owned = []
    else:
        contracts = LEGACY_CONTRACTS
        original=json.loads((root/'verification/delta-btc-execution.json').read_text())
        entry=original['order_result']['result']
        manual=dict(order_id=str(entry['id']),symbol='BTCUSD',position='long',contracts=10,
            product_id=84,contract_value='.001',entry=entry['average_fill_price'],leverage=5,
            stop_loss=original['plan']['stop'],target=original['plan']['target'],
            planned_risk=original['plan']['planned_loss_with_fee_buffer'],opened_at=entry['created_at'],
            classification='manual_demo_execution_test',strategy_version='manual-v1')
        owned=[r for r in legacy_rows if r['order_id']!=manual['order_id']]+[manual]
    journal = OrderJournal(run/'entries.json')
    observed={}
    with tempfile.TemporaryFile(mode='w+',encoding='utf-8') as err:
        async with stdio_client(_delta_testnet_parameters(),errlog=err) as (read,write):
            async with ClientSession(read,write) as session:
                await session.initialize()
                call = partial(_call_delta, session)
                async def pages(name,args):
                    return await complete_pages(call,name,args)
                connection=await call('get_connection_status',{})
                if connection['environment']!='india_testnet':
                    raise RuntimeError('Only india_testnet is authorized')
                observed['unresolved_entry'] = await journal.recover(call)
                owned_by_id = {row['order_id']:row for row in owned}
                entries = (campaign_members(journal.trades(), legacy_rows, manifest['started_at'], previous_rows)
                           if fresh else journal.trades())
                for row in entries:
                    owned_by_id[row['order_id']] = row
                owned = list(owned_by_id.values())
                registered=[r for r in owned if 'product_id' in r and 'contract_value' in r]
                start = min((inclusive_history_start(datetime.fromisoformat(r['opened_at'])) for r in registered),
                            default=0)
                observed['positions']=(await call('get_margined_positions',{}))['result']
                observed['orders']=await pages('get_open_orders',{'page_size':50})
                observed['fills'], observed['transactions'] = [], []
                if registered:
                    archive_path = run/'verified-history.sqlite3' if fresh else None
                    windows = ()
                    if archive_path is not None and archive_path.is_file() and not observed['unresolved_entry']:
                        windows = reconciliation_windows(start, datetime.now(timezone.utc), registered, previous_rows)
                    history = await read_reconciliation_history(call, _history_arguments(registered), start,
                        archive_path=archive_path, windows=windows, environment=connection['environment'])
                    observed['fills'] = history['get_fills']
                    observed['transactions'] = history['get_wallet_transactions']
                indexed = ReconciliationHistory(observed['fills'], observed['transactions'])
                groups = {}
                rows = []
                for row in owned:
                    if row.get('position_episode_id'):
                        key = (row['position_episode_id'], row['product_id'])
                        groups.setdefault(key, []).append(row)
                    else:
                        rows.append(reconcile_trade(row, observed['fills'], observed['transactions'],
                                                    observed['positions'], indexed=indexed) if row in registered else row)
                for group in groups.values():
                    rows.extend(reconcile_batch_position(group, observed['fills'],
                                observed['transactions'], observed['positions'], observed['orders'], indexed=indexed))
                for row in rows:
                    if (row['status'] == 'open' and 'remaining_contracts' in row
                            and not row.get('position_episode_id')):
                        row['protection_verified'] = verified_protection(row, observed['orders'])
                rows.sort(key=lambda r:r['opened_at'])
                now=datetime.now(timezone.utc)
                if fresh and rows:
                    from .delta_time_exit import manage_time_exits
                    from .delta_shadow import refresh_trade1_shadows
                    await manage_time_exits(call, run, rows, observed, execute=execute_demo)
                    await refresh_trade1_shadows(call, rows, run/'shadows.json', now.isoformat())
                    for row in rows:
                        row['campaign_verified'] = eligible_completed_trade(row)
                queue_path=run/'reviews.json'
                queue=json.loads(queue_path.read_text()) if queue_path.exists() else {'batches':[]}
                record_cohort_reviews(queue, rows, contracts=contracts)
                campaign_reviews = refresh_campaign_reviews(queue, rows, now.isoformat())
                atomic_json(queue_path,queue)
                campaign = campaign_state(rows, observed['positions'], observed['orders'], now,
                                          other_account_trades=legacy_rows if fresh else ())
                if fresh:
                    reserved = sum((D(str(row['planned_risk'])) for row in (*rows, *legacy_rows)
                                    if row['status'] != 'closed'), D(0))
                    remaining = max(D(0), D(30) - D(campaign['daily_loss_usd']) - reserved)
                    campaign.update(reserved_open_risk_usd=str(reserved), remaining_daily_risk_usd=str(remaining),
                                    remaining_planned_risk_usd=str(min(D(10), remaining)))
                if observed['unresolved_entry']:
                    campaign['blocked'] = True
                    campaign['reasons'].append('An order with an unknown outcome needs reconciliation')
                if any(row['status'] == 'open' and not row.get('protection_verified') for row in rows):
                    campaign['blocked'] = True
                    campaign['reasons'].append('Exchange stop-loss and target coverage could not be verified')
                if scan_signals:
                    if fresh and campaign['blocked']:
                        products, observed['signals'] = [], {}
                    elif batch_preview:
                        products = await batch_products(call)
                        observed['signals'] = await scan(call, sorted({p['symbol'] for p in products}))
                    else:
                        observed['signals'] = await scan(call)
                    entry_preview = await (preview_batch(call, observed['signals'], campaign, products=products,
                                                         contracts=contracts)
                                           if batch_preview else preview(call, observed['signals'], campaign))
                if execute_demo:
                    risk_rows = legacy_rows + rows if fresh else rows
                    owned_fills = {key for row in risk_rows if row['status']=='closed' for key in row.get('fill_ids', [])}
                    async def inventory_clear():
                        day_start = datetime.fromisoformat(campaign['trading_day_ist']+'T00:00:00+05:30')
                        if datetime.now(timezone.utc).timestamp() >= day_start.timestamp() + 86400:
                            return False
                        fresh_fills = await pages('get_fills', {
                            'start_time_us':inclusive_history_start(day_start), 'page_size':50})
                        if any(fill['id'] not in owned_fills for fill in fresh_fills):
                            return False
                        positions = (await call('get_margined_positions', {}))['result']
                        orders = await pages('get_open_orders', {'page_size':50})
                        return not orders and all(D(str(p['size'])) == 0 for p in positions)

                    run = ledger_path.parent
                    hold = entry_hold_reason(run)
                    review_due = any(
                        item['status'] == 'awaiting_manager'
                        for item in queue.get('campaign_reviews', {}).get('manager_handoffs', {}).values()
                    )
                    if hold:
                        execution = {'status': hold}
                    elif review_due:
                        execution = {'status': 'campaign_review_due'}
                    elif entry_preview['status'] != 'planned':
                        execution = {'status': entry_preview['status']}
                    else:
                        quota = await read_weekly_quota()
                        if not quota_allows_entry(quota, now=time.time()):
                            status = quota['status'] if quota['status'] != 'available' else 'weekly_quota_unavailable'
                            execution = {'status': status}
                        else:
                            def stopped():
                                return entry_hold_reason(run) or not quota_allows_entry(quota, now=time.time())

                            if batch_preview:
                                execution = await execute_batch(call, pages, journal, entry_preview,
                                    observed['signals'], campaign, inventory_clear, stopped, contracts=contracts)
                            else:
                                execution = await execute_entry(call, journal, entry_preview, observed['signals'],
                                                                campaign, inventory_clear, stopped)
                        execution['weekly_quota'] = quota
    data=dict(as_of=now.isoformat(),environment='india_testnet',
        worker_mode='read_only',autonomous_entries_enabled=False,trades=rows,review=review(rows),
        campaign=campaign,
        limits=dict(contracts=contracts,risk_usd=10,daily_loss_usd=30,
                    max_positions=MIN_BATCH_COINS if batch_preview else 1,
                    minimum_distinct_coins=MIN_BATCH_COINS if batch_preview else 1,target_closed=10000),
        raw=observed)
    if scan_signals:
        data['signals'] = observed['signals']
        data['entry_preview'] = entry_preview
    handoffs = campaign_reviews['manager_handoffs']
    if fresh:
        data['campaign_id'] = campaign_id
        data['baseline_version'] = manifest['strategy_version']
        data['limits'].update(max_positions=MIN_BATCH_COINS, minimum_distinct_coins=MIN_BATCH_COINS)
    data['campaign_reviews'] = dict(
        groups=len(handoffs),
        awaiting_manager=[key for key, item in handoffs.items() if item['status']=='awaiting_manager'],
        reviewed=sum(item['status']=='reviewed' and item['settlement_verified'] for item in handoffs.values()),
    )
    if 'forward_research' in queue:
        data['forward_research'] = queue['forward_research']
    if execute_demo:
        data.update(execution=execution, worker_mode='demo_execution', autonomous_entries_enabled=True)
    atomic_json(ledger_path,data)
    return data


def save_manager_review(root, report, campaign_id='legacy'):
    run, legacy = campaign_paths(root, campaign_id)
    path = run/'reviews.json'
    with Workspace(legacy).lock('reconciliation'):
        queue = json.loads(path.read_text(encoding='utf-8'))
        review_id = report['review_id']
        campaign = queue.get('campaign_reviews', {})
        reviews = campaign if review_id in campaign.get('manager_handoffs', {}) else queue
        record_manager_review(reviews, review_id, report['evidence_sha256'], report,
                              datetime.now(timezone.utc).isoformat())
        atomic_json(path, queue)
        return reviews['manager_handoffs'][review_id]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--campaign', choices=('legacy', 'trade1'), default='legacy')
    parser.add_argument('--scan-signals', action='store_true')
    parser.add_argument('--preview-batch', action='store_true', help='Plan simultaneous demo entries without sending orders')
    parser.add_argument('--record-manager-review', type=Path,
                        help='Save a manager report keyed by review_id and evidence_sha256')
    parser.add_argument('--refresh-history-archive', action='store_true',
                        help='Verify and publish completed Trade 1 IST history days without sending orders')
    args=parser.parse_args()
    if args.refresh_history_archive:
        if args.campaign != 'trade1' or args.record_manager_review or args.scan_signals or args.preview_batch:
            parser.error('--refresh-history-archive requires --campaign trade1 and no other action')
        print(json.dumps(asyncio.run(refresh_trade1_history_archive(args.root))))
        return
    if args.record_manager_review:
        report = json.loads(args.record_manager_review.read_text(encoding='utf-8'))
        saved = save_manager_review(args.root, report, args.campaign)
        print(json.dumps(dict(status=saved['status'], reviewed_at=saved['reviewed_at'])))
        return
    data=asyncio.run(asyncio.wait_for(snapshot(args.root, scan_signals=args.scan_signals,
                                               batch_preview=args.preview_batch, campaign_id=args.campaign),timeout=55))
    print(json.dumps({k:v for k,v in data.items() if k!='raw'}))


if __name__=='__main__': main()
