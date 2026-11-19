"""Delta demo research, settled review evidence and review decisions."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from math import comb
import hashlib
import json

from .delta_signal import VERSION
from .delta_plan import LEGACY_CONTRACTS, eligible_completed_trade


SPECIALIST_TRACKS = (
    'market_data', 'entry_exit', 'risk_costs', 'execution', 'reconciliation_validation',
)


def _campaign_metrics(values):
    total = sum(values, Decimal(0))
    largest_win = max((value for value in values if value > 0), default=None)
    largest_loss = min((value for value in values if value < 0), default=None)
    equity = peak = drawdown = Decimal(0)
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return dict(net_pnl_usd=str(total), mean_net_pnl_usd=str(total / len(values)),
                wins=sum(value > 0 for value in values),
                losses=sum(value < 0 for value in values),
                breakevens=sum(value == 0 for value in values),
                largest_win_usd=str(largest_win) if largest_win is not None else None,
                largest_loss_usd=str(largest_loss) if largest_loss is not None else None,
                without_largest_win_usd=str(total - largest_win) if largest_win is not None else str(total),
                max_drawdown_usd=str(drawdown))


def compared_exits(evidence):
    comparisons = {}
    for cap in (15, 30):
        actual, modeled = [], []
        pending = 0
        for row in evidence:
            alt = next((a for a in row.get('shadow_exits', []) if a['minutes'] == cap), {})
            if alt.get('status') in ('estimated', 'actual_early_exit'):
                actual.append(Decimal(row['net_pnl']))
                modeled.append(Decimal(alt['net_pnl']))
            elif alt.get('status') == 'pending':
                pending += 1
        n = len(actual)
        comparisons[str(cap)] = dict(pairs=n, pending=pending, unavailable=len(evidence)-pending-n,
            actual_win_rate=sum(v>0 for v in actual)/n if n else None,
            modeled_win_rate=sum(v>0 for v in modeled)/n if n else None,
            mean_paired_change_usd=str((sum(modeled)-sum(actual))/n) if n else None)
    return comparisons


def freeze(batch_id, as_of):
    return dict(batch_id=batch_id, version='delta-5m-breakout20-rvol15-v1',
                baseline_version=VERSION, frozen_at=as_of, min_rvol='1.5',
                minimum_trades=30, minimum_retained=10, minimum_skipped=10,
                minimum_nonzero_days=10, alpha=0.05)


def assess(candidate, rows):
    """Evaluate a skip-only filter against actual subsequent baseline fills."""
    frozen = datetime.fromisoformat(candidate['frozen_at'])
    ist = timezone(timedelta(hours=5, minutes=30))
    eligible = sorted(
        (row for row in rows if row['classification']=='strategy'
         and row['strategy_version']==candidate['baseline_version']
         and datetime.fromisoformat(row['opened_at']) > frozen),
        key=lambda row: (datetime.fromisoformat(row['opened_at']), row['order_id']),
    )
    sample = []
    for row in eligible:
        if row['status'] != 'closed':
            break
        full = (eligible_completed_trade(row) if row.get('campaign_id') == 'trade1'
                else row.get('filled_contracts') == LEGACY_CONTRACTS)
        if full and 'signal' in row:
            sample.append(row)
        if len(sample) == candidate['minimum_trades']:
            break
    baseline = filtered = Decimal(0)
    retained = wins = retained_wins = 0
    days = {}
    for row in sample:
        pnl = Decimal(row['net_pnl'])
        rvol = Decimal(row['signal']['rvol'])
        if not pnl.is_finite() or not rvol.is_finite() or rvol < 0:
            raise ValueError('Invalid forward validation observation')
        baseline += pnl
        wins += pnl > 0
        if rvol >= Decimal(candidate['min_rvol']):
            filtered += pnl
            retained += 1
            retained_wins += pnl > 0
        else:
            day = datetime.fromisoformat(row['opened_at']).astimezone(ist).date().isoformat()
            days[day] = days.get(day, Decimal(0)) - pnl
    nonzero_days = sum(v != 0 for v in days.values())
    improved_days = sum(v > 0 for v in days.values())
    p_value = (sum(comb(nonzero_days, k) for k in range(improved_days, nonzero_days + 1))
               / 2**nonzero_days if nonzero_days else None)
    status = 'collecting'
    if len(sample) >= candidate['minimum_trades']:
        enough = (retained >= candidate['minimum_retained']
                  and len(sample) - retained >= candidate['minimum_skipped']
                  and nonzero_days >= candidate['minimum_nonzero_days'])
        passes = (enough and filtered > max(0, baseline)
                  and retained_wins * len(sample) > wins * retained
                  and p_value is not None and p_value <= candidate['alpha'])
        status = 'passes_forward_screen' if passes else ('rejected' if enough else 'insufficient_sample')
    return dict(status=status, observations=len(sample), retained=retained, skipped=len(sample)-retained,
                baseline_net_usd=str(baseline), filtered_net_usd=str(filtered),
                baseline_win_rate=wins/len(sample) if sample else None,
                filtered_win_rate=retained_wins/retained if retained else None,
                nonzero_ist_days=nonzero_days, day_sign_test_p=p_value,
                order_ids=[row['order_id'] for row in sample], auto_promote=False,
                scope='Skip-only comparison on recorded baseline orders; no replacement entries modeled')


def advance(queue, rows, as_of):
    batches = queue['batches']
    if not batches:
        return
    research = queue.setdefault('forward_research', {'candidate':freeze(batches[0]['batch_id'], as_of)})
    research['validation'] = assess(research['candidate'], rows)
    for batch in batches:
        batch['status'] = 'reviewed'
        batch['candidate_version'] = research['candidate']['version']
        batch['next_action'] = 'Track the frozen candidate against subsequent baseline fills'


def refresh_manager_handoffs(queue, rows, as_of, *, campaign=False):
    """Persist manager work from finalized reviews without re-queuing unchanged evidence."""
    fields = ('order_id', 'symbol', 'batch_id', 'position_episode_id', 'classification',
              'strategy_version', 'signal_status_at_entry', 'signal', 'turnover_usd_at_entry', 'filled_contracts',
              'opened_at', 'closed_at', 'planned_risk', 'actual_commission', 'funding', 'net_pnl')
    if campaign:
        fields += ('position', 'entry', 'exit', 'leverage', 'stop_loss', 'target',
                   'gross_pnl', 'fill_ids', 'protection_verified', 'first_fill_at', 'deadline_at',
                   'close_submitted_at', 'close_delay_seconds', 'exit_order_ids', 'exit_reason', 'shadow_exits')
    assigned = queue.setdefault('manager_handoffs', {})
    by_order = {row['order_id']:row for row in rows}
    for batch in queue['batches']:
        key = batch['batch_id']
        previous = assigned.get(key, {})
        ids = batch['order_ids']
        if (not batch.get('settlement_verified') or len(set(ids)) != 10
                or any(order not in by_order for order in ids)):
            if previous:
                previous['settlement_verified'] = False
            continue
        evidence = [{field:by_order[order][field] for field in fields if field in by_order[order]}
                    for order in ids]
        digest = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
        if previous.get('evidence_sha256') == digest:
            previous['settlement_verified'] = True
            continue
        history = list(previous.get('previous_decisions', []))
        if previous.get('decision') is not None:
            history.append(dict(evidence_sha256=previous['evidence_sha256'], decision=previous['decision']))
        assigned[key] = dict(
            status='awaiting_manager', settlement_verified=True, evidence_sha256=digest,
            queued_at=as_of, evidence=evidence, statistics=batch.get('statistics'),
            previous_decisions=history,
            review_tracks=['execution, risk and costs', 'strategy research and validation'],
        )
        if campaign:
            stats = _campaign_metrics([Decimal(row['net_pnl']) for row in evidence])
            if any('shadow_exits' in row for row in evidence):
                stats['exit_comparison'] = compared_exits(evidence)
            net_pnl = Decimal(stats['net_pnl_usd'])
            outcome = 'profitable' if net_pnl > 0 else 'losing' if net_pnl < 0 else 'flat'
            assigned[key].update(workflow='campaign_v1', review_tracks=list(SPECIALIST_TRACKS),
                                 statistics=stats, outcome=outcome)


def _required_text(report, keys):
    return isinstance(report, dict) and all(
        isinstance(report.get(key), str) and report[key].strip() for key in keys)


def _campaign_decision(report, as_of):
    specialists = report.get('specialists')
    manager = report.get('manager')
    ceo = report.get('ceo')
    if not _required_text(specialists, SPECIALIST_TRACKS):
        raise ValueError('All five specialist findings are required')
    if not _required_text(manager, ('findings', 'recommendation')):
        raise ValueError('The profitability manager findings and recommendation are required')
    if (not _required_text(ceo, ('decision', 'rationale'))
            or ceo['decision'] not in ('retain_current', 'test_candidate')):
        raise ValueError('CEO must retain the current version or authorize an independently tested candidate')
    decision = dict(
        specialists={track: specialists[track] for track in SPECIALIST_TRACKS},
        manager={key: manager[key] for key in ('findings', 'recommendation')},
        ceo={key: ceo[key] for key in ('decision', 'rationale')},
    )
    if ceo['decision'] == 'test_candidate':
        candidate = report.get('candidate')
        keys = ('version', 'baseline_version', 'hypothesis', 'validation_protocol')
        if not _required_text(candidate, keys) or candidate['version'] == candidate['baseline_version']:
            raise ValueError('A distinct candidate, baseline, hypothesis and validation protocol are required')
        decision['candidate'] = dict({key: candidate[key] for key in keys}, frozen_at=as_of)
    return decision


def record_manager_review(queue, review_id, evidence_sha256, report, as_of):
    """Attach the team's review only to the settled evidence it evaluated."""
    item = queue['manager_handoffs'][review_id]
    if (not item['settlement_verified'] or item['evidence_sha256'] != evidence_sha256
            or item['status'] != 'awaiting_manager'):
        raise ValueError('Review evidence is stale, unsettled or already reviewed')
    if item.get('workflow') == 'campaign_v1':
        comparisons = (item.get('statistics') or {}).get('exit_comparison', {})
        if any(c['pending'] for c in comparisons.values()):
            raise ValueError('The paired exit observations are still pending')
        decision = _campaign_decision(report, as_of)
        candidate = decision.get('candidate')
        if candidate is not None:
            candidates = queue.setdefault('candidate_registry', {})
            if candidate['version'] in candidates:
                raise ValueError('Candidate version is already frozen')
            candidates[candidate['version']] = dict(
                candidate, review_id=review_id, evidence_sha256=evidence_sha256)
    else:
        required = ('execution_findings', 'strategy_findings', 'recommendation')
        if not _required_text(report, required):
            raise ValueError('Both review tracks and the manager recommendation are required')
        decision = {key: report[key] for key in required}
    item.update(status='reviewed', reviewed_at=as_of, decision=decision)
