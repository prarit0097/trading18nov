"""Reproduce gross 10-minute close-to-close-signal research on Delta testnet bars.

Usage from crypto-trader-skills:
    python research/delta_gross_panel.py CANDLES.json OUTPUT.csv

The same public cache can be downloaded with research.delta_october_comparison.
We validate it against the two published SHA-256 values before computing.
Each trigger uses only 52 consecutive, completed 5-minute bars. A model trade
requires positive volume on the next entry bar, takes that bar's opening
price, and exits at the opening price two bars later. Signals before that
exit are ignored within the same rule and coin. Exits without traded-volume
evidence are omitted and counted. Results pool BTCUSD and ETHUSD over the
archived IST window, with no portfolio sizing, fees, funding or slippage.
Mean return is arithmetic, in basis points. Flat returns stay in the denominator.
"""
import argparse
import csv
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

BAR = 300
HOLD = 600
REFERENCES = Path(__file__).with_name("delta-october-comparison.json")


def stochastic(high, low, close):
    span = max(high) - min(low)
    return (close - min(low)) / span if span else 0.5


def cutler(closes):
    moves = [b - a for a, b in zip(closes, closes[1:])]
    magnitude = sum(abs(move) for move in moves)
    return 100 * sum(max(move, 0) for move in moves) / magnitude if magnitude else 50


def signals(history):
    prior, last = history[-2:]
    closes = [bar["close"] for bar in history]
    highs = [bar["high"] for bar in history]
    lows = [bar["low"] for bar in history]
    mean = statistics.fmean
    average = mean(closes[-20:])
    deviation = statistics.pstdev(closes[-20:])
    previous_upper = mean(closes[-21:-1]) + 2 * statistics.pstdev(closes[-21:-1])
    close = last["close"]
    high20 = max(highs[-21:-1])
    low20 = min(lows[-21:-1])
    return {
        "Long Donchian close breakout 20": close > high20,
        "Short Donchian close breakdown 20": close < low20,
        "SMA20 crosses above SMA50": average > mean(closes[-50:])
            and mean(closes[-21:-1]) <= mean(closes[-51:-1]),
        "Close crosses above SMA20": close > average and prior["close"] <= mean(closes[-21:-1]),
        "Bollinger dip buy lower band 20 2": close < average - 2 * deviation,
        "Bollinger upside cross 20 2": close > average + 2 * deviation and prior["close"] <= previous_upper,
        "Cutler RSI14 crosses above 30": cutler(closes[-15:]) > 30 and cutler(closes[-16:-1]) <= 30,
        "Fast stochastic K14 crosses above 20": stochastic(highs[-14:], lows[-14:], close) > 0.2
            and stochastic(highs[-15:-1], lows[-15:-1], prior["close"]) <= 0.2,
        "Bullish engulfing real bodies": prior["close"] < prior["open"] and close > last["open"]
            and last["open"] <= prior["close"] and close >= prior["open"],
        "Inside-bar upside breakout": highs[-2] < highs[-3] and lows[-2] > lows[-3] and close > highs[-3],
        "Failed breakdown reclaim 20": last["low"] < low20 and close > low20,
        "Volume-confirmed Donchian 20": close > high20
            and last["volume"] > 1.5 * mean(bar["volume"] for bar in history[-21:-1]),
        "12-bar momentum crosses above zero": close > closes[-13] and closes[-2] <= closes[-14],
    }


def run(cache, output):
    manifest = json.loads(REFERENCES.read_bytes())
    raw = json.loads(cache.read_bytes())
    first = int(datetime.fromisoformat(manifest["from_ist"]).timestamp())
    end = int(datetime.fromisoformat(manifest["to_ist_exclusive"]).timestamp())
    returns = defaultdict(list)
    missing_exit = Counter()
    for symbol in ("BTCUSD", "ETHUSD"):
        rows = raw[symbol]
        encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
        if hashlib.sha256(encoded).hexdigest() != manifest["candle_sha256"][symbol]:
            raise ValueError(f"Candle digest mismatch for {symbol}")
        bars = {row["time"]: row for row in rows}
        assert len(rows) == len(bars)
        next_entry = Counter()
        for slot in range(first, end - HOLD, BAR):
            history = [bars.get(t) for t in range(slot - 52 * BAR, slot, BAR)]
            entry = bars.get(slot)
            if any(bar is None for bar in history) or not entry or not entry["volume"]:
                continue
            for name, triggered in signals(history).items():
                if not triggered or slot < next_entry[name]:
                    continue
                next_entry[name] = slot + HOLD
                settlement = bars.get(slot + HOLD)
                if not settlement or not settlement["volume"]:
                    missing_exit[name] += 1
                    continue
                direction = -1 if name == "Short Donchian close breakdown 20" else 1
                gross_return = direction * (settlement["open"] / entry["open"] - 1)
                returns[name].append(gross_return)
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["rule", "gross_wins", "settled", "gross_win_rate_pct", "mean_gross_bp", "unavailable_exits"])
        for name, values in sorted(returns.items()):
            wins = sum(value > 0 for value in values)
            writer.writerow([name, wins, len(values), f"{100 * wins / len(values):.1f}",
                             f"{10000 * statistics.fmean(values):.2f}", missing_exit[name]])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.cache, args.output)
