"""Fetch closed mark-price minutes for the read-only Delta candidate replay."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import time

from .delta_candidate_capture import public_result
from .delta_plan import CRYPTO_DEMO_SYMBOLS

MINUTE_SECONDS = 60
PAGE_SECONDS = 86_400


def mark_page(symbol, start, end, fetch):
    rows = fetch('/history/candles', symbol='MARK:'+symbol, resolution='1m', start=start, end=end-1)
    candles = {}
    for row in rows:
        at = row['time']
        if type(at) is not int or not start <= at < end or at % MINUTE_SECONDS or at in candles:
            raise ValueError('Invalid or duplicate mark candle timestamp')
        prices = {key:row[key] for key in ('open','high','low','close')}
        op, hi, lo, cl = (Decimal(str(value)) for value in prices.values())
        if not all(value.is_finite() for value in (op, hi, lo, cl)) or not 0 < lo <= min(op,cl) <= max(op,cl) <= hi:
            raise ValueError('Invalid mark candle prices')
        candles[at] = dict(time=at, **prices)
    return [candles[at] for at in sorted(candles)]


def fetch_mark_history(start, end, *, fetch=public_result, clock=time.time):
    """Fetch a bounded interval of closed minutes and disclose gaps per symbol."""
    if (type(start) is not int or type(end) is not int or start % MINUTE_SECONDS or end % MINUTE_SECONDS
            or not 0 <= start < end <= int(clock())//MINUTE_SECONDS*MINUTE_SECONDS):
        raise ValueError('Mark history requires a window of closed one-minute bars')
    expected = (end-start)//MINUTE_SECONDS

    def read_symbol(symbol):
        rows, failures = [], []
        for left in range(start,end,PAGE_SECONDS):
            right = min(left+PAGE_SECONDS,end)
            try:
                rows.extend(mark_page(symbol,left,right,fetch))
            except (ArithmeticError, KeyError, TypeError, ValueError, OSError, RuntimeError) as exc:
                failures.append(dict(start=left,end=right,reason=str(exc)))
        return rows, dict(expected_minutes=expected, observed_minutes=len(rows),
                          missing_minutes=expected-len(rows), failed_pages=failures)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = dict(zip(CRYPTO_DEMO_SYMBOLS,pool.map(read_symbol,CRYPTO_DEMO_SYMBOLS)))
    return ({symbol:result[0] for symbol,result in results.items()},
            {symbol:result[1] for symbol,result in results.items()})
