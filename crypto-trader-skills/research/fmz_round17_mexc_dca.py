"""Replay the published one-USDT daily purchase rule against public MEXC data."""

import argparse
import hashlib
import json
import re
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.fmz_native_public_params import StrategyPage, normalized
from research.nonpine_round9_dip import utc_day

ID = 4795
CAPITAL, BUFFER = Decimal(1000), Decimal("0.0003")
WINDOWS = (("2026-10-23", "2026-11-06"), ("2026-11-06", "2026-11-20"))


def replay(bars, start, end, venue, amount):
    step, taker = Decimal(venue["baseSizePrecision"]), Decimal(venue["takerCommission"])
    assert venue["isSpotTradingAllowed"] and "MARKET" in venue["orderTypes"]
    assert amount >= Decimal(venue["quoteAmountPrecisionMarket"])
    cash, base, fees, costs = CAPITAL, Decimal(0), Decimal(0), Decimal(0)
    peak, maximum, mark = CAPITAL, Decimal(0), None
    fills = []
    for at, opn, high, low, close, volume, *_ in bars:
        if not start <= at < end:
            continue
        price, mark = Decimal(opn), Decimal(close)
        assert Decimal(low) <= min(price, mark) <= max(price, mark) <= Decimal(high)
        quantity = (amount / price / step).to_integral_value(rounding=ROUND_DOWN) * step
        assert step <= quantity <= Decimal(volume)
        exchange_fee = quantity * taker
        quote_cost = price * quantity
        extra = quote_cost * BUFFER
        cash -= quote_cost + extra
        received = quantity - exchange_fee
        base += received
        fees += exchange_fee
        costs += extra
        fills.append([at, str(price), str(quantity), str(received), str(quote_cost)])
        equity = cash + base * mark
        peak = max(peak, equity)
        maximum = max(maximum, (peak - equity) / peak)
    assert len(fills) == 14 and cash >= 0
    return {
        "purchases": fills, "ending_cash": str(cash), "ending_base": str(base),
        "ending_mark": str(mark), "total_base_fees": str(fees),
        "marked_pnl_gross": str(cash + costs + (base + fees) * mark - CAPITAL),
        "marked_pnl_after_fees": str(cash + costs + base * mark - CAPITAL),
        "marked_pnl_after_costs": str(cash + base * mark - CAPITAL),
        "marked_daily_drawdown_after_costs": str(maximum),
    }


def run(archive, queue, publisher_html, root, output):
    target = json.loads(queue.read_bytes())[str(ID)]
    ref, doc = unquote(target["source"].split("/blob/", 1)[1]).split("/", 1)
    with ZipFile(archive) as source:
        raw = source.read(f"strategies-{ref}/{doc}")
    [body] = re.findall(rb"```\s*javascript\s*\n(.*?)```", raw, re.S)
    assert b"now.toISOString().slice(0,10)" in body and b"exchange.Buy(-1, singleInvestAmount)" in body
    assert not re.search(rb"exchange\.Sell\s*\(", body)
    html = publisher_html.read_bytes()
    page = StrategyPage()
    page.feed(html.decode("utf-8"))
    code = normalized(body.decode("utf-8"))
    previews = [p for text in page.previews if len(p := normalized(text)) >= 70 and code.startswith(p)]
    assert previews and type(page.values["singleInvestAmount"]) is int and page.values["singleInvestAmount"] == 1
    amount = Decimal(page.values["singleInvestAmount"])
    manifest = json.loads((root / "daily-manifest.json").read_bytes())
    for name, record in manifest.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == record["sha256"]
    rows, receipts, venues = [], {}, {}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        data = json.loads((root / (symbol + "-daily.json")).read_bytes())
        assert all(y[0] - x[0] == 86_400_000 for x, y in zip(data, data[1:]))
        [venue] = json.loads((root / (symbol + "-metadata.json")).read_bytes())["symbols"]
        assert venue["symbol"] == symbol
        venues[symbol] = {key: venue[key] for key in ("baseSizePrecision", "quoteAmountPrecisionMarket", "takerCommission")}
        for start, end in WINDOWS:
            matched = replay(data, utc_day(start) * 1000, utc_day(end) * 1000, venue, amount)
            receipts[f"{symbol}/{start}"] = matched
            rows.append({
                "id": ID, "period": f"{start} to {end} UTC", "market": symbol,
                "currency": "USDT", "group": "FMZ daily investment · MEXC daily-open variant",
                "archive_interval": "60s UTC date poll", "interval": "1d opening sample",
                "exit": "Open inventory with marked evidence", "order_family": "One-USDT spot market purchase",
                "trades": 0, "unsettled": len(matched["purchases"]), "gross_wins": 0, "fee_wins": 0,
                "net_wins": 0, "gross": 0, "after_fees": 0, "net": 0, "fees": 0, "execution": 0,
                "gross_dd": 0, "fee_dd": 0, "net_dd": 0, "net_dd_pct": 0,
            })
    output.write_text(json.dumps({
        "coverage": [[ID, "Tested · MEXC one-USDT daily accumulation variant",
                      "Recovered true numeric author default of one USDT. MEXC permits that market-order amount on BTC and ETH. Four historical opening samples reconcile purchases and ending holdings."]],
        "results": rows, "receipts": receipts, "exchange_config": venues, "archives": manifest,
        "source": target["source"], "source_sha256": hashlib.sha256(raw).hexdigest(),
        "publisher": "https://www.fmz.com/strategy/151259", "publisher_sha256": hashlib.sha256(html).hexdigest(),
        "verified_preview_chars": max(map(len, previews)),
        "minimum_order_reference": "https://www.mexc.com/announcements/article/announcement-on-the-adjustment-to-the-minimum-order-amount-for-spot-trading-pairs-17827791517449",
        "assumptions": [
            "The archive omits venue and starting cash. The independent MEXC spot sleeves start at 1,000 USDT. The publisher's form gives a numeric one-USDT amount.",
            "The source triggers once each UTC date. The model uses the observed opening trade of each day as the execution-price sample. This is a daily-open variant of the polling source.",
            "The venue validates one USDT at submission. Estimated fill quantity is cut down to the observed product size step. Remainder stays in cash. The archived capture's product taker rate is charged in base, plus a separate 3 bp friction allowance.",
            "Source has no sale rule. All 56 modeled purchases remain open. The report marks holdings at observed end closes and gives daily mark-to-market drawdown separately from zero realized closes.",
        ],
    }, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for item in ("archive", "queue", "author_html", "inputs", "output"):
        parser.add_argument(item, type=Path)
    args = parser.parse_args()
    run(args.archive, args.queue, args.author_html, args.inputs, args.output)
