from datetime import datetime
from decimal import Decimal
import unittest
from unittest.mock import patch

from crypto_skills.delta_candidate_capture import IST
from crypto_skills.delta_candidate_replay import model_batch, model_portfolio, replay_pair


class CandidateReplayTests(unittest.TestCase):
    def setUp(self):
        self.entry = dict(status='modeled_entry',
            entries=[dict(symbol='ETHUSD',stop='99',target='102',quantity='3',contracts=3),
                     dict(symbol='BTCUSD',stop='99',target='102',quantity='3',contracts=3)],
            fills=[dict(symbol='ETHUSD',filled=3,avg_price='100',state='full'),
                   dict(symbol='BTCUSD',filled=1,avg_price='100',state='partial')])
        candle=[dict(time=t, open='100',low='99.5',high='101',close='100') for t in range(0,660,60)]
        self.exit = {symbol:dict(mark_bars=candle,exit_quotes=[dict(time=606,bids=[dict(price='100.10',size=3)])],
                               funding_usd='0') for symbol in ('ETHUSD','BTCUSD')}

    def run_batch(self, entry):
        with patch('crypto_skills.delta_candidate_replay.evaluate_entry',return_value=entry):
            return model_batch({'captured_at':4},{},0,self.exit,cash='160',day_loss='0',
                               ready_only=False,fee_rate='.001')

    def test_partial_position_is_settled_in_cash_but_not_in_full_size_sample(self):
        r=self.run_batch(self.entry)
        self.assertTrue(r['complete'])
        self.assertEqual(r['closed_at'],606)
        self.assertAlmostEqual(Decimal(r['total_net_usd']),Decimal('-.4004'))
        self.assertEqual([Decimal(value) for value in r['full_size_net_usd']],[Decimal('-.3003')])

    def test_unknown_exit_is_preserved_without_fabricating_aggregate_pnl(self):
        self.exit.pop('BTCUSD')
        r=self.run_batch(self.entry)
        self.assertFalse(r['complete'])
        self.assertIsNone(r['total_net_usd'])
        self.assertEqual(r['positions'][1]['exit']['status'],'unavailable')

    def test_no_ready_batch_does_not_create_a_trade(self):
        r=self.run_batch(dict(status='insufficient_distinct_coins',fills=[]))
        self.assertTrue(r['complete'])
        self.assertEqual(r['positions'],[])
        self.assertEqual(r['full_size_net_usd'],[])

    def test_account_cash_changes_only_after_close_and_partial_costs_still_count(self):
        start=int(datetime(2026,11,20,tzinfo=IST).timestamp())
        slots={s:{'snapshot':{},'exits':{}} for s in range(start,start+86400,300)}
        flat=dict(decision_status='insufficient_distinct_coins',planned_lots=0,fill_attempts=[],
                  complete=True,closed_at=None,total_net_usd='0',full_size_net_usd=[],settled_net_usd=[])
        filled=dict(complete=True,closed_at=start+604,total_net_usd='-1.50',full_size_net_usd=['-1.20'],
                    settled_net_usd=['-1.20','-.30'],decision_status='mark_outside_brackets',
                    planned_lots=4,fill_attempts=[{'state':'full'},{'state':'partial'},{'state':'unfilled'}])
        with patch('crypto_skills.delta_candidate_replay.model_batch',side_effect=[filled]+[flat]*300) as batch:
            days=model_portfolio(slots,{},start,start+86400,cash='160',ready_only=False,fee_rate='.001')
        self.assertEqual(batch.call_args_list[1].args[2],start+900)
        self.assertEqual(batch.call_args_list[1].kwargs['cash'],Decimal('158.50'))
        self.assertEqual(batch.call_args_list[1].kwargs['day_loss'],Decimal('1.50'))
        self.assertEqual(days[0]['cash_net_usd'],'-1.50')
        self.assertEqual(days[0]['full_size_net_usd'],['-1.20'])
        self.assertEqual(days[0]['settled_net_usd'],['-1.20','-.30'])
        evidence = days[0]['execution']
        self.assertEqual((evidence['scheduled_slots'], evidence['busy_slots'], evidence['observed_slots'],
                          evidence['unreplayed_slots']), (286, 2, 284, 0))
        self.assertEqual((evidence['planned_lots'],evidence['attempted_lots'],evidence['unsent_lots']),
                         (4,3,1))
        self.assertEqual(evidence['ioc_outcomes'], {'full':1,'partial':1,'unfilled':1})
        self.assertEqual(evidence['decisions']['insufficient_distinct_coins'], 283)

    def test_missing_flat_opportunity_marks_future_portfolio_unknown(self):
        start=int(datetime(2026,11,20,tzinfo=IST).timestamp())
        days=model_portfolio({}, {},start,start+2*86400,cash='160',ready_only=False,fee_rate='.001')
        self.assertEqual([day['complete'] for day in days],[False,False])
        self.assertEqual(days[0]['execution']['missing_frame_slots'],1)
        self.assertEqual([d['execution']['unreplayed_slots'] for d in days],[287,286])

    def test_pair_uses_the_same_frames_cash_and_fee_for_both_arms(self):
        frames={123:{'snapshot':{},'exits':{}}}
        baseline=[dict(day='2026-11-20',complete=True,cash_net_usd='-1',full_size_net_usd=['-1'],
                       settled_net_usd=['-1'],execution={'attempted_lots':1})]
        candidate=[dict(day='2026-11-20',complete=True,cash_net_usd='0',full_size_net_usd=[],
                        settled_net_usd=[],execution={'attempted_lots':0})]
        with patch('crypto_skills.delta_candidate_replay.model_portfolio',side_effect=[baseline,candidate]) as replay:
            result=replay_pair(frames,{},123,124,cash='160',fee_rate='.000531')
        a,b=replay.call_args_list
        self.assertEqual(a.args,b.args)
        self.assertEqual(a.kwargs['cash'],b.kwargs['cash'])
        self.assertEqual(a.kwargs['fee_rate'],b.kwargs['fee_rate'])
        self.assertNotEqual(a.kwargs['ready_only'],b.kwargs['ready_only'])
        self.assertEqual(result['days'][0]['baseline'],['-1'])
        self.assertEqual(result['days'][0]['candidate'],[])
        self.assertEqual(result['days'][0]['baseline_execution']['attempted_lots'],1)
        self.assertEqual(result['days'][0]['candidate_execution']['attempted_lots'],0)
        self.assertFalse(result['auto_promote'])
