import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from crypto_skills.core import utc
from crypto_skills.delta_time_exit import manage_time_exits


class TimeExitTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.run_dir = Path(folder.name) / 'trade1'
        self.run_dir.mkdir()
        self.row = dict(order_id='101', product_id=84, symbol='BTCUSD', position='long',
                        opened_at='2026-01-01T11:59:50Z', status='open', fill_ids=['A', 'B'],
                        remaining_contracts=10)
        self.obs = dict(orders=[], fills=[
            dict(id='B', order_id='101', side='buy', size='8', product_id=84, created_at='2026-01-01T12:00:06Z'),
            dict(id='A', order_id='101', side='buy', size='2', product_id=84, created_at='2026-01-01T12:00:01Z'),
        ])
        self.live = 10
        self.submitted = []
        self.orders = {}
        self.env = 'india_testnet'
        self.timeout = False
        self.unknown = False
        self.market_orders = []
        self.foreign_fill = False

    async def exchange(self, name, args):
        if name == 'get_connection_status':
            return dict(environment=self.env)
        if name == 'get_positions':
            return dict(result=dict(size=self.live))
        if name == 'get_open_orders':
            return dict(result=self.market_orders)
        if name == 'get_fills':
            if self.foreign_fill:
                return dict(result=[{'id':'external-reentry'}])
            return dict(result=[max(self.obs['fills'], key=lambda f:f['created_at'])])
        if name == 'place_order':
            self.submitted.append(dict(args))
            self.assertIn(args['client_order_id'], (self.run_dir/'time-exits.json').read_text())
            order = dict(args, id=200+len(self.submitted), state='closed', unfilled_size=0)
            self.orders[args['client_order_id']] = order
            if self.timeout:
                raise TimeoutError('Lost acknowledgement')
            return dict(result=order)
        if name == 'get_order_by_id':
            if self.unknown:
                raise RuntimeError('Order lookup unavailable')
            if 'order_id' in args:
                return dict(result={'id':args['order_id'], 'product_id':84, 'side':'sell'})
            return dict(result=self.orders[args['client_order_id']])
        self.fail(name)

    async def tick(self, at, execute=True):
        await manage_time_exits(self.exchange, self.run_dir, [self.row], self.obs,
                                execute=execute, now=utc('2026-01-01T' + at + 'Z'))

    async def test_first_exchange_fill_starts_persisted_clock_and_closes_only_remaining(self):
        await self.tick('12:10:00')
        self.assertEqual(self.row['deadline_at'], '2026-01-01T12:10:01Z')
        self.assertEqual(self.submitted, [])
        self.assertIn(self.row['deadline_at'], (self.run_dir / 'time-exits.json').read_text())
        self.row['remaining_contracts'] = self.live = 6
        await self.tick('12:10:03')
        self.assertEqual(self.row['close_delay_seconds'], 2)
        self.assertEqual(len(self.submitted), 1)
        order = self.submitted[0]
        self.assertEqual((order['side'], order['size'], order['order_type'], order['reduce_only']),
                         ('sell', 6, 'market_order', True))
        await self.tick('12:10:04')
        self.assertEqual(len(self.submitted), 1)

    async def test_transient_windows_replace_denial_preserves_one_timed_exit(self):
        self.row.update(contracts=3, remaining_contracts=3, fill_ids=['A'])
        self.obs['fills'] = [dict(fill, size='3') for fill in self.obs['fills'] if fill['id']=='A']
        self.live = 3
        await self.tick('12:10:00')
        journal = self.run_dir / 'time-exits.json'
        original = journal.read_bytes()
        replace = os.replace
        interrupted = False

        def temporarily_denied(source, target):
            nonlocal interrupted
            if Path(target) == journal and not interrupted:
                interrupted = True
                self.assertEqual(journal.read_bytes(), original)
                self.assertEqual(self.submitted, [])
                error = PermissionError('Windows sharing denied')
                error.winerror = 5
                raise error
            return replace(source, target)

        with patch.object(os, 'replace', side_effect=temporarily_denied):
            await self.tick('12:10:03')
        await self.tick('12:10:04')
        self.assertTrue(interrupted)
        self.assertEqual(len(self.submitted), 1)
        self.assertEqual(self.row['deadline_at'], '2026-01-01T12:10:01Z')
        self.assertEqual(self.submitted[0]['size'], 3)
        self.assertTrue(self.submitted[0]['reduce_only'])

    async def test_three_contract_timed_exit_rejects_more_than_the_owned_size(self):
        self.row.update(contracts=3, remaining_contracts=4, fill_ids=['A'])
        self.obs['fills'] = [fill for fill in self.obs['fills'] if fill['id'] == 'A']
        self.live = 4
        with self.assertRaises(ValueError):
            await self.tick('12:10:03')
        self.assertEqual(self.submitted, [])
        self.row['remaining_contracts'] = self.live = 2
        await self.tick('12:10:03')
        self.assertEqual([order['size'] for order in self.submitted], [2])

    async def test_protective_close_and_restart_before_deadline(self):
        self.obs['orders'] = [dict(id=301, product_id=84, bracket_order=True, reduce_only=True,
                                   side='sell', stop_order_type='stop_loss_order')]
        await self.tick('12:01:01')
        self.obs['orders'] = []
        self.row.update(status='closed', remaining_contracts=0, fill_ids=['A','B','C'])
        self.obs['fills'].append(dict(id='C', order_id=301, side='sell', size='10', product_id=84,
                                     created_at='2026-01-01T12:05:00Z'))
        await self.tick('12:11:01')
        self.assertEqual(self.row['exit_reason'], 'stop_loss')
        self.assertEqual(self.row['exit_order_ids'], ['301'])
        self.assertEqual(self.submitted, [])

    async def test_lost_ack_restart_never_resends_before_known_terminal_and_matched_fills(self):
        self.timeout = self.unknown = True
        await self.tick('12:11:01')
        await self.tick('12:11:02')
        self.assertEqual(len(self.submitted), 1)
        self.timeout = self.unknown = False
        order = next(iter(self.orders.values()))
        order.update(state='cancelled', unfilled_size=7)
        await self.tick('12:11:03')
        self.assertEqual(len(self.submitted), 1)
        self.row.update(remaining_contracts=7, fill_ids=['A','B','X'])
        self.obs['fills'].append(dict(id='X', size='3', product_id=84, order_id=order['id'], side='sell',
                                     created_at='2026-01-01T12:11:01Z'))
        self.live = 7
        await self.tick('12:11:05')
        self.assertEqual([x['size'] for x in self.submitted], [10,7])
        self.assertNotEqual(*[x['client_order_id'] for x in self.submitted])

    async def test_read_only_flat_race_external_close_and_wrong_environment(self):
        await self.tick('12:12:00', execute=False)
        self.live = 0
        await self.tick('12:12:00')
        self.live = 9
        await self.tick('12:12:00')
        self.live = 10
        self.foreign_fill = True
        await self.tick('12:12:00')
        self.assertEqual(self.submitted, [])
        self.foreign_fill = False
        self.market_orders = [dict(product_id=84, side='sell', reduce_only=True, state='open')]
        await self.tick('12:12:00')
        self.market_orders = []
        self.env = 'india_prod'
        with self.assertRaises(RuntimeError):
            await self.tick('12:12:00')
        self.assertEqual(self.submitted, [])

    async def test_timed_fill_recovered_after_flat(self):
        self.timeout = True
        await self.tick('12:10:01')
        order = next(iter(self.orders.values()))
        self.row.update(status='closed', remaining_contracts=0, fill_ids=['A','B','X'])
        self.obs['fills'].append(dict(id='X', size='10', product_id=84, order_id=order['id'], side='sell',
                                     created_at='2026-01-01T12:10:01Z'))
        await self.tick('12:11:01', execute=False)
        self.assertEqual(self.row['exit_reason'], 'ten_minute')
        self.assertEqual(self.row['exit_order_ids'], [str(order['id'])])

    async def test_partial_ioc_pending_accounting_only_closes_proven_open_size(self):
        self.row.update(status='reconciliation_pending', expected_filled_contracts=5,
                        contracts=10, contract_value='.001', fill_ids=[])
        self.row.pop('remaining_contracts')
        self.obs['fills'] = [dict(id='A', order_id=101, side='buy', size='4', product_id=84,
                                  price='100', commission='.003', created_at='2026-01-01T12:00:01Z',
                                  meta_data={'new_position':{'size':4}})]
        self.obs['positions'] = [dict(product_id=84, size=4)]
        self.obs['transactions'] = []
        self.live = 4
        await self.tick('12:10:01')
        self.assertEqual([x['size'] for x in self.submitted], [4])
        self.assertEqual(self.row['status'], 'reconciliation_pending')
        self.assertTrue(self.row['timer_exposure_open'])

    async def test_confirmed_zero_fill_rejection_permits_new_intent(self):
        self.timeout = True
        await self.tick('12:10:01')
        rejected = next(iter(self.orders.values()))
        rejected.update(state='rejected', unfilled_size=10)
        self.timeout = False
        await self.tick('12:10:06')
        self.assertEqual([x['size'] for x in self.submitted], [10,10])
        self.assertNotEqual(*[x['client_order_id'] for x in self.submitted])
