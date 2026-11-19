"""Combine a modeled batch entry with its timestamped exit evidence."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import partial
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from .delta_candidate_capture import IST, VERSION, validation_window
from .delta_candidate_entry import evaluate_entry
from .delta_candidate_exit import HOLD_SECONDS, book_midpoint, timed_exit
from .delta_candidate_frames import ReplayFrames
from .delta_candidate_funding import load_schedule
from .delta_candidate_marks import fetch_mark_history
from .delta_candidate_protection import ProtectiveArchive
from .delta_plan import TRADE1_CONTRACTS

INCOMPLETE_ENTRY = 'incomplete_market_evidence'


def model_batch(snapshot, products, slot, exit_data, *, cash, day_loss, ready_only, fee_rate, stress=False):
    """Return a cash result only if all known modeled exposure can settle."""
    decision = evaluate_entry(snapshot,products,slot,cash=cash,day_loss=day_loss,ready_only=ready_only)
    plans = {plan['symbol']:plan for plan in decision.get('entries', [])}
    positions = []
    for fill in decision['fills']:
        if fill['filled'] == 0:
            continue
        symbol = fill['symbol']
        plan = plans[symbol]
        trade = dict(entry_price=fill['avg_price'],first_fill_at=snapshot['captured_at'],
                     filled=fill['filled'],stop=plan['stop'],target=plan['target'],
                     contract_value=str(Decimal(plan['quantity'])/plan['contracts']),
                     entry_fee_rate=fee_rate)
        evidence = exit_data.get(symbol)
        try:
            if evidence is None:
                raise ValueError('Close evidence was not captured')
            if stress:
                trade['entry_midpoint'] = str(book_midpoint(snapshot['coins'][symbol]['book']))
            funding = evidence.get('funding_usd')
            per_contract = evidence.get('funding_per_contract')
            if per_contract is not None:
                funding = str(Decimal(per_contract)*fill['filled'])
            archive = evidence.get('protection')
            schedule = evidence.get('schedule')
            close = timed_exit(trade,evidence['mark_bars'],evidence['exit_quotes'],
                               exit_fee_rate=fee_rate,funding_usd=funding,stress=stress,
                               protective_books=partial(archive.prove,symbol) if archive is not None else None,
                               zero_funding_through=partial(schedule.proves_zero,symbol,trade['first_fill_at'])
                               if schedule is not None else None)
            if close['status'] == 'modeled_exit':
                close.setdefault('funding_source', evidence.get('funding_source') or 'supplied_cashflow')
        except (ArithmeticError, KeyError, TypeError, ValueError) as error:
            close = {'status':'unavailable','reason':str(error)}
        positions.append(dict(symbol=symbol,entry=trade,exit=close))
    complete = decision['status'] != INCOMPLETE_ENTRY and all(
        position['exit']['status']=='modeled_exit' for position in positions)
    result = dict(decision_status=decision['status'],positions=positions,fill_attempts=decision['fills'],
                  planned_lots=len(plans),
                  complete=complete,total_net_usd=None,full_size_net_usd=None,closed_at=None)
    if complete:
        chronological = sorted(positions,key=lambda p:p['exit']['close_time'])
        result.update(
            total_net_usd=str(sum((Decimal(p['exit']['net_usd']) for p in positions),Decimal(0))),
            settled_net_usd=[p['exit']['net_usd'] for p in chronological],
            full_size_net_usd=[p['exit']['net_usd'] for p in chronological
                               if p['entry']['filled']==TRADE1_CONTRACTS],
            closed_at=max((p['exit']['close_time'] for p in positions),default=None))
    return result


def model_portfolio(frames, products, start, end, *, cash, ready_only, fee_rate, stress=False):
    """Replay a single arm with carried cash, IST loss limits and serial exposure."""
    def local(t):
        return datetime.fromtimestamp(t, IST)

    if end <= start or any(local(t).strftime('%H%M%S') != '000000' for t in (start,end)):
        raise ValueError('Replay dates must be complete consecutive IST days')
    days = {local(t).date():dict(day=local(t).date().isoformat(),complete=True,risk_passed=True,
                                cash_net=Decimal(0),full_size_net_usd=[],settled_net_usd=[],
                                execution=dict(scheduled_slots=min(86400,end-HOLD_SECONDS-t)//300,
                                               busy_slots=0,observed_slots=0,missing_frame_slots=0,
                                               incomplete_batch_slots=0,planned_lots=0,attempted_lots=0,
                                               decisions=Counter(),ioc_outcomes=Counter()))
            for t in range(start,end,86400)}
    balance = Decimal(cash)
    if not balance.is_finite() or balance <= 0:
        raise ValueError('Invalid initial cash')

    flat_at = start
    for slot in range(start,end-HOLD_SECONDS,300):
        day = local(slot).date()
        execution = days[day]['execution']
        if slot < flat_at:
            execution['busy_slots'] += 1
            continue
        frame = frames.get(slot)
        if frame is not None:
            batch = model_batch(frame['snapshot'],products,slot,frame['exits'],cash=balance,
                                day_loss=max(Decimal(0), -days[day]['cash_net']),
                                ready_only=ready_only,fee_rate=fee_rate,stress=stress)
            execution['observed_slots'] += 1
            execution['decisions'][batch['decision_status']] += 1
            execution['planned_lots'] += batch['planned_lots']
            execution['attempted_lots'] += len(batch['fill_attempts'])
            execution['ioc_outcomes'].update(fill['state'] for fill in batch['fill_attempts'])
            if batch['complete']:
                if batch['closed_at'] is not None:
                    flat_at = batch['closed_at']
                    exit_day = local(flat_at).date()
                    pnl = Decimal(batch['total_net_usd'])
                    days[exit_day]['cash_net'] += pnl
                    days[exit_day]['full_size_net_usd'].extend(batch['full_size_net_usd'])
                    days[exit_day]['settled_net_usd'].extend(batch['settled_net_usd'])
                    balance += pnl
                    if days[exit_day]['cash_net'] < -30 or balance < 0:
                        days[exit_day]['risk_passed'] = False
                continue
            execution['incomplete_batch_slots'] += 1
        else:
            execution['missing_frame_slots'] += 1
        # Without the next position or cash balance, later results cannot be inferred.
        for key, record in days.items():
            if key >= day:
                record['complete'] = False
        break
    for record in days.values():
        record['cash_net_usd'] = str(record.pop('cash_net'))
        execution = record['execution']
        execution['unsent_lots'] = execution['planned_lots']-execution['attempted_lots']
        execution['unreplayed_slots'] = execution['scheduled_slots']-sum(
            execution[key] for key in ('busy_slots','observed_slots','missing_frame_slots'))
    return list(days.values())


def replay_pair(frames, products, start, end, *, cash, fee_rate, include_stress=False):
    baseline, candidate = (
        model_portfolio(frames,products,start,end,cash=cash,ready_only=ready_only,fee_rate=fee_rate)
        for ready_only in (False,True))
    days = [dict(day=b['day'],complete=b['complete'] and c['complete'],
                 risk_passed=b.get('risk_passed',False) and c.get('risk_passed',False),
                 baseline=b['full_size_net_usd'],candidate=c['full_size_net_usd'],
                 baseline_settled_net_usd=b['settled_net_usd'],candidate_settled_net_usd=c['settled_net_usd'],
                 baseline_cash_net_usd=b['cash_net_usd'],candidate_cash_net_usd=c['cash_net_usd'],
                 baseline_execution=b['execution'],candidate_execution=c['execution'])
            for b,c in zip(baseline,candidate)]
    if include_stress:
        stressed_baseline, stressed_candidate = (
            model_portfolio(frames,products,start,end,cash=cash,ready_only=ready_only,
                            fee_rate=fee_rate,stress=True) for ready_only in (False,True))
        for day,b,c in zip(days,stressed_baseline,stressed_candidate):
            day.update(stressed_baseline=b['full_size_net_usd'],stressed_candidate=c['full_size_net_usd'],
                       stressed_baseline_settled_net_usd=b['settled_net_usd'],
                       stressed_candidate_settled_net_usd=c['settled_net_usd'],
                       stressed_baseline_cash_net_usd=b['cash_net_usd'],
                       stressed_candidate_cash_net_usd=c['cash_net_usd'],
                       stressed_baseline_execution=b['execution'],stressed_candidate_execution=c['execution'],
                       complete=day['complete'] and b['complete'] and c['complete'],
                       risk_passed=day['risk_passed'] and b['risk_passed'] and c['risk_passed'])
    return dict(days=days, complete=all(day['complete'] for day in days), auto_promote=False)


def registered_input(data, registered):
    for key in ('version','evidence_sha256'):
        if data.get(key) != registered[key]:
            raise ValueError('Replay inputs do not match the frozen '+key)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('settlement_evidence',nargs='?',type=Path,
                        help='Frozen candidate identity, completed_through_ist, cash, fee_rate, marks and funding_per_contract')
    parser.add_argument('--fetch-marks',action='store_true',help='Fetch closed public testnet mark candles for the cutoff')
    args = parser.parse_args()
    if args.fetch_marks and not args.settlement_evidence:
        parser.error('--fetch-marks requires a settlement evidence file with a replay cutoff')
    run = Path(__file__).resolve().parents[1]/'runs/trade1'
    queue = json.loads((run/'reviews.json').read_text(encoding='utf-8'))['campaign_reviews']
    registered = queue['candidate_registry'][VERSION]
    start, end = validation_window(registered['frozen_at'])
    catalog = json.loads((run/'candidate-input-products.json').read_text(encoding='utf-8'))
    registered_input(catalog,registered)
    path = run/'four-ready-quotes.sqlite3'
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        identity = json.loads(db.execute('SELECT identity FROM metadata WHERE id=1').fetchone()[0])
        registered_input(identity,registered)
        if (identity.get('environment')!='india_testnet'
                or datetime.fromisoformat(identity['start'])!=start
                or datetime.fromisoformat(identity['end'])!=end):
            raise ValueError('Captured testnet window does not match the registered window')
        count = db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]
        now = datetime.now(timezone.utc)
        status = 'awaiting_start' if now<start else ('collecting' if now<end else 'evidence_required')
        report = dict(version=VERSION,evidence_sha256=registered['evidence_sha256'],
                      baseline_version=registered['baseline_version'],captured_slots=count,
                      start_ist=start.astimezone(IST).isoformat(),end_ist=end.astimezone(IST).isoformat(),
                      status=status,
                      auto_promote=False)
        if args.settlement_evidence:
            data = json.loads(args.settlement_evidence.read_text(encoding='utf-8'))
            registered_input(data,registered)
            until = date.fromisoformat(data['completed_through_ist']) + timedelta(days=1)
            cutoff = datetime(until.year,until.month,until.day,tzinfo=IST)
            if not start < cutoff <= min(end,datetime.now(timezone.utc)):
                raise ValueError('Replay cutoff must be a completed date in the frozen window')
            first, last = int(start.timestamp()), int(cutoff.timestamp())
            funding = {int(slot):value for slot,value in data['funding_per_contract'].items()}
            schedule = load_schedule(run,identity,first,last)
            if args.fetch_marks:
                marks, coverage = fetch_mark_history(first,last)
                report['mark_history'] = dict(source='delta_india_testnet_public',coverage=coverage)
            else:
                marks = data['marks']
            protection = ProtectiveArchive(run/'protective-quotes',identity,cutoff=last)
            with TemporaryDirectory(prefix='candidate-replay-',dir=run) as scratch:
                with closing(sqlite3.connect(Path(scratch)/'quotes.sqlite3')) as snapshot:
                    db.backup(snapshot,pages=256)
                    frames = ReplayFrames(snapshot,first,last,marks,funding,schedule=schedule,protection=protection)
                    report.update(replay_pair(frames,catalog['products'],first,last,
                                              cash=data['cash'],fee_rate=data['fee_rate'],include_stress=True),
                                  status='paired_modeled_outcomes')
        print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
