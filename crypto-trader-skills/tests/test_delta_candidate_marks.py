from collections import defaultdict
import unittest

from crypto_skills.delta_candidate_marks import fetch_mark_history


def bar(at):
    return dict(time=at,open=1,high=2,low=.5,close=1.5,volume=None)


class CandidateMarkTests(unittest.TestCase):
    def test_fetches_disjoint_closed_minute_pages_and_preserves_gaps(self):
        start, split, end = 600000, 686400, 686520
        calls = defaultdict(list)

        def feed(path, **args):
            self.assertEqual(path,'/history/candles')
            self.assertEqual(args['resolution'],'1m')
            calls[args['symbol']].append((args['start'],args['end']))
            return [bar(at) for at in reversed(range(args['start'],args['end'],60)) if at!=start+60]

        marks, coverage = fetch_mark_history(start,end,fetch=feed,clock=lambda:end+30)
        self.assertEqual(calls['MARK:BTCUSD'],[(start,split-1),(split,end-1)])
        self.assertEqual(marks['BTCUSD'][0]['time'],start)
        self.assertEqual(marks['BTCUSD'][-1]['time'],end-60)
        self.assertNotIn(start+60,{row['time'] for row in marks['BTCUSD']})
        self.assertEqual(coverage['BTCUSD']['missing_minutes'],1)
        self.assertEqual(coverage['BTCUSD']['failed_pages'],[])

    def test_ambiguous_page_stays_unavailable_and_future_cutoff_is_rejected(self):
        start, end = 600000, 600180

        def feed(path, **args):
            return [bar(start),bar(start)] if args['symbol']=='MARK:ETHUSD' else [bar(start)]

        marks, coverage = fetch_mark_history(start,end,fetch=feed,clock=lambda:end)
        self.assertFalse(marks['ETHUSD'])
        self.assertEqual(coverage['ETHUSD']['missing_minutes'],3)
        self.assertEqual(coverage['ETHUSD']['failed_pages'][0]['start'],start)
        self.assertEqual(len(marks['BTCUSD']),1)
        with self.assertRaisesRegex(ValueError,'closed'):
            fetch_mark_history(start,end,fetch=feed,clock=lambda:end-1)
