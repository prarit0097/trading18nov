"""Verify OctoBot cross-venue arbitrage entry conditions on real spot trades."""

import argparse
import csv
import gzip
import hashlib
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.nonpine_round4_basis import SECOND
from research.nonpine_round4_metrics import metrics
from research.nonpine_round6_arbitrage import DATES, SIZE

IDENT = 6003
THRESHOLD = 0.0025


def prices(file, first, last, exchange, symbol):
    output = {}
    before = 0
    with gzip.open(file, "rt", encoding="ascii", newline="") as stream:
        for row in csv.DictReader(stream):
            arrival = int(row["local_timestamp"])
            assert arrival >= before
            before = arrival
            if arrival > last * SECOND:
                break
            if arrival >= (first - 2) * SECOND:
                assert row["exchange"] == exchange and row["symbol"] == symbol
                value = float(row["price"])
                assert value > 0
                output[(arrival + SECOND - 1) // SECOND] = (arrival, value)
    return output


def screen(tables, first, last):
    current = [None] * len(tables)
    observations = 0
    long_signals = short_signals = 0
    minimum = maximum = 0.0
    for at in range(first - 2, last + 1):
        for i, series in enumerate(tables):
            current[i] = series.get(at, current[i])
        if at < first or any(q is None for q in current):
            continue
        timestamps, marks = zip(*current, strict=True)
        earliest = min(timestamps)
        if (
            at * SECOND - earliest > 2 * SECOND
            or max(timestamps) - earliest > SECOND // 2
        ):
            continue
        own = marks[0]
        other = sum(marks[1:]) / (len(marks) - 1)
        gap = other / own - 1
        minimum, maximum = min(gap, minimum), max(gap, maximum)
        observations += 1
        long_signals += other > own * (1 + THRESHOLD)
        short_signals += other < own * (1 - THRESHOLD)
    assert observations >= 1000
    return {
        "observations": observations,
        "min_delta": minimum,
        "max_delta": maximum,
        "long_signals": long_signals,
        "short_signals": short_signals,
    }


def run(prior_dir, new_dir, archive_path, baseline, output):
    [item] = [r for r in read(baseline)["disposition"] if r["id"] == IDENT]
    assert not item["status"].startswith("Tested")
    rev, rel = item["source"].split("/blob/")[1].split("/", 1)
    folder = f"OctoBot-Tentacles-{rev}/{rel.rsplit('/', 1)[0]}"
    with ZipFile(archive_path) as archive:
        source = {
            n: hashlib.sha256(archive.read(n)).hexdigest()
            for n in archive.namelist()
            if n.startswith(folder + "/") and n.endswith("/arbitrage_trading.py")
        }
    assert len(source) == 1
    other = {
        (x["date"], x["venue"], x["symbol"].replace("-", "")): x
        for x in read(new_dir / "cross-trades-manifest.json")
    }
    results, receipts, evidence = [], {}, {}
    for date in DATES:
        midnight = int(datetime.fromisoformat(date + "T00:00:00+00:00").timestamp())
        first, last = midnight + 300, midnight + 28_500
        for asset in SIZE:
            filename = f"{date}-binance-trades-{asset}.csv.gz"
            file = prior_dir / filename
            with file.open("rb") as stream:
                sha = hashlib.file_digest(stream, "sha256").hexdigest()
            url = f"https://datasets.tardis.dev/v1/binance/trades/{date.replace('-', '/')}/{asset}.csv.gz"
            evidence[url] = sha
            series = [prices(file, first, last, "binance", asset)]
            for venue in ("bybit-spot", "okex"):
                x = other[date, venue, asset]
                file = new_dir / x["file"]
                with file.open("rb") as stream:
                    assert (
                        hashlib.file_digest(stream, "sha256").hexdigest() == x["sha256"]
                    )
                evidence[x["url"]] = x["sha256"]
                series.append(prices(file, first, last, venue, x["symbol"]))
            result = screen(series, first, last)
            # Any emitted entry requires historical limit/OCO order replay.
            assert result["long_signals"] == result["short_signals"] == 0, (
                date,
                asset,
                result,
            )
            receipts[f"{date}/{asset}"] = result
            results.append(
                {
                    "id": IDENT,
                    "period": date,
                    "group": "OctoBot · Spot arb entry replay",
                    "market": asset,
                    "currency": "USDT",
                    "interval": "1s causally sampled prints",
                    "archive_interval": "Binance, Bybit and OKX spot trade ticks",
                    "exit": "Archived limit and OCO gates inactive",
                    **metrics([]),
                }
            )
            print(date, asset, result, flush=True)
    reason = (
        "Archived 0.25% entry rule on synchronized last-trade snapshots. Binance spot assessed "
        "against the contemporaneous average of Bybit and OKX spot prices. No entry reached "
        "the boundary, so the archived limit/OCO lifecycle was never triggered."
    )
    write(
        output,
        {
            "coverage": [[IDENT, "Tested · OctoBot entry replay, no closes", reason]],
            "results": results,
            "source": source,
            "input_hashes": evidence,
            "receipts": receipts,
            "threshold": THRESHOLD,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("prior_dir", "new_dir", "archive_path", "baseline", "output"):
        parser.add_argument(name, type=Path)
    run(**vars(parser.parse_args()))
