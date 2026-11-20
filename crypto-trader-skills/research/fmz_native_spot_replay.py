"""Prepare and reconcile the isolated FMZ native spot replay."""

import argparse
import csv
import hashlib
import json
import math
import re
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote, urlencode
from urllib.request import urlopen
from zipfile import ZipFile

from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.delta_strategy_replay import EQUITY, EXECUTION, FEE, ROOT, stamp, summarize

COMMIT = "342baf9e74fdf83f3ef0b4c010200b1c3ddb9924"
ENGINE = f"https://raw.githubusercontent.com/fmzquant/backtest_javascript/{COMMIT}/backtest_javascript_wasm.js"
ENGINE_SHA = "d2cac831db3b2cdce8c9bf1e5aa35bdbdc695d91464ca6dbf7fe0259a0509be8"
WINDOWS = {"Reference": ("2026-09-23", "2026-10-21"), "Later": ("2026-10-21", "2026-11-04")}
COINS = ("BTC", "ETH")
TESTED = {476, 597}
PENDING = {
    62: "The archive supplies rsi_period and atrma_period but omits atr_period, tick_interval and slide_price.",
    539: "MACD strategy needs source defaults for ac1, bc1, SlidePrice, BanlanceRatio, orderTimeout and TrailingStop.",
    595: "Documented Martingale example sends an unbound 0.001 quote-unit market buy below the spot minimum. A futures or base-quantity interpretation would change order semantics.",
    739: "RSI thresholds, RSIPeriod, Interval and SlidePrice need the source's parameter defaults.",
    1123: "Single-pattern TA-Lib teaching example stops immediately on detection and has no closed-position rule.",
    1133: "Example binds the inverse XBTUSD contract and references Amount without a source default.",
    5426: "Trend strategy needs documented EMA_Fast, EMA_Slow, LoopInterval, SlidePrice, MinStock and EnableGoingShort defaults.",
}
GROUP = "FMZ JS · Binance Spot"
EXIT = "Native FMZ strategy orders"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def get(url, destination):
    if not destination.exists():
        with urlopen(url, timeout=35) as stream:
            destination.write_bytes(stream.read())
    return destination.read_bytes()


def sources(archive):
    items = {}
    with ZipFile(archive) as fmz, (ROOT / "public-strategy-catalogue.csv").open(encoding="utf-8-sig") as stream:
        for i, row in enumerate(csv.DictReader(stream), 1):
            if i not in TESTED | PENDING.keys():
                continue
            source = row["source_url"]
            relative = unquote(source.split(f"/{FMZ_REF}/", 1)[1])
            raw = fmz.read(f"strategies-{FMZ_REF}/{relative}")
            blocks = re.findall(r"(?ms)^\x60{3}[^\n]*\n(.*?)^\x60{3}", raw.decode())
            bodies = [b for b in blocks if re.search(r"\bfunction\s+main\s*\(", b)]
            assert len(bodies) == 1, i
            items[i] = {"name": row["name"], "source": source, "source_sha256": digest(raw), "code": bodies[0]}
    return items


def prepare(archive, work):
    work.mkdir(exist_ok=True, parents=True)
    content = get(ENGINE, work / "upstream.cjs")
    assert digest(content) == ENGINE_SHA
    text = content.decode().replace("\r\n", "\n")
    anchor = "},httpGet=function(url){let options"
    assert text.count(anchor) == 1
    adapted = text.replace(anchor, "},httpGet=function(url){return globalThis.__offlineProbe(url);let options")
    (work / "fmz-wasm-engine.cjs").write_bytes(adapted.encode())
    worker = (ROOT / "fmz_native_spot_worker.cjs").read_text(encoding="utf-8")
    worker = worker.replace("\n", "\r\n").encode()
    (work / "spot-replay-paged.cjs").write_bytes(worker)
    candidates = work / "candidate-source"
    candidates.mkdir(exist_ok=True)
    for i, item in sources(archive).items():
        if i in TESTED:
            (candidates / f"{i}.js").write_bytes(item["code"].encode())

    def fetch(job):
        coin, start, end = job
        begin, stop = stamp(start) - 900_000, stamp(end)
        fields = dict(detail="true", round="true", feeder="local", event="feed", eid="Binance",
                      depth=5, trades=0, custom=0, period=300_000, symbol=f"{coin}_USDT")
        fields.update({"from": begin, "to": stop})
        url = "https://q.fmz.com/data/history?" + urlencode(fields)
        filename = f"{coin}-{begin}-{stop}.json"
        raw = get(url, work / filename)
        document = json.loads(raw)
        bars = document["data"]
        assert document["detail"]["symbol"] == fields["symbol"]
        assert [x[0] for x in bars] == list(range(begin * 1000, (stop + 1) * 1000, 300_000))
        assert all(0 < x[3] <= min(x[1], x[4]) <= max(x[1], x[4]) <= x[2] and x[5] > 0 for x in bars)
        return dict(coin=coin, start=start, end=end, file=filename, url=url, sha256=digest(raw))

    with ThreadPoolExecutor(max_workers=4) as pool:
        manifest = list(pool.map(fetch, [(coin, *window) for coin in COINS for window in WINDOWS.values()]))
    write(work / "spot-feed.json", manifest)


def reconcile(record, metadata, raw_prices):
    start, end = stamp(metadata["start"]) * 1000, stamp(metadata["end"]) * 1000
    assert record["status"] and record["requests"] == 1 and start < record["last"]["Time"] <= end
    account = record["account"]
    assert account["FrozenBalance"] == account["FrozenStocks"] == 0
    orders = sorted(record["orders"], key=lambda x: (x["Time"], x["Id"]))
    assert len(orders) == len({x["Id"] for x in orders})
    trades, entry = [], deque()
    cash, stocks = EQUITY, 0.0
    for order in orders:
        time, quantity, price, side = (order[x] for x in ("Time", "DealAmount", "AvgPrice", "Type"))
        assert order["Symbol"] == f"{record['coin']}_USDT" and side in (0, 1)
        assert start <= time < end and 0 <= quantity <= order["Amount"] and order["Offset"] == 0
        if not quantity:
            continue
        # Native orders expose the placement time, used here as the ledger event timestamp.
        assert price > 0 and raw_prices[time // 300_000 * 300_000][5] > 0
        sign, turnover = (1 if side == 0 else -1), quantity * price
        cash -= sign * turnover + turnover * FEE
        stocks += sign * quantity
        if side == 0:
            entry.append((quantity, price))
            continue
        while quantity > 1e-9:
            open_size, open_price = entry.popleft()
            closed = min(open_size, quantity)
            gross = closed * (price - open_price)
            exposure = closed * (price + open_price)
            trades.append((time, gross, gross - exposure * FEE, gross - exposure * (FEE + EXECUTION)))
            quantity -= closed
            if open_size - closed > 1e-9:
                entry.appendleft((open_size - closed, open_price))
    assert math.isclose(cash, account["Balance"], abs_tol=1e-7, rel_tol=0)
    assert math.isclose(stocks, account["Stocks"], abs_tol=1e-9, rel_tol=0)
    if not entry:
        assert math.isclose(sum(x[2] for x in trades), cash - EQUITY, abs_tol=1e-7, rel_tol=0)
    return trades, len(entry), {"cash_difference": cash - account["Balance"], "stock_difference": stocks - account["Stocks"]}


def finalize(archive, work, destination):
    items = sources(archive)
    feeds = read(work / "spot-feed.json")
    manifest = {(r["coin"], r["start"]): r for r in feeds}
    trials, evidence = {}, []
    for record in read(work / "spot-replay-paged.json"):
        i, coin, start = (record[k] for k in ("id", "coin", "period"))
        assert not record.get("reason"), record
        metadata = manifest[(coin, start)]
        raw = (work / metadata["file"]).read_bytes()
        assert digest(raw) == metadata["sha256"]
        values = reconcile(record, metadata, {x[0]: x for x in json.loads(raw)["data"]})
        assert (i, coin, start) not in trials
        trials[i, coin, start] = values[:2]
        evidence.append({"id": i, "coin": coin, "start": start, "account": record["account"],
                         "checks": values[2], "orders": record["orders"]})
    assert trials.keys() == {(i, c, start) for i in TESTED for c in COINS for start, _ in WINDOWS.values()}

    rows = []
    coverage = [[i, "FMZ native JS pending", why] for i, why in PENDING.items()]
    for i in sorted(TESTED):
        item = items[i]
        archived_code = (work / "candidate-source" / f"{i}.js").read_text(encoding="utf-8")
        assert archived_code == item["code"].replace("\r\n", "\n")
        for period, (start, _) in WINDOWS.items():
            btc, b_open = trials[i, "BTC", start]
            eth, e_open = trials[i, "ETH", start]
            values = (("BTCUSDT spot", btc, b_open), ("ETHUSDT spot", eth, e_open),
                      ("BTCUSDT + ETHUSDT spot", btc + eth, b_open + e_open))
            for market, sample, unsettled in values:
                row = summarize((GROUP, item["name"], market, EXIT), period, sample, unsettled)
                row.update(id=i, source=item["source"], source_sha256=item["source_sha256"],
                           interval="15m", archive_interval="", quote_currency="USDT", market_data="FMZ Binance spot")
                rows.append(row)
        status = "Tested · FMZ native spot" if any(r["trades"] for r in rows if r["id"] == i) else "Tested · FMZ native spot, no closes"
        coverage.append([i, status, "FMZ native JavaScript with 15m charts and 5m Binance spot base history. Retired minimum quantity method sourced from market metadata."])
    output = dict(engine="FMZ backtest_javascript WASM", engine_revision=COMMIT, engine_sha256=ENGINE_SHA,
                  source_revision=FMZ_REF, windows=WINDOWS, market_feeds=feeds, quote_currency="USDT",
                  worker_sha256=digest((work / "spot-replay-paged.cjs").read_bytes()),
                  coverage=sorted(coverage), results=rows, order_evidence=evidence)
    write(destination, output)
    print(f"{len(trials)} native trials, {len(rows)} result rows, {len(coverage)} dispositions")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "finalize"))
    parser.add_argument("archive", type=Path)
    parser.add_argument("work", type=Path)
    parser.add_argument("output", type=Path, nargs="?")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.archive, args.work)
    else:
        finalize(args.archive, args.work, args.output)
