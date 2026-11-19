import unittest
from unittest.mock import patch
from crypto_skills.delta_signal import closed_breakout, preview


class DeltaSignalTests(unittest.TestCase):
    def setUp(self):
        self.bars = [dict(time=t, open='100', high='101', low='99', close='100', volume='5')
                     for t in range(300, 6900, 300)]

    def test_only_completed_candles_can_trigger(self):
        self.bars[-1].update(high='104', close='103', volume='10')
        self.assertEqual(closed_breakout(self.bars[::-1], 6750)['status'], 'waiting')
        signal = closed_breakout(self.bars[::-1], 6900)
        self.assertEqual(signal['status'], 'ready')
        self.assertEqual(signal['closed_at'], 6900)
        self.assertEqual(signal['rvol'], '2')

    def test_gap_or_stale_watch_window_blocks_signal(self):
        with self.assertRaisesRegex(ValueError, 'gap'):
            closed_breakout(self.bars[:4] + self.bars[5:], 6900)
        with self.assertRaisesRegex(ValueError, 'stale'):
            closed_breakout(self.bars, 7200)

    def test_duplicate_timestamp_does_not_make_valid_dataset(self):
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            closed_breakout(self.bars + [self.bars[-1]], 6900)


class DeltaPreviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_ready_signal_flows_into_ten_contract_plan(self):
        product = dict(id=84, symbol='BTCUSD', contract_type='perpetual_futures',
                       notional_type='vanilla', is_quanto=False, contract_value='.001',
                       tick_size='.5', taker_commission_rate='.0005',
                       trading_status='operational', contract_unit_currency='BTC',
                       underlying_asset={'symbol':'BTC'}, quoting_asset={'symbol':'USD'},
                       settling_asset={'symbol':'USD'})
        replies = {
            'get_wallet_balances':[{'asset_symbol':'USD','available_balance':'171'}],
            'get_product':product,
            'get_ticker':dict(symbol='BTCUSD', product_id=84, timestamp=6900000000,
                              quotes={'best_bid':'63999.5','best_ask':'64000'}),
        }
        async def call(name, args):
            return {'result':replies[name]}
        with patch('crypto_skills.delta_signal.time.time', return_value=6901):
            result = await preview(call, {'BTCUSD':{'status':'ready','closed_at':6900}},
                                   {'blocked':False,'daily_loss_usd':'0'})
        self.assertEqual(result['status'], 'planned')
        self.assertEqual(result['plan']['contracts'], 10)
        self.assertEqual(result['signal_id'], 'BTCUSD:6900')

    async def test_position_or_order_gate_skips_entry_preflight(self):
        async def call(name, args):
            self.fail(f'Account gate should prevent {name}')
        result = await preview(call, {'BTCUSD':{'status':'ready'}}, {'blocked':True})
        self.assertEqual(result['status'], 'account_blocked')

    async def test_stale_signal_does_not_fetch_quotes(self):
        async def call(name, args):
            self.fail(f'Stale signal should prevent {name}')
        result = await preview(call, {'BTCUSD':{'status':'ready','closed_at':0}}, {'blocked':False})
        self.assertEqual(result['status'], 'waiting')
