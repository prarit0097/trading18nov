from contextlib import closing
import sqlite3
import unittest

from crypto_skills.delta_candidate_books import capture_books, init_deadline_store, record_books
from crypto_skills.delta_candidate_capture import record
from crypto_skills.delta_candidate_frames import assemble_frames


class DeadlineBookTests(unittest.TestCase):
    def test_deferred_capture_rejects_books_from_before_the_exact_deadline(self):
        deadline = 600606.25

        def quote(path, **params):
            symbol = path.rsplit('/', 1)[-1]
            stamp = deadline-1 if symbol=='BTCUSD' else deadline+1
            return dict(symbol=symbol,last_updated_at=int(stamp*1_000_000),
                        buy=[dict(price='1',size=3)],sell=[dict(price='1.01',size=3)])

        result = capture_books(deadline,fetch=quote,clock=lambda:deadline+2)
        self.assertEqual(result['coins']['BTCUSD']['status'],'unavailable')
        self.assertEqual(result['coins']['ETHUSD']['status'],'valid')

    def test_deadline_tape_supplies_post_timer_book_without_rewriting_an_existing_record(self):
        slot, opened, deadline = 600000, 600006.25, 600606.25
        snapshot = dict(captured_at=opened, coins={})
        with closing(sqlite3.connect(':memory:')) as db:
            init_deadline_store(db, {'version':'fixture'})
            record(db,slot,snapshot)
            bids=[dict(price='1',size=3)]
            book=dict(symbol='ETHUSD',last_updated_at=int((deadline+1)*1_000_000),
                      buy=bids,sell=[dict(price='1.01',size=3)])
            record(db,slot+600,dict(captured_at=deadline+1,coins={'ETHUSD':dict(
                status='valid',book_observed_at=deadline+.5,
                book=dict(book,last_updated_at=int((deadline-.5)*1_000_000)))}))
            data=dict(deadline_at=deadline,captured_at=deadline+2,coins={'ETHUSD':dict(
                status='valid',book_observed_at=deadline+1.5,book=book)})
            self.assertTrue(record_books(db,slot,data))
            self.assertFalse(record_books(db,slot,dict(data,coins={})))
            frames=assemble_frames(db,slot,slot+900,{}, {})
        self.assertEqual(frames[slot]['exits']['ETHUSD']['exit_quotes'],
                         [dict(time=deadline+1.5,bids=bids,best_ask='1.01')])
