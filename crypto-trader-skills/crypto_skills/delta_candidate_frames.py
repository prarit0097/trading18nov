"""Join captured entry and deadline books with mark and funding evidence."""
import json
from math import isfinite
from decimal import Decimal

from .delta_candidate_books import load_books
from .delta_candidate_capture import MAX_QUOTE_AGE
from .delta_candidate_exit import HOLD_SECONDS
from .delta_plan import CRYPTO_DEMO_SYMBOLS

DAY_SECONDS = 86_400


def exit_quote(close_snapshot, symbol, deadline):
    coin = close_snapshot.get('coins', {}).get(symbol, {})
    if coin.get('status') != 'valid':
        return []
    try:
        observed = float(coin['book_observed_at'])
        book = coin['book']
        exchange = int(book['last_updated_at'])/1e6
        age = observed-exchange
        if (not isfinite(observed) or not -2 <= age <= MAX_QUOTE_AGE
                or not deadline <= exchange or not deadline <= observed < deadline+MAX_QUOTE_AGE
                or observed > float(close_snapshot['captured_at'])
                or book['symbol'] != symbol or not book['buy']):
            return []
        quote = dict(time=observed,bids=book['buy'])
        if book.get('sell'):
            quote['best_ask'] = str(min(Decimal(str(level['price'])) for level in book['sell']))
        return [quote]
    except (ArithmeticError, KeyError, TypeError, ValueError):
        return []


def index_marks(marks):
    by_symbol = {}
    for symbol in CRYPTO_DEMO_SYMBOLS:
        source = marks.get(symbol, [])
        by_symbol[symbol] = {row['time']:row for row in source}
        if len(by_symbol[symbol]) != len(source):
            raise ValueError('Duplicate reference minute for '+symbol)
    return by_symbol


def assemble_frames(connection, start, end, marks, funding, *, schedule=None, protection=None):
    """Return captured opportunities only. Missing books and funding stay missing."""
    return _assemble(connection,start,end,end,index_marks(marks),funding,schedule,protection)


def _assemble(connection, start, end, context_end, by_symbol, funding, schedule, protection):
    snapshots = {slot:json.loads(payload) for slot,payload in connection.execute(
        'SELECT slot,payload FROM observations WHERE slot>=? AND slot<? ORDER BY slot',(start,context_end))}
    deadline_books = load_books(connection,start,end)
    frames = {}
    for slot, snapshot in snapshots.items():
        if slot >= end:
            break
        exit_snapshot = snapshots.get(slot+HOLD_SECONDS, {})
        dedicated = deadline_books.get(slot, {})
        opened = snapshot.get('captured_at')
        deadline = opened+HOLD_SECONDS if type(opened) in (int, float) else None
        exits = {}
        for symbol in CRYPTO_DEMO_SYMBOLS:
            quotes = []
            if deadline is not None:
                quotes = exit_quote(exit_snapshot,symbol,deadline)
                if dedicated.get('deadline_at') == deadline:
                    quotes += exit_quote(dedicated,symbol,deadline)
                quotes = sorted(quotes,key=lambda quote:quote['time'])[:1]
            limit = int(quotes[0]['time']) if quotes else slot+HOLD_SECONDS+MAX_QUOTE_AGE
            candles = by_symbol[symbol]
            mark_path = [candles[t] for t in range(slot,limit//60*60+1,60) if t in candles]
            amount = funding.get(slot,{}).get(symbol)
            source = 'supplied_cashflow' if amount is not None else None
            if (amount is None and schedule is not None and quotes
                    and schedule.proves_zero(symbol, snapshot.get('captured_at'), quotes[0]['time'])):
                amount, source = '0', 'observed_schedule_no_event'
            exits[symbol] = dict(mark_bars=mark_path,exit_quotes=quotes,
                                 funding_per_contract=amount,funding_source=source)
            if protection is not None and schedule is not None:
                exits[symbol].update(protection=protection,schedule=schedule)
        frames[slot] = dict(snapshot=snapshot,exits=exits)
    return frames


class ReplayFrames:
    """Serve one day's decision frames and their cross-midnight exit context."""

    def __init__(self, connection, start, end, marks, funding, *, schedule=None, protection=None):
        self.connection = connection
        self.start, self.end = start, end
        self.marks = index_marks(marks)
        self.funding, self.schedule, self.protection = funding, schedule, protection
        self.loaded_start = None
        self.frames = {}

    def get(self, slot, default=None):
        if not self.start <= slot < self.end:
            return default
        day = self.start + (slot-self.start)//DAY_SECONDS*DAY_SECONDS
        if day != self.loaded_start:
            stop = min(day+DAY_SECONDS,self.end)
            context = min(stop+HOLD_SECONDS,self.end)
            self.frames.clear()
            self.loaded_start = None
            self.frames = _assemble(self.connection,day,stop,context,self.marks,self.funding,
                                    self.schedule,self.protection)
            self.loaded_start = day
        return self.frames.get(slot,default)
