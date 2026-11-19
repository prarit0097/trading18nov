"""Read archived mark and depth evidence for a modeled protective exit."""
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import gzip
from itertools import pairwise
import json

US = 1_000_000
SEGMENT_MS = 300_000


class ProtectiveArchive:
    def __init__(self, root, identity, *, cutoff):
        self.root = root
        self.identity = identity
        self.cutoff_ms = cutoff*1000
        self.files = {}

    def _rows(self, symbol, minute):
        first = (minute-2)*1000
        last = min((minute+63)*1000,self.cutoff_ms)
        day = datetime.fromtimestamp(first/1000,timezone.utc).date()
        final_day = datetime.fromtimestamp((last-1)/1000,timezone.utc).date()
        while day <= final_day:
            if day not in self.files:
                self.files[day] = tuple((int(path.name.split('-',1)[0]),path)
                                        for path in (self.root/day.isoformat()).glob('*.jsonl.gz'))
            for start,path in self.files[day]:
                if start >= last or (start//SEGMENT_MS+1)*SEGMENT_MS <= first:
                    continue
                with gzip.open(path,'rt',encoding='utf-8') as stream:
                    header = json.loads(next(stream))
                    if (header['schema'] != 1 or header['identity'] != self.identity
                            or header['first_receipt_ms'] != start or not header['stream_id']):
                        raise ValueError('Protective archive does not match frozen evidence')
                    index = header['symbols'].index(symbol)
                    for line in stream:
                        row = json.loads(line)
                        if (row[0] in ('candle','book') and row[1] == index
                                and first <= row[3] < last and row[2] < self.cutoff_ms*1000
                                and -2000 <= row[3]-row[2]/1000 <= 3000):
                            yield row,header['stream_id']
            day += timedelta(days=1)

    def prove(self, symbol, touch, opened, deadline, stop, target):
        """Require a bracketed first crossing and continuous displayed depth."""
        kind = touch['trigger_type']
        if kind not in ('stop_loss','take_profit'):
            return None
        try:
            minute = touch['trigger_minute']
            rows = sorted(self._rows(symbol,minute),key=lambda item:(item[0][2],item[0][3]))
            candles = [(row,stream) for row,stream in rows if row[0]=='candle' and row[4]==minute*US]
            for (left,stream),(right,other) in pairwise(candles):
                low_left, high_left, low_right, high_right = map(Decimal,(str(left[7]),str(left[6]),
                                                                        str(right[7]),str(right[6])))
                if not stop < low_left <= high_left < target:
                    return None
                crossed = low_right <= stop and high_right < target if kind=='stop_loss' else (
                    low_right > stop and high_right >= target)
                if not crossed:
                    continue
                if (stream != other or not opened*US <= left[2] < right[2] < deadline*US
                        or not 0 < right[2]-left[2] <= 3*US or right[3] < left[3]
                        or low_right > low_left or high_right < high_left):
                    return None
                return self._bracket_books(rows,stream,left[2],right,opened,deadline)
        except (ArithmeticError, IndexError, KeyError, OSError, StopIteration, TypeError, ValueError):
            return None
        return None

    @staticmethod
    def _bracket_books(rows, stream, earliest, crossing, opened, deadline):
        books = [row for row,key in rows if row[0]=='book' and key==stream]
        stamps = [row[2] for row in books]
        anchor = bisect_right(stamps,earliest)-1
        final = bisect_left(stamps,crossing[2]+US//2)
        if anchor < 0 or final >= len(books) or not opened*US <= stamps[anchor] or (
                earliest-stamps[anchor] > US or stamps[final] >= deadline*US
                or stamps[final]-crossing[2] > 1_500_000 or books[final][3] < crossing[3]):
            return None
        series = books[anchor:final+1]
        if any(not 0 < new[2]-old[2] <= US or new[3]<old[3] for old,new in pairwise(series)):
            return None
        return dict(trigger_window_us=[earliest,crossing[2]],
                    quotes=[dict(time=book[2]/US,best_ask=book[6][0],
                                 bids=[dict(price=price,size=size) for price,size in book[5]])
                            for book in series])
