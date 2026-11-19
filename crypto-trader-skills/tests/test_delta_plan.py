import unittest
from decimal import Decimal as D
from crypto_skills import delta_plan as p


class DeltaPlanTests(unittest.TestCase):
    def test_trade1_uses_three_contracts_and_only_counts_full_three_contract_positions(self):
        planned = p.plan(self.product(), self.ticker(), 1000, 160, 0, 0,
                         batch=True, contracts=3)
        self.assertEqual(planned['contracts'], 3)
        self.assertEqual(D(planned['quantity']), D('.003'))
        trade = dict(campaign_id='trade1', symbol='BTCUSD', status='closed', contracts=3,
                     classification='strategy', filled_contracts=3, exited_contracts=3, net_pnl='2')
        self.assertTrue(p.eligible_completed_trade(trade))
        self.assertFalse(p.eligible_completed_trade(dict(trade, filled_contracts=2)))
        self.assertFalse(p.eligible_completed_trade(dict(trade, exited_contracts=2)))
        self.assertFalse(p.eligible_completed_trade(dict(trade, contracts=10)))

    def test_batch_ranks_turnover_and_cannot_substitute_repeats_for_four_coins(self):
        from unittest.mock import patch
        coins = tuple(f'COIN{i}USD' for i in range(11))
        data = []
        for i,symbol in enumerate(coins):
            product = dict(self.product(), id=i+1, symbol=symbol,
                           underlying_asset={'symbol':symbol[:-3]}, contract_unit_currency=symbol[:-3],
                           contract_value='1', tick_size='.00001')
            ticker = dict(self.ticker(), product_id=i+1, symbol=symbol, turnover_usd=str(i+1),
                          quotes={'best_bid':'.15200', 'best_ask':'.15210'})
            data.append((product, ticker, {'status':'waiting'}))
        with patch.object(p,'CRYPTO_DEMO_SYMBOLS',coins):
            batch = p.plan_batch(data, 1000, '162', '8.68')
            denied = p.plan_batch(data[:3], 1000, '162', '8.68')
            over_risk = p.plan_batch(data, 1000, '162', '29')
            penultimate = p.plan_batch(data[:3], 1000, '162', '8.68', completed=9996)
            final = p.plan_batch(data[:3], 1000, '162', '8.68', completed=9997)
            finished = p.plan_batch(data, 1000, '162', '8.68', completed=10000)
        self.assertEqual(batch['status'], 'planned')
        self.assertEqual(len(batch['entries']), 4)
        self.assertEqual([e['symbol'] for e in batch['entries']], list(reversed(coins[-4:])))
        self.assertTrue(all(e['contracts'] == 10 and e['signal']['status'] == 'waiting'
                            for e in batch['entries']))
        self.assertLessEqual(D(batch['planned_loss']) + D('8.68'), 30)
        self.assertEqual(denied['status'], 'insufficient_distinct_coins')
        self.assertEqual(denied['entries'], [])
        self.assertEqual(over_risk['entries'], [])
        self.assertEqual(batch['distinct_symbols'], 4)
        self.assertEqual(penultimate['status'], 'insufficient_distinct_coins')
        self.assertEqual(final['status'], 'planned')
        self.assertEqual(len(final['entries']), 3)
        self.assertEqual(finished['entries'], [])

    def test_campaign_uses_ist_day_and_counts_full_trades(self):
        from datetime import datetime
        now = datetime.fromisoformat('2026-11-18T02:00:00+05:30')
        def closed(order, time, pnl, quantity=10, symbol='BTCUSD'):
            return dict(order_id=order, symbol=symbol, status='closed', filled_contracts=quantity,
                        closed_at=time, net_pnl=pnl)
        rows = [closed('a','2026-11-17T18:29:59Z','-12'),
                closed('b','2026-11-17T18:30:00Z','-24'),
                closed('c','2026-11-17T19:00:00Z','2',4),
                closed('d','2026-11-17T20:00:00Z','-1',symbol='ADAUSD')]
        result = p.campaign_state(rows, [], [], now)
        self.assertEqual(result['completed'], 2)
        self.assertEqual(result['daily_loss_usd'], '23')
        self.assertEqual(result['remaining_planned_risk_usd'], '7')

    def test_campaign_blocks_unreconciled_state_and_any_account_order(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        self.assertTrue(p.campaign_state([{'status':'reconciliation_pending'}], [], [], now)['blocked'])
        self.assertTrue(p.campaign_state([], [], [{'id':1}], now)['blocked'])
        self.assertTrue(p.campaign_state([], [{'size':-1}], [], now)['blocked'])

    def product(self):
        return dict(id=84,symbol='BTCUSD',contract_type='perpetual_futures',
                    contract_value='.001',contract_unit_currency='BTC',
                    underlying_asset={'symbol':'BTC'},quoting_asset={'symbol':'USD'},
                    settling_asset={'symbol':'USD'},tick_size='.1',taker_commission_rate='.0005',
                    trading_status='operational',notional_type='vanilla',is_quanto=False)

    def ticker(self):
        return dict(product_id=84,quotes={'best_bid':'63999','best_ask':'64000'},timestamp=1000000000)

    def test_risk_contains_fees_and_funding(self):
        r=p.plan(self.product(),self.ticker(),1000,171,0,0)
        self.assertEqual(r['contracts'],10)
        self.assertEqual(r['leverage'],5)
        self.assertLessEqual(D(r['planned_loss']),10)
        self.assertGreater(D(r['fee_buffer']),0)
        self.assertGreater(D(r['funding_buffer']),0)

    def test_all_other_positions_block(self):
        with self.assertRaises(ValueError): p.plan(self.product(),self.ticker(),1000,171,0,1)

    def test_budget_reserved_before_trade(self):
        with self.assertRaises(ValueError): p.plan(self.product(),self.ticker(),1000,171,25,0)

    def test_margin_shortfall_blocks(self):
        with self.assertRaises(ValueError): p.plan(self.product(),self.ticker(),1000,100,0,0)

    def test_stale_ticker_blocks(self):
        with self.assertRaises(ValueError): p.plan(self.product(),self.ticker(),1031,171,0,0)

    def test_wrong_contract_units_block(self):
        product=self.product();product['contract_unit_currency']='USD'
        with self.assertRaises(ValueError): p.plan(product,self.ticker(),1000,171,0,0)

    def test_batch_rejects_unlisted_coin_and_mismatched_underlying(self):
        for product in (
            dict(self.product(), symbol='ADAUSD', underlying_asset={'symbol':'ADA'},
                 contract_unit_currency='ADA'),
            dict(self.product(), underlying_asset={'symbol':'XRP'}, contract_unit_currency='XRP'),
        ):
            with self.subTest(symbol=product['symbol'], underlying=product['underlying_asset']):
                with self.assertRaises(ValueError):
                    p.plan(product,self.ticker(),1000,171,0,0,batch=True)

    def test_high_contract_risk_skips_instead_of_changing_count(self):
        product=self.product();product['contract_value']='1'
        with self.assertRaises(ValueError): p.plan(product,self.ticker(),1000,1000000,0,0)

    def test_production_environment_always_rejected(self):
        with self.assertRaises(ValueError): p.plan(self.product(),self.ticker(),1000,171,0,0,environment='india_prod')

    def test_infinite_cash_rejected(self):
        with self.assertRaises(ValueError): p.plan(self.product(),self.ticker(),1000,'Infinity',0,0)

    def test_negative_raw_fee_rejected(self):
        product=self.product(); product['taker_commission_rate']='-.5'
        with self.assertRaises(ValueError): p.plan(product,self.ticker(),1000,171,0,0)
