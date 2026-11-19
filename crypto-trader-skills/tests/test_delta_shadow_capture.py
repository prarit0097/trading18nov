import unittest

from crypto_skills.delta_shadow import seconds
from crypto_skills.delta_shadow_capture import capture_row, evaluate_capture, select_batch


class ShadowCaptureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.row = dict(order_id='1', batch_id='demo-1', campaign_id='trade1', symbol='XRPUSD',
                        status='open', filled_contracts=3, first_fill_at='2026-11-19T01:30:05.3Z')

    def test_selects_owned_batch_and_rejects_missing_venue_or_membership_evidence(self):
        ledger = dict(campaign_id='trade1', environment='india_testnet', trades=[self.row])
        self.assertEqual(select_batch(ledger, 'demo-1'), [self.row])
        for invalid in (
            dict(ledger, environment='india_prod'),
            dict(ledger, trades=[dict(self.row, filled_contracts=1)]),
            dict(ledger, trades=[dict(self.row, first_fill_at=None)]),
            dict(ledger, trades=[self.row, dict(self.row, order_id='2')]),
        ):
            with self.assertRaises(ValueError):
                select_batch(invalid, 'demo-1')

    def test_captures_the_earliest_valid_book_at_the_exchange_fill_deadline(self):
        deadline = seconds(self.row['first_fill_at']) + 900
        now = deadline - 45
        calls = []

        def sleep(duration):
            nonlocal now
            now += duration

        def fetch(path, *, depth):
            calls.append((now, path, depth))
            stamp = deadline - 1 if len(calls) == 1 else now
            return dict(symbol='XRPUSD', last_updated_at=int(stamp*1_000_000),
                        buy=[dict(price='1.01', size=3)], sell=[dict(price='1.02', size=3)])

        entry = capture_row(self.row, 15, fetch=fetch, clock=lambda: now, sleep=sleep)
        self.assertEqual(entry['deadline_at'], deadline)
        self.assertEqual(entry['capture']['status'], 'valid')
        self.assertEqual(calls, [(deadline+2, '/l2orderbook/XRPUSD', 5),
                                 (deadline+2.5, '/l2orderbook/XRPUSD', 5)])

    def test_expired_deadline_is_left_unavailable_without_fetching_a_book(self):
        now = seconds(self.row['first_fill_at'])+1815
        entry = capture_row(self.row, 30, clock=lambda: now,
                            fetch=lambda *args, **kwargs: self.fail('Historical books cannot be backfilled'))
        self.assertEqual(entry['capture']['status'], 'unavailable')

    async def test_evaluation_binds_evidence_to_a_settled_trade_and_closed_minute(self):
        row = dict(self.row, status='closed', exited_contracts=3, contracts=3, classification='strategy',
                   net_pnl='-.21', exit_reason='stop_loss', closed_at='2026-11-19T01:35:03Z')
        end = seconds(row['first_fill_at'])+900
        observation = dict(order_id=row['order_id'], symbol=row['symbol'], first_fill_at=row['first_fill_at'],
                           deadline_at=end, capture=dict(status='unavailable'))
        metadata = dict(status='depth_research_only', environment='india_testnet', campaign_id='trade1',
                        batch_id='demo-1', minutes=15)
        artifact = dict(metadata, comparisons=[observation])
        fetch = lambda *args, **kwargs: self.fail('Early bracket uses verified settlement')
        rows = await evaluate_capture([row], artifact, end+60, fetch=fetch)
        self.assertEqual(rows[0]['candle_baseline'], rows[0]['depth_fallback'])
        self.assertEqual(rows[0]['realized_net_usd'], '-.21')
        self.assertEqual(rows[0]['depth_fallback']['status'], 'actual_early_exit')
        self.assertEqual(artifact['comparisons'], [observation])
        for inputs, evidence, now in (
            ([dict(row, status='reconciliation_pending')], artifact, end+60),
            ([row], dict(metadata, comparisons=[dict(observation, deadline_at=end-1)]), end+60),
            ([row], artifact, end-10),
        ):
            with self.assertRaises(ValueError):
                await evaluate_capture(inputs, evidence, now, fetch=fetch)
