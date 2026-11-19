import unittest

from crypto_skills.delta_research import advance, assess, freeze, refresh_manager_handoffs, record_manager_review


class DeltaResearchTests(unittest.TestCase):
    def test_ten_trade_handoff_is_stable_and_reopens_after_cashflow_revision(self):
        ids = [f'order{i}' for i in range(10)]
        queue = {'batches':[dict(batch_id='ten', order_ids=ids, settlement_verified=True)]}
        row = dict(order_id='order', symbol='BTCUSD', net_pnl='-1', actual_commission='.1',
                   classification='strategy', strategy_version='v1')
        rows = [dict(row, order_id=order) for order in ids]
        refresh_manager_handoffs(queue, rows, 't1')
        item = queue['manager_handoffs']['ten']
        self.assertEqual(item['status'], 'awaiting_manager')
        digest = item['evidence_sha256']
        report = dict(execution_findings='Fees verified', strategy_findings='Sample is small',
                      recommendation='retain_current')
        record_manager_review(queue, 'ten', digest, report, 't1')
        refresh_manager_handoffs(queue, rows, 't2')
        self.assertEqual(queue['manager_handoffs']['ten']['status'], 'reviewed')
        rows[0]['net_pnl'] = '-2'
        refresh_manager_handoffs(queue, rows, 't3')
        revised = queue['manager_handoffs']['ten']
        self.assertEqual(revised['status'], 'awaiting_manager')
        self.assertEqual(revised['previous_decisions'][0]['decision']['recommendation'], 'retain_current')
        self.assertEqual(revised['evidence'][0]['net_pnl'], '-2')
        with self.assertRaises(ValueError):
            record_manager_review(queue, 'ten', digest, report, 't4')

    def test_campaign_handoff_requires_all_roles_and_blocks_unvalidated_promotion(self):
        from crypto_skills.delta_research import SPECIALIST_TRACKS

        pnl = ['10', '-2', '-1', '1'] + ['0'] * 6
        rows = [dict(order_id=str(i), net_pnl=value) for i, value in enumerate(pnl)]
        queue = {'batches': [dict(batch_id='ten', order_ids=[r['order_id'] for r in rows],
                                  settlement_verified=True)]}
        refresh_manager_handoffs(queue, rows, 't1', campaign=True)
        item = queue['manager_handoffs']['ten']
        self.assertEqual(item['outcome'], 'profitable')
        self.assertEqual(item['statistics']['largest_win_usd'], '10')
        self.assertEqual(item['statistics']['largest_loss_usd'], '-2')
        self.assertEqual(item['statistics']['without_largest_win_usd'], '-2')
        self.assertEqual(item['statistics']['mean_net_pnl_usd'], '0.8')
        self.assertEqual(item['statistics']['max_drawdown_usd'], '3')
        digest = item['evidence_sha256']
        specialists = {track: 'Verified finding' for track in SPECIALIST_TRACKS}
        report = dict(specialists=specialists, manager=dict(findings='One winner drove the result',
                      recommendation='Retain current version'),
                      ceo=dict(decision='retain_current', rationale='Independent evidence pending'))
        with self.assertRaisesRegex(ValueError, 'All five'):
            record_manager_review(queue, 'ten', digest, dict(report, specialists={}), 't2')
        bad_decision = dict(report, ceo=dict(decision='promote_candidate', rationale='Batch profit'))
        with self.assertRaisesRegex(ValueError, 'CEO'):
            record_manager_review(queue, 'ten', digest, bad_decision, 't2')
        record_manager_review(queue, 'ten', digest, report, 't2')
        refresh_manager_handoffs(queue, rows, 't3', campaign=True)
        self.assertEqual(item['status'], 'reviewed')
        self.assertEqual(item['decision']['ceo']['decision'], 'retain_current')

    def test_candidate_plan_is_frozen_and_cannot_reuse_a_version(self):
        from crypto_skills.delta_research import SPECIALIST_TRACKS

        queue = {'manager_handoffs': {key: dict(workflow='campaign_v1',
                   settlement_verified=True, evidence_sha256=key,
                   status='awaiting_manager') for key in ('ten', 'twenty')}}
        report = dict(
            specialists={track: 'Finding independently recorded' for track in SPECIALIST_TRACKS},
            manager=dict(findings='Execution costs were high', recommendation='Test tighter spread'),
            ceo=dict(decision='test_candidate', rationale='Evaluate with prospective data'),
            candidate=dict(version='experiment-v2', baseline_version='v1',
                           hypothesis='Avoid wider spreads', validation_protocol='Holdout trial'),
        )
        record_manager_review(queue, 'ten', 'ten', report, 't2')
        candidate = queue['candidate_registry']['experiment-v2']
        self.assertEqual(candidate['frozen_at'], 't2')
        self.assertEqual(candidate['review_id'], 'ten')
        self.assertEqual(candidate['evidence_sha256'], 'ten')
        report['candidate']['hypothesis'] = 'Changed after freeze'
        with self.assertRaisesRegex(ValueError, 'already frozen'):
            record_manager_review(queue, 'twenty', 'twenty', report, 't3')
        self.assertEqual(candidate['hypothesis'], 'Avoid wider spreads')
        self.assertEqual(queue['manager_handoffs']['twenty']['status'], 'awaiting_manager')

    def test_batch_refresh_preserves_frozen_rule_and_marks_review(self):
        queue = {'batches':[{'batch_id':'first'}]}
        advance(queue, [], '2026-11-18T10:00:00Z')
        queue['batches'].append({'batch_id':'second'})
        advance(queue, [], '2026-11-19T10:00:00Z')
        self.assertEqual(queue['forward_research']['candidate']['frozen_at'], '2026-11-18T10:00:00Z')
        self.assertEqual(queue['batches'][1]['status'], 'reviewed')
        self.assertEqual(queue['forward_research']['validation']['observations'], 0)

    def test_thirty_trade_result_can_pass_but_does_not_promote(self):
        from datetime import datetime, timedelta, timezone
        start = datetime(2026, 11, 19, tzinfo=timezone.utc)
        candidate = freeze('batch-a', '2026-11-18T10:00:00Z')
        rows = [dict(order_id=str(i), opened_at=(start+timedelta(days=i//2, hours=i%2)).isoformat(),
                     classification='strategy', strategy_version=candidate['baseline_version'],
                     status='closed', filled_contracts=10, net_pnl='3' if i%2 else '-2',
                     signal={'rvol':'2' if i%2 else '1'}) for i in range(30)]
        result = assess(candidate, rows)
        self.assertEqual(result['status'], 'passes_forward_screen')
        self.assertFalse(result['auto_promote'])
        self.assertEqual(result['filtered_net_usd'], '45')

    def test_only_entries_after_freeze_are_used(self):
        candidate = freeze('batch-a', '2026-11-18T10:00:00Z')
        def row(order, opened, rvol, pnl):
            return dict(order_id=order, opened_at=opened, classification='strategy',
                        status='closed', strategy_version='delta-5m-breakout20-v1',
                        filled_contracts=10, net_pnl=pnl,
                        signal={'rvol':rvol, 'closed_at':1794996000})
        rows = [row('old','2026-11-18T09:59:00Z','1','-100'),
                row('skip','2026-11-18T10:01:00Z','1','-2'),
                row('keep','2026-11-18T10:02:00Z','2','3')]
        data = assess(candidate, rows)
        self.assertEqual(data['status'], 'collecting')
        self.assertEqual(data['observations'], 2)
        self.assertEqual(data['retained'], 1)
        self.assertEqual(data['baseline_net_usd'], '1')
        self.assertEqual(data['filtered_net_usd'], '3')
