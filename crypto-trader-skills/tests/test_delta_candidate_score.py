from datetime import date, timedelta
import unittest

from crypto_skills.delta_candidate_score import evaluate


START='2026-11-20'


def sample():
    return [dict(day=(date.fromisoformat(START)+timedelta(days=i)).isoformat(),
                 complete=True, baseline=['-.5','1'], candidate=['2','1'],
                 stressed_baseline=['-.6','.8'], stressed_candidate=['1.8','.7'],
                 risk_passed=True) for i in range(84)]


class CandidateScoreTests(unittest.TestCase):
    def test_same_paired_dates_and_positive_bounds_are_required(self):
        good=evaluate(sample(), START)
        self.assertEqual(good['status'],'passes_metrics')
        self.assertGreater(good['win_rate_delta_lower_95'],0)
        self.assertGreater(good['net_per_trade_delta_lower_95'],0)
        self.assertEqual(good['candidate']['trades'],168)
        self.assertFalse(good['auto_promote'])

    def test_overlapping_or_unresolved_day_cannot_produce_pass(self):
        rows=sample()
        rows[-1]=dict(rows[-1],day=rows[-2]['day'])
        self.assertEqual(evaluate(rows, START)['status'],'inconclusive')
        rows=sample()
        rows[-1]['complete']=False
        self.assertEqual(evaluate(rows, START)['status'],'inconclusive')

    def test_cost_stress_can_reject_high_win_rate_candidate(self):
        rows=sample()
        for row in rows:
            row['stressed_candidate']=['-4','.7']
        self.assertEqual(evaluate(rows, START)['status'],'fails_metrics')

    def test_idle_days_are_included_and_no_candidate_means_inconclusive(self):
        rows=sample()
        for row in rows:
            row['candidate']=row['stressed_candidate']=[]
        result=evaluate(rows,START)
        self.assertEqual(result['status'],'inconclusive')
        self.assertEqual(result['candidate']['active_days'],0)
        self.assertEqual(result['candidate']['net_per_day'],0.0)

    def test_positive_daily_cash_cannot_pass_with_negative_full_trade_expectancy(self):
        rows=sample()
        for row in rows:
            row.update(
                baseline=['-4', '-1'],
                candidate=['-1.25', '.25'],
                candidate_settled_net_usd=['-1.25', '.25', '2'],
            )
        result=evaluate(rows, START)
        self.assertEqual(result['candidate']['mean_net_pnl_usd'], '-0.50')
        self.assertEqual(result['candidate']['net_per_day'], 1.0)
        self.assertGreater(result['win_rate_delta_lower_95'], 0)
        self.assertGreater(result['net_per_trade_delta_lower_95'], 0)
        self.assertEqual(result['status'], 'fails_metrics')

    def test_partial_fill_losses_count_toward_cash_and_drawdown(self):
        rows=sample()
        for row in rows:
            row['candidate_settled_net_usd']=['2','1','-4']
        result=evaluate(rows, START)
        self.assertEqual(result['candidate']['mean_net_pnl_usd'],'1.5')
        self.assertEqual(result['candidate']['net_per_day'],-1.0)
        self.assertEqual(result['candidate']['max_drawdown_usd'],'87')
        self.assertEqual(result['status'],'fails_metrics')
