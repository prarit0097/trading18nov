"""Historical buy-and-hold replay of FMZ #1100 with open inventory marked separately."""

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.nonpine_round11_daily import START_CASH, WINDOWS, data_with_opens
from research.nonpine_round9_dip import BUFFER, FEE, LOTS, utc_day

ID = 1100
CAPITAL = 10 * START_CASH
SLIDE = 0.3
MIN_CASH = 100


def replay(bars, start, end, lot):
    cash, balance, fees, friction = CAPITAL, 0.0, 0.0, 0.0
    price, pending = None, None
    submits, fills = [], []
    for at, opn, high, low, close, volume in bars:
        if at < start:
            price = close
            continue
        if at >= end:
            break
        pending = None
        if cash > MIN_CASH and price:
            limit = price + SLIDE
            quantity = math.floor(cash / limit * 1000) / 1000
            if quantity >= lot and quantity * limit >= 5:
                pending = (at, limit, quantity)
                submits.append(pending)
                if low < limit and quantity <= volume:
                    # Take favorable gap at the known open and resting executions at limit.
                    execution_price = min(opn, limit)
                    notional = execution_price * quantity
                    modeled = BUFFER * notional
                    if cash >= notional + modeled:
                        cash -= notional + modeled
                        balance += quantity * (1 - FEE)
                        fees += quantity * FEE
                        friction += modeled
                        fills.append((at, limit, execution_price, quantity, volume))
                        pending = None
        price = close
    assert price is not None and cash >= 0
    return {
        "submitted": len(submits), "fills": fills, "pending": pending,
        "cash": cash, "base": balance, "base_fee": fees, "execution_cost": friction,
        "closing_mark": price,
        "gross_marked_change": cash + friction + (balance + fees) * price - CAPITAL,
        "after_fee_marked_change": cash + friction + balance * price - CAPITAL,
        "after_cost_marked_change": cash + balance * price - CAPITAL,
    }


def run(data_root, source_zip, backlog, output):
    item = json.loads(backlog.read_bytes())[str(ID)]
    commit, filename = unquote(item["source"].split("/blob/", 1)[1]).split("/", 1)
    with ZipFile(source_zip) as archive:
        document = archive.read(f"strategies-{commit}/{filename}")
    [body] = re.findall(rb"```\s*javascript\s*\n(.*?)```", document, re.S)
    assert all(clause in body for clause in (
        b"ticker.Last + SlidePrice", b"var amount = adjustFloat(account.Balance / price);",
        b"account.Balance > minMoney && amount >= exchange.GetMinStock()",
        b"return Math.floor(v*1000)/1000", b"CancelPendingOrders();",
    ))
    assert not re.search(rb"\.Sell\s*\(", body)
    provenance, observations, results = {}, {}, []
    for symbol, lot in LOTS.items():
        bars, digests = data_with_opens(data_root, symbol)
        provenance[symbol] = digests
        for first, end in WINDOWS:
            result = replay(bars, utc_day(first), utc_day(end), lot)
            assert result["fills"]
            assert math.isclose(result["base"] + result["base_fee"], sum(f[3] for f in result["fills"]))
            assert math.isclose(result["cash"] + result["execution_cost"] + sum(f[2] * f[3] for f in result["fills"]), CAPITAL)
            observations[f"{symbol}/{first}"] = result
            metrics = dict.fromkeys(("gross", "fees", "after_fees", "execution", "net",
                                     "gross_dd", "fee_dd", "net_dd", "net_dd_pct",
                                     "gross_wins", "fee_wins", "net_wins"), 0)
            results.append({
                "id": ID, "period": f"{first} to {end} UTC", "market": symbol,
                "currency": "USDT", "group": "FMZ buy-and-hold · historical open inventory",
                "trades": 0, "unsettled": len(result["fills"]), "interval": "1m",
                "archive_interval": "60s source loop", "order_family": "One-way limit purchases",
                "exit": "Source has no sell rule", **metrics,
            })
    output.write_text(json.dumps({
        "coverage": [[ID, "Tested · Historical buy-and-hold, open inventory",
                      "Authored limit purchases verified in four BTC/ETH windows. Strategy has no sell rule. Open positions and mark-to-market performance are reported separately."]],
        "results": results, "open_inventory": observations,
        "source": item["source"], "source_sha256": hashlib.sha256(document).hexdigest(),
        "js_sha256": hashlib.sha256(body).hexdigest(), "archives": provenance,
        "assumptions": [
            "The archive omits a venue, market and initial wallet. This replay uses Binance BTC and ETH spot with 10,000 USDT per independent sleeve.",
            "The source checks every 60 seconds. Last completed minute close is the observed ticker value. A submitted limit needs strict trade-through in the following minute and adequate minute volume. A favorable open can improve execution.",
            "Each unfilled remainder is canceled before the next proposal. Price offset is source 0.3 quote, precision 0.001 base and minimum budget 100 quote. Binance lot and 5 USDT notional constrain fills.",
            "Fee is modeled at 10 bp of acquired base and friction at 3 bp of turnover. The tail mark includes entry fees and costs. Open lots have no realized win rate.",
        ],
    }, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("data", "source", "backlog", "output"):
        parser.add_argument(arg, type=Path)
    opts = parser.parse_args()
    run(opts.data, opts.source, opts.backlog, opts.output)
