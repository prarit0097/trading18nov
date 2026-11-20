"""BTC up/down snapshot replay with a causal Binance price signal."""

import argparse
import csv
import hashlib
import itertools
import json
import math
from bisect import bisect_right
from datetime import datetime
from pathlib import Path

import pyarrow.parquet as pq

from research.delta_pinets_catalogue import read, write
from research.nonpine_round4_metrics import metrics

IDENT = 6177
SERIES = "btc-up-or-down-15m"
QTY = 10
MODELED_FEE = 0.07


def ms(timestamp):
    return int(datetime.fromisoformat(timestamp).timestamp() * 1000)


def entry_book(book, up):
    top = {}
    for side in ("bids", "asks"):
        levels = json.loads(book[side])
        if not levels:
            return None
        top[side] = float(levels[0]["price"]), float(levels[0]["size"])
    bid, ask = top["bids"][0], top["asks"][0]
    if not 0 < bid <= ask < 1:
        return None
    # The archive's book is the first outcome (Up). The Down ask is the
    # complementary price and available size of the Up bid.
    price, size = top["asks"] if up else (1 - bid, top["bids"][1])
    return price if size >= QTY else None


def receipt(row, book, reference_times, reference_prices):
    opened, expiry, resolved = (
        ms(row[k]) for k in ("open_time", "close_time", "resolved_at")
    )
    assert row["outcomes"] == "Up|Down" and row["winning_outcome"] in ("Up", "Down")
    assert expiry - opened == 900_000 and resolved >= expiry
    anchor = bisect_right(reference_times, opened) - 1
    if anchor < 0 or opened - reference_times[anchor] > 5_000:
        return None
    for snapshot in book:
        at = snapshot["t"]
        if not opened + 60_000 <= at <= opened + 120_000:
            continue
        if snapshot["event_type"] != "snapshot" or snapshot["is_reseed"]:
            continue
        idx = bisect_right(reference_times, at) - 1
        if idx <= anchor or at - reference_times[idx] > 5_000:
            continue
        direction = reference_prices[idx] - reference_prices[anchor]
        if not direction:
            continue
        outcome = "Up" if direction > 0 else "Down"
        price = entry_book(snapshot, outcome == "Up")
        if price is None:
            continue
        gross = QTY * (int(outcome == row["winning_outcome"]) - price)
        fee = QTY * MODELED_FEE * price * (1 - price)
        return {
            "condition_id": row["condition_id"],
            "market_id": row["market_id"],
            "opened_ms": opened,
            "entry_ms": at,
            "exit_ms": resolved,
            "anchor_ms": reference_times[anchor],
            "signal_ms": reference_times[idx],
            "anchor": reference_prices[anchor],
            "signal": reference_prices[idx],
            "bought": outcome,
            "winner": row["winning_outcome"],
            "shares": QTY,
            "price": price,
            "gross": gross,
            "fees": fee,
        }
    return None


def pinned_file(work, name, url):
    path = work / name
    with path.open("rb") as stream:
        grabbed = {
            "file": name,
            "url": url,
            "sha256": hashlib.file_digest(stream, "sha256").hexdigest(),
        }
    return path, grabbed


def run(work, baseline, output):
    config = read(work / "source.json")
    start = config["base"]
    items = {row["id"]: row for row in read(baseline)["disposition"]}
    item = items[IDENT]
    assert not item["status"].startswith("Tested")
    metadata, meta = pinned_file(work, "markets.csv", f"{start}/markets.csv")
    ref, manifest = pinned_file(
        work, "reference-BTC.parquet", f"{start}/reference-BTC.parquet"
    )
    data = pq.read_table(ref, columns=["timestamp", "price"])
    times = data["timestamp"].to_pylist()
    prices = [float(x) for x in data["price"].to_pylist()]
    assert all(a <= b for a, b in itertools.pairwise(times))
    assert all(math.isfinite(p) and p > 0 for p in prices)
    evidence, trades, skipped = [meta, manifest], [], []
    with metadata.open(encoding="utf-8") as stream:
        markets = [row for row in csv.DictReader(stream) if row["series"] == SERIES]
    assert len({row["condition_id"] for row in markets}) == len(markets) == 96
    for row in sorted(markets, key=lambda r: r["open_time"]):
        file, recorded = pinned_file(work, row["file"], f"{start}/{row['file']}")
        evidence.append(recorded)
        book = pq.read_table(
            file, columns=["event_type", "t", "is_reseed", "bids", "asks"]
        ).to_pylist()
        assert all(x["t"] <= y["t"] for x, y in itertools.pairwise(book))
        if trial := receipt(row, book, times, prices):
            trades.append(trial)
        else:
            skipped.append(row["condition_id"])
    assert len(trades) + len(skipped) == len(markets) and trades
    periods = (
        ("15 Jun 2026 AM UTC", lambda t: t < ms("2026-06-15T12:00:00Z")),
        ("15 Jun 2026 PM UTC", lambda t: t >= ms("2026-06-15T12:00:00Z")),
    )
    rows = [
        {
            "id": IDENT,
            "name": item["name"],
            "source": item["source"],
            "period": label,
            "group": "Polymarket · BTC snapshot variant",
            "market": "BTC Up/Down",
            "quote_currency": "USDC",
            "archive_interval": "15m contracts",
            "interval": "Event",
            "exit": "Published market resolution",
            **metrics(
                [
                    (r["exit_ms"], r["gross"], r["fees"], 0.0)
                    for r in trades
                    if accept(r["opened_ms"])
                ]
            ),
        }
        for label, accept in periods
    ]
    coverage = [
        [
            IDENT,
            "Tested · BTC event snapshot variant",
            f"{len(trades)} modeled 10-share entries at archived best quotes. Binance 1–2 minute signal, public archived resolution and modeled taker fees.",
        ],
        [
            6178,
            "Protocol history and rules needed",
            "The available BTC archive uses a normalized Up book. A split/merge replay still needs observed executable two-sided prices and complete-set transaction costs.",
        ],
        [
            6179,
            "Protocol history and rules needed",
            "The captured BTC markets have two outcomes. Mutually exclusive conversion needs a crypto multi-outcome negative-risk market, synchronized quotes and conversion fees.",
        ],
    ]
    write(
        output,
        {
            "source": config,
            "attribution": "Marketlens, https://marketlens.trade (CC BY 4.0)",
            "fee_model": {
                "rate": MODELED_FEE,
                "formula": "shares * rate * price * (1 - price)",
            },
            "inputs": evidence,
            "entries": trades,
            "skipped_without_causal_fill": skipped,
            "coverage": coverage,
            "results": rows,
        },
    )
    print(f"{len(trades)} modeled BTC settlements across 96 markets")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("work", "baseline", "output"):
        parser.add_argument(arg, type=Path)
    run(**vars(parser.parse_args()))
