"""Run minimum-increment BTC Jelly Rolls on actual historical Deribit quotes."""

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import timedelta
from math import isfinite
from pathlib import Path
from statistics import median

from .nonpine_round4_metrics import metrics

SIZE = 0.1
OPTION_FEE_BTC = 0.0003
FEE_PREMIUM_CAP = 0.125
SIGNS = (1, -1, -1, 1)
DAY = timedelta(days=1)


def roundtrip(opening, closing, btc_reference):
    assert len(opening) == len(closing) == 4 and btc_reference > 0
    gross = fees = spread = 0.0
    for (bid_open, ask_open), (bid_close, ask_close), side in zip(
        opening, closing, SIGNS, strict=True
    ):
        assert 0 < bid_open <= ask_open and 0 < bid_close <= ask_close
        mid_open = (bid_open + ask_open) / 2
        mid_close = (bid_close + ask_close) / 2
        actual_open = ask_open if side > 0 else bid_open
        actual_close = bid_close if side > 0 else ask_close
        gross += side * (mid_close - mid_open)
        spread += (ask_open - bid_open + ask_close - bid_close) / 2
        fees += sum(
            min(OPTION_FEE_BTC, FEE_PREMIUM_CAP * premium)
            for premium in (actual_open, actual_close)
        )
    dollars = btc_reference * SIZE
    converted = (gross * dollars, fees * dollars, spread * dollars)
    return converted


def quote_book(snapshot):
    books = {}
    for row in snapshot:
        at, symbol, bid, ask, reference, expiry = (
            row[f]
            for f in (
                "snapshot_time",
                "instrument_name",
                "bid_price",
                "ask_price",
                "underlying_price",
                "expiry_date",
            )
        )
        if not (
            expiry > at
            and bid is not None
            and ask is not None
            and reference is not None
            and all(isfinite(x) and x > 0 for x in (bid, ask, reference))
            and bid <= ask
        ):
            continue
        asset, _, strike, kind = symbol.split("-")
        assert asset == "BTC" and kind in {"P", "C"}
        key = (expiry, float(strike), kind)
        assert key not in books
        books[key] = (symbol, (bid, ask), reference)
    return books


def choose_legs(at, book):
    strikes = defaultdict(set)
    for expiry, strike, kind in book:
        strikes[expiry, kind].add(strike)
    expiries = sorted({expiry for expiry, _ in strikes})
    selected = None
    for near in expiries:
        if not (3 * DAY <= near - at <= 9 * DAY):
            continue
        for far in expiries:
            if not (18 * DAY <= far - near <= 50 * DAY):
                continue
            common = set.intersection(
                *(strikes[e, f] for e in (near, far) for f in ("P", "C"))
            )
            if not common:
                continue
            reference = median(book[near, strike, "C"][2] for strike in common)
            strike = min(common, key=lambda n: (abs(n - reference), n))
            if not 0.95 <= strike / reference <= 1.05:
                continue
            legs = tuple(
                (exp, strike, kind) for exp in (far, near) for kind in ("C", "P")
            )
            selected = (legs, reference)
            break
        if selected is not None:
            break
    return selected


def load_observations(source):
    from pyarrow import compute as pc
    from pyarrow import parquet

    fields = [
        "snapshot_time",
        "instrument_name",
        "bid_price",
        "ask_price",
        "underlying_price",
        "expiry_date",
    ]
    file = parquet.ParquetFile(source)
    points = defaultdict(list)
    for batch in file.iter_batches(columns=fields, batch_size=180_000):
        stamp = batch.column("snapshot_time")
        mask = pc.and_(pc.equal(pc.hour(stamp), 12), pc.less(pc.day_of_week(stamp), 2))
        for record in batch.filter(mask).to_pylist():
            points[record["snapshot_time"]].append(record)
    return points, file.metadata.num_rows


def replay(source):
    points, count = load_observations(source)
    first_in_hour = {}
    for at, rows in sorted(points.items()):
        if 0 <= at.minute <= 4:
            first_in_hour.setdefault(at.date(), (at, rows))
    inputs, misses, unsettled = [], 0, 0
    for day, (at, rows) in sorted(first_in_hour.items()):
        if day.weekday() != 0:
            continue
        opening = quote_book(rows)
        result = choose_legs(at, opening)
        if result is None:
            misses += 1
            continue
        legs, reference = result
        exit_point = first_in_hour.get(day + DAY)
        if exit_point is None:
            unsettled += 1
            continue
        exit_at, close_rows = exit_point
        closing = quote_book(close_rows)
        if any(leg not in closing for leg in legs):
            unsettled += 1
            continue
        assert exit_at > at and all(
            opening[leg][0] == closing[leg][0] and leg[0] > exit_at for leg in legs
        )
        mids_open = [opening[leg][1] for leg in legs]
        mids_close = [closing[leg][1] for leg in legs]
        pnl = roundtrip(mids_open, mids_close, reference)
        inputs.append(
            {
                "entry_utc": at.isoformat() + "Z",
                "exit_utc": exit_at.isoformat() + "Z",
                "leg_names": [opening[leg][0] for leg in legs],
                "strike": legs[0][1],
                "entry_btc_reference_usd": reference,
                "entry_spread_sum_btc": sum(a - b for b, a in mids_open),
                "exit_spread_sum_btc": sum(a - b for b, a in mids_close),
                "pnl": pnl,
            }
        )
    assert 0 < len(inputs) <= 30
    with source.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    row = {
        "id": 6085,
        "group": "Deribit · minimum-size quoted Jelly Roll",
        "market": "BTC inverse options (USD)",
        "period": "2024 Jan–Jul archived quotes",
        "exit": "Next Tuesday 12:00 UTC on opposite best quotes",
        "currency": "USD",
        "archive_interval": "Hourly observed best bids and asks",
        "interval": "1h snapshots with weekly decisions",
        "order_family": "Four-leg minimum-increment quote replay",
        **metrics([(row["exit_utc"], *row["pnl"]) for row in inputs], unsettled),
    }
    return {
        "coverage": [
            [
                6085,
                "Tested · Deribit minimum-size quoted Jelly Roll",
                (
                    f"{len(inputs)} size-eligible BTC inverse Jelly Roll observations modeled from "
                    "synchronized observed positive best quotes. Exchange rules set the 0.1 BTC "
                    "minimum quantity increment. Uses opposite-side exits and capped taker fees per leg. "
                    "Individual best-quote marks model execution and omit atomic fill certainty."
                ),
            ],
        ],
        "results": [row],
        "observations": inputs,
        "source": {
            "sample_rows": count,
            "snapshot_hours_inspected": len(points),
            "missed_openings": misses,
            "sha256": sha,
            "description": "https://insights.deribit.com/education/option-backtest-selling-weekend-vol/",
            "file": "https://drive.google.com/file/d/1g9p2Kq8op40y4ZFQQ9AJw8a9CaDThOY8/view",
            "structure": "https://support.deribit.com/hc/en-us/articles/31424954956061-Combo-Books",
            "quantity_increment": "https://support.deribit.com/hc/en-us/articles/25944814912925-22-October-2021",
            "fee_schedule": "https://support.deribit.com/hc/en-us/articles/25944746248989-Fees",
        },
        "settings": {
            "quantity_per_leg_btc": SIZE,
            "gross_quote_convention": "Change in entry-to-exit midquotes",
            "execution_charge": "Sum of all eight half-spreads",
            "per_leg_option_fee_btc": OPTION_FEE_BTC,
            "option_fee_cap_fraction": FEE_PREMIUM_CAP,
            "usd_reference": "Entry near-expiry underlying reference held fixed for all BTC P&L valuation",
            "opening": "Monday 12:00 UTC first capture through 12:04",
            "closure": "Tuesday 12:00 UTC first capture through 12:04",
            "leg_selection": "First near expiry 3–9 days away and far expiry 18–50 days beyond near, shared strike closest to observed near reference within 5%",
            "limitations": "No observed atomic combo fill, order-book depth beyond one increment, latency or margin simulation.",
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    results = replay(args.sample)
    args.output.write_text(
        json.dumps(results, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        + "\n",
        encoding="utf8",
        newline="\n",
    )
    row = results["results"][0]
    print(row["id"], row["trades"], row["gross"], row["net"])


if __name__ == "__main__":
    main()
