import tempfile
import unittest
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from crypto_skills.core import Workspace, SkillError
from crypto_skills import trade


NOW = '2026-11-17T12:00:00+00:00'
CONFIG = dict(mode='paper', symbol='BTCUSDT', venue='fixture', product_type='spot',
              quote_currency='USDT', initial_cash='1000', fee_rate='0.001',
              slippage_bps='5', risk_budget='10', max_notional='200',
              max_total_exposure='400', max_daily_loss='50', risk_ttl_seconds=30,
              max_market_age_seconds=120, signal_ttl_seconds=300, qty_step='0.01',
              price_tick='0.01', min_notional='5', max_spread_bps='30',
              stop_pct='1', target_r='2', lookback=3, min_rvol='0')


def market():
    now = datetime.fromisoformat(NOW)
    bars = []
    for i, close in enumerate(['98', '99', '100', '102']):
        bars.append(dict(time=(now - timedelta(minutes=4-i)).isoformat(),
                         open=close, high=str(Decimal(close)+Decimal('.1')),
                         low=str(Decimal(close)-Decimal('.1')), close=close,
                         volume='10', closed=True))
    return dict(symbol='BTCUSDT', venue='fixture', product_type='spot',
                interval_seconds=60, as_of=NOW, bars=bars, bid='102', ask='102.1',
                metadata=dict(qty_step='0.01', price_tick='0.01', min_notional='5'),
                health=dict(valid=True, gaps=[], closed_bars=4),
                source=dict(mode='fixture', price_unit='USDT', volume_unit='BTC'))


class TradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Workspace(self.tmp.name)
        self.ws.write('config', CONFIG, now=NOW)
        self.ws.write('market', market(), now=NOW)

    def run_cmd(self, command, **kwargs):
        args = dict(workspace=self.tmp.name, now=NOW, command=command,
                    action=None, price=None, side='long')
        args.update(kwargs)
        return trade.run(Namespace(**args))

    def ready(self):
        for command in ['entry', 'plan', 'size', 'risk']:
            result = self.run_cmd(command)
        self.assertTrue(result['data']['approved'], result)
        return result

    def update_config(self, **changes):
        config = dict(CONFIG, **changes)
        self.ws.write('config', config, now=NOW)

    def test_breakout_uses_lagged_closed_bars_and_waits_without_signal(self):
        p = self.run_cmd('entry')['data']
        self.assertEqual(p['status'], 'ready')
        self.assertEqual(p['entry'], '102')
        self.assertEqual(p['breakout_level'], '100.1')
        data = market()
        data['bars'][-1].update(close='100', high='100.1', low='99.9', open='100')
        self.ws.write('market', data, now=NOW)
        self.assertEqual(self.run_cmd('entry')['data']['status'], 'waiting')
        self.assertEqual(self.run_cmd('plan')['data']['status'], 'waiting')

    def test_unclosed_bar_does_not_create_a_signal(self):
        data = market()
        data['bars'][-1]['closed'] = False
        data['health']['closed_bars'] = 3
        self.ws.write('market', data, now=NOW)
        self.assertEqual(self.run_cmd('entry')['data']['status'], 'waiting')

    def test_missing_limits_and_zero_budget_cannot_produce_order(self):
        for config in [dict(CONFIG, risk_budget='0'), {k:v for k,v in CONFIG.items() if k != 'max_notional'}]:
            with self.subTest(config=config):
                self.ws.write('config', config, now=NOW)
                with self.assertRaises(SkillError):
                    self.run_cmd('entry')

    def test_unhealthy_future_stale_and_gapped_markets_fail_closed(self):
        cases = [dict(as_of='2026-11-17T12:00:01+00:00'),
                 dict(as_of='2026-11-17T11:50:00+00:00'),
                 dict(health=dict(valid=False, gaps=[], closed_bars=4)),
                 dict(health=dict(valid=True, gaps=['missing'], closed_bars=4))]
        for change in cases:
            self.ws.write('market', dict(market(), **change), now=NOW)
            with self.subTest(change=change), self.assertRaises(SkillError):
                self.run_cmd('entry')

    def test_null_market_timestamp_cannot_be_replaced_by_current_clock(self):
        data=market();data['as_of']=None
        self.ws.write('market',data,now=NOW)
        from crypto_skills.core import utc
        with patch('crypto_skills.trade.utc',side_effect=lambda value=None:utc(NOW if value is None else value)):
            with self.assertRaises(SkillError):self.run_cmd('entry')

    def test_eth_spot_uses_same_handoffs_and_paper_accounting(self):
        self.update_config(symbol='ETHUSDT')
        data=market();data['symbol']='ETHUSDT';data['source']['volume_unit']='ETH'
        self.ws.write('market',data,now=NOW)
        self.ready()
        self.run_cmd('paper',action='submit')
        ledger=self.ws.read('ledger')['data']
        self.assertEqual(ledger['positions'][0]['symbol'],'ETHUSDT')
        self.run_cmd('paper',action='close',price='103')
        ledger=self.ws.read('ledger')['data']
        self.assertEqual(ledger['positions'],[])
        self.assertEqual(len(ledger['orders']),2)

    def test_size_includes_adverse_fill_fees_rounding_and_cash_cap(self):
        self.ready()
        size = self.ws.read('sizing')['data']
        self.assertEqual(size['fill_price'], '102.16')
        self.assertEqual(size['quantity'], '1.95')
        self.assertEqual(size['notional'], '199.2120')
        self.assertLessEqual(Decimal(size['cash_required']), Decimal('1000'))
        self.assertLessEqual(Decimal(size['worst_case_loss']), Decimal('10'))
        self.setUp()
        self.update_config(initial_cash='10')
        self.ready()
        self.assertEqual(self.ws.read('sizing')['data']['quantity'], '0.09')

    def test_minimum_notional_blocks_small_account(self):
        self.update_config(initial_cash='2')
        for cmd in ['entry', 'plan', 'size']:
            result = self.run_cmd(cmd)
        self.assertEqual(result['data']['status'], 'blocked')
        self.assertFalse(self.run_cmd('risk')['data']['approved'])

    def test_expired_or_invalidated_risk_never_submits(self):
        for mutation in ['config', 'market', 'proposal', 'plan', 'sizing', 'portfolio', 'ttl']:
            with self.subTest(mutation=mutation):
                self.setUp()
                self.ready()
                if mutation == 'config':
                    self.update_config(max_notional='150')
                elif mutation != 'ttl':
                    art = self.ws.read(mutation)
                    self.ws.write(mutation, dict(art['data'], test_revision=True), now=NOW)
                with self.assertRaises(SkillError):
                    self.run_cmd('paper', action='submit', now='2026-11-17T12:00:31+00:00' if mutation == 'ttl' else NOW)

    def test_paper_submit_is_idempotent_and_persists_actual_ask_fill(self):
        self.ready()
        first = self.run_cmd('paper', action='submit')
        second = self.run_cmd('paper', action='submit')
        self.assertEqual(first, second)
        self.assertEqual(len(first['data']['orders']), 1)
        position = self.ws.read('portfolio')['data']['positions'][0]
        self.assertEqual(position['entry_price'], '102.16')
        self.assertEqual(self.ws.read('portfolio')['data']['cash'], '800.5887880')

    def test_risk_revalidates_after_exclusive_lock_is_acquired(self):
        self.ready()
        original_lock = Workspace.lock
        ws = self.ws
        from contextlib import contextmanager
        @contextmanager
        def mutate_then_lock(instance):
            with original_lock(instance):
                old = ws.read('market')
                ws.write('market', dict(old['data'], bid='99', ask='100'), now=NOW)
                yield
        with patch.object(Workspace, 'lock', mutate_then_lock):
            with self.assertRaises(SkillError):
                self.run_cmd('paper', action='submit')
        self.assertEqual(self.ws.read('portfolio')['data']['positions'], [])

    def test_close_books_fees_daily_loss_and_survives_restart(self):
        self.update_config(max_daily_loss='1')
        self.ready()
        self.run_cmd('paper', action='submit')
        close = self.run_cmd('paper', action='close', price='100')
        self.assertEqual(self.run_cmd('paper', action='close', price='100'), close)
        portfolio = Workspace(self.tmp.name).read('portfolio')['data']
        self.assertEqual(portfolio['positions'], [])
        self.assertEqual(portfolio['realized_pnl'], '-4.6062120')
        self.assertEqual(portfolio['daily_realized']['2026-11-17'], '-4.6062120')
        self.assertEqual(close['data']['orders'][-1]['price_source'], 'manual_hypothetical_mark')
        for cmd in ['entry', 'plan', 'size']:
            self.run_cmd(cmd)
        self.assertFalse(self.run_cmd('risk')['data']['approved'])

    def test_perpetual_signal_is_research_only_and_execution_is_blocked(self):
        self.update_config(product_type='linear_perpetual')
        data = market()
        data['product_type'] = 'linear_perpetual'
        self.ws.write('market', data, now=NOW)
        for cmd in ['entry', 'plan', 'size']:
            self.run_cmd(cmd)
        risk = self.run_cmd('risk')['data']
        self.assertFalse(risk['approved'])
        self.assertIn('margin', ' '.join(risk['reasons']))
        with self.assertRaises(SkillError):
            self.run_cmd('paper', action='submit')

    def test_same_clock_produces_identical_signal_and_risk(self):
        first = self.ready()
        second = self.ready()
        self.assertEqual(first, second)

    def test_relative_volume_gate_and_waiting_risk_are_inspectable(self):
        self.update_config(min_rvol='2')
        for cmd in ['entry', 'plan', 'size', 'risk']:
            result = self.run_cmd(cmd)
        self.assertFalse(result['data']['approved'])
        self.assertEqual(self.ws.read('proposal')['data']['status'], 'waiting')

    def test_fee_adjusted_risk_budget_and_total_exposure_cap(self):
        self.update_config(risk_budget='0.1')
        self.ready()
        size = self.ws.read('sizing')['data']
        self.assertEqual(size['quantity'], '0.06')
        self.assertEqual(size['worst_case_loss'], '0.0865848')
        self.update_config(max_total_exposure='5')
        for cmd in ['entry', 'plan', 'size', 'risk']:
            result = self.run_cmd(cmd)
        self.assertFalse(result['data']['approved'])

    def test_wide_spread_blocks_approval(self):
        data = market()
        data['bid'] = '101'
        self.ws.write('market', data, now=NOW)
        for cmd in ['entry', 'plan', 'size', 'risk']:
            result = self.run_cmd(cmd)
        self.assertFalse(result['data']['approved'])
        self.assertIn('Spread', ' '.join(result['data']['reasons']))

    def test_changed_ledger_invalidates_risk_even_with_repaired_projection(self):
        self.ready()
        old = self.ws.read('ledger')
        self.ws.write('ledger', dict(old['data'], cash='900'),
                      inputs={'previous_ledger': old['digest']}, now=NOW)
        with self.assertRaises(SkillError):
            self.run_cmd('paper', action='submit')
        self.assertEqual(self.ws.read('portfolio')['data']['positions'], [])

    def test_journal_commit_recovers_projection_failure_without_duplicate_fill(self):
        self.ready()
        original_write = Workspace.write
        def fail_projection(instance, kind, *args, **kwargs):
            if kind == 'portfolio':
                raise OSError('Simulated crash after journal commit')
            return original_write(instance, kind, *args, **kwargs)
        with patch.object(Workspace, 'write', fail_projection):
            with self.assertRaises(OSError):
                self.run_cmd('paper', action='submit')
        result = self.run_cmd('paper', action='submit')
        self.assertEqual(len(result['data']['orders']), 1)
        self.assertEqual(len(self.ws.read('portfolio')['data']['positions']), 1)

    def test_close_without_inventory_is_rejected(self):
        with self.assertRaises(SkillError):
            self.run_cmd('paper', action='close', price='100')

    def test_future_account_timestamp_does_not_allow_backdated_close(self):
        self.ready()
        self.run_cmd('paper', action='submit')
        with self.assertRaises(SkillError):
            self.run_cmd('paper', action='close', price='100', now='2026-11-16T12:00:00+00:00')

    def test_missing_market_price_or_volume_units_are_rejected(self):
        for field in ['price_unit', 'volume_unit']:
            data = market()
            del data['source'][field]
            self.ws.write('market', data, now=NOW)
            with self.subTest(field=field), self.assertRaises(SkillError):
                self.run_cmd('entry')

    def test_executable_fill_must_stay_strictly_between_stop_and_target(self):
        # Stop=100.98, target=104.04; adverse tick rounding can reach either.
        for ask in ['100.1', '100.92', '103.98', '104.1']:
            with self.subTest(ask=ask):
                self.setUp()
                data = market()
                data.update(bid=ask, ask=ask)
                self.ws.write('market', data, now=NOW)
                self.run_cmd('entry')
                self.run_cmd('plan')
                with self.assertRaises(SkillError):
                    self.run_cmd('size')

    def test_signal_age_cannot_be_refreshed_by_new_pipeline_artifacts(self):
        for command, kwargs in [('plan', {}), ('risk', {}), ('paper', {'action':'submit'})]:
            self.setUp()
            self.update_config(signal_ttl_seconds=30)
            for stage in ['entry', 'plan', 'size', 'risk']:
                self.run_cmd(stage, now='2026-11-17T12:00:29+00:00')
            with self.subTest(command=command), self.assertRaises(SkillError):
                self.run_cmd(command, now='2026-11-17T12:00:58+00:00', **kwargs)


if __name__ == '__main__':
    unittest.main()
