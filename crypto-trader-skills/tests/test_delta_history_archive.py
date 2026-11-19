from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from crypto_skills.delta_history_archive import (
    HistoryArchive, publish_verified_history, read_reconciliation_history, reconciliation_windows,
    sealed_windows, timestamp_us,
)


def fill(i, at):
    return dict(id=i,product_id=84,created_at=f'1970-01-01T00:00:00.{at:06d}Z')


class HistoryArchiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_publication_checks_full_exchange_read_before_replacing_archive(self):
        tool, args = 'get_fills', {'product_ids': [84]}
        lower, windows = 10, [(10, 20), (20, 30)]
        original = [fill(3, 30), fill(2, 20), fill(1, 15)]
        corrected = [fill(3, 30), fill(4, 20), fill(1, 15)]
        window_rows, full_rows = original, original

        async def call(name, request):
            start, end = request['start_time_us'], request['end_time_us']
            source = full_rows if (start, end) == (10, 30) else window_rows
            return {'result': [row for row in source if
                start < timestamp_us(datetime.fromisoformat(row['created_at'])) <= end]}

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'verified-history.sqlite3'
            async def publish():
                return await publish_verified_history(call, {tool: args}, lower, windows,
                    archive_path=path, environment='india_testnet', account=55)

            self.assertEqual(await publish(), {tool: 3})
            before = path.read_bytes()
            window_rows = corrected
            with self.assertRaisesRegex(ValueError, 'full exchange history'):
                await publish()
            self.assertEqual(path.read_bytes(), before)
            full_rows = corrected
            self.assertEqual(await publish(), {tool: 3})
            with closing(sqlite3.connect(path)) as db:
                archive = HistoryArchive(db, 'india_testnet', 55, read_only=True)
                self.assertEqual(archive.revision_count(tool, args, 10, 20), 2)
                self.assertEqual(archive.revision_count(tool, args, 20, 30), 1)

    def test_windows_keep_unsettled_and_unknown_entries_live_in_ist(self):
        ist = timezone(timedelta(hours=5, minutes=30))
        now = datetime(2026, 11, 19, 0, 1, tzinfo=ist)
        first = dict(order_id='1', opened_at='2026-11-16T23:00:00+05:30')
        pending = dict(order_id='2', opened_at='2026-11-17T19:12:00Z')
        today = dict(order_id='3', opened_at='2026-11-18T18:30:00Z')
        lower = timestamp_us(datetime.fromisoformat(first['opened_at'])) - 1
        settled = dict(first, status='closed', net_pnl='0')
        matching = [dict(settled), dict(pending, status='settlement_pending')]
        previous_cutoff = timestamp_us(now.replace(day=18, minute=0))
        today_cutoff = timestamp_us(now.replace(minute=0))
        for previous in (matching, [settled]):
            self.assertEqual(
                reconciliation_windows(lower, now, [first, pending, today], previous),
                sealed_windows(lower, previous_cutoff),
            )
        self.assertEqual(
            reconciliation_windows(lower, now, [first, today], [settled]),
            sealed_windows(lower, today_cutoff),
        )
        self.assertEqual(reconciliation_windows(lower, now, [first, today], []), [])

    async def test_read_history_rechecks_account_and_keeps_live_tail(self):
        lower, boundary = 10, 20
        arguments = {'get_fills': {'product_ids': [84], 'page_size': 50},
                     'get_wallet_transactions': {'asset_ids': [3], 'page_size': 200}}
        old_wallet = dict(uuid='old', user_id=55, asset_id=3, created_at=fill(1, 20)['created_at'])
        new_wallet = dict(old_wallet, uuid='new', created_at=fill(1, 30)['created_at'])
        all_rows = {'get_fills': [fill(2, 30), fill(1, 20)],
                    'get_wallet_transactions': [new_wallet, old_wallet]}
        calls = []
        account = 55
        probe_failed = False

        async def call(tool, request):
            calls.append((tool, dict(request)))
            if 'start_time_us' not in request:
                if probe_failed:
                    raise RuntimeError('Account probe temporarily unavailable')
                return {'result': [dict(new_wallet, user_id=account)]}
            upper = request.get('end_time_us', 30)
            return {'result': [row for row in all_rows[tool] if
                request['start_time_us'] < timestamp_us(datetime.fromisoformat(row['created_at'])) <= upper]}

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'verified-history.sqlite3'
            with closing(sqlite3.connect(path)) as db:
                writer = HistoryArchive(db, 'india_testnet', account)
                for tool, args in arguments.items():
                    await writer.window(call, tool, args, lower, boundary)
            for current_account, windows, expected_reads in (
                (55, [(lower, boundary)], [None, boundary, boundary]),
                (56, [(lower, boundary)], [None, lower, lower]),
                (55, [], [lower, lower]),
            ):
                account = current_account
                calls.clear()
                result = await read_reconciliation_history(call, arguments, lower,
                    archive_path=path, windows=windows, environment='india_testnet')
                self.assertEqual(result, all_rows)
                self.assertEqual([args.get('start_time_us') for _, args in calls], expected_reads)
            probe_failed = True
            calls.clear()
            self.assertEqual(await read_reconciliation_history(call, arguments, lower,
                archive_path=path, windows=[(lower,boundary)], environment='india_testnet'), all_rows)
            self.assertEqual([args.get('start_time_us') for _, args in calls], [None, lower, lower])
            probe_failed = False
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('DROP TABLE revisions')
            calls.clear()
            self.assertEqual(await read_reconciliation_history(call, arguments, lower,
                archive_path=path, windows=[(lower,boundary)], environment='india_testnet'), all_rows)
            self.assertEqual([args.get('start_time_us') for _, args in calls], [None, lower, lower])

    def test_closed_day_windows_keep_ist_midnight_in_fresh_history(self):
        day = 86_400_000_000
        midnight = 66_600_000_000
        lower = midnight+5
        self.assertEqual(sealed_windows(lower,midnight+3*day),[
            (lower,midnight+day-1), (midnight+day-1,midnight+2*day-1),
            (midnight+2*day-1,midnight+3*day-1),
        ])
        self.assertEqual(sealed_windows(lower,midnight),[])

    async def test_live_tail_reuses_only_a_complete_disjoint_archive_prefix(self):
        with closing(sqlite3.connect(':memory:')) as db:
            cache = HistoryArchive(db,'india_testnet','account-1')
            tool, args = 'get_fills', {'product_ids':[84]}
            fetched=[]
            async def call(name,request):
                fetched.append(dict(request))
                lower=request['start_time_us']
                upper=request.get('end_time_us',40)
                return {'result':[fill(at,at) for at in (40,30,20,15) if lower<at<=upper]}
            await cache.window(call,tool,args,10,20)
            rows, used = await cache.read_live(call,tool,args,10,[(10,20)])
            self.assertEqual([row['id'] for row in rows],[40,30,20,15])
            self.assertTrue(used)
            self.assertEqual(fetched[-1]['start_time_us'],20)
            rows, used = await cache.read_live(call,tool,args,10,[(10,20),(20,29)])
            self.assertFalse(used)
            self.assertEqual(fetched[-1]['start_time_us'],10)
            self.assertEqual(len(rows),4)
            with self.assertRaisesRegex(ValueError,'contiguous'):
                await cache.read_live(call,tool,args,10,[(10,20),(21,29)])

            async def corrected(name,request):
                fetched.append(dict(request))
                rows = [fill(40,40),fill(20,21)]
                return {'result':rows if request['start_time_us']==10 else rows[-1:]}
            rows, used = await cache.read_live(corrected,tool,args,10,[(10,20)])
            self.assertFalse(used)
            self.assertEqual(fetched[-1]['start_time_us'],10)
            self.assertEqual([row['id'] for row in rows],[40,20])

    async def test_persisted_window_reuses_exhausted_pages_and_preserves_revisions(self):
        with closing(sqlite3.connect(':memory:')) as db:
            archive = HistoryArchive(db, 'india_testnet', 'account-1')
            arguments = {'product_ids':[84], 'page_size':1}
            requests = []
            async def first(tool,args):
                requests.append((tool,args))
                if 'after' not in args:
                    return dict(result=[fill(2,20)],meta={'after':'page-two'})
                return dict(result=[fill(1,11)],meta={})
            rows = await archive.window(first,'get_fills',arguments,10,20)
            self.assertEqual(rows,[fill(2,20),fill(1,11)])
            self.assertEqual([args.get('after') for _,args in requests],[None,'page-two'])
            self.assertTrue(all((args['start_time_us'],args['end_time_us'])==(10,20) for _,args in requests))
            restarted = HistoryArchive(db,'india_testnet','account-1')
            self.assertEqual(await restarted.window(first,'get_fills',arguments,10,20),rows)
            self.assertEqual(len(requests),2)

            async def late(tool,args):
                return dict(result=[fill(3,16)],meta={})
            self.assertEqual(await restarted.window(late,'get_fills',arguments,10,20,refresh=True),[fill(3,16)])
            self.assertEqual(await restarted.window(first,'get_fills',arguments,10,20,refresh=True),rows)
            self.assertEqual(restarted.revision_count('get_fills',arguments,10,20),3)
            with self.assertRaisesRegex(ValueError,'account'):
                HistoryArchive(db,'india_testnet','another-account')
            with db:
                db.execute("UPDATE revisions SET digest='invalid' WHERE id=(SELECT MAX(id) FROM revisions)")
            with self.assertRaisesRegex(ValueError,'digest mismatch'):
                await restarted.window(first,'get_fills',arguments,10,20)

    async def test_partial_pages_or_wrong_account_do_not_commit(self):
        with closing(sqlite3.connect(':memory:')) as db:
            archive = HistoryArchive(db,'india_testnet','55')
            async def repeated(tool,args):
                return dict(result=[fill(1,20)],meta={'after':'repeated'})
            with self.assertRaisesRegex(RuntimeError,'Repeated pagination cursor'):
                await archive.window(repeated,'get_fills',{},10,20)
            self.assertEqual(archive.revision_count('get_fills',{},10,20),0)

            async def unexpected_wallet(tool,args):
                return dict(result=[dict(uuid='row-a',user_id=56,created_at=fill(1,15)['created_at'])])
            with self.assertRaisesRegex(ValueError,'wallet account'):
                await archive.window(unexpected_wallet,'get_wallet_transactions',{},10,20)
            self.assertEqual(archive.revision_count('get_wallet_transactions',{},10,20),0)

            async def boundary(tool,args):
                return dict(result=[fill(1,10)])
            with self.assertRaisesRegex(ValueError,'outside'):
                await archive.window(boundary,'get_fills',{},10,20)
            self.assertEqual(archive.revision_count('get_fills',{},10,20),0)
