"""Check BTC Polymarket split/merge thresholds on both captured outcome books."""

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

ID = 6178
MARKET = "3534492"
DATA_URL = (
    "https://huggingface.co/datasets/polyorderbooks/polymarket-btc-5min-historical-l2/"
    "resolve/25d091ea919f44c479f6eb1871a2062d64a779ca/polymarket_btc_5min_l2.jsonl"
)
DATA_SHA = "d6cfc0e388f31d810b752c67f2e363150330cb422915fd107503268a5ca3e6c2"
SUMMARY_URL = DATA_URL.replace("_l2.jsonl", "_l2_summary.csv")
SUMMARY_SHA = "f0c2effe2338b2bdc16bf715ce2d1af9de59a6d2ee83e13515e92b13663cbc89"


def quotes(raw):
    books = defaultdict(dict)
    token_ids = defaultdict(set)
    for line in raw.splitlines():
        row = json.loads(line, parse_float=Decimal)
        assert row["market_id"] == MARKET and row["resolved_winner"] == "Yes"
        stamp = datetime.fromisoformat(row["timestamp"])
        outcome = row["outcome"]
        assert outcome in ("Yes", "No") and outcome not in books[stamp]
        token_ids[outcome].add(row["token_id"])
        levels = []
        for side, choose in (("bids", max), ("asks", min)):
            prices = [
                level["price"] for level in row[side]
                if level["size"] > 0 and 0 <= level["price"] <= 1
            ]
            top = choose(prices) if prices else None
            assert top == row["best_" + side[:-1]]
            levels.append(top)
        books[stamp][outcome] = levels
    assert len(books) == 300 and len({*token_ids["Yes"], *token_ids["No"]}) == 2
    stamps = sorted(books)
    assert all(next_ - now == timedelta(seconds=1) for now, next_ in zip(stamps, stamps[1:]))
    return stamps, books, {outcome: next(iter(values)) for outcome, values in token_ids.items()}


def run(snapshot, summary, output):
    raw = snapshot.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == DATA_SHA
    stamps, book, tokens = quotes(raw)
    csv_data = summary.read_bytes()
    assert hashlib.sha256(csv_data).hexdigest() == SUMMARY_SHA
    seen = set()
    for row in csv.DictReader(csv_data.decode("utf-8").splitlines()):
        at, outcome = datetime.fromisoformat(row["timestamp"]), row["outcome"]
        assert (at, outcome) not in seen and tokens[outcome] == row["token_id"]
        seen.add((at, outcome))
        values = [Decimal(row[k]) if row[k] else None for k in ("best_bid", "best_ask")]
        assert book[at][outcome] == values
    assert len(seen) == len(stamps) * 2
    ask_sets, bid_sets, missing = [], [], {"asks": 0, "bids": 0}
    for at in stamps:
        assert set(book[at]) == {"Yes", "No"}
        yes, no = book[at]["Yes"], book[at]["No"]
        for idx, series, name in ((0, bid_sets, "bids"), (1, ask_sets, "asks")):
            if yes[idx] is None or no[idx] is None:
                missing[name] += 1
            else:
                series.append((yes[idx] + no[idx], at))
    smallest, buy_at = min(ask_sets)
    largest, sell_at = max(bid_sets)
    assert smallest > 1 > largest
    results = [{
        "id": ID, "period": "2026-08-13 04:50–04:55 UTC",
        "group": "Polymarket · paired historical outcome snapshots",
        "market": "BTC 5-minute Up/Down (USD)", "currency": "USD",
        "exit": "Complete-set merge or split parity", "order_family": "Paired executable quote check",
        "interval": "1s", "archive_interval": "1s",
        "trades": 0, "unsettled": 0, "gross_wins": 0, "fee_wins": 0, "net_wins": 0,
        "gross": 0, "fees": 0, "execution": 0, "after_fees": 0, "net": 0,
        "gross_dd": 0, "fee_dd": 0, "net_dd": 0, "net_dd_pct": 0,
    }]
    output.write_text(json.dumps({
        "coverage": [[ID, "Tested · Two-sided BTC complete-set quotes, no trade",
                      "Matched both historical outcome ladders at every second of a resolved BTC market. Neither complete-set side crossed collateral parity before fees."]],
        "results": results,
        "source": DATA_URL, "snapshot_sha256": DATA_SHA,
        "summary_source": SUMMARY_URL, "summary_sha256": SUMMARY_SHA,
        "archive_attribution": "PolyOrderbooks, CC BY 4.0",
        "position_reference": "https://docs.polymarket.com/trading/positions/manage",
        "rows": 2 * len(stamps), "market_id": MARKET, "tokens": tokens,
        "joint_quote_checks": {"bids": len(bid_sets), "asks": len(ask_sets)},
        "missing_joint_quote": missing,
        "minimum_complete_set_ask": {"value": str(smallest), "time": buy_at.isoformat()},
        "maximum_complete_set_bid": {"value": str(largest), "time": sell_at.isoformat()},
        "assumptions": [
            "One unit of collateral corresponds to equal Yes and No quantities. Best asks provide a lower bound on acquisition price and best bids provide an upper bound on sale proceeds. Worse available ladder prices cannot improve either bound.",
            "The sampled joint book is considered before latency, fees and settlement costs. No positive gross edge is present, so any nonnegative cost preserves the zero-trade outcome.",
            "No decisions were inferred where either outcome lacked an executable quote. One resolved five-minute market provides a narrow historical sample, and one-second recording cannot assess events between snapshots.",
        ],
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("summary", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.snapshot, args.summary, args.output)
