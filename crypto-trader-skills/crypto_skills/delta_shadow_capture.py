"""Capture public depth for an owned Delta demo batch's hypothetical exits."""
import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import time

from .core import Workspace
from .delta_candidate_books import BOOK_DELAY, project_book
from .delta_candidate_capture import MAX_QUOTE_AGE, public_result
from .delta_ledger import atomic_json
from .delta_plan import CRYPTO_DEMO_SYMBOLS, MIN_BATCH_COINS, TRADE1_CONTRACTS, eligible_completed_trade
from .delta_shadow import CAPS, estimate, minute, seconds


def select_batch(ledger, batch_id):
    if (ledger.get('environment') != 'india_testnet' or ledger.get('campaign_id') != 'trade1'
            or re.fullmatch(r'demo-[0-9]+', batch_id) is None):
        raise ValueError('Expected an owned Trade 1 India testnet batch')
    rows = [row for row in ledger['trades'] if row.get('batch_id') == batch_id]
    if (not 1 <= len(rows) <= MIN_BATCH_COINS
            or len({row['order_id'] for row in rows}) != len(rows)
            or len({row['symbol'] for row in rows}) != len(rows)
            or any(row.get('campaign_id') != 'trade1' or row['symbol'] not in CRYPTO_DEMO_SYMBOLS
                   or row.get('filled_contracts') != TRADE1_CONTRACTS
                   or not row.get('first_fill_at') for row in rows)):
        raise ValueError('Missing owned three-contract fill evidence for the batch')
    for row in rows:
        seconds(row['first_fill_at'])
    return rows


def capture_row(row, minutes, *, fetch=public_result, clock=time.time, sleep=time.sleep):
    if minutes not in CAPS:
        raise ValueError('Expected a 15- or 30-minute research horizon')
    deadline = seconds(row['first_fill_at']) + minutes * 60
    while clock() < deadline + BOOK_DELAY:
        sleep(min(30, max(0, deadline + BOOK_DELAY - clock())))
    snapshot = dict(status='unavailable', reason='Book capture window has already passed')
    for attempt in range(3):
        if clock() >= deadline + MAX_QUOTE_AGE:
            break
        snapshot = project_book(row['symbol'], deadline, fetch, clock)
        if snapshot['status'] == 'valid' or attempt == 2:
            break
        sleep(.5)
    return dict(symbol=row['symbol'], order_id=row['order_id'], first_fill_at=row['first_fill_at'],
                deadline_at=deadline, capture=snapshot)


def capture_batch(run, batch_id, minutes):
    ledger = json.loads((run / 'ledger.json').read_text(encoding='utf-8'))
    rows = select_batch(ledger, batch_id)
    if minutes not in CAPS:
        raise ValueError('Expected a 15- or 30-minute research horizon')
    stem = f'shadow-books-{batch_id}-{minutes}'
    path = run / f'{stem}.json'
    with Workspace(run).lock(stem):
        if path.exists():
            raise FileExistsError(f'{path.name} already contains the deadline evidence')
        with ThreadPoolExecutor(max_workers=len(rows)) as pool:
            comparisons = list(pool.map(lambda row: capture_row(row, minutes), rows))
        artifact = dict(status='depth_research_only', environment='india_testnet',
                        campaign_id='trade1', batch_id=batch_id, minutes=minutes, comparisons=comparisons)
        atomic_json(path, artifact)
    return path, artifact


async def evaluate_capture(rows, artifact, now, *, fetch=public_result):
    minutes = artifact['minutes']
    if (artifact['status'], artifact['environment'], artifact['campaign_id']) != (
            'depth_research_only', 'india_testnet', 'trade1') or minutes not in CAPS:
        raise ValueError('Expected a Trade 1 depth research artifact')
    observations = artifact['comparisons']
    by_id = {str(row['order_id']): row for row in rows}
    if len(observations) != len(by_id) or {str(x['order_id']) for x in observations} != set(by_id):
        raise ValueError('Book capture does not match the owned batch')
    for item in observations:
        row = by_id[str(item['order_id'])]
        end = seconds(row['first_fill_at']) + minutes * 60
        if (row['batch_id'] != artifact['batch_id'] or not eligible_completed_trade(row)
                or (item['symbol'], item['first_fill_at'], item['deadline_at']) != (
                    row['symbol'], row['first_fill_at'], end) or now < minute(end) + 60):
            raise ValueError('Need matching settled trade and a completed reference minute')

    output = []
    for item in observations:
        row = by_id[str(item['order_id'])]
        closed, end = seconds(row['closed_at']), item['deadline_at']
        baseline = fallback = dict(status='unavailable', reason='Actual close timing prevents paired replay')
        if row['exit_reason'] in ('stop_loss', 'take_profit') and closed <= end:
            baseline = fallback = dict(status='actual_early_exit', net_pnl=row['net_pnl'])
        elif row['exit_reason'] == 'ten_minute' and closed < end:
            cache = {}

            async def read_history(_, args):
                key = tuple(sorted(args.items()))
                if key not in cache:
                    cache[key] = dict(result=await asyncio.to_thread(fetch, '/history/candles', **args))
                return cache[key]

            baseline = await estimate(read_history, row, closed, end)
            fallback = await estimate(read_history, row, closed, end, deadline_book=item['capture'])
        output.append(dict(item, candle_baseline=baseline, depth_fallback=fallback,
                           realized_net_usd=row['net_pnl']))
    return output


def evaluate_batch(run, batch_id, minutes):
    ledger = json.loads((run / 'ledger.json').read_text(encoding='utf-8'))
    rows = select_batch(ledger, batch_id)
    stem = f'shadow-books-{batch_id}-{minutes}'
    path = run / f'{stem}.json'
    with Workspace(run).lock(stem):
        artifact = json.loads(path.read_text(encoding='utf-8'))
        if (artifact['batch_id'], artifact['minutes']) != (batch_id, minutes):
            raise ValueError('Mismatched research batch or horizon')
        artifact['comparisons'] = asyncio.run(asyncio.wait_for(evaluate_capture(rows, artifact, time.time()), 45))
        atomic_json(path, artifact)
    return path, artifact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, default=Path('runs/trade1'))
    parser.add_argument('--batch-id', required=True)
    parser.add_argument('--minutes', type=int, choices=CAPS, required=True)
    parser.add_argument('--evaluate', action='store_true', help='Evaluate an existing capture against settled fills')
    args = parser.parse_args()
    operation = evaluate_batch if args.evaluate else capture_batch
    path, artifact = operation(args.run, args.batch_id, args.minutes)
    print(json.dumps(dict(path=str(path), valid=sum(row['capture']['status'] == 'valid'
                                                   for row in artifact['comparisons']),
                          captured=len(artifact['comparisons']))))


if __name__ == '__main__':
    main()
