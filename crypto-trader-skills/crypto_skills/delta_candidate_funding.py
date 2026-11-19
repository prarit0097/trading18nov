"""Derive modeled zero funding only from a continuous observed schedule."""
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from itertools import pairwise
import json
from math import isfinite
from typing import NamedTuple

from .delta_plan import CRYPTO_DEMO_SYMBOLS

MAX_GAP_MS = 120_000


class Observation(NamedTuple):
    receipt_ms: int
    exchange_us: int
    next_us: int
    interval: int
    stream: str


class FundingSchedule:
    def __init__(self, rows):
        self.symbols = defaultdict(list)
        for row in rows:
            symbol = row['symbol']
            stamp = Observation(*(row[key] for key in ('received_utc_ms', 'observed_exchange_us',
                                'next_realization_us', 'interval_seconds', 'stream_id')))
            receipt, exchange, upcoming, interval, stream = stamp
            rate = row.get('observed_rate')
            if (symbol not in CRYPTO_DEMO_SYMBOLS or any(type(v) is not int for v in stamp[:4])
                    or not isinstance(stream, str) or not stream or interval <= 0
                    or not -2_000_000 <= receipt*1000-exchange <= 15_000_000
                    or not max(receipt*1000, exchange) < upcoming <= exchange+interval*1_000_000
                    or type(rate) not in (int, float) or not isfinite(rate)):
                raise ValueError('Invalid public funding observation')
            self.symbols[symbol].append(stamp)
        for observations in self.symbols.values():
            observations.sort()

    def proves_zero(self, symbol, opened_at, closed_at):
        observations = self.symbols.get(symbol)
        if (not observations or type(opened_at) not in (int, float) or type(closed_at) not in (int, float)
                or not isfinite(opened_at) or not isfinite(closed_at) or not 0 <= opened_at < closed_at):
            return False
        opened_ms, closed_ms = opened_at*1000, closed_at*1000
        receipt = lambda observation: observation.receipt_ms
        before = bisect_right(observations, opened_ms, key=receipt)-1
        after = bisect_left(observations, closed_ms, key=receipt)
        while before >= 0 and observations[before].exchange_us > opened_ms*1000:
            before -= 1
        while after < len(observations) and observations[after].exchange_us < closed_ms*1000:
            after += 1
        if before < 0 or after == len(observations):
            return False
        reference = observations[before]
        previous_settlement = reference.next_us-reference.interval*1_000_000
        if not previous_settlement < opened_ms*1000 < closed_ms*1000 < reference.next_us:
            return False
        covering = observations[before:after+1]
        return (all(sample[2:]==reference[2:] for sample in covering)
                and all(0 <= new.receipt_ms-old.receipt_ms <= MAX_GAP_MS
                        and 0 <= new.exchange_us-old.exchange_us <= MAX_GAP_MS*1000
                        for old, new in pairwise(covering)))


def load_schedule(run, identity, start, end):
    """Read only observed receipt times from the requested frozen replay window."""
    def sample_rows():
        day = datetime.fromtimestamp(start, timezone.utc).date()
        last = datetime.fromtimestamp(end-1, timezone.utc).date()
        while day <= last:
            path = run/f'four-ready-funding-{day.isoformat()}.jsonl'
            if path.exists():
                with path.open(encoding='utf-8') as stream:
                    for line in stream:
                        row = json.loads(line)
                        if any(row.get(key) != value for key, value in identity.items()):
                            raise ValueError('Funding observation does not match the frozen candidate')
                        if (start*1000 <= row['received_utc_ms'] < end*1000
                                and start*1_000_000 <= row['observed_exchange_us'] < end*1_000_000):
                            yield row
            day += timedelta(days=1)

    return FundingSchedule(sample_rows())
