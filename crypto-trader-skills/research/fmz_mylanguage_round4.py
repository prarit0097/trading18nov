"""Replay archived MyLanguage signals under a documented Binance linear model."""

import argparse
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.delta_strategy_replay import EQUITY, EXECUTION, FEE, NOTIONAL, stamp, summarize
from research.fmz_mylanguage_round3 import DOC, bars, ema, inputs, source_items
from research.fmz_native_round3 import WINDOWS

INTERVALS = {262: 1440, 485: 15, 1008: 60, 1009: 60, 1010: 60, 1011: 60,
             1340: 30, 1353: 60, 2089: 15, 2499: 60, 4392: 60, 5695: 60}
NOTES = {
    262: "One position per side through reversal. The archived directive omits a volume and filter.",
    485: "Apply AUTOFILTER and a fixed 1,000 USDT stake in place of inverse equity sizing.",
    1008: "Preserve archived N=120 over the current public default. Replace inverse equity sizing.",
    1009: "Keep the lagged exit predicate state and archived S1. Replace inverse equity sizing.",
    1010: "Set the DATE boundary to UTC. Replace inverse equity sizing.",
    1011: "Treat each source position as one lot, and evaluate the source's same-bar orders in sequence.",
    1340: "Separate long and short slots, with a fixed stake in place of inverse XBTUSD perpetual sizing.",
    1353: "Treat NEW_ORDER as the next traded-minute open for entry and use that as the recorded stop basis.",
    2089: "Keep independent long and short positions and replace original inverse lot sizing.",
    2499: "Apply the China rebar formula to Binance perpetuals. No original rebar result is implied.",
    4392: "Preserve the source's 2:1 short to long sizing ratio at fixed quote stakes.",
    5695: "Retain archived N=100 and use public NC and SLOSS. Replace account-based sizing.",
}
ARCHIVED = {1008: {"N": 120, "percent": 5}, 1009: {"percent": 5},
            1010: {"percent": 5}, 1011: {"percent": 5}, 5695: {"N": 100, "MINAMOUNT": 10}}


def cross_up(left, right):
    prior = right.shift() if isinstance(right, pd.Series) else right
    return (left > right) & (left.shift() <= prior)


def cross_down(left, right):
    prior = right.shift() if isinstance(right, pd.Series) else right
    return (left < right) & (left.shift() >= prior)


def rsi(prices, n):
    changes = prices.diff()
    up = changes.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    absolute = changes.abs().ewm(alpha=1 / n, adjust=False).mean()
    return 100 * up / absolute


def mean(series, n):
    return series.rolling(n).mean()


def high(series, n):
    return series.rolling(n, min_periods=1).max()


def low(series, n):
    return series.rolling(n, min_periods=1).min()


def true_range(h, l, c):
    return pd.concat([h - l, (c.shift() - h).abs(), (c.shift() - l).abs()], axis=1).max(axis=1, skipna=False)


def features(id_, frame, args):
    f = frame.copy()
    o, h, l, c, v = (f[key] for key in ("open", "high", "low", "close", "volume"))
    f["long"] = f["short"] = f["close_long"] = f["close_short"] = False
    if id_ == 262:
        n = args["N"]
        range_ = np.maximum(high(h.shift(), n) - low(c.shift(), n), high(c.shift(), n) - low(l.shift(), n))
        f["long"], f["short"] = c > o + args["KS"] * range_, c < o - args["KX"] * range_
    elif id_ == 485:
        ma, rs = mean(c, args["Y"]), rsi(c, 2)
        f["short"], f["close_short"] = (c > ma) & (rs > 90), (c > ma) & (rs < 10)
        f["long"], f["close_long"] = (c < ma) & (rs < 10), (c < ma) & (rs > 90)
    elif id_ == 1008:
        n = args["N"]
        idx = pd.Series(np.arange(len(f)), index=f.index)
        hh = n - (idx - idx.where(high(h, n) > high(h.shift(), n)).ffill() + 1).fillna(n).clip(upper=n)
        ll = n - (idx - idx.where(low(l, n) < low(l.shift(), n)).ffill() + 1).fillna(n).clip(upper=n)
        up, down = hh * 100 / n, ll * 100 / n
        avg = ema(c.shift(), n)
        f["long"] = (cross_up(up, 70) | cross_down(down, 30)) & (up > down) & (c > avg)
        f["short"] = (cross_up(down, 70) | cross_down(up, 30)) & (up < down) & (c < avg)
        f["close_long"] = (up > down) & cross_down(up, 50)
        f["close_short"] = (up < down) & cross_down(down, 50)
    elif id_ == 1009:
        n = args["S1"]
        prior = c.shift()
        a, b = ema(prior, 10 * n), ema(ema(prior, 10 * n), n)
        d = np.maximum(h.diff().abs(), l.diff().abs())
        change = (d.where(h + l > h.shift() + l.shift(), 0) - d.where(h + l < h.shift() + l.shift(), 0)) / (d.where(h + l != h.shift() + l.shift(), 0) + 2 * n)
        avg = mean(change, n)
        twice = ema(avg, n)
        ready = pd.Series(np.arange(len(f)) + 1 > 10 * n, index=f.index)
        f["long"] = (ready & (prior > a) & (a > b) & (change > 0) & (avg > twice)).shift(fill_value=False)
        f["short"] = (ready & (prior < a) & (a < b) & (change < 0) & (avg < twice)).shift(fill_value=False)
        f["close_long"], f["close_short"] = prior < a, prior > a
        f["prior_close"] = prior
    elif id_ == 1010:
        n = args["LENGTH1"]
        a, b = ema(c.shift(), n), ema(c.shift(), n * 10)
        atr = mean(true_range(h, l, c), n)
        dayopen = o.groupby(o.index.normalize()).transform("first")
        prior = c.shift()
        f["long"] = (prior >= (dayopen + 3 * atr).shift()) & (v > 0) & (a > b) & (prior >= h.shift(n))
        f["short"] = (prior <= (dayopen - 3 * atr).shift()) & (v > 0) & (a < b) & (prior <= l.shift(n))
        f["close_long"], f["close_short"] = prior <= l.shift(10 * n), prior >= h.shift(10 * n)
        f["prior_close"] = prior
    elif id_ == 1011:
        n = args["LENTH"]
        avg = (h + l + 2 * c) / 4
        f["long"], f["short"] = (h >= high(2 * avg - l, n).shift()) & (v > 0), (l <= low(2 * avg - h, n).shift()) & (v > 0)
        f["distance"] = 50 * mean(true_range(h, l, c), n)
    elif id_ == 1340:
        n = args["N"]
        bottom, top = low(l, 9), high(h, 9)
        k = (100 * (c - bottom) / (top - bottom)).ewm(alpha=1 / 3, adjust=False).mean()
        d = k.ewm(alpha=1 / 3, adjust=False).mean()
        ma = ema(c, n)
        f["long"], f["short"] = (c > ma) & (k < d), (c < ma) & (k > d)
        f["close_long"], f["close_short"] = c < ma, c > ma
    elif id_ == 1353:
        macd = ema(c, 12) - ema(c, 26)
        diff = macd - ema(macd, 9)
        a, b = mean(c, 50), mean(c, 120)
        f["long"] = (macd > 0) & (a > b) & (diff > 0) & (c > a) & (c.shift() > a.shift())
        f["short"] = (macd < 0) & (a < b) & (diff < 0) & (c < a) & (c.shift() < a.shift())
        f["close_long"] = (macd.shift() < 0) | (a.shift() < b.shift())
        f["close_short"] = (macd.shift() > 0) | (a.shift() > b.shift())
    elif id_ == 2089:
        a, b, rs = ema(c, args["N1"]), ema(c, args["N2"]), rsi(c, 9)
        f["long"] = (a > b) & (c > np.maximum(a, b)) & cross_up(rs, 70)
        f["short"] = (a < b) & (c < np.minimum(a, b)) & cross_down(rs, 30)
        f["close_long"], f["close_short"] = a < b, a > b
    elif id_ == 2499:
        n = args["N"]
        vol_range = ((h - l) * v).rolling(n).sum()
        vol_body = ((c - o).abs() * v).rolling(n).sum()
        ma = mean(c, n)
        buy = ((c - l) * v).rolling(n).sum() / vol_range > .5
        buy &= (((c - o).clip(lower=0) * v).rolling(n).sum() / vol_body > .5) & (c > ma)
        sell = ((h - c) * v).rolling(n).sum() / vol_range > .5
        sell &= (((o - c).clip(lower=0) * v).rolling(n).sum() / vol_body > .5) & (c < ma)
        f["long"], f["short"] = buy & (h >= high(h, n)), sell & (l <= low(l, n))
        f["close_long"], f["close_short"] = c < ma, c > ma
        f["distance"] = args["M"] * mean(h - l, n)
    elif id_ == 4392:
        n = args["len"]
        avg = mean((high(h, n) + low(l, n)) / 2, 5)
        weights = np.arange(n) - (n - 1) / 2
        slope = avg.rolling(n).apply(lambda x: np.dot(x, weights) / np.dot(weights, weights), raw=True)
        f["long"], f["short"] = slope > slope.shift(), slope < slope.shift()
    elif id_ == 5695:
        n = args["N"]
        rank = ema(v * (c - c.shift(args["NC"])), n)
        f["long"], f["short"] = (rank > 0) & (h >= high(h, n)), (rank < 0) & (l <= low(l, n))
        f["close_long"], f["close_short"] = rank < 0, rank > 0
    else:
        raise ValueError(id_)
    return f


def exits(id_, bar, side, current, args, delayed):
    signal, highest, lowest, entry_signal_bar = current
    trigger = bar.close_long if side == 1 else bar.close_short
    if id_ in (1340, 2089, 5695):
        distance = args["SLOSS"] * .01 * signal
        delta = side * (bar.close - signal)
        inclusive = id_ != 2089
        return (delta <= -distance if inclusive else delta < -distance) or (
            trigger and (id_ == 5695 or (delta >= distance if inclusive else delta > distance))
        )
    if id_ == 1353:
        return trigger or (bar.low <= signal * .95 if side == 1 else bar.high >= signal * 1.05)
    if id_ == 1009:
        return delayed[side]
    if id_ == 1010:
        return trigger and side * (bar.prior_close - signal) >= 0
    if id_ == 1011:
        return bar.Index > entry_signal_bar and (bar.high >= signal + bar.distance if side == 1 else bar.low <= signal - bar.distance)
    if id_ == 2499:
        extreme = highest if side == 1 else lowest
        return side * (bar.close - signal) < -bar.distance or (trigger and side * (extreme - signal) > bar.distance)
    return trigger


def simulate(id_, candles, prices, funding, first, end, args):
    ledger = []
    active = {}
    delayed = {1: False, -1: False}
    step = INTERVALS[id_] * 60
    eligible = candles.loc[pd.Timestamp(first, unit="s", tz="UTC"):pd.Timestamp(end - step - 1, unit="s", tz="UTC")]
    execution = prices.loc[pd.Timestamp(first, unit="s", tz="UTC"):pd.Timestamp(end - 60, unit="s", tz="UTC")]
    times = execution.index.as_unit("s").asi8
    minute = dict(zip(times, zip(execution.open, execution.volume)))
    summary = []

    def close(side, t, quote):
        entry, basis, qty, _ = active.pop(side)
        gross = side * qty * (quote - basis)
        turnover = qty * (quote + basis)
        carry = sum(-side * qty * mark * rate for at, mark, rate in funding if entry < at <= t)
        fee, execution_cost = turnover * FEE, turnover * EXECUTION
        summary.append((t, gross, gross - fee, gross - fee - execution_cost + carry, carry))
        ledger.append([side, entry, t, basis, quote, qty, fee, execution_cost, carry])

    for bar in eligible.itertuples():
        t = int(bar.Index.timestamp()) + step
        quote, volume = minute[t]
        assert volume > 0 and quote > 0
        order = (-1, 1) if id_ == 5695 else (1, -1)
        reverse = id_ not in (485, 1340, 1353, 2089)
        filter_signal = id_ in (485, 1353, 4392, 5695)
        opened = False
        for side in order:
            if (bar.long if side == 1 else bar.short) and side not in active and (reverse or not filter_signal or not active):
                if reverse and -side in active:
                    close(-side, t, quote)
                signal = quote if id_ == 1353 else bar.close
                stake = NOTIONAL * (2 if id_ == 4392 and side == -1 else 1)
                active[side] = (t, quote, stake / quote, (signal, -np.inf, np.inf, bar.Index))
                opened = True
                if filter_signal:
                    break
        for side, (entry, basis, qty, state) in list(active.items()):
            signal, highest, lowest, entry_bar = state
            if entry < t:
                state = (signal, max(highest, bar.high), min(lowest, bar.low), entry_bar)
                active[side] = (entry, basis, qty, state)
                if not (filter_signal and opened) and exits(id_, bar, side, state, args, delayed):
                    close(side, t, quote)
            if id_ == 1009:
                crossed = bar.close_long if side == 1 else bar.close_short
                delayed[side] = crossed and side * (bar.prior_close - signal) > .01 * signal
    return summary, ledger, len(active)


def run(scratch, output):
    items = source_items(scratch / "fmz.zip")
    current = {r["id"] for r in read(Path(__file__).with_name("remaining-backtest-round3-coverage.json"))["disposition"]
               if r["status"] == "FMZ native offline replay pending"}
    assert INTERVALS.keys() <= items.keys() & current
    directory = scratch / "nonpine" / "binance"
    manifest = read(directory / "manifest.json")
    markets = {coin: inputs(directory, coin + "USDT", manifest) for coin in ("BTC", "ETH")}
    cache = {(coin, period): bars(raw, period) for coin, (raw, _, _) in markets.items() for period in set(INTERVALS.values())}
    prior = read(scratch / "round3-native" / "round3-parameter-checks.json")
    additional = read(scratch / "round4" / "native-params" / "receipt.json")
    parameters = {r["id"]: r for r in prior + additional}
    results, coverage, evidence, specs = [], [], [], []
    for id_, interval in INTERVALS.items():
        item = items[id_]
        param = parameters.get(id_, {})
        args = {**param.get("args", {}), **ARCHIVED.get(id_, {})}
        specs.append({"id": id_, "parameter_evidence": param, "args": args, "interval_minutes": interval,
                      "source": item["source"], "document_sha256": item["document_sha256"],
                      "formula_sha256": hashlib.sha256(item["code"].encode()).hexdigest()})
        has_close = False
        for start, (end, label) in WINDOWS.items():
            windows = {}
            for coin, (raw, rates, _) in markets.items():
                f = features(id_, cache[coin, interval], args)
                events, ledger, opened = simulate(id_, f, raw, rates, stamp(start), stamp(end), args)
                assert len(events) == len(ledger) and all(l[1] <= l[2] for l in ledger)
                windows[coin] = events, opened
                evidence.append({"id": id_, "coin": coin, "start": start, "closed_lots": ledger, "open_count": opened})
            btc, ob = windows["BTC"]
            eth, oe = windows["ETH"]
            has_close |= bool(btc or eth)
            for scope, trades, opened in (("BTCUSDT", btc, ob), ("ETHUSDT", eth, oe), ("BTCUSDT + ETHUSDT", btc + eth, ob + oe)):
                row = summarize(("FMZ MyLanguage · Confirmed-bar linear variant", item["name"],
                                 scope + " perp", "Archived signals, fixed quote stake"), label, [x[:4] for x in trades], opened)
                row.update(id=id_, source=item["source"], source_sha256=item["document_sha256"],
                           interval=f"{interval}m", starting_equity=EQUITY, adaptation=NOTES[id_],
                           market_data="Binance USD-M candles and funding", quote_currency="USDT",
                           funding=sum(x[4] for x in trades))
                row["execution"] += row["funding"]
                results.append(row)
        status = "Tested · FMZ MyLanguage linear variant" + ("" if has_close else ", no closes")
        coverage.append([id_, status, NOTES[id_]])
    write(output, {"baseline": "fd4ad038", "source_revision": FMZ_REF, "language_reference": DOC,
                   "markets": {coin: value[2] for coin, value in markets.items()}, "specs": specs,
                   "lot_fields": ["side", "entry", "exit", "entry_price", "exit_price", "size", "fees", "execution", "funding"],
                   "coverage": coverage, "closed_lots": evidence, "results": results})
    print(len(coverage), "variants,", len(results), "result rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scratch", type=Path)
    parser.add_argument("output", type=Path)
    options = parser.parse_args()
    run(options.scratch, options.output)
