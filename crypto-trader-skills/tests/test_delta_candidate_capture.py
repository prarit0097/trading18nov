import sqlite3
import unittest
from unittest.mock import patch

from crypto_skills.delta_candidate_capture import capture, init_store, main, project_coin, record, validation_window
from crypto_skills.delta_signal import INTERVAL, LOOKBACK


class CandidateCaptureTests(unittest.TestCase):
    def test_window_starts_next_full_ist_day_for_84_days(self):
        start, end = validation_window('2026-11-18T19:51:32Z')
        self.assertEqual(start.isoformat(), '2026-11-19T18:30:00+00:00')
        self.assertEqual((end-start).days, 84)

    def test_stale_quote_and_missing_book_do_not_become_valid_observations(self):
        slot = 600000

        def fetch(path, **args):
            symbol = args.get('symbol') or path.rsplit('/',1)[-1]
            if path == '/history/candles':
                return [dict(time=t, open=1, close=1, high=1, low=1, volume=5)
                        for t in range(slot-6300, slot, 300)]
            if path.startswith('/tickers/'):
                time = slot-60 if symbol=='ETHUSD' else slot
                return dict(symbol=symbol, timestamp=time*1000000, product_id=1, mark_price='1',
                            quotes={'best_bid':'.99','best_ask':'1'}, turnover_usd='100')
            if symbol=='BTCUSD':
                raise RuntimeError('exchange unavailable')
            return dict(symbol=symbol,last_updated_at=slot*1000000,
                        buy=[{'price':'.99','size':3}],sell=[{'price':'1','size':3}])

        sample = capture(slot, fetch=fetch, clock=lambda:slot+4)
        self.assertEqual(sample['coins']['SOLUSD']['status'], 'valid')
        self.assertEqual(sample['coins']['SOLUSD']['signal']['status'], 'waiting')
        self.assertEqual(sample['coins']['BTCUSD']['status'], 'unavailable')
        self.assertEqual(sample['coins']['ETHUSD']['status'], 'unavailable')
        self.assertFalse(sample['complete'])

    def test_smoke_fails_if_any_required_coin_is_unavailable(self):
        observation = dict(complete=False, coins={
            'BTCUSD': {'status': 'valid'},
            'ETHUSD': {'status': 'unavailable', 'reason': 'Capture finished after the decision window'},
        })
        with (patch('sys.argv', ['capture', '--smoke']),
              patch('crypto_skills.delta_candidate_capture.capture', return_value=observation),
              patch('builtins.print')):
            with self.assertRaises(SystemExit) as failure:
                main()
        self.assertEqual(failure.exception.code, 1)

    def test_slot_records_are_idempotent_and_candidate_identity_is_fixed(self):
        connection=sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        init_store(connection, {'version':'v1','start':1,'end':2})
        self.assertTrue(record(connection,600,{'complete':False}))
        self.assertFalse(record(connection,600,{'complete':True}))
        self.assertEqual(connection.execute('SELECT COUNT(*) FROM observations').fetchone()[0],1)
        with self.assertRaises(ValueError):
            init_store(connection, {'version':'v2','start':1,'end':2})

    def test_candle_request_seeds_leading_zero_volume_bars_but_keeps_the_frozen_window(self):
        slot = 600000
        window_start = slot - (LOOKBACK + 1) * INTERVAL

        def fetch(path, **args):
            if path == '/history/candles':
                start = args['start']
                self.assertEqual(args['end'], slot-1)
                return [dict(time=t, open=1, close=1, high=1, low=1, volume=0 if
                             window_start <= t < window_start + 2*INTERVAL else 5)
                        for t in range(start, slot, INTERVAL)
                        if start <= slot-48*INTERVAL or not window_start <= t < window_start + 2*INTERVAL]
            if path.startswith('/tickers/'):
                return dict(symbol='DOGEUSD', timestamp=slot*1_000_000,
                            quotes={'best_bid':'.99','best_ask':'1'})
            return dict(symbol='DOGEUSD', last_updated_at=slot*1_000_000,
                        buy=[{'price':'.99','size':3}],sell=[{'price':'1','size':3}])

        record = project_coin('DOGEUSD', slot, fetch, lambda: slot + 5)
        self.assertEqual(record['status'], 'valid')
        self.assertEqual([row['time'] for row in record['candles']], list(range(window_start,slot,INTERVAL)))
        self.assertEqual([row['volume'] for row in record['candles'][:2]], [0,0])
        self.assertEqual(record['signal']['closed_at'], slot)
