"""Run Hummingbot arbitrage thresholds on two synchronized CEX spot books."""

import argparse
import hashlib
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.nonpine_round4_basis import SECOND, snapshots
from research.nonpine_round4_metrics import metrics

IDENT = 5969
DATES = ("2026-10-01", "2026-11-01")
VENUES = ("bybit-spot", "okex")
SIZE = {"BTCUSDT": 0.001, "ETHUSDT": 0.02}
FEE = 0.001
BUFFER = 0.0003
THRESHOLD = 0.01


def legs(buy, sell, at, qty):
    if buy is None or sell is None:
        return None
    if (
        abs(buy[0] - sell[0]) > SECOND // 2
        or at * SECOND - min(buy[0], sell[0]) > SECOND
    ):
        return None
    if min(buy[4], sell[3]) < qty:
        return None
    return buy[2], sell[1]


def replay(first, second, start, end, qty):
    current = [None, None]
    cash = [5000.0, 5000.0]
    base = None
    pending = None
    closed, ledger = [], []
    observations = signals = misses = 0
    for at in range(start - 2, end + 1):
        current[0] = first.get(at, current[0])
        current[1] = second.get(at, current[1])
        if at < start:
            continue
        prices = [legs(current[b], current[1 - b], at, qty) for b in (0, 1)]
        if any(prices):
            observations += 1
            if base is None:
                base = [5000 / ((q[1] + q[2]) / 2) for q in current]

        if pending is not None:
            buy_market, buy_seen, sell_seen = pending
            pair = prices[buy_market]
            sell_market = 1 - buy_market
            if (
                pair is None
                or cash[buy_market] < qty * pair[0] * (1 + FEE)
                or base[sell_market] < qty
            ):
                misses += 1
            else:
                buy_price, sell_price = pair
                cash[buy_market] -= qty * buy_price * (1 + FEE)
                cash[sell_market] += qty * sell_price * (1 - FEE)
                base[buy_market] += qty
                base[sell_market] -= qty
                gross = qty * (sell_price - buy_price)
                turnover = qty * sum(pair)
                closed.append((at, gross, turnover * FEE, turnover * BUFFER))
                ledger.append(
                    [
                        at - 1,
                        at,
                        buy_market,
                        qty,
                        buy_seen,
                        sell_seen,
                        buy_price,
                        sell_price,
                    ]
                )
            pending = None

        if at >= end or base is None:
            continue
        for b, pair in enumerate(prices):
            if not pair:
                continue
            buy, sell = pair
            if (
                (sell - buy - FEE * (buy + sell)) / buy > THRESHOLD
                and cash[b] >= qty * buy * (1 + FEE)
                and base[1 - b] >= qty
            ):
                signals += 1
                pending = b, buy, sell
                break
    assert pending is None and signals == len(closed) + misses
    return closed, observations, signals, misses, ledger


def run(prior_dir, new_dir, archive_path, baseline, output):
    [item] = [r for r in read(baseline)["disposition"] if r["id"] == IDENT]
    assert not item["status"].startswith("Tested")
    ref = item["source"].split("/blob/")[1].split("/")[0]
    sources = (
        "/controllers/generic/arbitrage_controller.py",
        "/arbitrage_executor/arbitrage_executor.py",
    )
    with ZipFile(archive_path) as archive:
        digests = {
            n: hashlib.sha256(archive.read(n)).hexdigest()
            for n in archive.namelist()
            if n.startswith(f"hummingbot-{ref}/") and n.endswith(sources)
        }
    assert len(digests) == len(sources)
    a = {
        (m["date"], m["symbol"]): m
        for m in read(prior_dir / "manifest.json")
        if m["exchange"] == "binance"
    }
    b = {
        (m["date"], m["exchange"], m["symbol"].replace("-", "")): m
        for m in read(new_dir / "manifest.json")
        if m.get("dataset") == "quotes"
    }
    results, receipts, data = [], {}, {}
    for date in DATES:
        midnight = int(datetime.fromisoformat(date + "T00:00:00+00:00").timestamp())
        start, end = midnight + 300, midnight + 28_500
        for asset, qty in SIZE.items():
            source = a[date, asset]
            primary = snapshots(prior_dir / source["file"], source, start, end)
            data[source["url"]] = source["sha256"]
            for other in VENUES:
                challenger = b[date, other, asset]
                extra = snapshots(new_dir / challenger["file"], challenger, start, end)
                data[challenger["url"]] = challenger["sha256"]
                closed, synced, signals, misses, ledger = replay(
                    primary, extra, start, end, qty
                )
                assert synced >= 1000, (date, asset, other, synced)
                receipts[f"{date}/{asset}/{other}"] = {
                    "synchronized_eligible_seconds": synced,
                    "signals": signals,
                    "unexecuted_pairs": misses,
                    "fills": ledger,
                }
                results.append(
                    {
                        "id": IDENT,
                        "period": date,
                        "group": f"Hummingbot · Binance versus {other} CEX variant",
                        "market": asset,
                        "currency": "USDT",
                        "interval": "1s quotes",
                        "archive_interval": "Synchronized two-sided spot books",
                        "exit": "Prefunded paired market fill",
                        **metrics(closed),
                    }
                )
                print(date, asset, other, synced, signals, len(closed), flush=True)
    status = "Tested · Hummingbot CEX spot quote variant"
    if not any(row["trades"] for row in results):
        status += ", no closes"
    reason = (
        "Source controller's strict 1% after-fee threshold, sized cross-venue quotes, "
        "one-second confirmation and prefunded placement. BTC/ETH same-quote CEX variant "
        "replaces the archived SOL CEX/Jupiter pair. No private queue or simulated AMM."
    )
    write(
        output,
        {
            "coverage": [[IDENT, status, reason]],
            "results": results,
            "sources": digests,
            "data_hashes": data,
            "receipts": receipts,
            "settings": {
                "threshold": THRESHOLD,
                "fee_per_side": FEE,
                "execution_per_side": BUFFER,
                "latency_seconds": 1,
            },
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("prior_dir", "new_dir", "archive_path", "baseline", "output"):
        parser.add_argument(name, type=Path)
    run(**vars(parser.parse_args()))
