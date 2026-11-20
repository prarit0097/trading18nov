"""Check the archived daily ratings against independent 4h indicator calculations."""

import math


def minus(left, right):
    return [None if a is None or b is None else a - b for a, b in zip(left, right, strict=True)]


def fraction(n, d, scale=1):
    return None if n is None or d in (None, 0) else scale * n / d


def lag(series, length=1):
    return [None] * length + series[:-length]


def moving(series, n, mean=None, mode="sma"):
    items, values = [], []
    previous = None
    alpha = 2 / (n + 1) if mode == "ema" else 1 / n
    for value in series:
        if value is not None:
            items.append(value)
            if len(items) >= n:
                window = items[-n:]
                if mean is not None:
                    previous = mean(window)
                elif mode == "sma" or previous is None:
                    previous = math.fsum(window) / n
                else:
                    previous = alpha * value + (1 - alpha) * previous
        values.append(previous)
    return values


def aligned(fn, *vectors):
    return [None if None in args else fn(*args) for args in zip(*vectors, strict=True)]


def select_daily(samples):
    return samples[5::6]


def stoch(src, high, low, n):
    hi = moving(high, n, max)
    lo = moving(low, n, min)
    return aligned(lambda s, h, l: fraction(s - l, h - l, 100), src, hi, lo)


def rsi(close, n):
    dr = minus(close, lag(close))
    gain = moving([None if v is None else max(v, 0) for v in dr], n, mode="rma")
    loss = moving([None if v is None else -min(v, 0) for v in dr], n, mode="rma")
    return aligned(lambda u, d: 100 if d == 0 else 0 if u == 0 else 100 - 100 / (1 + u / d), gain, loss)


def oscillators(base):
    close, high, low = ([b[name] for b in base] for name in ("close", "high", "low"))
    hl2 = [(a + b) / 2 for a, b in zip(high, low, strict=True)]
    rs = rsi(close, 14)
    s = moving(stoch(close, high, low, 14), 3)
    signal = moving(s, 3)
    sr = moving(stoch(rs, rs, rs, 14), 3)
    signal_r = moving(sr, 3)
    ccima = moving(close, 20)
    def dev(window):
        avg = math.fsum(window) / len(window)
        return math.fsum(abs(x - avg) for x in window) / len(window)
    abs_dev = moving(close, 20, dev)
    cci = aligned(lambda p, sma, d: fraction(p - sma, 0.015 * d), close, ccima, abs_dev)
    ao = minus(moving(hl2, 5), moving(hl2, 34))
    momentum = minus(close, lag(close, 10))
    macd = minus(moving(close, 12, mode="ema"), moving(close, 27, mode="ema"))
    peak, trough = moving(high, 14, max), moving(low, 14, min)
    wr = aligned(lambda p, h, l: fraction(p - h, h - l, 100), close, peak, trough)
    prev_close = lag(close)
    buying_pressure = aligned(lambda c, lo, p: c - min(lo, p), close, low, prev_close)
    true_range = aligned(lambda h, lo, p: max(h, p) - min(lo, p), high, low, prev_close)
    ult = []
    for n in (7, 14, 28):
        b = moving(buying_pressure, n, math.fsum)
        t = moving(true_range, n, math.fsum)
        ult.append(aligned(fraction, b, t))
    ultimate = aligned(lambda a, b, c: 100 * (4 * a + 2 * b + c) / 7, *ult)
    up, down = minus(high, lag(high)), minus(lag(low), low)
    plus, minus_dm = [[x if x is not None and y is not None and x > y and x > 0 else 0 for x, y in zip(a, b, strict=True)] for a, b in ((up, down), (down, up))]
    average_range = moving(true_range, 14, mode="rma")
    dp = aligned(lambda value, t: fraction(value, t, 100), moving(plus, 14, mode="rma"), average_range)
    dm = aligned(lambda value, t: fraction(value, t, 100), moving(minus_dm, 14, mode="rma"), average_range)
    ci = aligned(lambda p, m: abs(p - m) / (p + m or 1), dp, dm)
    adx = moving(ci, 14, mode="rma")
    ema_bbp = moving(close, 13, mode="ema")
    return tuple(map(select_daily, (rs, s, signal, sr, signal_r, cci, ao, momentum, macd, wr, ultimate, adx, dp, dm, minus(high, ema_bbp), minus(low, ema_bbp))))


def indicator_votes(chart, base):
    price = [b["close"] for b in chart]
    src = [b["close"] for b in base]
    sma_values = {n: select_daily(moving(src, n)) for n in (9, 10, 20, 30, 50, 100, 200)}
    rs, sk, sd, rsk, rsd, cci, ao, mom, macd, wr, uo, adx, plus, minus_dm, bulls, bears = oscillators(base)
    all_votes = []
    for i, close in enumerate(price):
        moving_votes = [-1 if (v := sma_values[n][i]) is not None and v > close else 1 for n in (10, 20, 30, 50, 100, 200) * 2 + (9, 20)]
        osc = []
        for line, bull, bear in (
            (rs, lambda a, b: a < 30 and a > b, lambda a, b: a > 70 and a < b),
            ((sk, sd), lambda a, b: a < 20 and b != 0 and a / b > 1, lambda a, b: a > 80 and b != 0 and a / b < 1),
            (cci, lambda a, b: a < -100 and a < b, lambda a, b: a > 100 and a > b),
            (ao, lambda a, b: a > 0 and a > b, lambda a, b: a < 0 and a < b),
            (mom, lambda a, _: a > 0, lambda a, _: a <= 0),
            (macd, lambda a, _: a > 0, lambda a, _: a <= 0),
            ((rsk, rsd), lambda a, b: a < 20 and b != 0 and a / b > 1, lambda a, b: a > 80 and b != 0 and a / b < 1),
            (wr, lambda a, b: a < -80 and a > b, lambda a, b: a > -20 and a < b),
            (uo, lambda a, _: a >= 70, lambda a, _: a <= 30),
        ):
            if isinstance(line, tuple):
                va, vb = (x[i] for x in line)
            elif line is mom or line is macd or line is uo:
                va, vb = line[i], 0
            else:
                va, vb = line[i], line[i - 1] if i else None
            osc.append(0 if None in (va, vb) else int(bull(va, vb)) - int(bear(va, vb)))
        dependent = None not in (adx[i], plus[i], minus_dm[i]) and adx[i] * 100 >= 20 and minus_dm[i] != 0
        osc.append(int(plus[i] > minus_dm[i]) - int(plus[i] < minus_dm[i]) if dependent else 0)
        positive = i and None not in (bears[i], bears[i - 1]) and bears[i] < 0 and bears[i] > bears[i - 1]
        negative = i and None not in (bulls[i], bulls[i - 1]) and bulls[i] > 0 and bulls[i] < bulls[i - 1]
        osc.append(-1 if negative else 1 if positive else 0)
        all_votes.append((moving_votes, osc))
    return all_votes
