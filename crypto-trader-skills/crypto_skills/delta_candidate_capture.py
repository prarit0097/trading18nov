"""Capture read-only Delta demo inputs for the frozen four-READY candidate."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, nullcontext
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import subprocess
import time
from urllib.parse import urlencode
from urllib.request import urlopen

from .core import Workspace
from .delta_plan import CRYPTO_DEMO_SYMBOLS
from .delta_signal import INTERVAL, LOOKBACK, closed_breakout

BASE = 'https://cdn-ind.testnet.deltaex.org/v2'
VERSION = 'delta-demo-trade1-four-ready-v1'
IST = timezone(timedelta(hours=5, minutes=30))
DAYS = 84
CAPTURE_DELAY = 4
MAX_QUOTE_AGE = 15
CANDLE_REQUEST_BARS = 48


def validation_window(frozen_at):
    registered = datetime.fromisoformat(frozen_at)
    if registered.utcoffset() is None:
        raise ValueError('Candidate registration must have a timezone')
    local = registered.astimezone(IST) + timedelta(days=1)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    return start, start + timedelta(days=DAYS)


def public_result(path, **params):
    url = BASE + path
    if params:
        url += '?' + urlencode(params)
    with urlopen(url, timeout=5) as response:
        payload = json.load(response)
    if payload.get('success') is not True:
        raise RuntimeError('Public Delta request failed')
    return payload['result']


def project_coin(symbol, slot, fetch, clock):
    coin = {}
    try:
        window_start = slot - (LOOKBACK + 1) * INTERVAL
        # An earlier traded bar helps Delta return zero-volume bars at the window's leading edge.
        candles = fetch('/history/candles', symbol=symbol, resolution='5m',
                        start=slot-CANDLE_REQUEST_BARS*INTERVAL, end=slot-1)
        coin['candles'] = sorted((bar for bar in candles if window_start <= bar['time'] < slot),
                                 key=lambda bar:bar['time'])
        coin['signal'] = closed_breakout(coin['candles'], slot)
        ticker = fetch('/tickers/'+symbol)
        coin['ticker'] = {field:ticker[field] for field in (
            'symbol','timestamp','product_id','mark_price','quotes','turnover_usd',
            'funding_rate','next_funding_realization') if field in ticker}
        book = fetch('/l2orderbook/'+symbol, depth=5)
        coin['book'] = book
        now = clock()
        coin['book_observed_at'] = now
        if now >= slot+MAX_QUOTE_AGE:
            raise ValueError('Capture finished after the decision window')
        for feed, timestamp in ((ticker,'timestamp'),(book,'last_updated_at')):
            age = now - int(feed[timestamp])/1000000
            if feed['symbol'] != symbol or not -2 <= age <= MAX_QUOTE_AGE:
                raise ValueError('Exchange timestamp or symbol is inconsistent')
        best = ticker['quotes']
        if not 0 < Decimal(best['best_bid']) <= Decimal(best['best_ask']):
            raise ValueError('Invalid ticker bid/ask')
        if not book['buy'] or not book['sell']:
            raise ValueError('Displayed order book is empty')
    except (OSError, TimeoutError, TypeError, KeyError, ValueError, RuntimeError, ArithmeticError) as exc:
        return dict(coin, status='unavailable', reason=str(exc))
    return dict(coin, status='valid')


def capture(slot, *, fetch=public_result, clock=time.time):
    if type(slot) is not int or slot%INTERVAL != 0:
        raise ValueError('Capture slot must be a five-minute boundary')
    started = clock()
    with ThreadPoolExecutor(max_workers=len(CRYPTO_DEMO_SYMBOLS)) as pool:
        results = pool.map(lambda symbol:project_coin(symbol,slot,fetch,clock),CRYPTO_DEMO_SYMBOLS)
        coins = dict(zip(CRYPTO_DEMO_SYMBOLS,results))
    return dict(started_at=started, captured_at=clock(), coins=coins,
                complete=all(row['status']=='valid' for row in coins.values()))


def init_store(connection, identity):
    key = json.dumps(identity, sort_keys=True)
    with connection:
        connection.execute('CREATE TABLE IF NOT EXISTS metadata (id INTEGER PRIMARY KEY CHECK(id=1), identity TEXT NOT NULL)')
        connection.execute('CREATE TABLE IF NOT EXISTS observations (slot INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
        connection.execute('INSERT OR IGNORE INTO metadata VALUES (1,?)',(key,))
        if connection.execute('SELECT identity FROM metadata WHERE id=1').fetchone()[0] != key:
            raise ValueError('Database belongs to different frozen evidence')


def record(connection, slot, payload):
    with connection:
        result = connection.execute('INSERT OR IGNORE INTO observations VALUES (?,?)',
                                    (slot,json.dumps(payload, allow_nan=False)))
    return result.rowcount == 1


def run_capture(run):
    with Workspace(run).lock('candidate_capture'):
        capture_window(run)


def capture_registration(run):
    queue = json.loads((run/'reviews.json').read_text(encoding='utf-8'))['campaign_reviews']
    candidate = queue['candidate_registry'][VERSION]
    start, end = validation_window(candidate['frozen_at'])
    identity = dict(version=VERSION, baseline_version=candidate['baseline_version'],
                    review_id=candidate['review_id'], evidence_sha256=candidate['evidence_sha256'],
                    start=start.isoformat(), end=end.isoformat(), environment='india_testnet')
    return identity, start, end


def capture_window(run):
    identity, start, end = capture_registration(run)
    with closing(sqlite3.connect(run/'four-ready-quotes.sqlite3', timeout=10)) as connection:
        init_store(connection, identity)
        print(json.dumps(identity), flush=True)
        lower, upper = int(start.timestamp()), int(end.timestamp())
        while not (run/'STOP_CANDIDATE_CAPTURE').exists():
            now = time.time()
            slot = int(now//INTERVAL)*INTERVAL
            if now >= upper:
                break
            if slot < lower or now < slot+CAPTURE_DELAY:
                time.sleep(min(30,max(0.2,max(lower,slot)+CAPTURE_DELAY-now)))
            elif now < slot+MAX_QUOTE_AGE and not connection.execute(
                    'SELECT 1 FROM observations WHERE slot=?',(slot,)).fetchone():
                record(connection,slot,capture(slot))
            else:
                time.sleep(min(30,max(0.2,slot+INTERVAL+CAPTURE_DELAY-now)))


def run_node_capture(run, node, *, study, smoke=False):
    identity, _, _ = capture_registration(run)
    script = Path(__file__).with_name(f'delta_candidate_{study}.mjs')
    args = [node, str(script), str(run), json.dumps(identity),
            'smoke' if smoke else 'record', *CRYPTO_DEMO_SYMBOLS]
    with nullcontext() if smoke else Workspace(run).lock(f'candidate_{study}'):
        subprocess.run(args, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smoke',action='store_true',help='Verify public access without writing qualification data')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--funding-node', help='Node executable for public funding observation capture')
    mode.add_argument('--exit-books', action='store_true', help='Capture books at exact modeled exit deadlines')
    mode.add_argument('--protection-node', help='Node executable for the public protective quote archive')
    args = parser.parse_args()
    run = Path(__file__).resolve().parents[1]/'runs/trade1'
    if args.funding_node:
        run_node_capture(run, args.funding_node, study='funding', smoke=args.smoke)
    elif args.protection_node:
        run_node_capture(run, args.protection_node, study='protection', smoke=args.smoke)
    elif args.exit_books:
        from .delta_candidate_books import BOOK_DELAY, capture_books, run_books
        if args.smoke:
            deadline = time.time()
            time.sleep(BOOK_DELAY)
            raw = capture_books(deadline)
            print(json.dumps({symbol:row['status'] for symbol,row in raw['coins'].items()}))
            if not any(row['status']=='valid' for row in raw['coins'].values()):
                raise SystemExit(1)
        else:
            run_books(run)
    elif args.smoke:
        slot = int(time.time()//INTERVAL)*INTERVAL
        result = capture(slot)
        print(json.dumps({symbol:dict(candles=len(row.get('candles',[])),ticker='ticker' in row,book='book' in row,
                                     signal=row.get('signal',{}).get('status'), status=row['status'],
                                     reason=row.get('reason')) for symbol,row in result['coins'].items()}))
    else:
        run_capture(run)


if __name__ == '__main__':
    main()
