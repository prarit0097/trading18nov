"""Replay documented signals on public Delta Testnet candles. No exchange orders.

Run from crypto-trader-skills with the reference cache and a later public cache:
    python -m research.delta_strategy_replay reference.json later.json results.json
Caches contain OHLCV arrays keyed by Delta symbol, including a day of warm-up.
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone, timedelta
import hashlib
from itertools import groupby
import json
import math
from pathlib import Path
import statistics

from research.delta_gross_panel import BAR, HOLD, REFERENCES, signals

IST = timezone(timedelta(hours=5, minutes=30))
COINS = ("BTCUSD", "ETHUSD")
UNIVERSE = (*COINS, "SOLUSD", "XRPUSD", "DOGEUSD")
NOTIONAL, EQUITY, FEE, EXECUTION = 1_000, 10_000, .00059, .00030
ROOT = Path(__file__).parent
JESSE = ("Donchian", "MACD_EMA", "RSI2", "SMACrossover")
LATER = ("2026-10-21", "2026-11-04")


def stamp(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=IST).timestamp())


def fetch_later(path):
    from research.delta_october_comparison import fetch_page

    begin, end = stamp(LATER[0]) - 86400, stamp(LATER[1])
    step = 172800
    jobs = [(symbol, start, min(start + step, end))
            for symbol in UNIVERSE for start in range(begin, end, step)]
    candles = {symbol: {} for symbol in UNIVERSE}
    with ThreadPoolExecutor(max_workers=5) as pool:
        for symbol, rows in pool.map(fetch_page, jobs):
            candles[symbol].update((bar["time"], bar) for bar in rows if begin <= bar["time"] < end)
    ordered = {symbol: sorted(rows.values(), key=lambda bar: bar["time"])
               for symbol, rows in candles.items()}
    path.write_text(json.dumps(ordered), encoding="utf8")


def load(path):
    raw = json.loads(path.read_bytes())
    hashes, indexed = {}, {}
    for symbol in UNIVERSE:
        rows = raw[symbol]
        hashes[symbol] = hashlib.sha256(
            json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        indexed[symbol] = {bar["time"]: bar for bar in rows}
        assert len(indexed[symbol]) == len(rows)
        for bar in rows:
            assert bar["time"] % BAR == 0 and bar["volume"] >= 0
            assert 0 < bar["low"] <= min(bar["open"], bar["close"])
            assert max(bar["open"], bar["close"]) <= bar["high"]
    return indexed, hashes


def trading_bar(bar):
    return bar is not None and bar["volume"] > 0


def fill(legs, entry, close, bars):
    gross = fee = execution = 0.0
    for symbol, direction in legs:
        a = bars[symbol][entry]["open"]
        b = bars[symbol][close]["open"]
        size = NOTIONAL / len(legs) / a
        gross += direction * size * (b - a)
        fee += FEE * size * (a + b)
        execution += EXECUTION * size * (a + b)
    return close, gross, gross - fee, gross - fee - execution


def directional(bars, first, end):
    samples, missing = defaultdict(list), Counter()
    for symbol in COINS:
        series = bars[symbol]
        available = Counter()
        for slot in range(first, end - HOLD, BAR):
            prior = [series.get(t) for t in range(slot - 52 * BAR, slot, BAR)]
            if not all(prior) or not trading_bar(series.get(slot)):
                continue
            for name, trigger in signals(prior).items():
                key = ("Directional 13", name, symbol, "10 min")
                samples[key]
                if not trigger or slot < available[name]:
                    continue
                available[name] = slot + HOLD
                if not trading_bar(series.get(slot + HOLD)):
                    missing[key] += 1
                    continue
                direction = -1 if name == "Short Donchian close breakdown 20" else 1
                samples[key].append(fill([(symbol, direction)], slot, slot + HOLD, bars))
    return samples, missing


def relative(bars, first, end):
    source = json.loads((ROOT / "strategy-survey-relative-value.json").read_bytes())
    names = [row[0] for row in source["results"]]
    samples, missing = defaultdict(list), Counter()

    def ratio(t):
        return math.log(bars["ETHUSD"][t]["close"] / bars["BTCUSD"][t]["close"])

    for slot in range(first, end - HOLD, HOLD):
        prior = slot - BAR
        legs_by_rule = []
        try:
            ranks = [(bars[s][prior]["close"] / bars[s][prior - 12 * BAR]["close"], s) for s in UNIVERSE]
        except KeyError:
            continue
        if min(x[0] for x in ranks) < max(x[0] for x in ranks):
            # Choose the alphabetically first symbol at either tied extreme.
            weakest = min(ranks)[1]
            strongest = min(ranks, key=lambda row: (-row[0], row[1]))[1]
            legs_by_rule += [(names[0], [(strongest, 1)]), (names[1], [(weakest, 1)]),
                             (names[2], [(strongest, 1), (weakest, -1)]),
                             (names[3], [(weakest, 1), (strongest, -1)])]
        try:
            history = [ratio(t) for t in range(prior - 24 * BAR, prior, BAR)]
            deviation = statistics.pstdev(history)
            zscore = (ratio(prior) - statistics.fmean(history)) / deviation if deviation else 0
        except KeyError:
            zscore = 0
        if abs(zscore) > 2:
            side = 1 if zscore < 0 else -1
            legs_by_rule += [(names[4], [("ETHUSD", side), ("BTCUSD", -side)]),
                             (names[5], [("ETHUSD", -side), ("BTCUSD", side)])]
        for name, legs in legs_by_rule:
            market = "ETH/BTC" if name.startswith("ETH/BTC") else "Five-coin universe"
            key = ("Relative value 6", name, market, "10 min")
            samples[key]
            if not all(trading_bar(bars[s].get(slot)) for s, _ in legs):
                continue
            if not all(trading_bar(bars[s].get(slot + HOLD)) for s, _ in legs):
                missing[key] += 1
                continue
            samples[key].append(fill(legs, slot, slot + HOLD, bars))
    return samples, missing


def jesse_indicators(series, first, end):
    """Close-based Jesse entry/exit logic, with documented local EMA/Wilder seeding."""
    window = []
    ema = {}
    macd = gain = loss = 0.0
    for slot in range(first - 288 * BAR, end, BAR):
        bar = series.get(slot - BAR)
        if bar is None:
            window.clear()
            ema.clear()
            continue
        close = bar["close"]
        if window:
            delta = close - window[-1]["close"]
            gain = (gain + max(delta, 0)) / 2
            loss = (loss + max(-delta, 0)) / 2
        else:
            gain = loss = 0
        for period in (12, 26, 100):
            prev = ema.get(period, close)
            ema[period] = prev + 2 / (period + 1) * (close - prev)
        difference = ema[12] - ema[26]
        macd = macd + .2 * (difference - macd) if window else difference
        window.append(bar)
        if len(window) < 200 or slot < first:
            continue
        slow = statistics.fmean(r["close"] for r in window[-200:])
        mid = statistics.fmean(r["close"] for r in window[-50:])
        fast = statistics.fmean(r["close"] for r in window[-5:])
        channel = window[-21:-1]
        rsi = 100 * gain / (gain + loss) if gain + loss else 50
        yield slot, {
            "Donchian": (int(close > slow and close > max(b["high"] for b in channel)),
                         close < min(b["low"] for b in channel), False),
            "MACD_EMA": (int(close > ema[100] and difference > macd),
                         close < ema[100] and difference < macd, False),
            "RSI2": (1 if close > slow and rsi <= 10 else -1 if close < slow and rsi >= 90 else 0,
                     close > fast, close < fast),
            "SMACrossover": (1 if mid > slow else -1 if mid < slow else 0,
                             mid < slow, mid > slow),
        }


def source_variants(bars, first, end):
    samples, missing = defaultdict(list), Counter()
    for symbol in COINS:
        series = bars[symbol]
        active, available = {}, Counter()
        for slot, rules in jesse_indicators(series, first, end):
            if not trading_bar(series.get(slot)):
                continue
            for name, (entry, exit_long, exit_short) in rules.items():
                fixed = ("Jesse rule ports", name, symbol, "10 min")
                original = ("Jesse rule ports", name, symbol, "Source signal exit")
                samples[fixed]
                samples[original]
                if entry and slot >= available[name] and slot + HOLD < end:
                    available[name] = slot + HOLD
                    if trading_bar(series.get(slot + HOLD)):
                        samples[fixed].append(fill([(symbol, entry)], slot, slot + HOLD, bars))
                    else:
                        missing[fixed] += 1
                if name in active:
                    start, direction = active[name]
                    if exit_long if direction == 1 else exit_short:
                        samples[original].append(fill([(symbol, direction)], start, slot, bars))
                        del active[name]
                elif entry:
                    active[name] = (slot, entry)
        for name in active:
            missing[("Jesse rule ports", name, symbol, "Source signal exit")] += 1
        key = ("Baseline", "Always long", symbol, "10 min")
        for slot in range(first, end - HOLD, HOLD):
            if trading_bar(series.get(slot)) and trading_bar(series.get(slot + HOLD)):
                samples[key].append(fill([(symbol, 1)], slot, slot + HOLD, bars))
    return samples, missing


def candlesticks(bars, first, end):
    import numpy as np
    import talib

    names = talib.get_function_groups()["Pattern Recognition"]
    samples, missing = defaultdict(list), Counter()
    for symbol in COINS:
        series = bars[symbol]
        # Initialize rows even when the pattern has no executable triggers.
        for name in names:
            samples[("TA-Lib pattern tests", name, symbol, "10 min")]
        for _, group in groupby(enumerate(sorted(series)), key=lambda row: row[1] - row[0] * BAR):
            times = [t for _, t in group]
            ohlc = [np.array([series[t][field] for t in times], dtype=float)
                    for field in ("open", "high", "low", "close")]
            for name in names:
                key = ("TA-Lib pattern tests", name, symbol, "10 min")
                available = 0
                outputs = getattr(talib, name)(*ohlc)
                for idx in np.flatnonzero(outputs):
                    slot = times[idx] + BAR
                    if not first <= slot < end - HOLD or slot < available:
                        continue
                    if not trading_bar(series.get(slot)):
                        continue
                    available = slot + HOLD
                    if not trading_bar(series.get(slot + HOLD)):
                        missing[key] += 1
                        continue
                    direction = 1 if outputs[idx] > 0 else -1
                    samples[key].append(fill([(symbol, direction)], slot, slot + HOLD, bars))
    return samples, missing


def drawdown(points):
    running = peak = EQUITY
    worst_usd = worst_pct = 0
    by_close = defaultdict(float)
    for moment, pnl in points:
        by_close[moment] += pnl
    for moment in sorted(by_close):
        running += by_close[moment]
        peak = max(peak, running)
        worst_usd = max(worst_usd, peak - running)
        worst_pct = max(worst_pct, (peak - running) / peak)
    return worst_usd, worst_pct


def summarize(key, period, sample, missing):
    group, name, market, exit_rule = key
    _, gross, fee_only, net = zip(*sample) if sample else ((), (), (), ())
    gross_dd, gross_dd_pct = drawdown((x[0], x[1]) for x in sample)
    fee_dd, fee_dd_pct = drawdown((x[0], x[2]) for x in sample)
    net_dd, net_dd_pct = drawdown((x[0], x[3]) for x in sample)
    return dict(group=group, name=name, market=market, exit=exit_rule, period=period,
                trades=len(sample), unsettled=missing, gross_wins=sum(x > 1e-9 for x in gross),
                fee_wins=sum(x>0 for x in fee_only), net_wins=sum(x>0 for x in net),
                gross=sum(gross), after_fees=sum(fee_only), net=sum(net),
                fees=sum(gross)-sum(fee_only), execution=sum(fee_only)-sum(net),
                gross_dd=gross_dd, fee_dd=fee_dd, net_dd=net_dd,
                gross_dd_pct=gross_dd_pct, fee_dd_pct=fee_dd_pct, net_dd_pct=net_dd_pct)


def run(reference, later):
    manifest = json.loads(REFERENCES.read_bytes())
    results, evidence = [], {}
    for period, begin, until, path in [
        ("Reference", manifest["from_ist"][:10], manifest["to_ist_exclusive"][:10], reference),
        ("Later", *LATER, later),
    ]:
        candles, hashes = load(path)
        if period == "Reference":
            assert all(hashes[s] == manifest["candle_sha256"][s] for s in UNIVERSE)
        first, end = stamp(begin), stamp(until)
        evidence[period] = dict(start_ist=begin, end_ist_exclusive=until, candle_sha256=hashes,
                                active_bars={s:sum(first <= t < end and trading_bar(b) for t,b in c.items())
                                             for s,c in candles.items()})
        for replay in (directional, relative, source_variants, candlesticks):
            samples, missing = replay(candles, first, end)
            for key in list(samples):
                group, name, symbol, exit_rule = key
                if symbol not in COINS:
                    continue
                combined = (group, name, "BTC + ETH", exit_rule)
                samples[combined].extend(samples[key])
                missing[combined] += missing[key]
            results.extend(summarize(k, period, sample, missing[k]) for k,sample in sorted(samples.items()))
    # Exact regression against all thirteen previously published gross samples.
    with (ROOT / "delta-gross-panel.csv").open(encoding="utf-8", newline="") as f:
        old = {r["rule"]:r for r in csv.DictReader(f)}
    for r in results:
        if r["period"] == "Reference" and r["group"] == "Directional 13" and r["market"] == "BTC + ETH":
            prior = old.pop(r["name"])
            assert r["gross_wins"] == int(prior["gross_wins"]) and r["trades"] == int(prior["settled"])
            assert abs(r["gross"] / r["trades"] * 10 - float(prior["mean_gross_bp"])) < .006
            assert r["unsettled"] == int(prior["unavailable_exits"])
    assert not old
    return dict(results=results, periods=evidence, model=dict(notional=NOTIONAL, equity=EQUITY,
                 fee_per_side=FEE, execution_per_side=EXECUTION))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for k in ("reference", "later", "output"):
        parser.add_argument(k, type=Path)
    parser.add_argument("--fetch-later", action="store_true", help="Download the later public cache if absent")
    args = parser.parse_args()
    if args.fetch_later and not args.later.is_file():
        fetch_later(args.later)
    payload = run(args.reference, args.later)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf8")
    print(f"Wrote {len(payload['results'])} result rows")
