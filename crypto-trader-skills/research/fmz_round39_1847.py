"""Reconcile the funding shortfall in previously recorded #1847 aborts."""

import json
import sys
from decimal import Decimal
from pathlib import Path

from research.fmz_round7_magnifier import sha256, write

RECEIPT = "09ec4bb9121d82683c27314f1b04b985b283efb0d6d55f6d239b76338466fd2f"
SOURCE = "9289e40e25340ac47c2fe42e7aa57aeefcb16f38ae286c0c0648330534400c0d"


def main(document, receipt, output):
    assert sha256(document) == SOURCE and sha256(receipt) == RECEIPT
    body = document.read_text(encoding="utf-8")
    assert "_N(account.Balance / openPrice, 4) < openAmount" in body
    assert "openId = openFunc(openPrice, openAmount);" in body
    evidence = json.loads(receipt.read_bytes(), parse_float=Decimal)
    fee = evidence["execution_model"]["fee_each_side"]
    assert fee == Decimal(".00059")
    cases = []
    for item in evidence["native_evidence"]:
        if item["id"] != 1847:
            continue
        assert item["archive_sha256"] == SOURCE
        case = {
            "market": item["market"],
            "period": item["period"],
            "archive_abort": item["native_source_abort"],
            "host_receipt_sha256": item["raw_receipt_sha256"],
        }
        rejected = [v for v in item["final_order_attempts"] if v["id"] is None]
        if rejected:
            assert item["submission_totals"]["rejected"] == len(rejected) == 10
            assert {v["kind"] for v in rejected} == {"Buy"}
            ((price, qty),) = {(v["price"], v["amount"]) for v in rejected}
            gross = price * qty
            charge = gross * fee
            account = item["native_closing_account"]
            assert account["FrozenBalance"] == 0
            cash = account["Balance"]
            assert gross < cash < gross + charge
            case.update(
                {
                    "limit": str(price),
                    "base_quantity": str(qty),
                    "quote_at_submitted_limit": str(gross),
                    "entry_fee_buffer": str(charge),
                    "available_quote_after_cleanup": str(cash),
                    "minimum_quote_missing": str(gross + charge - cash),
                    "repeated_rejections": len(rejected),
                }
            )
        cases.append(case)
    assert len(cases) == 4 and sum("minimum_quote_missing" in v for v in cases) == 3
    write(
        output,
        {
            "schema": "FMZ #1847 native spot rejection affordability review",
            "source_sha256": SOURCE,
            "previous_receipt_sha256": RECEIPT,
            "fee_per_side": str(fee),
            "cases": cases,
            "scope": "The source declares its buy affordable from quote size without reserving the fee. The required limit-order notional plus the original model's fee exceeds even the recorded cash after releasing all frozen quote in three terminal scopes. No new market runs or counterfactual trades are inferred from this calculation.",
            "coverage": [
                [
                    1847,
                    "Pending · authored abort under fee-inclusive spot admission",
                    "The prior native spot executions stop in all four scopes. For three of them a Decimal check proves the exact repeated buy amount was under cash before fees and unaffordable after the applied fee. The fourth failed during opening without these recorded rejections.",
                ]
            ],
            "results": [],
        },
    )


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
