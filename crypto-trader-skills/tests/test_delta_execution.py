import json
import tempfile
import unittest
from pathlib import Path

from crypto_skills.delta_execution import OrderJournal, execute_batch, execute_entry, verified_protection


class OrderRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_batch_executor_verifies_four_distinct_products(self):
        await self._verify_four_distinct_products(10)

    async def test_trade1_sends_three_contracts_for_each_of_four_products(self):
        await self._verify_four_distinct_products(3)

    async def test_abandoned_batch_saves_the_quote_that_exceeded_its_ioc_limit(self):
        await self._verify_four_distinct_products(3, above_limit=True)

    async def _verify_four_distinct_products(self, contracts, *, above_limit=False):
        from datetime import datetime, timedelta, timezone
        import time
        from unittest.mock import AsyncMock, patch

        ist = timezone(timedelta(hours=5, minutes=30))
        sizes = {1:0, 2:0, 3:0, 4:0}
        brackets = {}
        requests = []
        symbols = {1:'DOGEUSD', 2:'XRPUSD', 3:'SOLUSD', 4:'ETHUSD'}
        plans = [dict(environment='india_testnet', product_id=pid, symbol=symbols[pid],
                      side='buy', contracts=contracts, leverage=1, quantity=str(contracts), limit='.16',
                      stop='.15', target='.18', planned_loss='.6', margin_reserve='1.61',
                      signal={'status':'waiting'}, lot_number=slot)
                 for slot, pid in enumerate(symbols, 1)]
        batch = dict(status='planned', requested_entries=4, entries=plans,
                     expires_at=time.time()+15, margin_budget='100', daily_risk_budget='20')
        campaign = {'trading_day_ist':datetime.now(ist).date().isoformat(), 'completed':0}

        async def call(name, args):
            if name == 'get_connection_status':
                return {'environment':'india_testnet'}
            if name == 'get_product_leverage':
                return {'result':{'leverage':1}}
            if name == 'get_margined_positions':
                return {'result':[dict(product_id=pid,size=size) for pid,size in sizes.items() if size]}
            if name == 'get_positions':
                return {'result':{'size':sizes[args['product_id']]}}
            if name == 'get_wallet_balances':
                return {'result':[dict(asset_symbol='USD',available_balance='150')]}
            if name == 'get_ticker':
                pid = next(key for key,value in symbols.items() if value==args['symbol'])
                bid, ask = ('.16', '.1601') if above_limit and pid == 1 else ('.155', '.1551')
                return {'result':dict(product_id=pid,timestamp=int(time.time()*1e6),mark_price='.155',
                                      quotes={'best_bid':bid,'best_ask':ask})}
            self.assertEqual(name, 'place_order')
            pid = args['product_id']
            intent = next(row for row in json.loads(journal.path.read_text(encoding='utf-8'))
                          if row['client_order_id'] == args['client_order_id'])
            quote = intent['preflight_quote']
            self.assertEqual(intent['state'], 'submitted_unknown')
            self.assertEqual((quote['bid'], quote['ask'], quote['mark']), ('0.155', '0.1551', '0.155'))
            self.assertLessEqual(quote['exchange_timestamp_us'], int(time.time()*1e6))
            self.assertLessEqual(datetime.fromisoformat(quote['checked_at']),
                                 datetime.fromisoformat(intent['submission_started_at']))
            requests.append(args)
            self.assertEqual(args['size'], contracts)
            self.assertEqual('bracket_stop_loss_price' in args, sizes[pid]==0)
            sizes[pid] += args['size']
            brackets[pid] = [dict(product_id=pid, state='pending', reduce_only=True,
                bracket_order=True, side='sell', unfilled_size=sizes[pid],
                stop_trigger_method='mark_price', stop_order_type=kind, stop_price=price)
                for kind, price in [('stop_loss_order','.15'),('take_profit_order','.18')]]
            return {'result':dict(id=len(requests), client_order_id=args['client_order_id'],
                product_id=pid, side='buy', size=args['size'], unfilled_size=0, state='closed',
                created_at=datetime.now(timezone.utc).isoformat(), average_fill_price='.1551')}

        async def pages(name, args):
            self.assertEqual(name,'get_open_orders')
            return [order for pid,orders in brackets.items()
                    if pid in args.get('product_ids', symbols) for order in orders]

        with tempfile.TemporaryDirectory() as directory:
            journal = OrderJournal(Path(directory)/'entries.json')
            with patch('crypto_skills.delta_signal.preview_batch', AsyncMock(return_value=batch)):
                result = await execute_batch(call, pages, journal, batch, {}, campaign,
                                             AsyncMock(return_value=True), lambda:False,
                                             contracts=contracts)
            if above_limit:
                self.assertEqual(requests, [])
                self.assertEqual(result['abandoned_lots'], 4)
                abandoned = json.loads(journal.path.read_text(encoding='utf-8'))
                self.assertTrue(all(row['state'] == 'batch_abandoned' for row in abandoned))
                self.assertEqual([row['batch_stop_reason'] for row in abandoned], [result['stop_detail']]*4)
                self.assertIn('quote_check_failure', abandoned[0])
                failure = abandoned[0]['quote_check_failure']
                self.assertEqual(failure['reasons'], ['ask_above_ioc_limit'])
                self.assertEqual(failure['symbol'], 'DOGEUSD')
                self.assertEqual(failure['ask'], '0.1601')
                self.assertEqual(failure['limit'], '0.16')
                self.assertEqual(result['quote_check_failure'], failure)
                self.assertTrue(all('submission_started_at' not in row for row in abandoned))
                return
            self.assertEqual(result['full_lots'], 4)
            self.assertEqual(result['abandoned_lots'], 0)
            self.assertFalse(result['protection_unconfirmed'])
            self.assertEqual(sizes, dict.fromkeys(symbols, contracts))
            trades = journal.trades()
            self.assertEqual(len({row['order_id'] for row in trades}), 4)
            self.assertTrue(all(row['contracts'] == contracts and row['contract_value'] == '1'
                                for row in trades))

    async def test_repeated_products_cannot_execute(self):
        from unittest.mock import AsyncMock
        call = AsyncMock()
        proposal = dict(status='planned', entries=[{'product_id':1, 'symbol':'BTCUSD'}]*4)
        result = await execute_batch(call, None, None, proposal, {}, {'completed':0}, None, lambda:False)
        self.assertEqual(result['status'], 'insufficient_distinct_coins')
        call.assert_not_awaited()

    async def test_two_distinct_products_can_only_execute_as_final_batch(self):
        from unittest.mock import AsyncMock
        call = AsyncMock()
        proposal = dict(status='planned', entries=[
            {'product_id':1, 'symbol':'BTCUSD'}, {'product_id':2, 'symbol':'XRPUSD'}
        ])
        early = await execute_batch(call, None, None, proposal, {}, {'completed':9996}, None, lambda:True)
        final = await execute_batch(call, None, None, proposal, {}, {'completed':9998}, None, lambda:True)
        self.assertEqual(early['status'], 'insufficient_distinct_coins')
        self.assertEqual(final['status'], 'stopped')
        call.assert_not_awaited()

    async def test_same_product_addition_uses_existing_bracket_and_checks_full_qty(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = OrderJournal(Path(directory) / 'entries.json')
            plan = dict(environment='india_testnet', product_id=1, symbol='DOGEUSD',
                        side='buy', contracts=10, leverage=1, quantity='10',
                        limit='.16', stop='.15', target='.18', planned_loss='.6',
                        margin_reserve='1.61', signal={'status':'waiting'})
            batch = dict(status='planned', requested_entries=3,
                         entries=[dict(plan, lot_number=i) for i in (1,2,3)],
                         margin_budget='100', daily_risk_budget='20')
            submitted = []
            async def call(name, args):
                if name == 'get_connection_status':
                    return {'environment':'india_testnet'}
                submitted.append(args)
                return {'result':dict(id=len(submitted), client_order_id=args['client_order_id'],
                    product_id=1, side='buy', size=10, unfilled_size=0, state='closed',
                    created_at='2026-11-18T15:00:00Z', average_fill_price='.16')}
            checked = []
            async def verify(intent, quantity):
                checked.append(quantity)
                return quantity < 20
            intents = await journal.submit_batch(call, batch, 'same-product', verify=verify)
            self.assertEqual(checked, [10,20])
            self.assertIn('bracket_stop_loss_price', submitted[0])
            self.assertNotIn('bracket_stop_loss_price', submitted[1])
            self.assertEqual(intents[2]['state'], 'batch_abandoned')
            self.assertEqual([row['batch_slot'] for row in journal.trades()], [1,2])

    async def test_batch_journals_all_lots_before_first_send(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'entries.json'
            journal = OrderJournal(path)
            plan = dict(environment='india_testnet', product_id=1, symbol='DOGEUSD',
                        side='buy', contracts=10, leverage=1, quantity='10',
                        limit='.16', stop='.15', target='.18', planned_loss='.6',
                        margin_reserve='1.61', signal={'status':'waiting'})
            batch = dict(status='planned', requested_entries=10,
                         entries=[dict(plan, lot_number=i) for i in range(1,11)],
                         margin_budget='100', daily_risk_budget='20')
            sent = []
            async def call(name, args):
                if name == 'get_connection_status':
                    return {'environment':'india_testnet'}
                self.assertEqual(name, 'place_order')
                saved = json.loads(path.read_text())
                self.assertEqual(len(saved), 10)
                self.assertEqual(saved[0]['state'], 'submitted_unknown')
                self.assertEqual(saved[1]['state'], 'batch_staged')
                sent.append(args)
                raise TimeoutError('Order result lost')
            async def verify(intent, quantity):
                self.fail('Cannot verify a missing response')
            with self.assertRaises(TimeoutError):
                await journal.submit_batch(call, batch, 'demo-test', verify=verify)
            self.assertEqual(len(sent), 1)
            saved = json.loads(path.read_text())
            self.assertEqual([x['state'] for x in saved],
                             ['submitted_unknown'] + ['batch_abandoned'] * 9)
            self.assertEqual({row['batch_stop_reason'] for row in saved[1:]},
                             {'An earlier submission outcome is unknown'})
    async def test_eligible_entry_confirms_leverage_and_submits_refreshed_plan(self):
        from unittest.mock import AsyncMock, patch
        original = dict(status='planned', signal_id='new', expires_at=9999999999,
                        signal={'version':'v1'}, plan=dict(product_id=84, leverage=5, limit='64000'))
        fresh = dict(original, plan=dict(original['plan'], limit='64001'))
        journal = AsyncMock()
        journal.attempted = lambda _: False
        journal.submit.return_value = {'state':'filled','client_order_id':'cts-test'}
        call = AsyncMock(side_effect=[
            {'environment':'india_testnet'}, {'result':{'leverage':'2'}}, {},
            {'result':{'leverage':'5'}},
        ])
        with patch('crypto_skills.delta_signal.preview', AsyncMock(return_value=fresh)):
            result = await execute_entry(call, journal, original, {}, {}, AsyncMock(return_value=True),
                                         lambda:False)
        self.assertEqual(result['status'], 'filled')
        self.assertEqual(call.await_args_list[2].args,
                         ('set_product_leverage', {'product_id':84,'leverage':'5'}))
        self.assertEqual(journal.submit.await_args.args[1], fresh['plan'])
        self.assertTrue(journal.submit.await_args.kwargs['can_send']())

    async def test_account_changes_after_quote_prevent_submission(self):
        from unittest.mock import AsyncMock, patch
        proposal = dict(status='planned', signal_id='new', expires_at=9999999999,
                        signal={'version':'v1'}, plan=dict(product_id=84, leverage=5))
        journal = AsyncMock()
        journal.attempted = lambda _: False
        async def call(name, args):
            if name == 'get_connection_status':
                return {'environment':'india_testnet'}
            if name == 'get_product_leverage':
                return {'result':{'leverage':'5'}}
            self.fail(f'Unexpected exchange operation {name}')
        inventory = AsyncMock(side_effect=[True, False])
        with patch('crypto_skills.delta_signal.preview', AsyncMock(return_value=proposal)):
            result = await execute_entry(call, journal, proposal, {}, {}, inventory, lambda:False)
        self.assertEqual(result['status'], 'account_changed')
        journal.submit.assert_not_awaited()

    def test_protection_must_cover_remaining_position(self):
        row = dict(product_id=84, position='long', remaining_contracts=6,
                   stop_loss='63191.5', target='65591.5')
        sl = dict(id=1, product_id=84, side='sell', size=6, unfilled_size=6,
                  state='pending', reduce_only=True, bracket_order=True,
                  stop_trigger_method='mark_price', stop_order_type='stop_loss_order',
                  stop_price='63191.5')
        tp = dict(sl, id=2, stop_order_type='take_profit_order', stop_price='65591.5')
        self.assertTrue(verified_protection(row, [sl, tp]))
        self.assertFalse(verified_protection(row, [sl, dict(tp, unfilled_size=4)]))
        self.assertFalse(verified_protection(row, [sl, dict(tp, reduce_only=False)]))
        self.assertFalse(verified_protection(row, [sl, tp, dict(sl, id=3)]))

    async def test_accepted_order_with_lost_response_is_recovered_without_resubmit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'entries.json'
            sent = []
            plan = dict(environment='india_testnet', product_id=84, symbol='BTCUSD',
                        side='buy', contracts=10, leverage=5, quantity='.01',
                        limit='64000', stop='63200', target='65600', planned_loss='9.3')

            async def exchange(name, args):
                if name == 'get_connection_status':
                    return {'environment':'india_testnet'}
                if name == 'place_order':
                    saved = json.loads(path.read_text())
                    self.assertEqual(saved[0]['client_order_id'], args['client_order_id'])
                    self.assertEqual(args['time_in_force'], 'ioc')
                    sent.append(args)
                    raise TimeoutError('Response lost')
                return {'result': dict(id=123, client_order_id=args['client_order_id'],
                    product_id=84, side='buy', size=10, unfilled_size=4,
                    state='cancelled', created_at='2026-11-18T00:00:00Z',
                    average_fill_price='63990')}

            journal = OrderJournal(path)
            with self.assertRaises(TimeoutError):
                await journal.submit(exchange, plan, 'v1', 'BTCUSD:2026-11-18T00:00:00Z')
            with self.assertRaisesRegex(RuntimeError, 'unresolved'):
                await journal.submit(exchange, plan, 'v1', 'another-signal')
            await OrderJournal(path).recover(exchange)
            self.assertEqual(len(sent), 1)
            self.assertEqual(next(OrderJournal(path).trades())['order_id'], '123')
            with self.assertRaisesRegex(RuntimeError, 'already attempted'):
                await journal.submit(exchange, plan, 'v1', 'BTCUSD:2026-11-18T00:00:00Z')

    async def test_production_session_never_submits(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = OrderJournal(Path(directory) / 'entries.json')
            async def exchange(name, args):
                self.assertEqual(name, 'get_connection_status')
                return {'environment':'india_prod'}
            with self.assertRaisesRegex(RuntimeError, 'testnet'):
                await journal.submit(exchange, {'environment':'india_testnet'}, 'v1', 'signal')
