import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from crypto_skills.delta_ledger import campaign_paths, campaign_members, initialize_trade1, refresh_campaign_reviews
from crypto_skills.delta_plan import campaign_state, eligible_completed_trade
from crypto_skills.delta_observer import next_poll_delay


class Trade1CampaignTests(unittest.TestCase):
    def test_legacy_losses_still_limit_today_but_never_count(self):
        legacy = dict(symbol='BTCUSD', status='closed', filled_contracts=10, net_pnl='-30',
                      closed_at='2026-11-18T14:01:00Z')
        now = datetime(2026, 11, 18, 15, tzinfo=timezone.utc)
        state = campaign_state([], [], [], now, other_account_trades=[legacy])
        self.assertEqual(state['completed'], 0)
        self.assertEqual(state['daily_loss_usd'], '30')
        self.assertTrue(state['blocked'])

    def test_journal_membership_requires_new_order_and_original_epoch(self):
        epoch = '2026-11-18T10:00:00+00:00'
        row = dict(order_id='1', opened_at=epoch, position_episode_id='ep', contracts=3)
        self.assertEqual(campaign_members([row], [], epoch)[0]['campaign_id'], 'trade1')
        with self.assertRaises(ValueError):
            campaign_members([row], [row], epoch)
        with self.assertRaises(ValueError):
            campaign_members([dict(row, opened_at='2026-11-17T22:00:00Z')], [], epoch)
        with self.assertRaises(ValueError):
            campaign_members([], [], epoch, [dict(row, campaign_id='trade1')])

    def test_initializing_again_keeps_existing_checkpoint_and_hold_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, _ = campaign_paths(Path(tmp), 'trade1')
            first = initialize_trade1(run)
            (run/'ENTRY_HOLD').unlink()
            second = initialize_trade1(run)
            self.assertEqual(first, second)
            self.assertFalse((run/'ENTRY_HOLD').exists())
            self.assertEqual(json.loads((run/'entries.json').read_text()), [])

    def test_partial_exit_cannot_count_in_fresh_workbook(self):
        row = dict(campaign_id='trade1', classification='strategy', symbol='BTCUSD',
                   status='closed', contracts=3, filled_contracts=3, exited_contracts=2, net_pnl='1')
        self.assertFalse(eligible_completed_trade(row))
        self.assertTrue(eligible_completed_trade(dict(row, exited_contracts=3)))

    def test_empty_held_campaign_can_migrate_without_resetting_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            epoch = '2026-11-18T10:00:00Z'
            manifest = dict(campaign_id='trade1', environment='india_testnet',
                            started_at=epoch, time_exit_seconds=600,
                            strategy_version='delta-demo-liquid-four-v5+trade1-10m-v1')
            (run/'campaign.json').write_text(json.dumps(manifest))
            (run/'ENTRY_HOLD').touch()
            (run/'entries.json').write_text('[{"state":"submitted_unknown"}]')
            with self.assertRaises(ValueError):
                initialize_trade1(run)
            self.assertEqual(json.loads((run/'campaign.json').read_text()), manifest)
            (run/'entries.json').write_text('[]')
            updated = initialize_trade1(run)
            self.assertEqual(updated['contracts'], 3)
            self.assertTrue(updated['strategy_version'].endswith('+trade1-3c-10m-v2'))
            self.assertEqual(updated['started_at'], epoch)
            self.assertEqual(initialize_trade1(run), updated)

    def test_issue_review_only_for_ten_verified_three_contract_trades(self):
        row = dict(campaign_id='trade1', classification='strategy', strategy_version='current',
                   symbol='BTCUSD', status='closed', contracts=3, filled_contracts=3,
                   exited_contracts=3, net_pnl='1', closed_at='2026-11-18T10:01:00Z')
        rows = [dict(row, order_id=str(i)) for i in range(10)]
        invalid = [dict(row, order_id='partial', exited_contracts=2),
                   dict(row, order_id='old', contracts=10, filled_contracts=10, exited_contracts=10)]
        queue = {'campaign_reviews': {'batches': []}}
        self.assertEqual(refresh_campaign_reviews(queue, rows[:-1]+invalid, 'time')['batches'], [])
        result = refresh_campaign_reviews(queue, rows+invalid, 'time')
        self.assertEqual(len(result['batches']), 1)
        self.assertEqual(set(result['batches'][0]['order_ids']), {str(i) for i in range(10)})

    def test_deadline_wakes_before_normal_poll(self):
        now = datetime(2026, 11, 18, 10, tzinfo=timezone.utc)
        rows = [dict(status='open', deadline_at='2026-11-18T10:00:04+00:00')]
        self.assertEqual(next_poll_delay(60, rows, now.timestamp()), 1)
        self.assertEqual(next_poll_delay(60, rows, now.timestamp()-30), 24)
