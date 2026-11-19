import importlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from crypto_skills.core import SkillError, Workspace


def config():
    return dict(mode='paper', symbol='BTCUSDT', venue='fixture', product_type='spot',
                initial_cash='1000', fee_rate='0.001', slippage_bps='10',
                risk_budget='10', max_notional='200', qty_step='0.001',
                stop_pct='10', target_r='2', lookback=2, price_tick='0.01', min_notional='5',
                quote_currency='USDT', max_total_exposure='400', max_daily_loss='50')


def market(prices=None):
    prices = prices or [(100, 101, 99, 100), (100, 101, 99, 100),
                        (100, 112, 99, 110), (120, 150, 90, 125),
                        (125, 130, 120, 125)]
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = [dict(time=(start + timedelta(minutes=i)).isoformat(),
                 open=str(o), high=str(h), low=str(l), close=str(c),
                 volume='100', closed=True) for i, (o, h, l, c) in enumerate(prices)]
    return dict(symbol='BTCUSDT', venue='fixture', product_type='spot',
                interval_seconds=60, bars=bars, bid='124', ask='126',
                as_of=(start + timedelta(minutes=len(bars))).isoformat(),
                source=dict(mode='fixture',price_unit='USDT',volume_unit='BTC'),
                metadata=dict(qty_step='0.001', price_tick='0.01', min_notional='5'),
                health=dict(valid=True, gaps=[], closed_bars=len(bars)))


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('crypto_skills.research'),
                             'Research engine is not implemented')
        self.module = importlib.import_module('crypto_skills.research')

    def test_backtest_next_open_stop_first_and_accounting(self):
        result = self.module.backtest(market(), config())
        trade = result['trades'][0]
        self.assertEqual(Decimal(trade['entry_price']), Decimal('120.12'))
        self.assertEqual(trade['exit_reason'], 'stop_first_ambiguous')
        self.assertEqual(Decimal(trade['exit_price']), Decimal('98.90'))
        self.assertEqual(Decimal(result['metrics']['final_cash']),
                         Decimal('1000') + sum(Decimal(t['net_pnl']) for t in result['trades']))
        self.assertGreater(Decimal(result['metrics']['total_fees']), 0)

    def test_next_open_keeps_closed_signal_plan_levels(self):
        trade=self.module.backtest(market(),config())['trades'][0]
        self.assertEqual(Decimal(trade['stop']),Decimal('99'))
        self.assertEqual(Decimal(trade['target']),Decimal('132'))

    def test_gap_beyond_signal_target_is_not_a_new_plan(self):
        m=market([(100,101,99,100),(100,101,99,100),(100,112,99,110),
                  (150,160,140,150),(150,151,149,150)])
        trades=self.module.backtest(m,config())['trades']
        self.assertTrue(all(t['entry_time']!=m['bars'][3]['time'] for t in trades))
        self.assertEqual(trades[0]['entry_time'],m['bars'][4]['time'])

    def test_open_at_original_stop_skips_without_zero_division(self):
        m=market([(100,101,99,100),(100,101,99,100),(100,112,99,110),
                  (99,100,98,99),(99,100,98,99)])
        c=config();c.update(fee_rate='0',slippage_bps='0')
        self.assertEqual(self.module.backtest(m,c)['metrics']['trade_count'],0)

    def test_backtest_gap_exit_at_worse_open(self):
        m = market([(100,101,99,100),(100,101,99,100),(100,112,99,110),
                    (120,125,115,120),(90,100,85,95)])
        trade = self.module.backtest(m, config())['trades'][0]
        self.assertEqual(trade['exit_reason'], 'stop_gap')
        self.assertEqual(Decimal(trade['exit_price']), Decimal('89.91'))

    def test_known_target_open_precedes_later_bar_stop(self):
        m = market([(100,101,99,100),(100,101,99,100),(100,112,99,110),
                    (120,125,115,120),(150,160,90,120)])
        trade = self.module.backtest(m, config())['trades'][0]
        self.assertEqual(trade['exit_reason'], 'target')

    def test_backtest_respects_relative_volume_filter(self):
        c = config(); c['min_rvol'] = '2'
        result = self.module.backtest(market(), c)
        self.assertEqual(result['metrics']['trade_count'], 0)

    def test_backtest_fee_and_slip_adjusted_stop_loss_fits_budget(self):
        c = config(); c.update(fee_rate='0.01', stop_pct='1', max_notional='10000',
                               max_total_exposure='10000')
        trade = self.module.backtest(market(), c)['trades'][0]
        self.assertGreaterEqual(Decimal(trade['net_pnl']), Decimal('-10'))
        self.assertEqual(Decimal(trade['exit_price']) % Decimal('.01'), 0)

    def test_backtest_exposure_daily_loss_and_minimum_notional(self):
        c = config(); c.update(max_total_exposure='50', max_daily_loss='0.01')
        result = self.module.backtest(market(), c)
        self.assertEqual(result['metrics']['trade_count'], 1)
        trade = result['trades'][0]
        self.assertLessEqual(Decimal(trade['quantity'])*Decimal(trade['entry_price']), 50)
        c['min_notional'] = '60'; m = market(); m['metadata']['min_notional'] = '60'
        self.assertEqual(self.module.backtest(m, c)['metrics']['trade_count'], 0)

    def test_research_rejects_missing_units_times_and_unclosed_timestamp(self):
        for field in ('as_of','source'):
            m = market(); del m[field]
            with self.subTest(field=field), self.assertRaises(SkillError):
                self.module.backtest(m, config())
        m = market(); m['as_of'] = m['bars'][-1]['time']
        with self.assertRaises(SkillError):
            self.module.backtest(m, config())
        m = market(); m['metadata']['qty_step'] = '1'
        with self.assertRaises(SkillError):
            self.module.backtest(m, config())

    def test_perpetual_backtest_and_plan_replay_fail_without_contract(self):
        c, m = config(), market()
        c['product_type'] = m['product_type'] = 'linear_perpetual'
        p = dict(status='ready', side='long', entry='125', stop='100', target='150')
        with self.assertRaises(SkillError):
            self.module.backtest(m, c)
        with self.assertRaises(SkillError):
            self.module.simulate(m, c, p, replays=1)

    def test_unclosed_bar_cannot_trigger_or_fill(self):
        m = market()
        m['bars'][3]['closed'] = False
        m['bars'] = m['bars'][:4]
        m['health']['closed_bars'] = 3
        result = self.module.backtest(m, config())
        self.assertEqual(result['metrics']['trade_count'], 0)

    def test_simulation_settles_costs_on_flat_underlying(self):
        m = market([(100,100,100,100)] * 8)
        p = dict(status='ready', side='long', entry='100', stop='90', target='120')
        r = self.module.simulate(m, config(), p, seed=19, replays=100, steps=6, block_size=4)
        self.assertEqual(r['metrics']['loss_count'], 100)
        self.assertEqual(r['metrics']['underlying_positive_count'], 0)
        self.assertLess(Decimal(r['metrics']['mean_net_pnl_per_unit']), 0)
        self.assertEqual(r['metrics']['unique_block_sequences'], 1)
        self.assertEqual(r['metrics']['timeout_count'], 100)

    def test_simulation_seed_reproducible_and_all_paths_counted(self):
        p = dict(status='ready', side='long', entry='125', stop='100', target='150')
        kwargs = dict(seed=19, replays=200, steps=6, block_size=2)
        a = self.module.simulate(market(), config(), p, **kwargs)
        b = self.module.simulate(market(), config(), p, **kwargs)
        self.assertEqual(a['metrics'], b['metrics'])
        self.assertEqual(sum(a['metrics'][k] for k in ('win_count','loss_count','flat_count')), 200)
        self.assertEqual(sum(a['metrics'][k] for k in ('stop_count','target_count','timeout_count')), 200)

    def test_world_actual_ten_thousand_finite_participants(self):
        r = self.module.world(market(), config(), seed=19, agents=10000, steps=20)
        metric = r['metrics']
        self.assertEqual(metric['participant_count'], 10000)
        self.assertEqual(metric['submitted_orders'], 200000)
        self.assertGreater(metric['matched_trades'], 0)
        self.assertGreater(metric['participants_traded'], 0)
        self.assertEqual(metric['initial_cash_units'], metric['final_cash_units'])
        self.assertEqual(metric['initial_inventory_lots'], metric['final_inventory_lots'])
        self.assertTrue(metric['all_balances_nonnegative'])
        self.assertTrue(r['ledger_sample'])
        b = self.module.world(market(), config(), seed=19, agents=10000, steps=20)
        self.assertEqual(r['metrics'], b['metrics'])
        self.assertEqual(r['ledger_digest'], b['ledger_digest'])

    def test_caps_invalid_plan_and_gaps_rejected(self):
        p = dict(status='ready', side='long', entry='100', stop='110', target='90')
        with self.assertRaises(SkillError):
            self.module.simulate(market(), config(), p, replays=2)
        with self.assertRaises(SkillError):
            self.module.world(market(), config(), agents=10001)
        m = market(); m['bars'][1]['time'] = m['bars'][0]['time']
        with self.assertRaises(SkillError):
            self.module.backtest(m, config())

    def test_missing_market_units_are_not_inferred(self):
        m = market(); del m['metadata']
        with self.assertRaises(SkillError):
            self.module.backtest(m, config())
        c = config(); del c['price_tick']
        with self.assertRaises(SkillError):
            self.module.world(market(), c, agents=2, steps=1)

    def test_run_missing_market_records_insufficient_data(self):
        with tempfile.TemporaryDirectory() as t:
            w = Workspace(t); w.write('config', config())
            a = SimpleNamespace(workspace=t, command='backtest', now=None)
            self.assertEqual(self.module.run(a)['data']['status'], 'insufficient_data')

    def test_run_rejects_stale_plan_lineage(self):
        with tempfile.TemporaryDirectory() as t:
            w = Workspace(t)
            c = w.write('config', config()); m = w.write('market', market())
            p = dict(status='ready', side='long', entry='125', stop='100', target='150')
            w.write('plan', p, inputs={'config': c['digest'], 'market':'stale'})
            args = SimpleNamespace(workspace=t, command='simulate', now=None,
                                   seed=19, replays=20, steps=6, block_size=2)
            with self.assertRaises(SkillError):
                self.module.run(args)
            w.write('plan', p, inputs={'config':c['digest'], 'market':m['digest']})
            result = self.module.run(args)
            self.assertEqual(result['inputs']['market'], m['digest'])
            self.assertEqual(result['data']['status'], 'complete')

    def test_simulation_rejects_changed_transitive_proposal_and_named_inputs(self):
        with tempfile.TemporaryDirectory() as t:
            w = Workspace(t); c = w.write('config', config())
            m = w.write('market', market(), inputs={'config':c['digest']})
            inputs = {'config':c['digest'],'market':m['digest']}
            proposal = w.write('proposal',dict(status='ready'),inputs=inputs)
            plan = dict(status='ready', side='long', entry='125', stop='100', target='150')
            w.write('plan',plan,inputs=dict(inputs,proposal=proposal['digest']))
            args = SimpleNamespace(workspace=t, command='simulate', now=None,
                                   seed=19,replays=2,steps=2,block_size=2)
            w.write('proposal',dict(status='waiting'),inputs=inputs)
            with self.assertRaises(SkillError):
                self.module.run(args)
            proposal = w.write('proposal',dict(status='ready'),inputs=dict(inputs,config='old'))
            w.write('plan',plan,inputs=dict(inputs,proposal=proposal['digest']))
            with self.assertRaises(SkillError):
                self.module.run(args)


if __name__ == '__main__':
    unittest.main()
