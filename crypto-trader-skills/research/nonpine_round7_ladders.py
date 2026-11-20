"""Historical OctoBot grid and neutral staggered-order variants."""

import argparse
import hashlib
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.nonpine_round4_basis import SECOND, snapshots
from research.nonpine_round4_metrics import metrics
from research.nonpine_round5_pmm import prints
from research.nonpine_round6_index import BUFFER, FEE, LOTS, START

DATES = ("2026-10-01", "2026-11-01")
MODES = {6008: ("Grid", 20, 0.0), 6013: ("Staggered neutral", 25, 0.30)}
TICK = 0.01
MIN_NOTIONAL = 5
SPREAD, INCREMENT = 0.015, 0.005
ALLOCATED = 0.90
MIRROR_DELAY_US = SECOND


@dataclass(frozen=True)
class Order:
    slot: int
    side: int
    price: float
    qty: float
    posted: int
    first: "Order | None"


def floor_lot(value, lot):
    return math.floor(value / lot + 1e-10) * lot


def at_tick(price, tick, side):
    grid = price / tick
    units = math.floor(grid + 1e-10) if side > 0 else math.ceil(grid - 1e-10)
    return round(units * tick, 8)


def crossed(orders, exchange_time, side, price, amount):
    candidates = [
        order
        for order in orders
        if order.side == side
        and exchange_time > order.posted
        and side * (order.price - price) > 0
    ]
    fills = []
    for order in sorted(candidates, key=lambda p: (-side * p.price, p.posted, p.slot)):
        if amount + 1e-12 < order.qty:
            break
        fills.append(order)
        amount -= order.qty
    return fills


def mirror(order, increment, tick, lot, posted):
    side = -order.side
    price = at_tick(order.price - side * increment, tick, side)
    qty = order.qty if side < 0 else floor_lot(order.qty * order.price / price, lot)
    return Order(
        order.slot, side, price, qty, posted, order if order.first is None else None
    )


def exit_values(first, current, at):
    assert first.side == -current.side and first.posted < current.posted < at
    quantity = min(first.qty, current.qty)
    gross = first.side * quantity * (current.price - first.price)
    turnover = first.price * first.qty + current.price * current.qty
    return at, gross, turnover * FEE, turnover * BUFFER


def initial_levels(center, count, slope, lot, posted):
    inc = round(floor_lot(center * INCREMENT, TICK), 8)
    spread = round(floor_lot(center * SPREAD, TICK), 8)
    assert 0 < inc < spread
    initial_cash, initial_base = START / 2, START / 2 / center
    orders = []
    weights = [1 + slope / 2 - slope * n / (count - 1) for n in range(count)]
    for side in (1, -1):
        budget = (initial_cash if side > 0 else initial_base) * ALLOCATED
        for i, weight in enumerate(weights):
            price = at_tick(center - side * (spread / 2 + i * inc), TICK, side)
            share = budget * weight / sum(weights)
            size = share / (price * (1 + FEE + BUFFER)) if side > 0 else share
            qty = floor_lot(size, lot)
            assert qty * price >= MIN_NOTIONAL
            orders.append(Order(len(orders) + 1, side, price, qty, posted, None))
    return orders, spread - inc, initial_cash, initial_base


def replay(trades, center, start, end, count, slope, lot):
    levels, delta, cash, base = initial_levels(
        center, count, slope, lot, start * SECOND
    )
    active = {order.slot: order for order in levels}
    closed, ledger, stats = (
        [],
        [],
        {"held_without_mirror": 0, "blocked_mirrors": 0, "prints": 0},
    )
    traded = {1: 0.0, -1: 0.0}
    for arrival, at, side, price, amount in trades:
        if arrival < start * SECOND:
            continue
        if arrival > end * SECOND:
            break
        stats["prints"] += 1
        for order in crossed(active.values(), at, side, price, amount):
            del active[order.slot]
            turnover = order.price * order.qty
            cash -= side * turnover + turnover * (FEE + BUFFER)
            base += side * order.qty
            traded[side] += order.qty
            assert min(cash, base) >= -1e-9
            if order.first:
                closed.append(exit_values(order.first, order, arrival))
                ledger.append(
                    {
                        "slot": order.slot,
                        "side": order.first.side,
                        "first_price": order.first.price,
                        "first_qty": order.first.qty,
                        "second_price": order.price,
                        "second_qty": order.qty,
                        "posted_us": order.posted,
                        "close_us": arrival,
                    }
                )
            reverse = mirror(order, delta, TICK, lot, arrival + MIRROR_DELAY_US)
            if reverse.side > 0:
                available = cash - sum(
                    x.qty * x.price * (1 + FEE + BUFFER)
                    for x in active.values()
                    if x.side > 0
                )
                allowed = available >= reverse.price * reverse.qty * (1 + FEE + BUFFER)
            else:
                available = base - sum(x.qty for x in active.values() if x.side < 0)
                allowed = available >= reverse.qty
            if allowed and reverse.qty * reverse.price >= MIN_NOTIONAL:
                active[order.slot] = reverse
            else:
                stats["blocked_mirrors"] += 1
                stats["held_without_mirror"] += int(reverse.first is not None)
    assert stats["prints"] >= 1000
    assert math.isclose(base, START / 2 / center + traded[1] - traded[-1], abs_tol=1e-9)
    assert cash + base * center > 0
    unsettled = stats["held_without_mirror"] + sum(
        x.first is not None for x in active.values()
    )
    return (
        closed,
        unsettled,
        ledger,
        {**stats, "cash": cash, "base": base, "delta": delta},
    )


def run(quote_dir, trade_dir, archive_path, baseline, output):
    old = {r["id"]: r for r in read(baseline)["disposition"]}
    rev = old[6008]["source"].split("/blob/")[1].split("/")[0]
    with ZipFile(archive_path) as archive:
        sources = {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in archive.namelist()
            if name.startswith(f"OctoBot-Tentacles-{rev}/Trading/Mode/")
            and name.endswith(("/grid_trading.py", "/staggered_orders_trading.py"))
        }
    assert len(sources) == 2
    quotes = {
        (x["date"], x["symbol"]): x
        for x in read(quote_dir / "manifest.json")
        if x["exchange"] == "binance"
    }
    results, evidence, receipts = [], {}, {}
    for date in DATES:
        midnight = int(datetime.fromisoformat(date + "T00:00:00+00:00").timestamp())
        start, end = midnight + 300, midnight + 28_500
        for asset, lot in LOTS.items():
            q = quotes[date, asset]
            grid = snapshots(quote_dir / q["file"], q, start, start + 20)
            start = min(
                at
                for at, row in grid.items()
                if at >= midnight + 300 and row is not None
            )
            _, bid, ask, _, _ = grid[start]
            center = (bid + ask) / 2
            fn = f"{date}-binance-trades-{asset}.csv.gz"
            file = trade_dir / fn
            with file.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            evidence[f"{date}/{asset}"] = {
                "quote": q,
                "trade_url": f"https://datasets.tardis.dev/v1/binance/trades/{date.replace('-', '/')}/{asset}.csv.gz",
                "trade_sha256": digest,
            }
            for ident, (name, count, slope) in MODES.items():
                fills, pending, ledger, stats = replay(
                    prints(file, asset), center, start, end, count, slope, lot
                )
                receipts[f"{ident}/{date}/{asset}"] = {
                    "first_utc_second": start,
                    "anchor": center,
                    "cycles": ledger,
                    **stats,
                }
                results.append(
                    {
                        "id": ident,
                        "period": date,
                        "group": f"OctoBot · {name} mirror-price variant",
                        "market": asset,
                        "currency": "USDT",
                        "interval": "Spot quote and trade ticks",
                        "archive_interval": "Binance spot trade capture",
                        "exit": "Filled opposite mirror order",
                        "order_family": "Static inventory ladder",
                        **metrics(fills, pending),
                    }
                )
                print(ident, date, asset, len(fills), pending, flush=True)
    coverage = []
    for ident, (name, count, _) in MODES.items():
        assert not old[ident]["status"].startswith(("Tested", "Excluded"))
        status = f"Tested · OctoBot {name} mirror-price variant"
        if not any(r["trades"] for r in results if r["id"] == ident):
            status += ", no closes"
        reason = (
            f"Source mirror price equals spread less increment. {count} levels per side, "
            "prefunded BTC/ETH spot, captured opposing strict trade-through prints, "
            "and confirmed order quantity. Static bounds, normalized allocation and one-second placement model."
        )
        coverage.append([ident, status, reason])
    write(
        output,
        {
            "coverage": coverage,
            "results": results,
            "source": sources,
            "inputs": evidence,
            "receipts": receipts,
            "settings": {
                "fee": FEE,
                "extra_cost": BUFFER,
                "cash": START,
                "spread": SPREAD,
                "increment": INCREMENT,
                "allocation": ALLOCATED,
                "mode": MODES,
            },
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("quote_dir", "trade_dir", "archive_path", "baseline", "output"):
        parser.add_argument(name, type=Path)
    run(**vars(parser.parse_args()))
