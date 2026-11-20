"""Replay unmatched atomic option combo buys through published option expiry."""

import argparse
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from research.delta_pinets_catalogue import read, write
from research.nonpine_round2_deribit import STRUCTURES, UNIT, epoch, sign, valid
from research.nonpine_round4_metrics import metrics

WINDOWS = {
    "2025 Jul–Dec": ("2025-07-01", "2026-01-01"),
    "2026 Jan–Nov": ("2026-01-01", "2026-11-04"),
}
CUTOFF = "2026-11-20"
FIRST = "2025-07-01"
EARLIER = {
    "2024 Jul–Dec": ("2024-07-01", "2025-01-01"),
    "2025 Jan–Jun": ("2025-01-01", "2025-07-01"),
}
API = "https://www.deribit.com/api/v2/public/get_delivery_prices"
MONTHS = {
    word: n + 1
    for n, word in enumerate(
        [
            "JAN",
            "FEB",
            "MAR",
            "APR",
            "MAY",
            "JUN",
            "JUL",
            "AUG",
            "SEP",
            "OCT",
            "NOV",
            "DEC",
        ]
    )
}


def contract(name):
    match = re.fullmatch(
        r"(BTC|ETH)-(\d{1,2})([A-Z]{3})(\d{2})-(\d+(?:\.\d+)?)-([CP])", name
    )
    if not match or match[3] not in MONTHS:
        raise ValueError("Unsupported inverse option leg")
    expiry = datetime(
        2000 + int(match[4]), MONTHS[match[3]], int(match[2]), 8, tzinfo=UTC
    )
    return match[1], expiry, float(match[5]), match[6]


def settle_leg(direction, qty, premium, entry_index, delivery, strike, kind):
    intrinsic = max(0.0, delivery - strike if kind == "C" else strike - delivery)
    open_value = qty * entry_index * premium
    taker = qty * entry_index * min(0.0003, 0.125 * premium)
    settlement = qty * min(0.00015 * delivery, 0.125 * intrinsic)
    return (
        direction * (qty * intrinsic - open_value),
        taker + settlement,
        open_value * 0.0003,
    )


def deliveries(location, first=FIRST):
    location.mkdir(parents=True, exist_ok=True)
    evidence, prices = [], {}
    for coin in UNIT:
        expected, offset = None, 0
        while expected is None or offset < expected:
            query = urlencode(
                {
                    "index_name": coin.lower() + "_usd",
                    "count": 100,
                    "offset": offset,
                    "start_timestamp": int(
                        datetime.fromisoformat(first).replace(tzinfo=UTC).timestamp()
                        * 1000
                    ),
                    "end_timestamp": int(
                        datetime.fromisoformat(CUTOFF).replace(tzinfo=UTC).timestamp()
                        * 1000
                    ),
                }
            )
            url = f"{API}?{query}"
            path = location / f"{coin}-delivery-{offset}.json"
            if not path.exists():
                with urlopen(url, timeout=25) as response:
                    raw = response.read()
                assert json.loads(raw)["result"]["data"]
                path.write_bytes(raw)
            raw = path.read_bytes()
            result = json.loads(raw)["result"]
            if expected is None:
                expected = result["records_total"]
            assert result["records_total"] == expected
            rows = result["data"]
            assert rows and len(rows) <= 100 and offset + len(rows) <= expected
            for row in rows:
                at, price = row["date"], row["delivery_price"]
                assert first <= at <= CUTOFF and math.isfinite(price) and price > 0
                assert (coin, at) not in prices
                prices[coin, at] = price
            evidence.append(
                {
                    "file": path.name,
                    "url": url,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "rows": len(rows),
                }
            )
            offset += len(rows)
    return prices, evidence


def entries(archives, codes):
    records, evidence, seen = defaultdict(list), [], set()
    for directory in archives:
        manifest = directory / "manifest.json"
        count = 0
        for page in read(manifest):
            if "-option_combo-" not in page["file"]:
                continue
            raw = (directory / page["file"]).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == page["sha256"]
            batch = json.loads(raw)
            assert not batch["has_more"] and len(batch["trades"]) == page["trades"]
            for row in batch["trades"]:
                coin, code, *_ = row["instrument_name"].split("-")
                if code not in codes:
                    continue
                assert (coin, row["trade_id"]) not in seen
                seen.add((coin, row["trade_id"]))
                records[coin, code].append(row)
                count += 1
        evidence.append(
            {
                "archive": directory.name,
                "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                "target_prints": count,
            }
        )
    return records, evidence


def position(row, coin, prices):
    amounts, details = [0.0] * 3, []
    for leg in row["legs"]:
        underlying, expiry, strike, kind = contract(leg["instrument_name"])
        at = int(expiry.timestamp() * 1000)
        date = expiry.date().isoformat()
        delivery = prices.get((coin, date))
        if underlying != coin or at <= row["timestamp"]:
            raise ValueError("Expected a same-asset option expiring after entry")
        if date >= CUTOFF or delivery is None:
            return None, []
        qty = leg["amount"] / row["amount"] * UNIT[coin]
        figures = settle_leg(
            sign(leg["direction"]),
            qty,
            leg["price"],
            row["index_price"],
            delivery,
            strike,
            kind,
        )
        for i, amount in enumerate(figures):
            amounts[i] += amount
        details.append(
            {
                "instrument": leg["instrument_name"],
                "expiry_ms": at,
                "delivery": delivery,
                "quantity": qty,
                "side": leg["direction"],
                "premium": leg["price"],
            }
        )
    return (max(leg["expiry_ms"] for leg in details), *amounts), details


def sample(prints, coin, dates, prices, side="buy"):
    start, stop = map(epoch, dates)
    ordered = sorted(
        (row for row in prints if start <= row["timestamp"] < stop),
        key=lambda r: (r["timestamp"], int(r["trade_id"].rsplit("-", 1)[-1])),
    )
    opened, pnl, receipts = set(), [], []
    eligible = 0
    for row in ordered:
        if row["direction"] != side or not valid(row, UNIT[coin], False):
            continue
        eligible += 1
        name = row["instrument_name"]
        if name in opened:
            continue
        try:
            closed, legs = position(row, coin, prices)
        except ValueError:
            continue
        opened.add(name)
        if closed is not None:
            pnl.append(closed)
            receipts.append(
                {
                    "trade_id": row["trade_id"],
                    "combo": name,
                    "entry_ms": row["timestamp"],
                    "entry_index": row["index_price"],
                    "legs": legs,
                }
            )
    return (
        pnl,
        len(opened) - len(pnl),
        {
            "observed": len(ordered),
            "eligible_entries": eligible,
            "closed": len(pnl),
            "entries": receipts,
        },
    )


def run(location, baseline, output, archives, older_after=None, side="buy"):
    targets = {
        row["id"]: row
        for row in read(baseline)["disposition"]
        if row["status"] == "Deribit earlier archive · no matched round trip"
    }
    if older_after:
        for ident in {row["id"] for row in read(older_after)["results"]}:
            targets.pop(ident)
    windows = EARLIER if older_after else WINDOWS
    first = next(iter(windows.values()))[0]
    codes = {ident: STRUCTURES[ident - 6054] for ident in targets}
    book, inputs = entries(archives, set(codes.values()))
    prices, delivery = deliveries(location, first)
    results, coverage, receipts = [], [], {}
    for ident, code in codes.items():
        rows, detail = [], {}
        for label, dates in windows.items():
            runs = {
                coin: sample(book[coin, code], coin, dates, prices, side)
                for coin in UNIT
            }
            detail[label] = {coin: trial[2] for coin, trial in runs.items()}
            series = [(coin, trade[0], trade[1]) for coin, trade in runs.items()]
            series.append(
                (
                    "BTC + ETH",
                    runs["BTC"][0] + runs["ETH"][0],
                    runs["BTC"][1] + runs["ETH"][1],
                )
            )
            for market, closed, unsettled in series:
                rows.append(
                    {
                        "id": ident,
                        "name": targets[ident]["name"],
                        "source": targets[ident]["source"],
                        "period": label,
                        "group": f"Deribit · observed {side} to expiry",
                        "market": market,
                        "quote_currency": "USD",
                        "archive_interval": "Trade prints and deliveries",
                        "interval": "Event",
                        "exit": "Published option expiry",
                        **metrics(closed, unsettled),
                    }
                )
        receipts[ident] = detail
        if not any(row["trades"] for row in rows):
            count = sum(
                x["observed"] for period in detail.values() for x in period.values()
            )
            coverage.append(
                [
                    ident,
                    "Deribit expiry model pending",
                    f"{code}: {count} archived prints. No qualifying {side} with verified delivery.",
                ]
            )
            continue
        results.extend(rows)
        coverage.append(
            [
                ident,
                "Tested · Deribit hold-to-expiry variant",
                f"First size-eligible combo {side} per instrument window, held through published expiry.",
            ]
        )
    write(
        output,
        {
            "windows": windows,
            "cutoff": CUTOFF,
            "position_side": side,
            "trade_archives": inputs,
            "delivery_archives": delivery,
            "receipts": receipts,
            "coverage": coverage,
            "results": results,
        },
    )
    print(
        f"Expiry model measured {len(results) // 6}/{len(targets)} pending IDs",
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("location", "baseline", "output"):
        parser.add_argument(name, type=Path)
    parser.add_argument("archives", nargs="+", type=Path)
    parser.add_argument("--older-after", type=Path)
    parser.add_argument("--side", choices=("buy", "sell"), default="buy")
    run(**vars(parser.parse_args()))
