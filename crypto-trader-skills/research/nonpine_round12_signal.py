"""Replay OctoBot's published Signal Trading evaluators on synchronized minute data."""

import argparse
import ast
import hashlib
import json
import math
from collections import Counter, deque
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import numpy as np

from research.nonpine_round9_dip import LOTS, klinger_difference, realtime_note, utc_day
from research.nonpine_round11_daily import (
    ARCHIVE_SHA, PIN, WINDOWS, data_with_opens, fragment, proposal, replay, summarize,
)

MODE = "Trading/Mode/signal_trading_mode/signal_trading.py"
STRATEGY = "Evaluator/Strategies/move_signals_strategy_evaluator/move_signals_strategy.py"
TREND = "Evaluator/Util/trend_analysis/trend_analysis.py"
MOMENTUM = "Evaluator/TA/momentum_evaluator/momentum.py"
INSTANT = "Evaluator/RealTime/instant_fluctuations_evaluator/instant_fluctuations.py"
PROFILE = "profiles/signal_trading/"
PERIODS = (1800, 3600, 14400)
WEIGHTS = (4, 3, 3)
INSTANT_CONFIG = {"price_difference_threshold_percent": 1, "volume_difference_threshold_percent": 400}


def pinned_functions(sources):
    trend = fragment(sources[TREND], "TrendAnalysis")
    targets = {"get_threshold_change_indexes", "peak_has_been_reached_already"}
    trend.body = [node for node in trend.body if getattr(node, "name", None) in targets]
    fractal = fragment(sources[STRATEGY], "_compute_fractal_evaluation", "MoveSignalsStrategyEvaluator")
    namespace = {
        "np": np, "numpy": np, "commons_constants": SimpleNamespace(START_PENDING_EVAL_NOTE=None),
        "MoveSignalsStrategyEvaluator": SimpleNamespace(SIGNAL_MINIMUM_THRESHOLD=0.15),
    }
    module = ast.fix_missing_locations(ast.Module(body=[trend, fractal], type_ignores=[]))
    exec(compile(module, "<pinned OctoBot signal functions>", "exec"), namespace)
    return namespace["TrendAnalysis"], namespace["_compute_fractal_evaluation"]


def framing(rows, trend, evaluate):
    if len(rows) < 35:
        return None
    oscillator = np.array(klinger_difference(rows[-500:]))
    current, sigma = float(oscillator[-1]), float(np.std(oscillator))
    if sigma == 0:
        return 0.0
    last_cross = trend.get_threshold_change_indexes(oscillator, 0)[-1]
    peaked = trend.peak_has_been_reached_already(oscillator[last_cross:])
    factor = (1.0 if abs(current) > sigma else 0.5) if peaked else 0.2
    note = max(-1, min(1, current * factor / sigma))
    closes = [row[2] for row in rows[-20:]]
    center, width = float(np.mean(closes)), 2 * float(np.std(closes))
    portion = (closes[-1] - center) / width if width else 0.0
    weight = math.copysign(min(1, portion * portion), portion) if width else None
    return evaluate(SimpleNamespace(signal=note, weight=weight), 1)


def signals(data, trend, evaluate):
    recent = deque(maxlen=10)
    open_candles, notes, decisions = {}, {}, {}
    histories = {period: [] for period in PERIODS}
    prior_alert = 0.0
    first = utc_day(WINDOWS[0][0])
    for at, _, high, low, price, quantity in data:
        clock = at + 60
        recent.append((price, quantity))
        alert = realtime_note(list(recent), price, quantity, INSTANT_CONFIG)
        sampled = alert is not None and abs(alert - prior_alert) >= 0.15
        if sampled:
            prior_alert = alert
        updated = sampled
        for period, history in histories.items():
            if at % period == 0:
                candle = high, low, price, quantity
            else:
                prior_high, prior_low, _, prior_qty = open_candles[period]
                candle = max(high, prior_high), min(low, prior_low), price, prior_qty + quantity
            open_candles[period] = candle
            if clock % period == 0:
                history.append(candle)
                notes[period] = framing(history, trend, evaluate)
                updated = True
            elif sampled:
                notes[period] = framing([*history, candle], trend, evaluate)
        if updated and clock >= first and all(notes.get(period) is not None for period in PERIODS):
            value = sum(notes[period] * w for period, w in zip(PERIODS, WEIGHTS, strict=True)) / sum(WEIGHTS)
            states = ("very_long", "long", "neutral", "short", "very_short")
            state = states[sum(value >= b for b in (-0.805, -0.325, 0.325, 0.805))]
            decisions[clock] = (price, state, value, "sampled_1m" if sampled else "scheduled")
    return decisions


def run(exchange, archive_path, output):
    with archive_path.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == ARCHIVE_SHA
    material = (MODE, STRATEGY, TREND, MOMENTUM, INSTANT, PROFILE + "profile.json",
                PROFILE + "specific_config/MoveSignalsStrategyEvaluator.json",
                PROFILE + "specific_config/SignalTradingMode.json", PROFILE + "tentacles_config.json")
    with ZipFile(archive_path) as archive:
        sources = {rel: archive.read(f"OctoBot-Tentacles-{PIN}/{rel}") for rel in material}
    profile = json.loads(sources[PROFILE + "profile.json"])["config"]
    assert profile["trader-simulator"]["starting-portfolio"] == {"BTC": 10, "USDT": 1000}
    assert profile["trading"]["risk"] == 0.5
    order_factory = partial(proposal, minimum_buy=0.99, market_floor=0.5)
    trend, fractal = pinned_functions(sources)
    results, histories, proven = [], {}, {}
    for symbol, lot in LOTS.items():
        data, archives = data_with_opens(exchange, symbol)
        mapping = signals(data, trend, fractal)
        projected = {at: item[:3] for at, item in mapping.items()}
        start_base = 10 if symbol == "BTCUSDT" else 0
        histories[symbol] = {"market_archives": archives, "minutes": len(data)}
        for first, last in WINDOWS:
            lo, hi = utc_day(first), utc_day(last)
            ledger = replay(data, projected, lo, hi, lot, start_base=start_base, order_factory=order_factory)
            summary = summarize(ledger, start_base=start_base)
            results.append({
                "id": 6012, "period": f"{first} to {last} UTC",
                "group": "OctoBot Signal Trading · isolated pair variant", "market": symbol,
                "currency": "USDT", "archive_interval": "30m, 1h, 4h and 1m",
                "interval": "30m/1h/4h + sampled 1m", "order_family": "Market, limit, and paired stop",
                "exit": "Source state transitions and Sell OCO", **summary,
            })
            events = [action for at, (_, _, _, action) in mapping.items() if lo <= at < hi]
            proven[f"{symbol}/{first}"] = {
                **ledger, "initial_base": start_base, "pending": vars(ledger["pending"]) if ledger["pending"] else None,
                "decision_counts": dict(Counter(events)),
            }
            print(symbol, first, summary["trades"], summary["net"], flush=True)
    assert any(row["trades"] for row in results)
    output.write_text(json.dumps({
        "coverage": [[6012, "Tested · OctoBot Signal Trading isolated-pair replay",
                      "Published Klinger and Bollinger reversal evaluators, closing 30m/1h/4h candles and sampled 1m alerts executed in separate BTC and ETH spot sleeves."]],
        "results": results, "observations": proven, "source_data": histories,
        "source": f"https://github.com/Drakkar-Software/OctoBot-Tentacles/tree/{PIN}/profiles/signal_trading",
        "source_archive_sha256": ARCHIVE_SHA,
        "source_sha256": {rel: hashlib.sha256(raw).hexdigest() for rel, raw in sources.items()},
        "assumptions": [
            "Original BTC/USDT, ETH/USDT, and ETH/BTC are a shared portfolio. This variant runs BTC and ETH separately, so original cross-pair capital competition is unavailable.",
            "BTC starts with the published 10 BTC and 1,000 USDT. The isolated ETH sleeve starts with 1,000 USDT and no base inventory. Both reset per test window.",
            "TA updates use synchronized candles with a 500-bar cap. Alerts replay completed one-minute samples, including the technical inputs available at the minute close. Intra-minute notification timing is unavailable.",
            "Published fee is 10 bp per side, with an additional 3 bp execution buffer. Passive trade-through, volume limits, OCO stop priority and next-minute execution follow the Round 11 spot replay.",
            "Win rates and drawdowns follow realized FIFO inventory allocations. BTC's initial reserve has basis at first observed open. Remaining inventory is unsettled.",
        ],
    }, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("exchange", "archive", "output"):
        parser.add_argument(argument, type=Path)
    options = parser.parse_args()
    run(options.exchange, options.archive, options.output)
