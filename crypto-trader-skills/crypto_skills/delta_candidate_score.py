"""Score paired, settled shadow portfolios against the frozen four-READY protocol."""
import argparse
from datetime import date, timedelta
from decimal import Decimal
import json
from math import floor
from pathlib import Path
from random import Random

from .delta_candidate_capture import DAYS, IST, VERSION, validation_window
from .delta_research import _campaign_metrics

ARMS = ('baseline','candidate','stressed_baseline','stressed_candidate')
WEEK = 7


def arm_metrics(days, settled):
    trades = [value for day in days for value in day]
    n = len(trades)
    metrics = _campaign_metrics(trades) if n else dict(
        wins=0, losses=0, breakevens=0, net_pnl_usd='0',
        mean_net_pnl_usd=None, max_drawdown_usd='0')
    cash = [value for day in settled for value in day]
    cash_stats = _campaign_metrics(cash) if cash else dict(net_pnl_usd='0',max_drawdown_usd='0')
    return dict(metrics, trades=n, active_days=sum(bool(day) for day in settled),
                max_drawdown_usd=cash_stats['max_drawdown_usd'],
                account_net_pnl_usd=cash_stats['net_pnl_usd'],
                net_per_day=float(Decimal(cash_stats['net_pnl_usd']) / len(days)),
                win_rate=metrics['wins']/n if n else None)


def block_totals(days):
    totals=[]
    for start in range(0,len(days),WEEK):
        values=[v for day in days[start:start+WEEK] for v in day]
        totals.append((len(values),sum(v>0 for v in values),float(sum(values))))
    return totals


def paired_bounds(baseline, candidate):
    """Sample the same full-week block IDs in both arms, preserving basket exposure."""
    rng=Random(19)
    blocks=len(baseline)
    win_delta, pnl_delta = [], []
    for _ in range(4000):
        indices=rng.choices(range(blocks),k=blocks)
        counts=[tuple(map(sum,zip(*(arm[i] for i in indices)))) for arm in (baseline,candidate)]
        (before_n,before_w,before_net),(after_n,after_w,after_net)=counts
        if not before_n or not after_n:
            return None
        win_delta.append(after_w/after_n-before_w/before_n)
        pnl_delta.append(after_net/after_n-before_net/before_n)
    k=floor(0.05*len(win_delta))
    return sorted(win_delta)[k],sorted(pnl_delta)[k]


def evaluate(rows, start_ist):
    start=date.fromisoformat(start_ist)
    expected=[(start+timedelta(days=i)).isoformat() for i in range(DAYS)]
    rows=sorted(rows,key=lambda row:row['day'])
    result={'status':'inconclusive','auto_promote':False,'expected_days':DAYS,'submitted_days':len(rows)}
    if [row['day'] for row in rows]!=expected or not all(row.get('complete') is True for row in rows):
        return dict(result,reason='Missing, duplicated or unresolved IST dates')
    try:
        series={arm:[[Decimal(str(v)) for v in row[arm]] for row in rows] for arm in ARMS}
        settled={arm:[[Decimal(str(v)) for v in row.get(arm+'_settled_net_usd',row[arm])]
                      for row in rows] for arm in ARMS}
        if any(not v.is_finite() for arms in (series,settled) for days in arms.values() for day in days for v in day):
            raise ValueError('Non-finite P&L')
    except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
        return dict(result,reason=str(exc))
    result.update({arm:arm_metrics(days,settled[arm]) for arm,days in series.items()})
    if not all(row.get('risk_passed') is True for row in rows):
        return dict(result,status='fails_metrics',reason='Risk compliance was not verified for every IST day')
    if not all(result[arm]['trades'] for arm in ARMS):
        return dict(result,reason='At least one arm has no settled trades')
    base, cand, stress_base, stress_cand=(result[arm] for arm in ARMS)
    bounds=paired_bounds(block_totals(series['baseline']),block_totals(series['candidate']))
    if bounds is None:
        return dict(result,reason='Insufficient independent blocks with settled trades in both arms')
    low_win,low_pnl=bounds
    result.update(win_rate_delta_lower_95=low_win,net_per_trade_delta_lower_95=low_pnl,
                  paired_week_blocks=DAYS//WEEK)
    stable_stress = (stress_cand['win_rate']>stress_base['win_rate']
                     and Decimal(stress_cand['mean_net_pnl_usd'])>max(
                         Decimal(stress_base['mean_net_pnl_usd']),Decimal(0))
                     and stress_cand['net_per_day']>0)
    if (low_win>0 and low_pnl>0 and Decimal(cand['mean_net_pnl_usd'])>0
            and cand['net_per_day']>0 and stable_stress
            and Decimal(cand['max_drawdown_usd'])<=Decimal(base['max_drawdown_usd'])):
        result['status']='passes_metrics'
    else:
        result['status']='fails_metrics'
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paired_outcomes',type=Path,
                        help='JSON with candidate identity and finalized daily shadow portfolios')
    args=parser.parse_args()
    run=Path(__file__).resolve().parents[1]/'runs/trade1'
    candidate=json.loads((run/'reviews.json').read_text(encoding='utf-8'))[
        'campaign_reviews']['candidate_registry'][VERSION]
    payload=json.loads(args.paired_outcomes.read_text(encoding='utf-8'))
    for key in ('version','baseline_version','evidence_sha256'):
        if candidate[key]!=payload.get(key):
            raise ValueError('Paired outcomes do not match the frozen candidate identity')
    start,_=validation_window(candidate['frozen_at'])
    print(json.dumps(evaluate(payload['days'],start.astimezone(IST).date().isoformat()),indent=2))


if __name__=='__main__':
    main()
