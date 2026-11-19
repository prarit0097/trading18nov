from contextlib import closing
import sqlite3
import unittest

from crypto_skills.delta_candidate_capture import init_store, record
from crypto_skills.delta_candidate_frames import ReplayFrames, assemble_frames
from crypto_skills.delta_candidate_funding import FundingSchedule


class CandidateFrameTests(unittest.TestCase):
    def test_day_window_matches_full_replay_across_the_midnight_boundary(self):
        first, midnight, end = 585000, 671400, 757800
        opened, close = midnight-300, midnight+300
        bid = dict(price='100',size=3)
        snapshot = dict(captured_at=close+7, coins={'BTCUSD':dict(status='valid',book_observed_at=close+7,
                        book=dict(symbol='BTCUSD',last_updated_at=(close+6)*1000000,buy=[bid]))})
        with closing(sqlite3.connect(':memory:')) as db:
            init_store(db,{'version':'fixture'})
            record(db,opened,dict(captured_at=opened+5,coins={}))
            record(db,close,snapshot)
            marks={'BTCUSD':[dict(time=close,low=1,high=1,open=1,close=1)]}
            reference=assemble_frames(db,first,end,marks,{})
            queries=[]
            db.set_trace_callback(queries.append)
            live=ReplayFrames(db,first,end,marks,{})
            self.assertEqual(live.get(opened),reference[opened])
            self.assertEqual(live.get(opened)['exits']['BTCUSD']['exit_quotes'],[dict(time=close+7,bids=[bid])])
            self.assertEqual(live.get(close),reference[close])
            self.assertEqual(live.get(opened),reference[opened])
            self.assertIsNone(live.get(end))
            snapshots=[sql for sql in queries if 'FROM observations' in sql]
            self.assertEqual(len(snapshots),3)
            self.assertIn('slot<672000',snapshots[0])

    def test_exit_uses_actual_read_time_and_requires_recorded_funding(self):
        slot=600000
        entry=dict(captured_at=slot+6, complete=True, coins={})
        bid=dict(price='1.0',size=3)
        observed=dict(captured_at=slot+611,complete=True,coins={'ETHUSD':dict(
            status='valid',book_observed_at=slot+608,book={
                'symbol':'ETHUSD','last_updated_at':(slot+607)*1000000,'buy':[bid]})})
        marks={'ETHUSD':[dict(time=t,low=1,high=1,open=1,close=1) for t in range(slot,slot+660,60)]}
        schedule=FundingSchedule(dict(symbol='ETHUSD',received_utc_ms=t*1000,
            observed_exchange_us=t*1000000,next_realization_us=(slot+1800)*1000000,
            interval_seconds=3600,observed_rate=.01,stream_id='active')
            for t in range(slot,slot+720,60))
        with closing(sqlite3.connect(':memory:')) as db:
            init_store(db,{'version':'fixture'})
            record(db,slot,entry)
            record(db,slot+600,observed)
            frames=assemble_frames(db,slot,slot+900,marks,{slot:{'ETHUSD':'-.1'}},schedule=schedule)
            inferred=assemble_frames(db,slot,slot+900,marks,{},schedule=schedule)
        eth=frames[slot]['exits']['ETHUSD']
        self.assertEqual(eth['exit_quotes'],[dict(time=slot+608,bids=[bid])])
        self.assertEqual(len(eth['mark_bars']),11)
        self.assertEqual(eth['funding_per_contract'],'-.1')
        self.assertEqual(eth['funding_source'],'supplied_cashflow')
        self.assertIsNone(frames[slot]['exits']['BTCUSD']['funding_per_contract'])
        self.assertEqual(inferred[slot]['exits']['ETHUSD']['funding_per_contract'],'0')
        self.assertEqual(inferred[slot]['exits']['ETHUSD']['funding_source'],'observed_schedule_no_event')

    def test_missing_capture_timestamp_does_not_create_a_close_quote(self):
        slot=600000
        entry=dict(captured_at=slot+5, complete=True,coins={})
        close=dict(captured_at=slot+606,complete=True,coins={'ETHUSD':dict(
            status='valid',book={'symbol':'ETHUSD','buy':[dict(price='1.0',size=3)]})})
        with closing(sqlite3.connect(':memory:')) as db:
            init_store(db,{'version':'fixture'})
            record(db,slot,entry)
            record(db,slot+600,close)
            frames=assemble_frames(db,slot,slot+900,{}, {})
        self.assertEqual(frames[slot]['exits']['ETHUSD']['exit_quotes'],[])
