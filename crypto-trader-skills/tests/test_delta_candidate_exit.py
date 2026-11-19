from decimal import Decimal
import unittest

from crypto_skills.delta_candidate_exit import timed_exit


class CandidateExitTests(unittest.TestCase):
    def setUp(self):
        self.trade=dict(entry_price='100',first_fill_at=4,filled=3,stop='99',target='102',
                        contract_value='1',entry_fee_rate='.001')
        self.mark=[dict(time=t,open='100',close='100',low='99.5',high='101')
                   for t in range(0,660,60)]
        self.bids=[{'price':'100.10','size':1},{'price':'100.00','size':2}]

    def test_timed_long_exit_walks_bids_then_debits_fees_and_funding(self):
        out=timed_exit(self.trade,self.mark, [{'time':606,'bids':self.bids}],
                       exit_fee_rate='.001',funding_usd='-.05')
        self.assertEqual(out['status'],'modeled_exit')
        self.assertEqual(out['close_time'],606)
        self.assertEqual(out['deadline_at'],604)
        self.assertEqual(Decimal(out['net_usd']),Decimal('-0.55010'))

    def test_quote_before_exact_deadline_unusable(self):
        out=timed_exit(self.trade,self.mark, [{'time':603,'bids':self.bids}],
                       exit_fee_rate='.001',funding_usd='0')
        self.assertEqual(out['status'],'unavailable')
        self.assertIsNone(out.get('net_usd'))

    def test_mark_touch_is_not_scored_as_timer_exit(self):
        self.mark[5]['low']='98'
        out=timed_exit(self.trade,self.mark, [{'time':607,'bids':self.bids}],
                       exit_fee_rate='.001',funding_usd='0')
        self.assertEqual(out['status'],'protective_exit_unresolved')
        self.assertEqual(out['trigger_type'],'stop_loss')
        self.assertIsNone(out.get('net_usd'))

    def test_missing_mark_or_funding_or_visible_bid_quantity_is_unavailable(self):
        self.assertEqual(timed_exit(self.trade,self.mark[1:],[{'time':606,'bids':self.bids}],
                                    exit_fee_rate='.001',funding_usd='0')['status'],'unavailable')
        self.assertEqual(timed_exit(self.trade,self.mark,[{'time':606,'bids':self.bids}],
                                    exit_fee_rate='.001',funding_usd=None)['status'],'unavailable')
        self.assertEqual(timed_exit(self.trade,self.mark,[{'time':606,'bids':self.bids[:1]}],
                                    exit_fee_rate='.001',funding_usd='0')['status'],'unavailable')

    def test_spread_and_depth_cost_can_be_doubled_without_changing_commissions(self):
        trade=dict(self.trade,entry_midpoint='99.95')
        quotes=[{'time':606,'bids':self.bids,'best_ask':'100.15'}]
        plain=timed_exit(trade,self.mark,quotes,exit_fee_rate='.001',funding_usd='0')
        stress=timed_exit(trade,self.mark,quotes,exit_fee_rate='.001',funding_usd='0',stress=True)
        self.assertEqual(Decimal(stress['extra_execution_usd']),Decimal('.425'))
        self.assertEqual(stress['fees_usd'],plain['fees_usd'])
        self.assertEqual(Decimal(stress['net_usd']),Decimal(plain['net_usd'])-Decimal('.425'))
        unknown=timed_exit(trade,self.mark,[{'time':606,'bids':self.bids}],
                           exit_fee_rate='.001',funding_usd='0',stress=True)
        self.assertEqual(unknown['status'],'unavailable')
