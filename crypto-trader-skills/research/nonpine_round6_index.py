"""Historical OctoBot two-asset index variant with sell-first rebalancing."""

import argparse
import csv
import hashlib
import math
from datetime import UTC, datetime
from io import TextIOWrapper
from pathlib import Path
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.nonpine_round4_metrics import metrics

IDENT = 6009
DAY = 86_400
FEE, BUFFER = 0.001, 0.0003
START = 10_000
LOTS = {"BTCUSDT": 0.00001, "ETHUSDT": 0.0001}
CUTOFF = 0.05
WINDOWS = (
    ("2025 Sep–Dec", ("2025-09", "2025-10", "2025-11", "2025-12")),
    ("2026 Aug–Oct", ("2026-08", "2026-09", "2026-10")),
)


def replay(sessions):
    cash = START
    basket = []
    closed, receipts = [], []
    for at, row in sorted(sessions.items()):
        mark = row["signal"]
        if basket:
            assert mark is not None
            exposures = [qty * p for (_, qty), p in zip(basket, mark, strict=True)]
            total = cash + sum(exposures)
            if (
                all(abs(x / total - 0.5) <= CUTOFF for x in exposures)
                and cash / total <= 0.10
            ):
                continue
            for (entry, qty), sell in zip(basket, row["sell"], strict=True):
                turnover = qty * (entry + sell)
                closed.append(
                    (at, qty * (sell - entry), turnover * FEE, turnover * BUFFER)
                )
                cash += qty * sell * (1 - FEE - BUFFER)
        receipt = {
            "at": at,
            "rebalanced": bool(basket),
            "sells": row["sell"] if basket else None,
            "buys": row["buy"],
            "pre_purchase_cash": cash,
        }
        pair_budget = cash / 2
        basket = []
        for buy, lot in zip(row["buy"], LOTS.values(), strict=True):
            qty = math.floor(pair_budget / (buy * (1 + FEE + BUFFER)) / lot) * lot
            assert qty * buy >= 5
            cash -= qty * buy * (1 + FEE + BUFFER)
            basket.append((buy, qty))
        assert cash >= -1e-9
        receipt.update(positions=basket, cash=cash)
        receipts.append(receipt)
    return closed, len(basket), receipts


def features(files):
    output = {}
    for file in files:
        with ZipFile(file) as archive:
            [member] = archive.namelist()
            with archive.open(member) as raw:
                for row in csv.reader(TextIOWrapper(raw, encoding="ascii")):
                    at = int(row[0])
                    mult = 1_000_000 if at >= 10**15 else 1_000
                    assert (int(row[6]) + 1) == at + 60 * mult
                    at //= mult
                    if at % DAY in (0, 60, DAY - 60):
                        assert at not in output and float(row[5]) > 0
                        output[at] = (float(row[1]), float(row[4]))
    return output


def run(binance, supplemental, archive_path, baseline, output):
    [item] = [r for r in read(baseline)["disposition"] if r["id"] == IDENT]
    assert item["status"] == "Framework inputs needed"
    ref, rel = item["source"].split("/blob/")[1].split("/", 1)
    folder = f"OctoBot-Tentacles-{ref}/{rel.rsplit('/', 1)[0]}"
    with ZipFile(archive_path) as archive:
        files = [f"{folder}/{name}" for name in ("index_trading.py", "metadata.json")]
        sources = {
            name: hashlib.sha256(archive.read(name)).hexdigest() for name in files
        }
    results, audit, ledger = [], {}, {}
    for period, months in WINDOWS:
        pairs = []
        for asset in LOTS:
            files = []
            for month in months:
                name = f"{asset}-1m-{month}.zip"
                path = (
                    supplemental / name
                    if month.startswith("2025")
                    else binance / ("klines-spot-" + name)
                )
                url = f"https://data.binance.vision/data/spot/monthly/klines/{asset}/1m/{name}"
                with path.open("rb") as stream:
                    audit[url] = hashlib.file_digest(stream, "sha256").hexdigest()
                files.append(path)
            pairs.append(features(files))
        a, b = pairs
        assert a.keys() == b.keys()
        start = int(
            datetime.fromisoformat(months[0] + "-01").replace(tzinfo=UTC).timestamp()
        )
        days = [d for d in sorted(a.keys()) if d % DAY == 0]
        assert len(days) >= 90 and days == list(range(start, days[-1] + DAY, DAY))
        sessions = {
            d: {
                "signal": (a[d - 60][1], b[d - 60][1]) if d > start else None,
                "sell": (a[d][0], b[d][0]),
                "buy": (a[d + 60][0], b[d + 60][0]),
            }
            for d in days
        }
        closes, unsettled, receipts = replay(sessions)
        ledger[period] = {"rebalances": receipts, "eligible_days": len(days)}
        results.append(
            {
                "id": IDENT,
                "period": period,
                "group": "OctoBot · Equal-weight index variant",
                "market": "BTC + ETH spot (USDT)",
                "currency": "USDT",
                "interval": "1d check, 1m fills",
                "archive_interval": "Binance spot 1m OHLCV",
                "exit": "Sell whole basket on rebalance",
                **metrics(closes, unsettled),
            }
        )
    reason = (
        "Source's one-day check, 5pp drift threshold and sell-before-buy rebalance. "
        "Configured static 50/50 BTC/ETH Binance spot, prior-minute close trigger, "
        "next-open sequential fills, costs and realized-lot drawdown. Final basket is unsettled."
    )
    write(
        output,
        {
            "coverage": [[IDENT, "Tested · OctoBot index rebalance variant", reason]],
            "results": results,
            "settings": {"fee": FEE, "extra_cost": BUFFER, "cash": START},
            "archive": audit,
            "sources": sources,
            "ledgers": ledger,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binance", "supplemental", "archive_path", "baseline", "output"):
        parser.add_argument(name, type=Path)
    run(**vars(parser.parse_args()))
