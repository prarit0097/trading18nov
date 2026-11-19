"""Record public books immediately after the replay's exact holding deadlines."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import sqlite3
import time

from .core import Workspace
from .delta_candidate_capture import (INTERVAL, MAX_QUOTE_AGE, capture_registration,
                                       init_store, public_result)
from .delta_candidate_exit import HOLD_SECONDS, book_midpoint
from .delta_plan import CRYPTO_DEMO_SYMBOLS

BOOK_DELAY = 2


def project_book(symbol, deadline, fetch, clock):
    try:
        book = fetch('/l2orderbook/'+symbol, depth=5)
        observed = clock()
        exchange = int(book['last_updated_at'])/1_000_000
        if (book['symbol'] != symbol or not deadline <= exchange <= observed+2
                or not deadline <= observed < deadline+MAX_QUOTE_AGE):
            raise ValueError('Book timestamp does not cover the deadline')
        book_midpoint(book)
    except (OSError, TypeError, KeyError, ValueError, RuntimeError, ArithmeticError) as exc:
        return dict(status='unavailable', reason=str(exc))
    return dict(status='valid', book_observed_at=observed, book=book)


def capture_books(deadline, *, fetch=public_result, clock=time.time):
    if not deadline <= clock() < deadline+MAX_QUOTE_AGE:
        raise ValueError('Capture is outside the post-deadline window')
    with ThreadPoolExecutor(max_workers=len(CRYPTO_DEMO_SYMBOLS)) as pool:
        results = pool.map(lambda symbol:project_book(symbol,deadline,fetch,clock),CRYPTO_DEMO_SYMBOLS)
        coins = dict(zip(CRYPTO_DEMO_SYMBOLS,results))
    return dict(deadline_at=deadline, captured_at=clock(), coins=coins)


def init_deadline_store(connection, identity):
    init_store(connection, identity)
    with connection:
        connection.execute('CREATE TABLE IF NOT EXISTS deadline_books (entry_slot INTEGER PRIMARY KEY, payload TEXT NOT NULL)')


def record_books(connection, slot, payload):
    with connection:
        result = connection.execute('INSERT OR IGNORE INTO deadline_books VALUES (?,?)',
                                    (slot, json.dumps(payload, allow_nan=False)))
    return result.rowcount == 1


def load_books(connection, start, end):
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='deadline_books'").fetchone():
        return {}
    return {slot:json.loads(payload) for slot,payload in connection.execute(
        'SELECT entry_slot,payload FROM deadline_books WHERE entry_slot>=? AND entry_slot<?', (start,end))}


def run_books(run):
    identity, start, end = capture_registration(run)
    lower, upper = int(start.timestamp()), int(end.timestamp())
    with Workspace(run).lock('candidate_exit_books'):
        with closing(sqlite3.connect(run/'four-ready-quotes.sqlite3', timeout=10)) as connection:
            init_deadline_store(connection, identity)
            print(json.dumps(dict(identity, mode='deadline_books')), flush=True)
            while not (run/'STOP_CANDIDATE_EXIT_BOOKS').exists():
                now = time.time()
                if now >= upper:
                    break
                current = int(now//INTERVAL)*INTERVAL
                entry = current-HOLD_SECONDS
                wake = min(upper,max(current+INTERVAL,lower+HOLD_SECONDS))
                if lower <= entry < upper-HOLD_SECONDS:
                    stored = connection.execute('SELECT payload FROM observations WHERE slot=?', (entry,)).fetchone()
                    exists = connection.execute('SELECT 1 FROM deadline_books WHERE entry_slot=?', (entry,)).fetchone()
                    if stored and not exists:
                        opened = json.loads(stored[0]).get('captured_at')
                        if type(opened) in (int, float) and entry <= opened < entry+MAX_QUOTE_AGE:
                            deadline = opened+HOLD_SECONDS
                            if now < deadline+BOOK_DELAY:
                                wake = deadline+BOOK_DELAY
                            elif now < deadline+MAX_QUOTE_AGE:
                                record_books(connection,entry,capture_books(deadline))
                time.sleep(min(30,max(0.1,wake-time.time())))
