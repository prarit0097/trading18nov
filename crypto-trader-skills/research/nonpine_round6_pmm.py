"""Source-bound Hummingbot PMM variants on historical Binance USD-M prints."""

import argparse
import csv
import gzip
import hashlib
import io
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.nonpine_round4_basis import SECOND, snapshots
from research.nonpine_round4_metrics import metrics
from research.nonpine_round5_pmm import eligible

DATES = ("2026-10-01", "2026-11-01")
VENUE = "binance-futures"
TREES = {5989: ("PMM Simple", (0.01, 0.02)), 5988: ("PMM Dynamic", (1, 2, 4))}
TICKS = {"BTCUSDT": 0.1, "ETHUSDT": 0.01}
MIN_NOTIONALS = {"BTCUSDT": 50, "ETHUSDT": 20}
LOT_SIZE = 0.001
BUDGET = 600
MAKER, TAKER, BUFFER = 0.0002, 0.0005, 0.0003
REFRESH, COOLING, HOLD = 301, 15, 45 * 60
STOP, TARGET = 0.03, 0.02
WARMUP = 142


@dataclass
class Level:
    side: int
    price: float
    size: float
    born: int
    entered: int | None = None
    target: float | None = None
    posted: int | None = None
    close: str | None = None


def limit_price(price, tick, side):
    return (math.floor if side > 0 else math.ceil)(price / tick) * tick


def consume(levels, at, side, price, amount):
    candidates = []
    for level in levels:
        if level.close:
            continue
        if level.entered is None:
            order = (level.price, level.born * SECOND)
            if at >= (level.born + REFRESH) * SECOND:
                continue
            order_side = level.side
        elif level.posted is not None:
            order = (level.target, level.posted * SECOND)
            order_side = -level.side
            if at >= (level.born + HOLD) * SECOND:
                continue
        else:
            continue
        if side == order_side and eligible(order, at, price, amount, side, level.size):
            candidates.append((order[0], order[1], level))
    filled = []
    for _, _, level in sorted(candidates, key=lambda x: (-side * x[0], x[1])):
        if amount + 1e-12 < level.size:
            break
        amount -= level.size
        if level.entered is None:
            level.entered = at
        else:
            level.close = "target"
        filled.append(level)
    return filled


def settle(level, exit_price, at, fee_rate):
    gross = level.size * level.side * (exit_price - level.price)
    fee = level.size * (level.price * MAKER + exit_price * fee_rate)
    return at, gross, fee, level.size * (level.price + exit_price) * BUFFER


def prints(path, asset):
    with gzip.open(path, "rt", encoding="ascii", newline="") as stream:
        last = 0
        for row in csv.DictReader(stream):
            at, arrival = int(row["timestamp"]), int(row["local_timestamp"])
            assert (
                arrival >= last and row["symbol"] == asset and row["exchange"] == VENUE
            )
            last = arrival
            assert row["side"] in {"buy", "sell"}
            yield (
                arrival,
                at,
                (1 if row["side"] == "sell" else -1),
                float(row["price"]),
                float(row["amount"]),
            )


def dynamic_features(files, first, last):
    import numpy as np
    import talib

    minutes = {}
    for file in files:
        with ZipFile(file) as archive:
            [member] = archive.namelist()
            with archive.open(member) as raw:
                for row in csv.reader(io.TextIOWrapper(raw, encoding="ascii")):
                    if not row[0].isdigit():
                        continue
                    at = int(row[0]) // 1000
                    if first - 60 <= at <= last:
                        assert int(row[6]) + 1 == (at + 60) * 1000
                        assert at not in minutes
                        minutes[at] = tuple(map(float, (row[2], row[3], row[4])))
    bars = []
    features = {}
    for end in range(first + 180, last + 1, 180):
        parts = [minutes[t] for t in (end - 180, end - 120, end - 60)]
        bars.append((max(x[0] for x in parts), min(x[1] for x in parts), parts[-1][2]))
        if len(bars) < WARMUP:
            continue
        h, low, c = np.asarray(bars[-WARMUP:]).T
        volatility = talib.NATR(h, low, c, timeperiod=14)[-1] / 100
        macd, _, histogram = talib.MACD(c, fastperiod=21, slowperiod=42, signalperiod=9)
        mean = np.nanmean(macd)
        std = np.nanstd(macd, ddof=1)
        assert volatility > 0 and std > 0
        bias = (-(macd[-1] - mean) / std + (1 if histogram[-1] > 0 else -1)) / 2
        features[end] = (float(c[-1] * (1 + bias * volatility / 2)), float(volatility))
    return features


def replay(quote_updates, trades, start, end, asset, spreads, features=None):
    active, next_open = {}, {}
    closed, ledger = [], []
    valid = 0
    quote = dyn = None
    current = next(trades, None)
    tick_size = TICKS[asset]
    max_level_quote = BUDGET / (2 * len(spreads))
    level_keys = [(side, level) for side in (1, -1) for level in spreads]

    def close(level, price, at, fee):
        receipt = settle(level, price, at, fee)
        closed.append(receipt)
        ledger.append(
            [
                level.born,
                level.entered,
                at,
                level.side,
                level.size,
                level.price,
                price,
                level.close,
                *receipt[1:],
            ]
        )

    for tick in range(start - 2, end + 1):
        while current is not None and current[0] <= tick * SECOND:
            arrival, at, side, price, amount = current
            if active:
                for level in consume(active.values(), at, side, price, amount):
                    if level.close == "target":
                        close(level, level.target, arrival, MAKER)
                        level.size = 0
            current = next(trades, None)
        quote = quote_updates.get(tick, quote)
        if features is not None:
            dyn = features.get(tick, dyn)
        has_quote = quote is not None and tick * SECOND - quote[0] <= 2 * SECOND
        depth = [quote[3], quote[4]] if has_quote else [0, 0]
        if tick >= start and has_quote:
            valid += 1
        for key, level in list(active.items()):
            if not level.size or (
                level.entered is None and tick >= level.born + REFRESH
            ):
                del active[key]
            elif level.entered is not None:
                if level.close:
                    depth_index = 0 if level.side > 0 else 1
                    if depth[depth_index] >= level.size:
                        depth[depth_index] -= level.size
                        close(level, quote[1 + depth_index], tick * SECOND, TAKER)
                        if level.close == "stop":
                            next_open[key] = tick + COOLING
                        del active[key]
                else:
                    stop_price = (
                        quote[1]
                        if has_quote and level.side > 0
                        else quote[2]
                        if has_quote
                        else None
                    )
                    if (
                        stop_price is not None
                        and level.side * (stop_price / level.price - 1) - MAKER <= -STOP
                    ):
                        level.close = "stop"
                    elif tick >= level.born + HOLD:
                        level.close = "time"
                    elif level.posted is None:
                        level.target = limit_price(
                            level.price * (1 + level.side * TARGET),
                            tick_size,
                            -level.side,
                        )
                        if has_quote and (
                            (level.side > 0 and level.target > quote[1])
                            or (level.side < 0 and level.target < quote[2])
                        ):
                            level.posted = tick
        if (
            tick < start
            or tick >= end
            or not has_quote
            or (features is not None and dyn is None)
        ):
            continue
        reference, scale = (
            dyn if features is not None else ((quote[1] + quote[2]) / 2, 1)
        )
        for key in level_keys:
            side, spread = key
            if key in active or tick < next_open.get(key, 0):
                continue
            limit = limit_price(
                reference * (1 - side * spread * scale), tick_size, side
            )
            if (
                limit <= 0
                or (side > 0 and limit >= quote[2])
                or (side < 0 and limit <= quote[1])
            ):
                continue
            quantity = math.floor(max_level_quote / limit / LOT_SIZE) * LOT_SIZE
            if quantity * limit >= MIN_NOTIONALS[asset]:
                active[key] = Level(side, limit, quantity, tick)
    assert valid >= 1000
    return (
        closed,
        sum(x.entered is not None and x.size > 0 for x in active.values()),
        ledger,
        valid,
    )


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def candle_inputs(directory, asset, date):
    prefix = f"klines-futures-{asset}-1m-"
    previous_month = "2026-09" if date.endswith("10-01") else "2026-10"
    current = date[:7] if date.endswith("10-01") else date
    return [directory / (prefix + day + ".zip") for day in (previous_month, current)]


def run(prior_quotes, trade_dir, candles, archive_path, baseline, output):
    old = {x["id"]: x for x in read(baseline)["disposition"]}
    ref = old[5989]["source"].split("/blob/")[1].split("/")[0]
    source_paths = (
        "/pmm_simple.py",
        "/pmm_dynamic.py",
        "/market_making_controller_base.py",
        "/position_executor/position_executor.py",
    )
    with ZipFile(archive_path) as archive:
        sources = {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in archive.namelist()
            if name.startswith(f"hummingbot-{ref}/") and name.endswith(source_paths)
        }
    assert len(sources) == len(source_paths)
    quotes = {
        (x["date"], x["symbol"]): x
        for x in read(prior_quotes / "manifest.json")
        if x["exchange"] == VENUE
    }
    trades = {
        (x["date"], x["symbol"]): x
        for x in read(trade_dir / "manifest.json")
        if x.get("exchange") == VENUE and x.get("dataset") == "trades"
    }
    results, data, receipts = [], {}, {}
    for date in DATES:
        midnight = int(datetime.fromisoformat(date + "T00:00:00+00:00").timestamp())
        for asset in TICKS:
            quote, trade = quotes[date, asset], trades[date, asset]
            trade_path = trade_dir / trade["file"]
            assert trade["sha256"] == checksum(trade_path)
            # The last 142 closed 3m bars must be available before session start.
            files = candle_inputs(candles, asset, date)
            start, end = midnight + 300, midnight + 28_500
            features = dynamic_features(files, midnight - WARMUP * 180, end)
            assert midnight in features
            grid = snapshots(prior_quotes / quote["file"], quote, start, end)
            data[f"{date}/{asset}"] = {
                "quotes": quote,
                "prints": trade,
                "binance_archives": {f.name: checksum(f) for f in files},
            }
            for ident, (label, spreads) in TREES.items():
                fills, unresolved, ledger, valid = replay(
                    grid,
                    prints(trade_path, asset),
                    start,
                    end,
                    asset,
                    spreads,
                    features if ident == 5988 else None,
                )
                receipts[f"{ident}/{date}/{asset}"] = {
                    "valid_seconds": valid,
                    "closes": ledger,
                }
                results.append(
                    {
                        "id": ident,
                        "period": date,
                        "group": f"Hummingbot · {label} maker variant",
                        "market": asset + " perp",
                        "currency": "USDT",
                        "interval": "1s quotes + market prints",
                        "archive_interval": "Binance USD-M quotes and trades",
                        "exit": "Stop, limit target or 45m timeout",
                        "order_family": "Independent, capital-bounded levels",
                        **metrics(fills, unresolved),
                    }
                )
                print(ident, date, asset, len(fills), unresolved, flush=True)
    coverage = []
    for ident, (label, _) in TREES.items():
        assert not old[ident]["status"].startswith("Tested")
        empty = not any(x["trades"] for x in results if x["id"] == ident)
        coverage.append(
            [
                ident,
                f"Tested · {label} trade-through variant"
                + (", no closes" if empty else ""),
                (
                    "Pinned spread and barrier settings on BTC and ETH Binance USD-M. Passive entries and targets "
                    "use later strict trade-through size. Stop and time exits use subsequent executable top-of-book. "
                    "Closed-candle data gate for the dynamic 3m NATR/MACD features. Leverage-normalized variant."
                ),
            ]
        )
    write(
        output,
        {
            "coverage": coverage,
            "results": results,
            "data": data,
            "sources": sources,
            "receipts": receipts,
            "settings": {
                "budget": BUDGET,
                "stop": STOP,
                "target": TARGET,
                "hold_seconds": HOLD,
                "refresh_seconds": REFRESH,
                "cooldown": COOLING,
                "maker_fee": MAKER,
                "taker_fee": TAKER,
                "extra_cost_per_side": BUFFER,
            },
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "prior_quotes",
        "trade_dir",
        "candles",
        "archive_path",
        "baseline",
        "output",
    ):
        parser.add_argument(name, type=Path)
    run(**vars(parser.parse_args()))
