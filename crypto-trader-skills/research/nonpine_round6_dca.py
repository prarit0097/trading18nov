"""Replay OctoBot's configurable weekly DCA with chained protective exits."""

import argparse
import csv
import hashlib
import math
from io import TextIOWrapper
from pathlib import Path
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.nonpine_round4_metrics import metrics
from research.nonpine_round6_index import BUFFER, FEE, LOTS, START, WINDOWS

IDENT = 6006
WEEK = 7 * 86400
STAKE = 100
DISCOUNT = 0.05
TARGET = 0.05
STOP = 0.10


def candles(files):
    previous = None
    for path in files:
        with ZipFile(path) as archive:
            [member] = archive.namelist()
            with TextIOWrapper(archive.open(member), encoding="ascii") as stream:
                for row in csv.reader(stream):
                    stamp = int(row[0])
                    unit = 1_000_000 if stamp >= 10**15 else 1_000
                    assert (int(row[6]) + 1) == stamp + 60 * unit
                    ts = stamp // unit
                    assert previous is None or ts == previous + 60
                    previous = ts
                    assert float(row[5]) >= 0
                    yield ts, *map(float, row[1:5]), float(row[5]) > 0


def replay(bars, lot):
    cash = START
    deadline = None
    pending = None
    held, closed, receipts = [], [], []
    for row in bars:
        at, op, high, low, close = row[:5]
        if len(row) == 6 and not row[5]:
            continue
        for position in held[:]:
            target = position["entry"] * (1 + TARGET)
            stop = position["entry"] * (1 - STOP)
            if low <= stop:
                price, why = min(op, stop), "stop"
            elif high > target:
                price, why = target, "target"
            else:
                continue
            entry, qty = position["entry"], position["quantity"]
            turnover = qty * (entry + price)
            gross = qty * (price - entry)
            closed.append((at, gross, turnover * FEE, turnover * BUFFER))
            cash += qty * price * (1 - FEE - BUFFER)
            receipts.append(
                {**position, "exit_at": at, "exit": price, "exit_reason": why}
            )
            held.remove(position)
        if pending is not None and low < pending[1]:
            placed, price, qty = pending
            cash -= qty * price * (1 + FEE + BUFFER)
            assert cash >= 0
            held.append(
                {"placed": placed, "entry_at": at, "entry": price, "quantity": qty}
            )
            pending = None
        if deadline is None or at >= deadline:
            # The newly submitted order sees the next bar. Replace only
            # the outstanding entry and retain protection for filled lots.
            limit = math.floor(close * (1 - DISCOUNT) * 100) / 100
            qty = (
                math.floor(min(STAKE, cash) / (limit * (1 + FEE + BUFFER)) / lot) * lot
            )
            pending = (at, limit, qty) if qty * limit >= 5 else None
            deadline = at + WEEK
    return closed, len(held), receipts


def run(binance, supplemental, archive_path, baseline, output):
    [item] = [r for r in read(baseline)["disposition"] if r["id"] == IDENT]
    assert item["status"] == "Framework inputs needed"
    rev, rel = item["source"].split("/blob/")[1].split("/", 1)
    p = f"OctoBot-Tentacles-{rev}/{rel.rsplit('/', 1)[0]}/dca_trading.py"
    with ZipFile(archive_path) as archive:
        source = hashlib.sha256(archive.read(p)).hexdigest()
    results, evidence, ledger = [], {}, {}
    for window, months in WINDOWS:
        for asset, lot in LOTS.items():
            files = []
            for month in months:
                name = f"{asset}-1m-{month}.zip"
                file = (
                    supplemental / name
                    if month.startswith("2025")
                    else binance / ("klines-spot-" + name)
                )
                files.append(file)
                url = f"https://data.binance.vision/data/spot/monthly/klines/{asset}/1m/{name}"
                with file.open("rb") as stream:
                    evidence[url] = hashlib.file_digest(stream, "sha256").hexdigest()
            closed, unsettled, fills = replay(candles(files), lot)
            ledger[f"{window}/{asset}"] = fills
            results.append(
                {
                    "id": IDENT,
                    "period": window,
                    "group": "OctoBot · Weekly protective DCA variant",
                    "market": asset,
                    "currency": "USDT",
                    "interval": "Weekly checks + 1m OHLCV",
                    "archive_interval": "Binance spot minute candles",
                    "exit": "5% target or 10% stop",
                    **metrics(closed, unsettled),
                }
            )
    assert any(x["trades"] for x in results)
    reason = (
        "Historical model of archived weekly time trigger and 5% entry offset. "
        "Enabled exposed 5% target and 10% stop settings. BTC/ETH spot, "
        "next-minute eligibility, conservative crossed prices and stop priority."
    )
    write(
        output,
        {
            "coverage": [[IDENT, "Tested · OctoBot weekly DCA variant", reason]],
            "results": results,
            "candles": evidence,
            "source": {p: source},
            "ledger": ledger,
            "settings": {
                "fee": FEE,
                "execution": BUFFER,
                "starting_cash": START,
                "stake": STAKE,
                "discount": DISCOUNT,
                "target": TARGET,
                "stop": STOP,
            },
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binance", "supplemental", "archive_path", "baseline", "output"):
        parser.add_argument(name, type=Path)
    run(**vars(parser.parse_args()))
