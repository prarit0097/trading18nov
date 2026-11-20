"""Replay the pinned OctoBot DailyTrading profile using closed Binance spot bars."""

import argparse
import ast
import asyncio
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from io import TextIOWrapper
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import numpy as np

from research.nonpine_round4_metrics import metrics
from research.nonpine_round9_dip import BUFFER, FEE, LOTS, MONTHS, read_minute, rsis, utc_day
from research.nonpine_round7_ladders import floor_lot

PIN = "f0ebe0c14db0928e50c2e39ea68e2ff9f427f765"
ARCHIVE_SHA = "5341dd9c9c014d4385173545080f6c54c24183ca8a9f7f04d9d299ecaa98172f"
PROFILE = "profiles/daily_trading/"
REQUIRED = {
    "trend": "Evaluator/Util/trend_analysis/trend_analysis.py",
    "ema": "Evaluator/TA/trend_evaluator/trend.py",
    "rsi": "Evaluator/TA/momentum_evaluator/momentum.py",
    "signal": "Evaluator/Strategies/mixed_strategies_evaluator/mixed_strategies.py",
    "orders": "Trading/Mode/daily_trading_mode/daily_trading.py",
    "profile": PROFILE + "profile.json",
    "settings": PROFILE + "specific_config/DailyTradingMode.json",
    "strategy": PROFILE + "specific_config/SimpleStrategyEvaluator.json",
    "activation": PROFILE + "tentacles_config.json",
}
DEPENDENCIES = {
    "data_util.py": "a184cc9ce351ff4cc388df8da2ea0ca10524837c88b48eadf05c08fb341feced",
    "abstract_evaluator.py": "b042d7aa7e1aebac3f56c4fd3a218787ccc1869f48ad4a200508d6d83f6591f8",
}
TIME_FRAMES = (3600, 14400, 86400)
WINDOWS = (("2026-09-23", "2026-10-21"), ("2026-10-21", "2026-11-05"))
START_BASE, START_CASH = 10.0, 1000.0


def fragment(source, name, cls=None):
    root = ast.parse(source)
    if cls:
        root = next(node for node in root.body if isinstance(node, ast.ClassDef) and node.name == cls)
    result = next(node for node in root.body if getattr(node, "name", None) == name)
    result.decorator_list = []
    return result


def sma(values, period):
    if len(values) < period:
        return np.array([])
    return np.convolve(values, np.ones(period) / period, mode="valid")


def indicator_runtime(material):
    trend = fragment(material["trend"], "TrendAnalysis")
    supported = {"get_trend", "get_threshold_change_indexes",
                 "get_estimation_of_move_state_relatively_to_previous_moves_length"}
    trend.body = [node for node in trend.body if getattr(node, "name", None) in supported]
    parts = [
        trend,
        fragment(material["data_util.py"], "normalize_data"),
        fragment(material["data_util.py"], "drop_nan"),
        fragment(material["ema"], "get_moving_average_analysis", "DoubleMovingAverageTrendEvaluator"),
        fragment(material["rsi"], "evaluate", "RSIMomentumEvaluator"),
        fragment(material["abstract_evaluator.py"], "set_eval_note", "AbstractEvaluator"),
    ]
    def rsi(values, period):
        return np.array(rsis(values, period))

    common = SimpleNamespace(START_PENDING_EVAL_NOTE=None, INIT_EVAL_NOTE=0.0)
    namespace = {
        "math": math, "np": np, "numpy": np, "common_constants": common,
        "commons_constants": common, "tulipy": SimpleNamespace(sma=sma, rsi=rsi),
        "evaluators_util": SimpleNamespace(get_eval_time=lambda **fields: 0),
    }
    tree = ast.fix_missing_locations(ast.Module(body=parts, type_ignores=[]))
    exec(compile(tree, "<pinned OctoBot indicators>", "exec"), namespace)
    namespace["EvaluatorUtil"] = SimpleNamespace(TrendAnalysis=namespace["TrendAnalysis"])
    namespace["data_util"] = SimpleNamespace(**{key: namespace[key] for key in ("normalize_data", "drop_nan")})
    return namespace


async def evaluate(bars, symbol, runtime):
    class Rsi:
        eval_note = None
        is_trend_change_identifier = True
        period_length = 14
        short_term_averages = [7, 5, 4, 3, 2, 1]
        long_term_averages = [40, 30, 20, 15, 10]
        set_eval_note = runtime["set_eval_note"]

        def eval_note_changed(self):
            pass

        async def evaluation_completed(self, *args, **kwargs):
            pass

    rows = {period: [] for period in TIME_FRAMES}
    evaluators = {period: Rsi() for period in TIME_FRAMES}
    latest, signals = {}, {}
    for at, _, _, _, close, _ in bars:
        clock = at + 60
        if clock % 3600:
            continue
        for period, series in rows.items():
            if clock % period:
                continue
            series.append(close)
            if len(series) < 15:
                continue
            values = np.array(series[-500:])
            average = sma(values, 2)
            rule = runtime["get_moving_average_analysis"]
            ma_note = (rule(values, average, 5) + rule(values, average, 10)) / 2
            rsi_evaluator = evaluators[period]
            await runtime["evaluate"](rsi_evaluator, symbol, symbol, period, values, clock)
            latest[period] = (ma_note or None, rsi_evaluator.eval_note)
        if len(latest) == len(TIME_FRAMES):
            notes = [note for pair in latest.values() for note in pair if note is not None]
            if notes:
                score = float(sum(notes) / len(notes))
                states = ("very_long", "long", "neutral", "short", "very_short")
                signals[clock] = (close, states[sum(score >= b for b in (-0.75, -0.15, 0.15, 0.75))], score)
    return signals


@dataclass
class Order:
    buy: bool
    quantity: float
    limit: float | None
    stop: float | None
    stopped: bool = False

    def eligible(self, opn, high, low):
        if self.stopped:
            return opn, "stop"
        if self.stop and low <= self.stop:
            self.stopped = True
            return min(opn, self.stop), "stop"
        if self.limit is None:
            return opn, "market"
        if (self.buy and low < self.limit) or (not self.buy and high > self.limit):
            return self.limit, "limit"
        return None, None


def proposal(mark, decision, note, cash, base, lot):
    buy, market = note < 0, decision.startswith("very_")
    risk = 0.1 if buy else 0.5
    if market:
        limit, stop = None, None
        fraction = min(1.0, 0.3 + (abs(note) + risk) * 0.35)
    else:
        skew = (1.5 - abs(note)) * 0.0075
        factor = max(0.98, 0.995 - skew) if buy else min(1.02, 1.005 + skew)
        limit = floor_lot(mark * factor, 0.01)
        stop = None if buy else floor_lot(mark * 0.97, 0.01)
        fraction = min(0.9, 0.1 + (abs(note) + risk) * 0.4)
        if not buy and base * mark < 0.05 * (cash + base * mark):
            fraction = 1.0
    size = cash / mark if buy else base
    if buy and limit is not None:
        size = min(size, cash / (limit * (1 + BUFFER)))
    quantity = floor_lot(size * fraction, lot)
    if quantity * (limit or mark) >= 5.0:
        return Order(buy, quantity, limit, stop)
    return None


def replay(bars, signals, start, end, lot):
    cash, base = START_CASH, START_BASE
    inventory, receipts, fills = deque(), [], []
    pending, prev, seed_price = None, None, None
    for at, opn, high, low, close, volume in bars:
        if at < start:
            continue
        if at >= end:
            break
        if seed_price is None:
            seed_price = opn
            inventory.append([base, seed_price, 1.0])
        if at in signals:
            price, state, note = signals[at]
            if prev != state and state != "neutral":
                pending = proposal(price, state, note, cash, base, lot)
            prev = state
        if pending is None:
            continue
        price, reason = pending.eligible(opn, high, low)
        if price is None:
            continue
        quantity = pending.quantity
        if pending.buy:
            quantity = min(quantity, floor_lot(cash / (price * (1 + BUFFER)), lot))
        if quantity * price < 5.0:
            pending = None
            continue
        if volume < quantity:
            continue
        fills.append({"at": at, "price": price, "quantity": quantity, "buy": pending.buy, "reason": reason})
        if pending.buy:
            cash -= quantity * price * (1 + BUFFER)
            base += quantity * (1 - FEE)
            inventory.append([quantity * (1 - FEE), price, 1 - FEE])
        else:
            cash += quantity * price * (1 - FEE - BUFFER)
            base -= quantity
            left = quantity
            while left > 1e-10:
                remaining, entry, delivery = inventory[0]
                sold = min(left, remaining)
                gross = sold * (price - entry)
                fees = sold * (price * FEE + entry * (1 / delivery - 1))
                costs = sold * BUFFER * (price + (entry / delivery if delivery < 1 else 0))
                receipts.append((at, gross, fees, costs))
                left -= sold
                inventory[0][0] -= sold
                if inventory[0][0] < 1e-10:
                    inventory.popleft()
        assert cash >= -1e-9 and base >= -1e-9
        assert math.isclose(base, sum(entry[0] for entry in inventory), abs_tol=1e-9)
        pending = None
    return {"fills": fills, "receipts": receipts, "pending": pending, "seed": seed_price,
            "remaining_base": base, "remaining_cash": cash, "inventory": list(inventory)}


def data_with_opens(root, symbol):
    rows, digests = read_minute(root, symbol)
    opens = []
    for month in MONTHS:
        with ZipFile(root / f"klines-spot-{symbol}-1m-{month}.zip") as archive:
            [entry] = archive.namelist()
            with archive.open(entry) as raw:
                for row in csv.reader(TextIOWrapper(raw, encoding="ascii")):
                    at = int(row[0])
                    opens.append((at // (1_000_000 if at >= 10**15 else 1000), float(row[1])))
    output = []
    for (at, high, low, close, quantity), (open_time, opn) in zip(rows, opens, strict=True):
        assert at == open_time and low <= opn <= high
        output.append((at, opn, high, low, close, quantity))
    return output, digests


def summarize(result):
    output = metrics(result["receipts"], len(result["inventory"]))
    changes = defaultdict(float)
    for at, gross, fees, costs in result["receipts"]:
        changes[at] += gross - fees - costs
    equity = peak = START_CASH + START_BASE * result["seed"]
    maximum = 0.0
    for at in sorted(changes):
        equity += changes[at]
        peak = max(peak, equity)
        maximum = max(maximum, (peak - equity) / peak)
    output["net_dd_pct"] = maximum
    return output


def run(exchange, octobot, deps, output):
    with octobot.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == ARCHIVE_SHA
    with ZipFile(octobot) as archive:
        material = {key: archive.read(f"OctoBot-Tentacles-{PIN}/{path}") for key, path in REQUIRED.items()}
    for name, expected in DEPENDENCIES.items():
        material[name] = (deps / name).read_bytes()
        assert hashlib.sha256(material[name]).hexdigest() == expected
    profile = json.loads(material["profile"])["config"]
    assert profile["trading"] == {"reference-market": "USDT", "risk": 0.5}
    assert profile["trader-simulator"]["starting-portfolio"] == {"BTC": START_BASE, "USDT": START_CASH}
    assert json.loads(material["settings"])["use_stop_orders"] is True
    assert json.loads(material["strategy"])["required_time_frames"] == ["1h", "4h", "1d"]
    runtime = indicator_runtime(material)
    results, evidence, observations = [], {}, {}
    for symbol, lot in LOTS.items():
        bars, digests = data_with_opens(exchange, symbol)
        signals = asyncio.run(evaluate(bars, symbol, runtime))
        evidence[symbol] = {"market_archives": digests, "minute_bars": len(bars)}
        for first, last in WINDOWS:
            result = replay(bars, signals, utc_day(first), utc_day(last), lot)
            period = f"{first} to {last} UTC"
            facts = summarize(result)
            results.append({
                "id": 6005, "period": period, "group": "OctoBot DailyTrading · synchronized bar replay",
                "market": symbol, "currency": "USDT", "archive_interval": "1h, 4h, 1d", "interval": "1h/4h/1d + 1m",
                "exit": "Source state transitions and Sell OCO", "order_family": "Market, limit, and paired stop",
                **facts,
            })
            observations[f"{symbol}/{first}"] = {
                **result, "pending": vars(result["pending"]) if result["pending"] else None,
                "state_hours": dict(Counter(value[1] for at, value in signals.items() if utc_day(first) <= at < utc_day(last))),
            }
            print(symbol, first, facts["trades"], facts["net"], flush=True)
    assert any(row["trades"] for row in results)
    output.write_text(json.dumps({
        "coverage": [[6005, "Tested · OctoBot DailyTrading synchronized bar replay",
                      "Published Binance BTC profile and separate ETH substitution. Executed pinned evaluator logic and source order sizing with historical minute fills and seeded inventory."]],
        "results": results, "evidence": evidence, "observations": observations,
        "source_sha256": {key: hashlib.sha256(value).hexdigest() for key, value in material.items()},
        "source": f"https://github.com/Drakkar-Software/OctoBot-Tentacles/tree/{PIN}/profiles/daily_trading",
        "source_archive_sha256": ARCHIVE_SHA,
        "source_dependencies": {
            "OctoBot-Commons": "fa72a8cff8ed816797acbbd881d528c4e3bb31c7",
            "OctoBot-Evaluators": "f3e855944ca41f3e21b7c63a4437354ce200f7b1",
        },
        "assumptions": [
            "Simultaneous closed timeframe updates are batched before the hourly decision. Exchange callback order and simulator queue priority are unavailable.",
            "Warmup starts 2026-08-01 UTC with a cap of 500 closed candles per indicator. Each window resets the trading wallet and resting order independently.",
            "BTC starts with the published 10 BTC and 1,000 USDT, with basis at first observed open. ETH uses 10 ETH and 1,000 USDT as a hypothetical separate deployment.",
            "Resting limits require strict trade-through and one minute of sufficient reported base volume. A paired stop wins ambiguity and becomes marketable at the next feasible open after an insufficient-volume trigger.",
            "Realized P&L counts FIFO inventory allocations. Initial holdings contribute their historical market movement after the starting valuation. Existing open inventory stays unsettled. Drawdown uses seed wallet value.",
            "Fills charge published 10 bp per side and a separate 3 bp modeled execution buffer. Order adaptation uses a 5 USDT minimum and price/size steps, with no venue queue or dust inference.",
        ],
    }, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("exchange", "octobot", "dependencies", "output"):
        parser.add_argument(argument, type=Path)
    args = parser.parse_args()
    run(args.exchange, args.octobot, args.dependencies, args.output)
