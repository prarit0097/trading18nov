"""Reconcile source-backed GM and GLV share receipt scenarios."""

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from research.delta_pinets_catalogue import read, write
from research.nonpine_round4_metrics import metrics

LABELS = {6180: "GM pool", 6181: "GLV vault"}


@dataclass(frozen=True)
class ReceiptTerms:
    timestamp: int
    shares_raw: int
    cash_usd: Decimal
    fee_usd: Decimal
    gas_usd: Decimal


def quote(amount_raw, oracle_price_raw):
    """GMX oracle prices already account for the asset's token precision."""
    return Decimal(amount_raw) * Decimal(oracle_price_raw) / Decimal(10**30)


def terms(raw):
    cash = quote(raw["usdc_raw"], raw["usdc_oracle"])
    fees = sum(quote(fee["amount_raw"], fee["oracle"]) for fee in raw["fees"])
    request_wei = raw["request_gas_used"] * raw["request_gas_price"]
    assert raw["keeper_wei"] + raw["refund_wei"] == raw["prepaid_keeper_wei"]
    assert raw["request_eth_observation_block"] <= raw["request_block"]
    assert raw["eth_observation_block"] <= raw["block"]
    gas = Decimal(
        request_wei * raw["request_eth_usd_8dp"]
        + raw["keeper_wei"] * raw["eth_usd_8dp"]
    ) / Decimal(10**26)
    if cash <= 0 or not raw["fees"] or fees < 0 or gas <= 0:
        raise ValueError("Receipt lacks cash, explicit nonnegative protocol fees or network cost")
    return ReceiptTerms(raw["timestamp"], raw["shares_raw"], cash, fees, gas)


def matched_leg(entry, exit, shares):
    if exit.timestamp <= entry.timestamp:
        raise ValueError("Receipt times must increase")
    if not 0 < shares <= min(entry.shares_raw, exit.shares_raw):
        raise ValueError("Invalid matched share amount")
    before = Decimal(shares) / entry.shares_raw
    after = Decimal(shares) / exit.shares_raw
    cash_change = after * exit.cash_usd - before * entry.cash_usd
    fees = before * entry.fee_usd + after * exit.fee_usd
    gas = before * entry.gas_usd + after * exit.gas_usd
    return exit.timestamp, float(cash_change + fees), float(fees), float(gas)


def report(data):
    groups = defaultdict(list)
    allocated = Counter()
    evidence = {}
    for pair in data["lots"]:
        ident = pair["id"]
        shares = pair["allocated_shares_raw"]
        for label in ("deposit", "withdrawal"):
            leg = pair[label]
            action = (leg["execution_tx"], leg["log_index"])
            fingerprint = (leg["shares_raw"], leg["usdc_raw"], leg["timestamp"])
            assert evidence.setdefault(action, fingerprint) == fingerprint
            allocated[action] += shares
            assert allocated[action] <= leg["shares_raw"]
        groups[ident, pair["period"], pair["instrument"]].append(
            matched_leg(terms(pair["deposit"]), terms(pair["withdrawal"]), shares)
        )

    results = [
        {
            "id": ident,
            "period": period,
            "group": f"GMX · {LABELS[ident]} normalized on-chain receipt variant",
            "market": instrument,
            "currency": "USD",
            "interval": "Arbitrum transaction order",
            "archive_interval": "Matched historical mint and burn receipts",
            "exit": "Observed redemption of allocated shares",
            "order_family": "Liquidity share deposit and withdrawal",
            **metrics(lots),
        }
        for (ident, period, instrument), lots in sorted(groups.items())
    ]
    covered = {r["id"] for r in results}
    coverage = [
        [
            ident,
            f"Tested · GMX {label} historical receipt variant",
            (
                "Observed Arbitrum USDC input/output, verified share mint/burn and protocol fees, "
                "then pro-rata matched share amounts and observed network costs. BTC-linked "
                "receipts only. This is a historical liquidity scenario with selected fills."
            ),
        ]
        for ident, label in LABELS.items()
        if ident in covered
    ]
    return {**data, "coverage": coverage, "results": results}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("receipts", type=Path)
    cli.add_argument("output", type=Path)
    args = cli.parse_args()
    write(args.output, report(read(args.receipts)))
