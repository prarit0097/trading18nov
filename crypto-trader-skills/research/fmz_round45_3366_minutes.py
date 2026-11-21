"""Replay the complete FMZ #3366 bracket with actual finer price chronology."""

import math
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from functools import lru_cache
from itertools import pairwise
from pathlib import Path

from research.fmz_round7_magnifier import (
    aggregate,
    ledger_metrics,
    read,
    sha256,
    verified_archives,
    write,
)
from research.fmz_round26_977 import csv_rows
from research.fmz_round34_3038 import min_candles
from research.fmz_round45_3366 import DAY, SOURCE, entry_signals, grid

MINUTE = 60_000
CAPITAL = 1_000_000
FEE = Decimal("0.00075")
PRIOR = "c1fa17b77c036455ac7c8e8c3049bef487f4c7c90587d03531af1bad39165e08"
MONTHS = ("2022-11", "2022-12", *(f"2023-{m:02d}" for m in range(1, 12)))


@dataclass(frozen=True)
class Position:
    side: int
    price: Decimal
    time: int


def price(value, step, direction):
    return grid(value, step, ROUND_CEILING if direction > 0 else ROUND_FLOOR)


def exit_points(position, previous_close, before_entry, tick):
    distance = previous_close * Decimal(".02")
    side = position.side
    activation = price(position.price + side * distance, tick, side)
    if before_entry:
        return activation, previous_close * Decimal(".005"), None, None
    fixed_stop = price(position.price * (1 - side * Decimal(".02")), tick, -side)
    target = price(position.price * (1 + side * Decimal(".09")), tick, side)
    return activation, previous_close * Decimal(".005"), fixed_stop, target


def trace(points, prices, direction, best, tick, actual=False):
    activation, offset, fixed, target = points
    for i, trade_price in enumerate(prices):
        available = [fixed] if fixed is not None else []
        if best is not None:
            available.append(price(best - direction * offset, tick, -direction))
        if available:
            stop = max(available, key=lambda x: direction * x)
            if (trade_price - stop) * direction <= 0:
                stop_kind = "fixed stop" if stop == fixed else "trailing stop"
                return (stop_kind, trade_price if i == 0 or actual else stop), best
        if target is not None and (trade_price - target) * direction >= 0:
            return ("target", trade_price if i == 0 else target), best
        reference = activation if best is None else best
        if (trade_price - reference) * direction >= 0:
            best = trade_price
    return None, best


@lru_cache(maxsize=32)
def raw_events(path, stamp):
    events = []
    for row in csv_rows(path):
        if not row[0].isdigit():
            continue
        observed_at = int(row[4])
        if observed_at >= stamp + MINUTE:
            break
        if observed_at >= stamp:
            events.append((int(row[0]), observed_at, float(row[1]), float(row[2])))
    assert events and all(a[0] < b[0] and a[1] <= b[1] for a, b in pairwise(events))
    return events


def recorded_minute(tape, market, minute, archive_map):
    stamp, opening, high, low, close, volume = minute
    date = datetime.fromtimestamp(stamp / 1000, UTC).strftime("%Y-%m-%d")
    filename = f"{market}-trades-{date}.zip"
    path = tape / filename
    if not path.exists():
        raise FileNotFoundError(f"Required raw path {market} {date} {stamp}")
    if (market, date) not in archive_map:
        digest = sha256(path)
        assert (tape / (filename + ".CHECKSUM")).read_text().split() == [
            digest,
            filename,
        ]
        archive_map[(market, date)] = {
            "name": filename,
            "sha256": digest,
            "url": f"https://data.binance.vision/data/futures/um/daily/trades/{market}/{filename}",
        }
    events = raw_events(path, stamp)
    prices = [t[2] for t in events]
    assert (prices[0], max(prices), min(prices), prices[-1]) == (
        opening,
        high,
        low,
        close,
    )
    assert math.isclose(math.fsum(t[3] for t in events), volume, rel_tol=1e-9)
    return [Decimal(str(x)) for x in prices]


def scan(minutes, market, position, points, best, tick, tape, archive_map):
    for minute in minutes:
        stamp, opening, high, low, close, volume = minute
        if not volume:
            continue
        o, h, l, c = (Decimal(str(x)) for x in (opening, high, low, close))
        a = trace(points, (o, h, l, c), position.side, best, tick)
        b = trace(points, (o, l, h, c), position.side, best, tick)
        if a[0] != b[0] or (a[0] is None and a[1] != b[1]):
            tape_prices = recorded_minute(tape, market, minute, archive_map)
            fill, best = trace(
                points, tape_prices, position.side, best, tick, actual=True
            )
        else:
            fill, best = a
        if fill:
            return (stamp, *fill), best
    return None, best


def close_trade(position, at, exit_price, reason):
    gross = (exit_price - position.price) * position.side
    fee = (position.price + exit_price) * FEE
    return {
        "dir": position.side,
        "qty": 1,
        "entryTime": position.time,
        "exitTime": at,
        "entryPrice": float(position.price),
        "exitPrice": float(exit_price),
        "commission": float(fee),
        "profit": float(gross - fee),
        "reason": reason,
    }


def settlement(market, chart, signals, minutes, tape, archive_map, restart):
    tick = Decimal(".1" if market == "BTCUSDT" else ".01")
    orders, exits = [], []
    position = best = None
    for i in range(1, len(chart) + 1):
        day = chart[0][0] + i * DAY
        start = i * 1440
        children = minutes[start : start + 1440]
        assert children and children[0][0] == day
        o = Decimal(str(children[0][1]))
        previous_close = Decimal(str(chart[i - 1][4]))
        signal = signals["buy"][i - 1] - signals["sell"][i - 1]
        closing = (
            position
            and signals["close long" if position.side == 1 else "close short"][i - 1]
        )
        new = signal and (position is None or position.side != signal)
        if position and (closing or new):
            assert children[0][5] > 0
            exits.append(close_trade(position, day, o, "opposite market signal"))
            position = best = None
        if new:
            assert children[0][5] > 0
            position = Position(signal, o, day)
            orders.append({"side": signal, "time": day, "price": float(o)})
        if position:
            if restart:
                best = None
            points = exit_points(position, previous_close, position.time == day, tick)
            filled, best = scan(
                children, market, position, points, best, tick, tape, archive_map
            )
            if filled:
                at, reason, p = filled
                exits.append(close_trade(position, at, p, reason))
                position = best = None
    mark = Decimal(str(minutes[-1][4]))
    terminal = (
        None
        if position is None
        else {
            "side": position.side,
            "entry": float(position.price),
            "entry_time": position.time,
            "mark": float(mark),
            "gross_unrealized": float((mark - position.price) * position.side),
            "entry_fee": float(position.price * FEE),
        }
    )
    return {"entries": orders, "exits": exits, "terminal": terminal}


def check_market(
    market, case, source_flags, minute_folder, tape, receipts, archive_map
):
    chart, hourly = case["chart"], case["hour"]
    start, end = chart[0][0], chart[-1][0] + DAY
    files = verified_archives(minute_folder, market, "1m", MONTHS, receipts)
    minutes = []
    for path in files:
        label = path.name.removesuffix(".zip")[-7:]
        dt = datetime.fromisoformat(label + "-01T00:00:00+00:00")
        next_month = (
            dt.replace(year=dt.year + 1, month=1)
            if dt.month == 12
            else dt.replace(month=dt.month + 1)
        )
        low = max(start, int(dt.timestamp()) * 1000)
        high = min(end + 320 * MINUTE, int(next_month.timestamp()) * 1000)
        minutes.extend(min_candles(path, low, high))
    assert len(minutes) == 347 * 1440 + 320
    rollup = aggregate(minutes[: 347 * 1440], 60)
    mismatches = [
        {"hourly": a[:5], "minutely": b[:5]}
        for a, b in zip(hourly, rollup, strict=True)
        if a[:5] != list(b[:5])
    ]
    assert not mismatches, (market, mismatches[:4])
    signals = entry_signals(chart)
    assert all(source_flags["scope " + n] == v for n, v in signals.items())
    primary = settlement(
        market, chart, signals, minutes, tape, archive_map, restart=False
    )
    alternate = settlement(
        market, chart, signals, minutes, tape, archive_map, restart=True
    )
    assert primary == alternate, (
        market,
        "daily trailing amendments affect the outcome",
    )
    return {
        "market": market,
        "verified_minutes": len(minutes),
        "parent_disagreements": mismatches,
        "same_ledger_with_restarted_daily_trailing_state": True,
        **primary,
    }


def main(document, prior_path, feed, native, minute_source, tape, output):
    assert sha256(document) == SOURCE and sha256(prior_path) == PRIOR
    prior = read(prior_path)
    assert (
        sha256(feed) == prior["input_sha256"]
        and sha256(native) == prior["native_probe_sha256"]
    )
    data = read(feed)["markets"]
    plots = read(native)
    receipts, archive_map = [], {}
    cases = [
        check_market(
            m,
            result,
            plots[m]["literal"]["plots"],
            minute_source,
            tape,
            receipts,
            archive_map,
        )
        for m, result in data.items()
    ]
    common = {
        "id": 3366,
        "group": "FMZ Bollinger · official minute bracket model",
        "period": "2022-11-22 to 2023-11-04 05:20 UTC exclusive",
        "currency": "USDT",
        "interval": "1d with recorded 1m triggers",
        "archive_interval": "1d",
        "pine_source_version": "5",
        "order_family": "Market entry, daily-amended fixed and trailing bracket",
        "exit": "First eligible source stop, target, trailing stop or opposite close",
    }
    results = []
    for selected in ([cases[0]], [cases[1]], cases):
        results.append(
            {
                **common,
                "market": " + ".join(c["market"] for c in selected),
                **ledger_metrics(
                    [t for c in selected for t in c["exits"]],
                    CAPITAL * len(selected),
                    sum(c["terminal"] is not None for c in selected),
                ),
            }
        )
    write(
        output,
        {
            "schema": "FMZ #3366 verified full-window physical bracket path",
            "source_sha256": SOURCE,
            "source_url": prior["source_url"],
            "prior_evidence_sha256": PRIOR,
            "input_sha256": sha256(feed),
            "minute_receipts": receipts,
            "raw_trade_receipts": list(archive_map.values()),
            "cases": cases,
            "results": results,
            "notes": "The source's latest complete daily signal arms next-open entries and exits. Its trailing activation starts with the entry, while fixed stop and target require a position-aware close. Amendment carry and reset policies both generate the same tested orders. Minute opens fill gaps; inside minutes the threshold is used when both high/low sweeps agree. Disagreement is resolved using checksum-verified raw prints. Simulated exit limits assume queue priority at the reached price. The partial final day is used only to execute existing orders. A 0.075% fee per side is added. Funding, bid/ask spread and own-order impact are outside the scope.",
            "coverage": [
                [
                    3366,
                    "Tested · complete causal minute bracket model",
                    "Official 1m and raw trade witnesses resolve original trade paths for BTC and ETH. Independent daily entry flags, tick-normalized brackets and two amendment controls agree.",
                ]
            ],
        },
    )


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
