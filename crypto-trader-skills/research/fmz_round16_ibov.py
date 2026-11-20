"""Replay FMZ #5617 with B3 monthly index closes and Binance BTC/ETH hourly opens."""

import argparse
import csv
import hashlib
import json
import math
import re
from base64 import b64decode
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.nonpine_round4_metrics import metrics
from research.nonpine_round9_dip import utc_day

ID, HOUR, CAPITAL = 5617, 3600, 10_000
FEE, BUFFER = 0.00059, 0.0003
WINDOWS = (("2023-08-14", "2023-09-13"), ("2023-09-13", "2024-03-13"))


def inputs(root):
    recorded = json.loads((root / "manifest.json").read_bytes())
    for name, info in recorded.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == info["sha256"]
    month_data = json.loads((root / "monthly.json").read_bytes(), parse_float=Decimal)
    closes = {(r["year"], r["month"]): Decimal(r["indexClosingRate"]) for r in month_data}
    export = b64decode((root / "monthly.csv").read_bytes()).decode("latin-1")
    independent = {}
    for row in csv.reader(export.splitlines(), delimiter=";"):
        if len(row) == 3 and row[0].isdigit():
            month, year, value = row
            independent[int(year), int(month)] = Decimal(value.replace(".", "").replace(",", "."))
    assert closes == independent and len(closes) == 36
    return closes, recorded


def candles(root, symbol, proof, closes):
    rows = []
    for name in sorted(n for n in proof if n.startswith(symbol) and n.endswith(".zip")):
        assert proof[name]["sha256"] == (root / (name + ".CHECKSUM")).read_text().split()[0].lower()
        with ZipFile(root / name) as source:
            [inner] = source.namelist()
            records = csv.reader(source.read(inner).decode("ascii").splitlines())
            for row in records:
                if not row[0].isdigit():
                    continue
                at = int(row[0]) // 1000
                opn, high, low, close, volume = map(float, row[1:6])
                assert at % HOUR == 0 and low <= min(opn, close) <= max(opn, close) <= high
                assert volume > 0
                clock = datetime.fromtimestamp(at, timezone.utc)
                key = (clock.year, clock.month - 1) if clock.month > 1 else (clock.year - 1, 12)
                rows.append((at, opn, close, key, closes[key]))
    assert all(b[0] - a[0] == HOUR for a, b in zip(rows, rows[1:]))
    return rows


def replay(rows, begin, finish):
    last = None
    prior, occupied = deque(maxlen=5), None
    pending = 0
    prior_difference = Decimal(0)
    balance = float(CAPITAL)
    decisions, fills, trade_log = [], [], []
    for at, opn, close, month, mark in rows:
        if at >= finish:
            break
        if pending:
            if occupied:
                side, quantity, basis = occupied
                turnover = quantity * (basis + opn)
                gross = side * quantity * (opn - basis)
                trade_log.append((at, gross, turnover * FEE, turnover * BUFFER))
                balance += gross
            quantity = balance / opn
            assert quantity > 0
            occupied = (pending, quantity, opn)
            fills.append((at, pending, quantity, opn))
            pending = 0
        prior.append(mark)
        if len(prior) == 5:
            difference = 5 * mark - sum(prior)
            crossed_up = difference > 0 >= prior_difference
            crossed_down = difference < 0 <= prior_difference
            direction = int(crossed_up) - int(crossed_down)
            if at >= begin and direction and (not occupied or direction != occupied[0]):
                pending = direction
                decisions.append((at + HOUR, list(month), str(mark), direction))
            prior_difference = difference
        last = close
    assert last and occupied
    stats = metrics(trade_log, 1)
    assert math.isclose(balance - CAPITAL, stats["gross"], abs_tol=1e-9)
    return stats, {"signals": decisions, "fills": fills, "settled": trade_log, "ending_position": occupied,
                   "ending_chart_close": last, "ending_realized_equity_gross": balance,
                   "next_open_instruction": pending}


def run(archive, queue, root, file):
    item = json.loads(queue.read_bytes())[str(ID)]
    ref, name = unquote(item["source"].split("/blob/", 1)[1]).split("/", 1)
    with ZipFile(archive) as source:
        raw = source.read(f"strategies-{ref}/{name}")
    [code] = re.findall(rb"```\s*pinescript\s*\n(.*?)```", raw, re.S)
    assert all(clause in code for clause in (
        b'base = input("BMFBOVESPA:IBOV")', b"base_ma = sma(base_cl, period)", b'defval=\'M\'',
        b"default_qty_value=100", b'strategy.entry("LONG", strategy.long)', b'strategy.close("SHORT")',
        b'strategy.entry("SHORT", strategy.short)', b'strategy.close("LONG")',
    ))
    closes, input_files = inputs(root)
    results, receipts = [], {}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        series = candles(root, symbol, input_files, closes)
        for first, end in WINDOWS:
            stats, evidence = replay(series, utc_day(first), utc_day(end))
            receipts[f"{symbol}/{first}"] = evidence
            results.append({
                "id": ID, "period": f"{first} to {end} UTC", "market": symbol,
                "currency": "USDT", "group": "FMZ L/S · official Ibovespa close timing variant",
                "interval": "1h", "archive_interval": "1h chart and monthly IBOV",
                "exit": "Opposite completed-month index crossover", "order_family": "Next-open market reversal",
                **stats,
            })
            print(symbol, first, stats["trades"], stats["net"], flush=True)
    assert any(row["trades"] for row in results)
    file.write_text(json.dumps({
        "coverage": [[ID, "Tested · Official B3 close timing variant",
                      "Monthly Ibovespa input independently matches the exchange JSON and CSV. Verified the original 1h rules and a longer follow-up with a calendar-safe monthly availability policy."]],
        "results": results, "receipts": receipts,
        "source": item["source"], "source_sha256": hashlib.sha256(raw).hexdigest(),
        "index_source_page": "https://sistemaswebb3-listados.b3.com.br/indexStatisticsPage/daily-evolution/IBOVESPA?language=pt-br",
        "input_files": input_files,
        "assumptions": [
            "The official B3 index closes replace the TradingView cross-symbol transfer. A published monthly close is eligible starting on the first UTC day after that month. The rule evaluates it after one complete BTC/ETH chart hour, which supplies a conservative explicit timing convention.",
            "The source SMA is applied after completed monthly data is merged into the hourly series, so the average spans five hourly samples.",
            "Archived window stays unchanged. The six-calendar-month follow-up is used only to observe several monthly updates. It is a separate historical comparison.",
            "Each scope starts at 10,000 USDT. One position tracks the published 100%-equity reversal. The paired market close and contrary entry settle the old position once, at the next observed open.",
            "Source has no commission setting. Reported cost sensitivity uses 5.9 bp fee and 3 bp friction per side on the same fills. Perpetual funding is outside the Pine comparison.",
        ],
    }, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("archive", "queue", "inputs", "output"):
        parser.add_argument(argument, type=Path)
    paths = parser.parse_args()
    run(paths.archive, paths.queue, paths.inputs, paths.output)
