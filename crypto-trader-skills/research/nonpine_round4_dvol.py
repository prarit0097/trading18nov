"""Causal observed-print basis entries in cash-settled BTC DVOL futures."""

import argparse
import hashlib
import itertools
import math
from datetime import UTC, datetime
from pathlib import Path

from research.delta_pinets_catalogue import read, write
from research.nonpine_round4_metrics import metrics

ENTRY_DELTA = 1.0
QTY = 0.1
DAY = 86_400_000
FEE = 0.0005


def observe(rows, expiry):
    """Require a later, size-eligible print for an already established signal."""
    signal = None
    for row in rows:
        if row["timestamp"] + DAY > expiry:
            break
        price, level, at = row["price"], row["index_price"], row["timestamp"]
        assert all(math.isfinite(x) and x > 0 for x in (price, level))
        if signal is not None:
            sign, source = signal
            side = "buy" if sign > 0 else "sell"
            age = at - source["timestamp"]
            if (
                0 < age <= 7_200_000
                and row["direction"] == side
                and row["amount"] >= QTY
            ):
                return sign, source, row
            if age <= 7_200_000:
                continue
        basis = level - price
        signal = ((1 if basis > 0 else -1), row) if abs(basis) >= ENTRY_DELTA else None
    return None


def replay(source, baseline, output):
    spec = {r["id"]: r for r in read(baseline)["disposition"]}
    assert all(not spec[key]["status"].startswith("Tested") for key in (6169, 6170))
    markets = read(source)
    assert (
        len({r["instrument"]["instrument_name"] for r in markets}) == len(markets) == 10
    )
    periods = [("2026 Jan–Jun", []), ("2026 Jul–Oct", [])]
    receipts, files = [], []
    for item in markets:
        instrument = item["instrument"]
        assert instrument["price_index"] == "btcdvol_usdc"
        assert (
            instrument["settlement_currency"] == "USDC"
            and instrument["contract_size"] == QTY
        )
        assert instrument["min_trade_amount"] == QTY
        expiry = instrument["expiration_timestamp"]
        name = instrument["instrument_name"]
        date = datetime.fromtimestamp(expiry / 1000, tz=UTC).date().isoformat()
        assert item["date"] == item["delivery"]["date"] == date
        delivery = item["delivery"]["delivery_price"]
        assert math.isfinite(delivery) and delivery > 0
        tape = item["trades"]["trades"]
        assert not item["trades"]["has_more"]
        assert len({r["trade_id"] for r in tape}) == len(tape)
        assert all(
            r["instrument_name"] == name
            and instrument["creation_timestamp"] <= r["timestamp"] < expiry
            for r in tape
        )
        assert all(
            a["timestamp"] <= b["timestamp"] for a, b in itertools.pairwise(tape)
        )
        files.append({"instrument": name, "url": item["url"], "prints": len(tape)})
        if fill := observe(tape, expiry):
            side, signal, entry = fill
            gross = side * QTY * (delivery - entry["price"])
            fees = QTY * FEE * (delivery + entry["price"])
            cost = QTY * entry["price"] * 0.0003
            periods[date >= "2026-07-01"][1].append((expiry, gross, fees, cost))
            receipts.append(
                {
                    "instrument": name,
                    "signal_trade_id": signal["trade_id"],
                    "buy_or_sell": entry["direction"],
                    "entry_trade_id": entry["trade_id"],
                    "signal_ms": signal["timestamp"],
                    "entry_ms": entry["timestamp"],
                    "entry": entry["price"],
                    "delivery": delivery,
                    "expiry_ms": expiry,
                    "signal_price": signal["price"],
                    "signal_index": signal["index_price"],
                }
            )
    assert receipts
    rows = [
        {
            "id": 6169,
            "name": spec[6169]["name"],
            "source": spec[6169]["source"],
            "group": "Deribit · DVOL basis variant",
            "period": period,
            "market": "BTC DVOL",
            "quote_currency": "USDC",
            "interval": "Event",
            "archive_interval": "Monthly futures",
            "exit": "Published DVOL delivery",
            **metrics(cash),
        }
        for period, cash in periods
    ]
    with source.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    coverage = [
        [
            6169,
            "Tested · DVOL futures basis variant",
            f"{len(receipts)} contracts modeled at a later size-eligible directional print and official cash settlement.",
        ],
        [
            6170,
            "Protocol history and rules needed",
            "BTC DVOL prints and deliveries verified for 10 expiries. The options hedge still needs synchronized executable prices and rules for its legs.",
        ],
    ]
    write(
        output,
        {
            "raw_snapshot_sha256": digest,
            "inputs": files,
            "quantity": QTY,
            "basis_trigger": ENTRY_DELTA,
            "entry_and_delivery_fee_rate": FEE,
            "receipts": receipts,
            "coverage": coverage,
            "results": rows,
        },
    )
    print(
        f"{len(receipts)} DVOL futures settlements verified from {len(markets)} contracts"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("source", "baseline", "output"):
        parser.add_argument(key, type=Path)
    replay(**vars(parser.parse_args()))
