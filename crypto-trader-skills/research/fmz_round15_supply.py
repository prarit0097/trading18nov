"""Replay FMZ #171 with documented alternative USDT circulating-supply history."""

import argparse
import csv
import hashlib
import json
import math
import re
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.nonpine_round4_metrics import metrics
from research.nonpine_round9_dip import BUFFER, utc_day

ID = 171
DAY, BAR = 86400, 7200
WINDOWS = (("2023-08-13", "2023-09-12"), ("2023-09-12", "2023-10-12"))
CAPITAL, FEE = 100.0, 0.001


def read_inputs(root):
    manifest = json.loads((root / "manifest.json").read_bytes())
    for name, info in manifest.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == info["sha256"]
    supply = {}
    for point in json.loads((root / "usdt.json").read_bytes()):
        number = point["totalCirculating"].get("peggedUSD")
        if number is not None:
            at = int(point["date"])
            assert at not in supply
            supply[at] = number
    books = {}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        candles = []
        for name in sorted(n for n in manifest if n.startswith(symbol) and n.endswith(".zip")):
            assert manifest[name]["sha256"] == (root / (name + ".CHECKSUM")).read_text().split()[0].lower()
            with ZipFile(root / name) as source:
                [key] = source.namelist()
                lines = source.read(key).decode("ascii").splitlines()
            for parts in csv.reader(lines):
                if parts[0].isdecimal():
                    at, opn, high, low, close, volume, *_ = parts
                    opn, close = float(opn), float(close)
                    stamp = int(at) // 1000
                    assert stamp % BAR == 0 and float(low) <= opn <= float(high)
                    assert float(low) <= close <= float(high) and float(volume) > 0
                    daily_label = ((stamp + BAR) // DAY) * DAY - DAY
                    value = supply[daily_label]
                    assert value > 0
                    candles.append((stamp, opn, close, daily_label, value))
        assert all(t[0] - r[0] == BAR for r, t in zip(candles, candles[1:]))
        books[symbol] = candles
    return books, manifest


def replay(candles, start, end):
    trailing = deque(maxlen=50)
    cash_equity, next_side, position = CAPITAL, 0, None
    decisions, orders, receipts = [], [], []
    mark = None
    for at, opn, close, source_day, value in candles:
        if at < start:
            trailing.append(value)
            continue
        if at >= end:
            break
        if next_side:
            if position:
                side, quantity, entry = position
                gross = side * quantity * (opn - entry)
                cash_equity += gross - opn * quantity * FEE
                receipts.append((at, gross, quantity * (entry + opn) * FEE, quantity * (entry + opn) * BUFFER))
            quantity = cash_equity / opn
            assert quantity > 0
            orders.append((at, opn, next_side, quantity, cash_equity))
            cash_equity -= opn * quantity * FEE
            position = (next_side, quantity, opn)
            next_side = 0
        assert len(trailing) == 50
        upper, lower = max(trailing), min(trailing)
        signal = 1 if value > upper else (-1 if value < lower else 0)
        if signal and (not position or signal != position[0]):
            decisions.append((at + BAR, source_day, value, upper, lower, signal))
            next_side = signal
        trailing.append(value)
        mark = close
    assert mark and position and cash_equity > 0
    side, quantity, entry = position
    closing = cash_equity + side * quantity * (mark - entry)
    m = metrics(receipts, 1)
    when = defaultdict(float)
    for at, gross, fees, friction in receipts:
        when[at] += gross - fees - friction
    equity, peak, drawdown = CAPITAL, CAPITAL, 0.0
    for at in sorted(when):
        equity += when[at]
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak - equity) / peak)
    m["net_dd_pct"] = drawdown
    assert math.isclose(cash_equity, CAPITAL + m["after_fees"] - entry * quantity * FEE)
    return m, {"decisions": decisions, "orders": orders, "receipts": receipts,
               "open_position": position, "waiting_for_next_open": next_side,
               "closing_market_price": mark, "closing_equity_with_fees": closing}


def run(archive, queue, root, output):
    item = json.loads(queue.read_bytes())[str(ID)]
    ref, filename = unquote(item["source"].split("/blob/", 1)[1]).split("/", 1)
    with ZipFile(archive) as source:
        raw = source.read(f"strategies-{ref}/{filename}")
    [body] = re.findall(rb"```\s*pinescript\s*\n(.*?)```", raw, re.S)
    assert all(word in body for word in (
        b'"GLASSNODE:USDT_SUPPLY", "D", close', b"input.int(50,", b"brrrrr > h[1]",
        b"brrrrr < l[1]", b"initial_capital = 100", b"commission_value = 0.1", b"default_qty_value = 100",
    ))
    candles, sources = read_inputs(root)
    observations, results = {}, []
    for symbol, series in candles.items():
        for first, last in WINDOWS:
            performance, log = replay(series, utc_day(first), utc_day(last))
            assert performance["trades"] > 0
            observations[f"{symbol}/{first}"] = log
            results.append({
                "id": ID, "period": f"{first} to {last} UTC", "market": symbol,
                "currency": "USDT", "group": "FMZ Brrrrr · circulating-supply input variant",
                "interval": "2h", "archive_interval": "2h chart / daily supply",
                "exit": "Opposite circulating-supply channel breakout", "order_family": "Next-open market reversal",
                **performance,
            })
            print(symbol, first, performance["trades"], performance["net"], flush=True)
    output.write_text(json.dumps({
        "coverage": [[ID, "Tested · Historical DefiLlama supply-input variant",
                      "Preserved 2h chart and authored Donchian reversals with lagged observed DefiLlama USDT circulating supply. Exact Glassnode input remains outside this comparison."]],
        "results": results, "observations": observations, "source": item["source"],
        "source_sha256": hashlib.sha256(raw).hexdigest(), "archive_data": sources,
        "assumptions": [
            "This is a source-bound input comparison. The archived GLASSNODE:USDT_SUPPLY series is replaced with DefiLlama USDT circulating quantities in the peggedUSD denomination. The two vendors can differ on coverage and timing.",
            "Archived daily labels are usable from the next UTC day. The channel uses the preceding 50 chart samples, each observing only its then-eligible daily value. Revised historical inputs may differ from received real-time records.",
            "The publisher gives BTC/USD-M. ETH/USD-M is a comparison using the same external signal and its own fill tape.",
            "Each market and window starts at 100 USDT. Trade sizing uses the source 100% equity behavior when the next bar opens. Commission is the source 0.1% per side and execution adds a separate 0.03% per side. Funding is outside the source Pine broker study.",
        ],
    }, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "queue", "inputs", "output"):
        parser.add_argument(name, type=Path)
    a = parser.parse_args()
    run(a.archive, a.queue, a.inputs, a.output)
