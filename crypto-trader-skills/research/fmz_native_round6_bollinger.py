"""Replay the archived FMZ 1098 Bollinger rules on verified closed spot candles."""

import argparse
import json
from collections import deque
from itertools import pairwise
from pathlib import Path
from typing import NamedTuple
from zipfile import ZipFile

import numpy as np
import talib

from research.delta_pinets_catalogue import read, write
from research.delta_strategy_replay import EQUITY, EXECUTION, FEE, stamp, summarize
from research.fmz_native_round3 import KEYS, WINDOWS
from research.fmz_native_round5 import assert_source
from research.fmz_native_round6_audit import BASE, ROOT, digest

IDENT = 1098
NOTES = (
    "Pinned Bollinger, SMA and RSI thresholds with source-matched one-minute defaults. "
    "Evaluate completed candles and execute on the following traded opening minute, "
    "with archive spot minimums and FIFO closed-lot accounting."
)


class Frame(NamedTuple):
    close: float
    upper: float
    mid: float
    lower: float
    upper_average: float
    lower_average: float
    close_average: float
    rsi: float


def actions(prior, now, position):
    signals = []
    if (
        now.upper > now.upper_average
        and prior.upper < prior.upper_average
        and now.lower < prior.lower
        and now.mid > prior.mid
        and now.close > now.close_average
        and now.rsi > 60
    ):
        signals.append(1)
        position += 1
    if (
        now.lower < now.lower_average
        and prior.lower > prior.lower_average
        and now.upper > prior.upper
        and now.mid < prior.mid
        and now.close < now.close_average
        and now.rsi < 40
    ):
        signals.append(-1)
        position -= 1
    if now.upper - now.lower < prior.upper - prior.lower:
        if (
            now.upper < now.upper_average
            and prior.upper > prior.upper_average
            and position > 0
        ):
            signals.append(-1)
            position -= 1
        if (
            now.lower > now.lower_average
            and prior.lower < prior.lower_average
            and position < 0
        ):
            signals.append(1)
            position += 1
    return signals, position


def replay(data, feed, args):
    assert args["period"] == 1 and feed["base_seconds"] == 60
    detail = data["detail"]
    scale = 10 ** detail["quotePrecision"]
    precision = 10 ** detail["basePrecision"]
    candles = data["data"]
    assert all(b[0] == a[0] + 60_000 for a, b in pairwise(candles))
    closes = np.array([r[4] / scale for r in candles], dtype=np.float64)
    upper, mid, lower = talib.BBANDS(
        closes, timeperiod=args["bo"], nbdevup=2, nbdevdn=2, matype=0
    )
    columns = (
        closes,
        upper,
        mid,
        lower,
        talib.SMA(upper, args["ma"]),
        talib.SMA(lower, args["ma"]),
        talib.SMA(closes, args["ma2"]),
        talib.RSI(closes, 12),
    )
    start, end = (stamp(feed[x]) * 1000 for x in ("start", "end"))
    cash, stock, position = EQUITY, 0.0, 0
    filled, outcomes, lots = [], [], deque()
    candidates = rejects = count = 0
    for i, row in enumerate(candles[1:-1], 1):
        if row[0] < start or row[0] >= end - 60_000:
            continue
        assert candles[i + 1][0] == row[0] + 60_000
        count += 1
        prior, now = (Frame(*(series[j] for series in columns)) for j in (i - 1, i))
        assert all(np.isfinite([*prior, *now]))
        flags, position = actions(prior, now, position)
        at, opening, *_, volume = candles[i + 1]
        price = opening / scale
        asked_cash, asked_stock = cash * 0.1, stock * 0.1
        for side in flags:
            candidates += 1
            limit = (
                min(cash, asked_cash) / (price * (1 + FEE))
                if side > 0
                else min(stock, asked_stock)
            )
            qty = int(limit * precision) / precision
            if (
                volume <= 0
                or qty < detail["minQty"]
                or qty * price < detail["minNotional"]
            ):
                rejects += 1
                continue
            value = qty * price
            fees = value * FEE
            cash -= side * value + fees
            stock += side * qty
            filled.append((at, side, qty, price, fees))
            if side > 0:
                lots.append((qty, price))
                continue
            left = qty
            while left > 1e-10:
                opened, basis = lots.popleft()
                size = min(opened, left)
                gross = size * (price - basis)
                turnover = size * (price + basis)
                fee_only = gross - turnover * FEE
                outcomes.append((at, gross, fee_only, fee_only - turnover * EXECUTION))
                left -= size
                if opened - size > 1e-10:
                    lots.appendleft((opened - size, basis))
        assert cash >= -1e-8 and stock >= -1e-8
    assert count == (end - start) // 60_000 - 1
    assert candidates == rejects + len(filled)
    assert abs(stock - sum(x[0] for x in lots)) < 1e-8
    return (
        outcomes,
        len(lots),
        {
            "signals": candidates,
            "rejected": rejects,
            "fills": filled,
            "cash": cash,
            "stock": stock,
            "last_source_state": position,
        },
    )


def run(archive, offline, output):
    item = next(r for r in read(BASE)["disposition"] if r["id"] == IDENT)
    check = next(
        r
        for r in read(ROOT / "fmz-native-round6-audit.json")["source_evidence"]
        if r["id"] == IDENT
    )
    reports = [
        r
        for r in read(offline / "round5-native-python-jobs.json")
        if r["item"]["id"] == IDENT
    ]
    outcomes, rows, receipts = {}, [], []
    with ZipFile(archive) as pinned:
        for entry in reports:
            assert_source(entry, pinned, {**item, **check})
            feed, args = entry["feed"], entry["item"]["args"]
            content = (offline / feed["file"]).read_bytes()
            assert digest(content) == feed["sha256"]
            cashflows, open_lots, receipt = replay(json.loads(content), feed, args)
            outcomes[feed["coin"], feed["start"]] = cashflows, open_lots
            receipts.append(
                {
                    **receipt,
                    "feed": feed,
                    "args": args,
                    "source_sha256": check["document_sha256"],
                }
            )
    assert outcomes.keys() == KEYS and any(t for t, _ in outcomes.values())
    for start, (_, window) in WINDOWS.items():
        btc, ob = outcomes["BTC", start]
        eth, oe = outcomes["ETH", start]
        for market, ledger, opened in (
            ("BTCUSDT", btc, ob),
            ("ETHUSDT", eth, oe),
            ("BTCUSDT + ETHUSDT", btc + eth, ob + oe),
        ):
            row = summarize(
                (
                    "FMZ Python · closed-bar Bollinger",
                    item["name"],
                    market + " spot",
                    "Archived Bollinger order rule",
                ),
                window,
                ledger,
                opened,
            )
            row.update(
                id=IDENT,
                interval="1m",
                archive_interval="1m",
                source=item["source"],
                quote_currency="USDT",
            )
            rows.append(row)
    write(
        output,
        {
            "baseline": "91ad53db",
            "coverage": [[IDENT, "Tested · FMZ Python closed-bar variant", NOTES]],
            "talib_version": talib.__version__,
            "results": rows,
            "receipts": receipts,
        },
    )
    print(IDENT, len(rows), "result rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("archive", "offline", "output"):
        parser.add_argument(field, type=Path)
    run(**vars(parser.parse_args()))
