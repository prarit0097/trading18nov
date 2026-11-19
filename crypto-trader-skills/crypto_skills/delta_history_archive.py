"""Read complete Delta history pages and preserve exact scoped window revisions."""
from contextlib import ExitStack, closing
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import zlib

STREAM_IDS = {'get_fills':'id', 'get_wallet_transactions':'uuid'}
EPOCH = datetime(1970,1,1,tzinfo=timezone.utc)
DAY_US = 86_400_000_000
IST_MIDNIGHT_US = 66_600_000_000
IST = timezone(timedelta(hours=5, minutes=30))


def timestamp_us(when):
    return (when-EPOCH)//timedelta(microseconds=1)


def sealed_windows(lower, fresh_from):
    """Split old history by IST dates, keeping the fresh midnight live."""
    if type(lower) is not int or lower<0 or type(fresh_from) is not int or (
            fresh_from-IST_MIDNIGHT_US)%DAY_US:
        raise ValueError('Fresh history must start at an IST midnight')
    first = lower+1
    midnight = (first-IST_MIDNIGHT_US)//DAY_US*DAY_US+IST_MIDNIGHT_US
    windows = []
    for end in range(midnight+DAY_US,fresh_from+1,DAY_US):
        windows.append((lower,end-1))
        lower = end-1
    return windows


def reconciliation_windows(lower, now, registered, previous_rows):
    """Keep today and each unresolved trade's entire IST day live."""
    previous = {row['order_id']: row for row in previous_rows}
    freshest_required_day = now.astimezone(IST).date()
    for entry in registered:
        old = previous.get(entry['order_id'], {})
        if (old.get('status') == 'closed' and old.get('net_pnl') is not None
                and old.get('opened_at') == entry['opened_at']):
            continue
        opened = datetime.fromisoformat(entry['opened_at'])
        freshest_required_day = min(freshest_required_day, opened.astimezone(IST).date())
    midnight = datetime.combine(freshest_required_day, datetime.min.time(), tzinfo=IST)
    return sealed_windows(lower, timestamp_us(midnight))


async def complete_pages(call, name, args):
    rows, seen, cursor = [], set(), None
    for _ in range(2000):
        request = dict(args, after=cursor) if cursor else dict(args)
        response = await call(name,request)
        page = response['result']
        if not isinstance(page,list):
            raise ValueError('Invalid Delta history page')
        rows.extend(page)
        cursor = (response.get('meta') or {}).get('after')
        if cursor is None or cursor=='':
            return rows
        if not isinstance(cursor,str):
            raise ValueError('Invalid Delta history cursor')
        if cursor in seen:
            raise RuntimeError('Repeated pagination cursor')
        seen.add(cursor)
    raise RuntimeError('Pagination incomplete')


async def history_account(call):
    response = await call('get_wallet_transactions', {'asset_ids': [3], 'page_size': 1})
    rows = response.get('result')
    if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict):
        return rows[0].get('user_id')
    return None


async def read_reconciliation_history(call, arguments, lower, *, archive_path=None,
                                      windows=(), environment):
    """Use a matching read-only archive when available, with a fresh exchange tail."""
    path = Path(archive_path).resolve() if archive_path is not None else None
    if windows and path is not None and path.is_file() and environment == 'india_testnet':
        try:
            account = await history_account(call)
        except RuntimeError:
            account = None
        if account is not None:
            with ExitStack() as resources:
                try:
                    connection = resources.enter_context(closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)))
                    archive = HistoryArchive(connection, environment, account, read_only=True)
                except (sqlite3.Error, ValueError):
                    archive = None
                if archive is not None:
                    return {tool: (await archive.read_live(call, tool, args, lower, windows))[0]
                            for tool, args in arguments.items()}
    return {tool: await complete_pages(call, tool, dict(args, start_time_us=lower))
            for tool, args in arguments.items()}


async def publish_verified_history(call, arguments, lower, windows, *, archive_path, environment, account):
    """Build complete window revisions and replace the archive after an independent full read."""
    if not windows:
        return {}
    boundary = lower
    for left, right in windows:
        if left != boundary or right <= left:
            raise ValueError('Archived history requires a contiguous prefix')
        boundary = right
    path = Path(archive_path).resolve()
    counts = {}
    with TemporaryDirectory(dir=path.parent) as directory:
        staged = Path(directory)/path.name
        with closing(sqlite3.connect(staged)) as database:
            if path.exists():
                with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)) as prior:
                    HistoryArchive(prior, environment, account, read_only=True)
                    prior.backup(database)
            archive = HistoryArchive(database, environment, account)
            for tool, args in arguments.items():
                archived = []
                for left, right in windows:
                    archived.extend(await archive.window(call, tool, args, left, right, refresh=True))
                full = await complete_pages(call, tool, dict(args, start_time_us=lower, end_time_us=boundary))
                archive._validate(archived, tool, args, lower, boundary)
                archive._validate(full, tool, args, lower, boundary)
                key = STREAM_IDS[tool]
                if {str(row[key]): row for row in archived} != {str(row[key]): row for row in full}:
                    raise ValueError(f'{tool} archive does not match full exchange history')
                counts[tool] = len(full)
        os.replace(staged, path)
    return counts


class HistoryArchive:
    def __init__(self, connection, environment, account, *, read_only=False):
        self.db, self.account = connection, str(account)
        if environment != 'india_testnet' or type(account) not in (int,str) or not self.account.strip():
            raise ValueError('An authenticated testnet account is required')
        binding = sha256(f'{environment}:{self.account}'.encode()).hexdigest()
        if read_only:
            stored = self.db.execute('SELECT account FROM binding WHERE id=1').fetchone()
            if stored != (binding,):
                raise ValueError('History archive belongs to another account')
            return
        with self.db:
            self.db.execute('CREATE TABLE IF NOT EXISTS binding (id INTEGER PRIMARY KEY CHECK(id=1), account TEXT NOT NULL)')
            self.db.execute('INSERT OR IGNORE INTO binding VALUES (1,?)',(binding,))
            if self.db.execute('SELECT account FROM binding WHERE id=1').fetchone()[0] != binding:
                raise ValueError('History archive belongs to another account')
            self.db.execute('''CREATE TABLE IF NOT EXISTS revisions (
                id INTEGER PRIMARY KEY, scope TEXT NOT NULL, lower_us INTEGER NOT NULL,
                upper_us INTEGER NOT NULL, digest TEXT NOT NULL, payload BLOB NOT NULL,
                observed_at TEXT NOT NULL)''')
            self.db.execute('CREATE INDEX IF NOT EXISTS by_window ON revisions(scope,lower_us,upper_us,id)')

    @staticmethod
    def _key(tool, args, lower, upper):
        if (tool not in STREAM_IDS or {'after','before','start_time_us','end_time_us'}.intersection(args)
                or type(lower) is not int or type(upper) is not int or not 0<=lower<upper):
            raise ValueError('Invalid archive scope or time bounds')
        return json.dumps([tool,args],sort_keys=True,allow_nan=False),lower,upper

    def _latest(self, key):
        return self.db.execute('''SELECT digest,payload FROM revisions
            WHERE scope=? AND lower_us=? AND upper_us=? ORDER BY id DESC LIMIT 1''',key).fetchone()

    def _cached(self, key):
        cached = self._latest(key)
        if cached is None:
            return None
        digest,payload = cached
        raw = zlib.decompress(payload)
        if sha256(raw).hexdigest() != digest:
            raise ValueError('History archive payload digest mismatch')
        return json.loads(raw)

    def revision_count(self, tool, args, lower, upper):
        return self.db.execute('''SELECT COUNT(*) FROM revisions
            WHERE scope=? AND lower_us=? AND upper_us=?''',self._key(tool,args,lower,upper)).fetchone()[0]

    def _validate(self, rows, tool, args, lower, upper):
        seen = set()
        for row in rows:
            identifier = row.get(STREAM_IDS[tool])
            if type(identifier) not in (str,int) or not identifier or str(identifier) in seen:
                raise ValueError('Missing or duplicate history row identifier')
            seen.add(str(identifier))
            stamp = timestamp_us(datetime.fromisoformat(row['created_at']))
            if not lower < stamp <= upper:
                raise ValueError('Exchange row is outside the requested history window')
            if tool=='get_wallet_transactions' and str(row.get('user_id')) != self.account:
                raise ValueError('Unexpected wallet account in archived evidence')
            for requested,actual in (('product_ids','product_id'),('asset_ids','asset_id')):
                if args.get(requested) and row.get(actual) not in args[requested]:
                    raise ValueError('Exchange row is outside the requested history filters')

    async def window(self, call, tool, args, lower, upper, *, refresh=False):
        key = self._key(tool,args,lower,upper)
        if not refresh:
            cached = self._cached(key)
            if cached is not None:
                return cached

        rows = await complete_pages(call,tool,dict(args,start_time_us=lower,end_time_us=upper))
        self._validate(rows,tool,args,lower,upper)
        raw = json.dumps(rows,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        digest = sha256(raw).hexdigest()
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            latest = self._latest(key)
            if latest is None or latest[0] != digest:
                self.db.execute('''INSERT INTO revisions(scope,lower_us,upper_us,digest,payload,observed_at)
                    VALUES (?,?,?,?,?,?)''',(*key,digest,zlib.compress(raw),datetime.now(timezone.utc).isoformat()))
        return rows

    async def read_live(self, call, tool, args, lower, windows, *, upper=None):
        """Use a fully evidenced archived prefix plus fresh tail or read all live."""
        async def fetch(start):
            query = dict(args,start_time_us=start)
            if upper is not None:
                query['end_time_us'] = upper
            return await complete_pages(call,tool,query)

        boundary, keys = lower, []
        for left,right in windows:
            if left != boundary:
                raise ValueError('Archived history requires a contiguous prefix')
            keys.append(self._key(tool,args,left,right))
            boundary = right
        if upper is not None and boundary >= upper:
            raise ValueError('Fresh cutoff must follow the archive prefix')
        if not keys:
            return await fetch(lower), False
        try:
            chunks = [self._cached(key) for key in keys]
        except (sqlite3.Error,ValueError,zlib.error):
            return await fetch(lower), False
        if any(chunk is None for chunk in chunks):
            return await fetch(lower), False
        fresh = await fetch(boundary)
        combined = fresh + [row for chunk in reversed(chunks) for row in chunk]
        # A corrected posting can reappear in the fresh tail with its original ID.
        try:
            self._validate(combined,tool,args,lower,upper if upper is not None else 2**63-1)
        except ValueError:
            return await fetch(lower), False
        return combined, True
