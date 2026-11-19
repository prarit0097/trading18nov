import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock
from datetime import datetime, timezone
from decimal import Decimal as D

from crypto_skills.delta_shadow import estimate, refresh_trade1_shadows, seconds


class ShadowTests(unittest.IsolatedAsyncioTestCase):
    def test_review_pairs_only_comparable_shadow_rows_and_retains_evidence(self):
        from crypto_skills.delta_research import refresh_manager_handoffs
        rows = [dict(order_id=str(i), net_pnl='1', shadow_exits=[
            dict(minutes=15, status='estimated', net_pnl='2') if i else dict(minutes=15, status='unavailable'),
            dict(minutes=30, status='pending')]) for i in range(10)]
        queue = {'batches':[dict(batch_id='x', order_ids=[r['order_id'] for r in rows], settlement_verified=True)]}
        refresh_manager_handoffs(queue, rows, 't', campaign=True)
        comparison = queue['manager_handoffs']['x']['statistics']['exit_comparison']
        self.assertEqual(comparison['15']['pairs'], 9)
        self.assertEqual(comparison['15']['mean_paired_change_usd'], '1')
        self.assertIsNone(comparison['30']['mean_paired_change_usd'])

    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'shadows.json'
        self.row = dict(order_id='1', campaign_id='trade1', classification='strategy',
                        symbol='XRPUSD', position='long', status='closed', contracts=3,
                        filled_contracts=3, exited_contracts=3, contract_value='1', entry='1', exit='1.005',
                        actual_commission='.01', entry_commission='.005', net_pnl='.04',
                        funding='0', first_fill_at='2026-11-18T16:03:00+00:00',
                        closed_at='2026-11-18T16:13:00+00:00', exit_reason='ten_minute',
                        stop_loss='.98', target='1.03')
        self.now = '2026-11-18T16:35:00+00:00'

    async def test_early_hosted_stop_uses_verified_net(self):
        self.row.update(exit_reason='stop_loss', net_pnl='-.22')
        call = AsyncMock()
        await refresh_trade1_shadows(call, [self.row], self.path, self.now)
        self.assertEqual([r['net_pnl'] for r in self.row['shadow_exits']], ['-.22'] * 2)
        call.assert_not_awaited()

    async def test_deadline_estimates_cache_and_costs(self):
        async def history(name, args):
            mark = args['symbol'].startswith('MARK:')
            return {'result':[dict(time=t, open='1.01', low='1.001', high='1.02', close='1.01',
                                   volume=None if mark else 100)
                              for t in range(args['start'], args['end']+1, 60)]}
        call = AsyncMock(side_effect=history)
        await refresh_trade1_shadows(call,[self.row],self.path,self.now)
        self.assertEqual([r['status'] for r in self.row['shadow_exits']], ['estimated'] * 2)
        self.assertTrue(all(0 < float(r['net_pnl']) < .09 for r in self.row['shadow_exits']))
        await refresh_trade1_shadows(AsyncMock(side_effect=AssertionError), [self.row], self.path, self.now)

    async def test_missing_history_does_not_create_a_profit_or_loss(self):
        await refresh_trade1_shadows(AsyncMock(return_value={'result':[]}), [self.row], self.path, self.now)
        self.assertTrue(all(r['status']=='unavailable' and r.get('net_pnl') is None
                            for r in self.row['shadow_exits']))

    async def test_depth_reference_resolves_an_empty_trade_minute_only_with_deadline_coverage(self):
        async def history(name, args):
            return {'result': [dict(time=t, open='1.01', low='1.001', high='1.02',
                                    close='1.01', volume=0)
                              for t in range(args['start'], args['end']+1, 60)]}

        closed = seconds(self.row['closed_at'])
        end = closed + 300
        baseline = await estimate(history, self.row, closed, end)
        self.assertEqual(baseline['status'], 'unavailable')
        book = dict(symbol='XRPUSD', last_updated_at=int((end+1)*1_000_000),
                    buy=[dict(price='1.009', size=1), dict(price='1.006', size=2)],
                    sell=[dict(price='1.012', size=5)])
        capture = dict(status='valid', book=book, book_observed_at=end+2)
        result = await estimate(history, self.row, closed, end, deadline_book=capture)
        self.assertEqual(result['status'], 'estimated')
        self.assertEqual(D(result['exit_price']), D('1.007') * D('.9995'))
        self.assertEqual(result['reference_exchange_us'], book['last_updated_at'])
        self.assertIn('displayed bid depth', result['method'])

        for unavailable in (dict(book, buy=book['buy'][:1]),
                            dict(book, last_updated_at=int((end-1)*1_000_000)),
                            dict(book, symbol='ETHUSD')):
            result = await estimate(history, self.row, closed, end,
                                    deadline_book=dict(capture, book=unavailable))
            self.assertEqual(result['status'], 'unavailable')
            self.assertNotIn('net_pnl', result)

    async def test_pending_horizons_do_not_read_future_data(self):
        call = AsyncMock()
        await refresh_trade1_shadows(call, [self.row], self.path, self.row['closed_at'])
        self.assertEqual([r['status'] for r in self.row['shadow_exits']], ['pending'] * 2)
        call.assert_not_awaited()

    async def test_history_outage_eventually_releases_review_with_missing_evidence(self):
        call = AsyncMock(side_effect=RuntimeError('unavailable'))
        for stamp in ('16:35', '16:37', '16:41'):
            await refresh_trade1_shadows(call, [self.row], self.path, '2026-11-18T'+stamp+':00Z')
        self.assertEqual([r['status'] for r in self.row['shadow_exits']], ['unavailable'] * 2)

    async def test_cross_hour_replay_requires_continuous_funding_and_valid_market_evidence(self):
        from crypto_skills.delta_candidate_funding import FundingSchedule

        closed = seconds('2026-11-18T16:59:15Z')
        end = closed + 900
        next_settlement = int(seconds('2026-11-18T20:00:00Z') * 1_000_000)
        start = int(closed // 60) * 60
        observations = [
            dict(symbol=self.row['symbol'], received_utc_ms=t * 1000,
                 observed_exchange_us=t * 1_000_000, next_realization_us=next_settlement,
                 interval_seconds=28800, stream_id='public-feed', observed_rate=.0001)
            for t in range(start, start + 16 * 60 + 1, 60)
        ]

        async def history(_, args):
            return {'result': [
                dict(time=t, open='1.01', low='1.001', high='1.02', close='1.01', volume=100)
                for t in range(args['start'], args['end'] + 1, 60)
            ]}

        schedule = FundingSchedule(observations)
        self.assertTrue(schedule.proves_zero(self.row['symbol'], closed, end))
        baseline = await estimate(history, self.row, closed, end)
        self.assertEqual(baseline['status'], 'unavailable')
        self.assertIn('funding unverified', baseline['reason'])

        verified = await estimate(history, self.row, closed, end, funding_schedule=schedule)
        self.assertEqual(verified['status'], 'estimated')
        self.assertIn('verified by public funding schedule', verified['method'])
        self.assertEqual(verified['funding'], '0')

        same_hour_closed = closed + 120
        same_hour_end = same_hour_closed + 300
        same_hour = await estimate(history, self.row, same_hour_closed, same_hour_end)
        self.assertEqual(same_hour['status'], 'estimated')
        self.assertEqual(same_hour, await estimate(history, self.row, same_hour_closed, same_hour_end,
                                                  funding_schedule=schedule))

        changed = dict(observations[5], next_realization_us=next_settlement + 60_000_000)
        for records in ([], observations[:2] + observations[5:],
                        observations[:5] + [changed] + observations[6:]):
            result = await estimate(history, self.row, closed, end, funding_schedule=FundingSchedule(records))
            self.assertEqual(result['status'], 'unavailable')
            self.assertIn('funding unverified', result['reason'])

        async def broken_history(name, args):
            reference = await history(name, args)
            if args['symbol'].startswith('MARK:'):
                reference['result'][2].update(low='.97', high='1.04')
            return reference

        uncertain = await estimate(broken_history, self.row, closed, end, funding_schedule=schedule)
        self.assertEqual(uncertain['status'], 'unavailable')
        self.assertIn('Both brackets touched', uncertain['reason'])

        async def target_history(name, args):
            reference = await history(name, args)
            if args['symbol'].startswith('MARK:'):
                reference['result'][2].update(high='1.04')
            return reference

        target = await estimate(target_history, self.row, closed, end, funding_schedule=schedule)
        self.assertEqual(target['status'], 'estimated')
        self.assertIn('mark target trigger', target['method'])

        async def no_volume(name, args):
            reference = await history(name, args)
            for bar in reference['result']:
                bar['volume'] = 0
            return reference

        quote_time = end + 2
        depth = dict(status='valid', book_observed_at=end+3,
                     book=dict(symbol=self.row['symbol'], last_updated_at=int(quote_time*1_000_000),
                               buy=[dict(price='1.01', size=3)], sell=[dict(price='1.02', size=3)]))
        charged = dict(self.row, funding='-.001')
        covered = await estimate(no_volume, charged, closed, end, deadline_book=depth, funding_schedule=schedule)
        self.assertEqual(covered['status'], 'estimated')
        self.assertEqual(D(covered['funding']), D('-.001'))
        self.assertEqual(covered['reference_exchange_us'], depth['book']['last_updated_at'])
        fee_rate = D('.005') / (D('1.005') * D(3))
        self.assertEqual(D(covered['fees']), D('.005') + D(covered['exit_price']) * D(3) * fee_rate)

        settlement = int((end+1)*1_000_000)
        at_deadline = [dict(r, next_realization_us=settlement) for r in observations
                       if r['observed_exchange_us'] < int(end*1_000_000)]
        at_deadline.append(dict(at_deadline[-1], received_utc_ms=int((end+.5)*1000),
                                observed_exchange_us=int((end+.5)*1_000_000)))
        clipped = FundingSchedule(at_deadline)
        self.assertTrue(clipped.proves_zero(self.row['symbol'], closed, end))
        self.assertFalse(clipped.proves_zero(self.row['symbol'], closed, quote_time))
        unavailable = await estimate(no_volume, self.row, closed, end, deadline_book=depth,
                                     funding_schedule=clipped)
        self.assertEqual(unavailable['status'], 'unavailable')
        self.assertIn('funding unverified', unavailable['reason'])
