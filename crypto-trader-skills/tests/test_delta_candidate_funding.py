from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from crypto_skills.delta_candidate_funding import FundingSchedule, load_schedule


class FundingScheduleTests(unittest.TestCase):
    def setUp(self):
        self.rows = [dict(symbol='ETHUSD', received_utc_ms=seconds*1000,
                          observed_exchange_us=seconds*1000000-100000,
                          next_realization_us=12000000000, interval_seconds=3600,
                          observed_rate=.01, stream_id='one-stream')
                     for seconds in range(9990, 10700, 60)]

    def test_consistent_fresh_schedule_covers_the_exact_holding_window(self):
        schedule = FundingSchedule(self.rows)
        self.assertTrue(schedule.proves_zero('ETHUSD', 10000.25, 10600.25))
        self.assertFalse(schedule.proves_zero('BTCUSD', 10000.25, 10600.25))

    def test_unknown_funding_stays_unknown_across_gaps_restarts_and_events(self):
        no_open_stamp = self.rows[1:]
        no_close_stamp = self.rows[:-1]
        gap = self.rows[:4] + self.rows[6:]
        restart = [dict(row, stream_id='restored') if i >= 5 else row for i, row in enumerate(self.rows)]
        funding_event = [dict(row, next_realization_us=10320000000 if i < 6 else 13920000000)
                         for i, row in enumerate(self.rows)]
        for rows in (no_open_stamp, no_close_stamp, gap, restart, funding_event):
            self.assertFalse(FundingSchedule(rows).proves_zero('ETHUSD', 10000.25, 10600.25))

    def test_capture_from_another_candidate_is_rejected(self):
        identity = {'version':'ready-v1', 'evidence_sha256':'registered'}
        with TemporaryDirectory() as directory:
            raw = Path(directory)/'four-ready-funding-1970-01-01.jsonl'
            raw.write_text(json.dumps(dict(self.rows[0], version='ready-v1', evidence_sha256='different'))+'\n',
                           encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'frozen candidate'):
                load_schedule(Path(directory), identity, 9000, 11000)

    def test_replay_cutoff_cannot_use_future_observations(self):
        identity = {'version':'ready-v1', 'evidence_sha256':'registered'}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root/'four-ready-funding-1970-01-01.jsonl'
            raw.write_text(''.join(json.dumps(dict(identity, **row))+'\n' for row in self.rows), encoding='utf-8')
            self.assertTrue(load_schedule(root, identity, 9000, 10700).proves_zero('ETHUSD', 10000.25, 10600.25))
            self.assertFalse(load_schedule(root, identity, 9000, 10610).proves_zero('ETHUSD', 10000.25, 10600.25))
