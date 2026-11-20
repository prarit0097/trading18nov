"""Replay Hummingbot's single-level spot PMM on historical quotes and prints."""

import argparse
import csv
import gzip
import hashlib
import math
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.nonpine_round4_basis import SECOND, snapshots
from research.nonpine_round4_metrics import metrics

IDENT = 5997
DATES = ("2026-10-01", "2026-11-01")
SIZE = {"BTCUSDT": 0.001, "ETHUSDT": 0.025}
FEE = 0.001
EXECUTION = 0.0003
SPREADS = (0.01, 0.0015)
TICK = 0.01
REFRESH = 1800
FILLED_DELAY = 60


def eligible(order, exchange_time, price, amount, order_side, size):
    limit, placed = order
    return (
        exchange_time > placed and amount >= size and (limit - price) * order_side > 0
    )


def position_fill(queue, closed, side, at, price, size):
    if queue and queue[0][0] != side:
        previous_side, _, previous = queue.pop(0)
        turnover = size * (previous + price)
        closed.append(
            (
                at,
                size * previous_side * (price - previous),
                turnover * FEE,
                turnover * EXECUTION,
            )
        )
    else:
        queue.append((side, at, price))


def prints(path, asset):
    with gzip.open(path, "rt", encoding="ascii", newline="") as stream:
        last = 0
        for row in csv.DictReader(stream):
            arrival, at = int(row["local_timestamp"]), int(row["timestamp"])
            assert (
                arrival >= last
                and row["exchange"] == "binance"
                and row["symbol"] == asset
            )
            assert row["side"] in ("buy", "sell")
            last = arrival
            yield (
                arrival,
                at,
                (1 if row["side"] == "sell" else -1),
                float(row["price"]),
                float(row["amount"]),
            )


def replay(quote_updates, trades, start, end, size, spread):
    initialized = False
    next_create = cancel = start
    orders, queue, closed, fills = {}, [], [], []
    quote = None
    current = next(trades, None)
    valid = 0
    cash = base = 0.0
    initial = 0.0
    for tick in range(start - 2, end + 1):
        while current is not None and current[0] <= tick * SECOND:
            arrival, at, side, price, amount = current
            order = orders.get(side)
            if (
                order
                and at < cancel * SECOND
                and eligible(order, at, price, amount, side, size)
            ):
                limit, placed = orders.pop(side)
                cash -= size * limit * (side + FEE)
                base += side * size
                assert min(base, cash) >= -1e-9
                position_fill(queue, closed, side, arrival, limit, size)
                fills.append([placed, arrival, side, limit])
                next_create = (arrival + SECOND - 1) // SECOND + FILLED_DELAY
                cancel = min(cancel, next_create)
            current = next(trades, None)
        quote = quote_updates.get(tick, quote)
        if tick >= cancel:
            orders.clear()
        if tick < start or quote is None or tick * SECOND - quote[0] > 2 * SECOND:
            continue
        valid += 1
        _, bid, ask, _, _ = quote
        mid = (bid + ask) / 2
        if not initialized:
            initial = base = 5_000 / mid
            cash, initialized = 5_000, True
        if tick >= next_create and not orders and tick < end:
            buy = math.floor(mid * (1 - spread) / TICK) * TICK
            sell = math.ceil(mid * (1 + spread) / TICK) * TICK
            if buy < ask and cash >= size * buy * (1 + FEE):
                orders[1] = buy, tick * SECOND
            if sell > bid and base >= size:
                orders[-1] = sell, tick * SECOND
            cancel = next_create = tick + REFRESH
    assert initialized and valid >= 1000
    assert math.isclose(base - initial, size * sum(x[0] for x in queue), abs_tol=1e-9)
    return closed, len(queue), fills, valid


def run(quote_dir, trade_dir, archive_path, baseline, output):
    [item] = [x for x in read(baseline)["disposition"] if x["id"] == IDENT]
    assert not item["status"].startswith("Tested")
    ref = item["source"].split("/blob/")[1].split("/")[0]
    with ZipFile(archive_path) as archive:
        sources = {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in archive.namelist()
            if name.startswith(
                f"hummingbot-{ref}/hummingbot/strategy/pure_market_making/"
            )
            and name.endswith(
                (
                    "/start.py",
                    "/pure_market_making.pyx",
                    "/pure_market_making_config_map.py",
                )
            )
        }
    assert len(sources) == 3
    quotes = {
        (x["date"], x["symbol"]): x
        for x in read(quote_dir / "manifest.json")
        if x["exchange"] == "binance"
    }
    results, receipts, files = [], {}, []
    for date in DATES:
        midnight = int(datetime.fromisoformat(date + "T00:00:00+00:00").timestamp())
        start, end = midnight + 300, midnight + 28_500
        for asset, size in SIZE.items():
            source = quotes[date, asset]
            filename = f"{date}-binance-trades-{asset}.csv.gz"
            trade_path = trade_dir / filename
            with trade_path.open("rb") as stream:
                sha = hashlib.file_digest(stream, "sha256").hexdigest()
            url = f"https://datasets.tardis.dev/v1/binance/trades/{date.replace('-', '/')}/{asset}.csv.gz"
            files.append({"trade": {"url": url, "sha256": sha}, "quote": source})
            updates = snapshots(quote_dir / source["file"], source, start, end)
            for spread in SPREADS:
                closed, open_lots, fills, valid = replay(
                    updates, prints(trade_path, asset), start, end, size, spread
                )
                label = f"{spread:.2%}"
                receipts[f"{date}/{asset}/{label}"] = {
                    "valid_seconds": valid,
                    "fills": fills,
                }
                results.append(
                    {
                        "id": IDENT,
                        "period": date,
                        "group": f"Hummingbot · PMM {label} trade-through variant",
                        "market": asset,
                        "currency": "USDT",
                        "interval": "1s quotes + trade ticks",
                        "exit": "Opposite maker fill, FIFO",
                        "archive_interval": "Top of book and trade prints",
                        "order_family": "Single-level pre-funded spot maker",
                        **metrics(closed, open_lots),
                    }
                )
    status = "Tested · Hummingbot PMM trade-through variant"
    if not any(row["trades"] for row in results):
        status += ", no closes"
    reason = (
        "Pinned PMM bid/ask and refresh logic modeled using two symmetric spread settings and 30-minute refresh. "
        "Binance BTC/ETH full-size, later opposing prints strictly through each resting price. "
        "Pre-funded spot inventory, FIFO realized closes and explicit fees; at-price queue fills excluded."
    )
    write(
        output,
        {
            "coverage": [[IDENT, status, reason]],
            "results": results,
            "pinned_source": sources,
            "data": files,
            "receipts": receipts,
            "settings": {
                "position_size": SIZE,
                "spreads": SPREADS,
                "refresh_seconds": REFRESH,
                "delay_seconds": FILLED_DELAY,
                "open_start_utc": "00:05",
                "end_utc": "07:55",
                "fee_per_side": FEE,
                "execution_per_side": EXECUTION,
            },
        },
    )
    print([(x["period"], x["market"], x["trades"], x["unsettled"]) for x in results])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("quote_dir", "trade_dir", "archive_path", "baseline", "output"):
        parser.add_argument(arg, type=Path)
    run(**vars(parser.parse_args()))
