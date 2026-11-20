"""Top-of-book replay of the documented spot/perpetual spread thresholds."""

import argparse
import csv
import gzip
import hashlib
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.nonpine_round4_metrics import metrics

IDENT = 5998
DATES = ("2026-10-01", "2026-11-01")
SIZES = {"BTCUSDT": 0.01, "ETHUSDT": 0.3}
SPOT_FEE, PERP_FEE = 0.001, 0.0005
OPEN, CLOSE = 0.01, 0.001
BUFFER = 0.0005
MIN_PAIRED_SAMPLES = 1_000
SECOND = 1_000_000


def snapshots(path, item, start, end):
    """Return causal second-boundary quotes on the collector timestamp."""
    with path.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == item["sha256"]
    grid = {}
    previous = -1
    with gzip.open(path, "rt", encoding="ascii", newline="") as stream:
        for row in csv.DictReader(stream):
            at = int(row["local_timestamp"])
            assert at >= previous
            previous = at
            if at > end * SECOND:
                break
            if at < (start - 2) * SECOND:
                continue
            assert (
                row["exchange"] == item["exchange"] and row["symbol"] == item["symbol"]
            )
            key = (at + SECOND - 1) // SECOND
            bid, ask, bq, aq = map(
                float,
                (
                    row["bid_price"],
                    row["ask_price"],
                    row["bid_amount"],
                    row["ask_amount"],
                ),
            )
            if 0 < bid <= ask and min(bq, aq) > 0:
                grid[key] = at, bid, ask, bq, aq
            else:
                grid[key] = None
    return grid


def quotes(spot, future, side, qty):
    """Return the spot and perpetual executable prices for one proposal."""
    _, sb, sa, sbq, saq = spot
    _, pb, pa, pbq, paq = future
    if side > 0:
        return (sa, pb) if min(saq, pbq) >= qty else None
    return (sb, pa) if min(sbq, paq) >= qty else None


def spread(pair, side):
    spot, future = pair
    buy, sell = (spot, future) if side > 0 else (future, spot)
    return (sell - buy) / buy


def sample(spot_updates, perp_updates, start, end, qty):
    spot = perp = current = None
    cooldown = 0
    paired, rows, entries = 0, [], []
    for at in range(start - 2, end + 1):
        spot = spot_updates.get(at, spot)
        perp = perp_updates.get(at, perp)
        if at < start or spot is None or perp is None:
            continue
        times = spot[0], perp[0]
        if at * SECOND - min(times) > 2 * SECOND or abs(times[0] - times[1]) > 500_000:
            continue
        paired += 1
        if current:
            entry_side, entry_at, opening = current
            closing = quotes(spot, perp, -entry_side, qty)
            if closing and spread(closing, -entry_side) >= CLOSE:
                gross = (
                    entry_side
                    * qty
                    * ((closing[0] - opening[0]) - (closing[1] - opening[1]))
                )
                fees = qty * (
                    SPOT_FEE * (closing[0] + opening[0])
                    + PERP_FEE * (closing[1] + opening[1])
                )
                rows.append(
                    (at, gross, fees, qty * BUFFER * (sum(opening) + sum(closing)))
                )
                entries.append(
                    {
                        "entry_utc_second": entry_at,
                        "close_utc_second": at,
                        "side": entry_side,
                        "opening": opening,
                        "closing": closing,
                    }
                )
                current, cooldown = None, at + 120
        elif at >= cooldown:
            for side in (1, -1):
                opening = quotes(spot, perp, side, qty)
                if opening and spread(opening, side) >= OPEN:
                    current = side, at, opening
                    break
    return rows, int(current is not None), paired, entries


def run(work, project_source, baseline, report):
    with ZipFile(project_source) as archive:
        names = [
            p
            for p in archive.namelist()
            if "/hummingbot/strategy/spot_perpetual_arbitrage/" in p
        ]
        evidence = {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in names
            if name.endswith(".py")
        }
        assert any(name.endswith("/arb_proposal.py") for name in evidence)
    catalogue = {r["id"]: r for r in read(baseline)["disposition"]}
    item = catalogue[IDENT]
    assert not item["status"].startswith("Tested")
    files = read(work / "manifest.json")
    index = {(x["date"], x["exchange"], x["symbol"]): x for x in files}
    assert len(index) == len(files) == 8
    rows, receipts = [], {}
    for date in DATES:
        midnight = int(datetime.fromisoformat(date + "T00:00:00+00:00").timestamp())
        start, end = midnight + 300, midnight + 28_500
        parts = []
        for market, qty in SIZES.items():
            captures = [
                index[date, connector, market]
                for connector in ("binance", "binance-futures")
            ]
            spot, perpetual = [
                snapshots(work / source["file"], source, start, end)
                for source in captures
            ]
            closed, unsettled, synced, cycles = sample(spot, perpetual, start, end, qty)
            assert synced >= MIN_PAIRED_SAMPLES, (date, market, synced)
            receipts[f"{date}/{market}"] = {
                "quantity": qty,
                "aligned_samples": synced,
                "cycles": cycles,
            }
            parts.append((market, closed, unsettled))
        parts.append(
            ("BTC + ETH", parts[0][1] + parts[1][1], parts[0][2] + parts[1][2])
        )
        for market, closed, unsettled in parts:
            rows.append(
                {
                    "id": IDENT,
                    "name": item["name"],
                    "source": item["source"],
                    "group": "Hummingbot · quote variant",
                    "period": date,
                    "market": market,
                    "quote_currency": "USDT",
                    "interval": "1s sample",
                    "archive_interval": "Top-of-book quotes",
                    "exit": "Reverse spread at least 0.1%",
                    **metrics(closed, unsettled),
                }
            )
    suffix = "" if any(r["trades"] for r in rows) else ", no closes"
    write(
        report,
        {
            "captures": files,
            "pinned_strategy_sources": evidence,
            "receipts": receipts,
            "settings": {
                "opening": OPEN,
                "closing": CLOSE,
                "interval_utc": ["00:05", "07:55"],
                "spot_fee": SPOT_FEE,
                "perp_fee": PERP_FEE,
                "execution_charge": BUFFER,
                "standalone_funding": "Excluded in modeled window",
            },
            "coverage": [
                [
                    IDENT,
                    "Tested · Hummingbot quote variant" + suffix,
                    "One-second, synchronized Binance spot/perp quotes. 1% opening and 0.1% reversal thresholds, level-one capacity, modeled simultaneous fills.",
                ]
            ],
            "results": rows,
        },
    )
    print(
        f"Verified {sum(x['aligned_samples'] for x in receipts.values())} synchronized spot/perp quotes"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("work", "project_source", "baseline", "report"):
        parser.add_argument(arg, type=Path)
    run(**vars(parser.parse_args()))
