import unittest
from datetime import datetime, timedelta, timezone

from crypto_skills.delta_batch_research import review_batch, validation_batches


START = datetime(2026, 11, 18, 10, tzinfo=timezone.utc)


def cohort(batch_id, minute, *, policy='baseline'):
    opened = START + timedelta(minutes=minute)
    return [
        dict(batch_id=batch_id, batch_slot=slot, entry_policy_version=policy,
             entry_observed_at=(opened - timedelta(seconds=1)).isoformat(),
             signal_status_at_entry='waiting' if slot < 6 else 'ready',
             order_id=f'{batch_id}-{slot}', status='closed', filled_contracts=10,
             symbol='ADAUSD', opened_at=opened.isoformat(),
             closed_at=(opened + timedelta(minutes=10)).isoformat(),
             net_pnl='-1' if slot < 6 else '2')
        for slot in range(1, 11)
    ]


class BatchResearchTests(unittest.TestCase):
    def test_review_counts_same_symbol_wait_lots_but_preserves_entry_evidence(self):
        rows = cohort('one', 1)
        report = review_batch(rows[::-1])
        self.assertEqual(report['net_pnl_usd'], '5')
        self.assertEqual(report['by_signal_status']['waiting']['lots'], 5)
        self.assertEqual(report['by_signal_status']['ready']['net_pnl_usd'], '10')
        rows[0]['net_pnl'] = '-2'
        changed = review_batch(rows, expected_entry_fingerprint=report['entry_fingerprint'])
        self.assertEqual(changed['net_pnl_usd'], '4')
        rows[0]['signal_status_at_entry'] = 'ready'
        with self.assertRaisesRegex(ValueError, 'entry evidence changed'):
            review_batch(rows, expected_entry_fingerprint=report['entry_fingerprint'])

    def test_late_entry_evidence_is_rejected(self):
        rows = cohort('one', 1)
        rows[0]['entry_observed_at'] = rows[0]['closed_at']
        with self.assertRaisesRegex(ValueError, 'predate'):
            review_batch(rows)

    def test_validation_excludes_pre_freeze_partial_and_cross_policy_overlap(self):
        rows = (cohort('discovery', -20) + cohort('base', 1) +
                cohort('overlap', 5, policy='candidate') + cohort('candidate', 20, policy='candidate') +
                cohort('confirmation', 40) + cohort('partial', 60)[:9])
        result = validation_batches(rows, frozen_at=START.isoformat())
        self.assertEqual([r['batch_id'] for r in result], ['candidate', 'confirmation'])
        self.assertEqual([r['batch_id'] for r in validation_batches(
            rows, frozen_at=START.isoformat(), policy_version='baseline')], ['confirmation'])
        self.assertTrue(all(r['lots'] == 10 for r in result))

    def test_open_overlapping_batch_is_not_an_independent_holdout(self):
        rows = cohort('open', 1)
        for row in rows:
            row.update(status='open', closed_at=None, net_pnl=None)
        rows += cohort('candidate', 30, policy='candidate')
        self.assertEqual(validation_batches(rows, frozen_at=START.isoformat()), [])
