"""Stage and reconcile offline FMZ strategy trials against public BTC and ETH data."""

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict, deque
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.delta_strategy_replay import EQUITY, EXECUTION, FEE, ROOT, stamp, summarize

PENDING = "FMZ native offline replay pending"
BLOCKS = re.compile(r"(?ms)^\x60{3}([^\n]*)\n(.*?)^\x60{3}")
JS_MAIN = re.compile(r"\bfunction\s+main\s*\(")
PINE_ORDERS = re.compile(r"\bstrategy\.(?:entry|order)\s*\(")
GROUP = "FMZ Native · Binance Spot"
PERIODS = {"2026-09-23": "Reference", "2026-10-21": "Later"}
MODEL_BLOCKS = {
    391: "Archived LTC/BTC parameters and cash inventory rules require the original pair.",
    595: "Archived 0.001 quote-unit market buy is below the Binance spot minimum.",
    694: "Multi-instrument configuration requires an LTC leg and initialized BTC, ETH and LTC inventory.",
    696: "One-minute OKEX grid needs its native order queue and inventory behavior.",
    697: "Archive config uses a one-minute OKEX spot adapter. Comparable native one-minute replay remains unverified.",
    1107: "Native Python grid exceeded the isolated batch time budget before its first complete order receipt.",
    1123: "TA-Lib pattern teaching example stops on its first detection and has no position-closing rule.",
    1183: "Published inputs recover the futures strategy. The position, fee and funding ledger still needs independent reconciliation.",
    1382: "Execution-only buy iceberg requires the original order slicing and queue model.",
    1383: "Execution-only sell iceberg requires seeded inventory and the original order queue model.",
    1942: "Two-sided one-minute perpetual grid requires reconciled concurrent long/short fills and funding.",
    2490: "Archived order quantity is for the original OKCoin inverse contract.",
    2515: "Published 120-bar lookback recovered. The daily native chart and history warmup were outside this replay pass.",
    4619: "Quote placement requires historical best bid/ask and an executable maker queue.",
    4620: "Order-book market-making results require synchronized depth, trades and queue execution.",
    4697: "Archived sizing and absolute price distances are for LTC/USDT on CoinEx.",
    4795: "All native order attempts used the published 1 USDT market-buy amount, below the reviewed Binance spot minimum.",
    4840: "Market and limit order teaching fixture lacks a historical trading rule.",
    4899: "Published leverage recovered. Perpetual exposure and funding must reconcile with the native broker ledger.",
    4920: "Execution-only buy iceberg requires the original order slicing and queue model.",
    4921: "Execution-only sell iceberg requires seeded inventory and the original order queue model.",
    5140: "Archive uses hourly base candles while its logic explicitly requests fifteen-minute records.",
    5618: "Flash-crash grid requires a historically supported intrabar fill and queue model.",
}


def source_config(code):
    block = re.search(r"/\*\s*backtest\s+(.*?)\*/", code, re.DOTALL | re.IGNORECASE)
    fields = dict(re.findall(r"(?m)^([\w]+):\s*([^\r\n]+)", block[1])) if block else {}
    parsed = {}
    if "args" in fields:
        for arg in json.loads(fields["args"]):
            assert isinstance(arg[0], str) and type(arg[1]) in (int, float, bool, str)
            assert arg[0] not in parsed
            parsed[arg[0]] = arg[1]
    return fields, parsed


def extract(archive, work):
    backlog = read(ROOT / "remaining-backtest-coverage.json")["disposition"]
    coverage, candidates, chosen = [], [], {}
    with ZipFile(archive) as fmz:
        for row in backlog:
            url = row["source"]
            revision = f"/fmzquant/strategies/blob/{FMZ_REF}/"
            if row["status"].startswith("Tested") or revision not in url:
                continue
            i = row["id"]
            relative = unquote(url.split(revision, 1)[1])
            raw = fmz.read(f"strategies-{FMZ_REF}/{relative}")
            document = raw.decode("utf-8")
            blocks = [(language.strip().lower(), code) for language, code in BLOCKS.findall(document)]
            js = [code for _, code in blocks if JS_MAIN.search(code)]
            if not js and any(PINE_ORDERS.search(code) for _, code in blocks):
                continue
            links = re.findall(r"(?m)^https://www\.fmz\.com/strategy/[0-9]+\s*$", document)
            chosen[i] = {"id": i, "name": row["name"], "source": url, "source_sha256": hashlib.sha256(raw).hexdigest(),
                         "parameter_page": links[-1].strip() if links else ""}
            if not js:
                languages = sorted({language for language, _ in blocks if language})
                label = ", ".join(languages) or "unlabelled text"
                coverage.append([i, PENDING, f"Archive contains {label} and has no standalone JavaScript main function."])
                continue
            if len(js) != 1:
                coverage.append([i, PENDING, f"Archive contains {len(js)} distinct JavaScript entry blocks with no selected configuration."])
                continue
            try:
                fields, args = source_config(js[0])
            except (ValueError, AssertionError, TypeError, IndexError):
                coverage.append([i, PENDING, "Archive's strategy argument defaults are not a complete JSON list of supported scalar values."])
                continue
            candidates.append({**chosen[i], "code": js[0], "fields": fields, "args": args})
    assert len(chosen) == len(coverage) + len(candidates)
    work.mkdir(exist_ok=True, parents=True)
    write(work / "native-source-candidates.json", candidates)
    write(work / "native-source-index.json", chosen)
    write(work / "native-source-coverage.json", coverage)
    print(f"{len(chosen)} native source dispositions and {len(candidates)} JavaScript candidates")


def summary(work):
    candidate = {x["id"]: x for x in read(work / "native-source-candidates.json")}
    stats = read(work / "native-screen.json")
    assert candidate.keys() == {x["id"] for x in stats}
    for row in stats:
        if row["reason"] is None:
            item = candidate[row["id"]]
            print(row["id"], "futures" if row["futures"] else "spot", item["fields"].get("period", ""),
                  item["fields"].get("exchanges", ""), item["name"])
    print(Counter(x["reason"] is None for x in stats))


def order_metrics(record, trial, *, market_buy_fee_on_turnover=False):
    feed = trial["feed"]
    begin, end = (stamp(feed[k]) * 1000 for k in ("start", "end"))
    assert end - 60000 <= record["last"]["Time"] <= end
    source = (trial["directory"] / feed["file"]).read_bytes()
    assert hashlib.sha256(source).hexdigest() == feed["sha256"]
    market_bars = {row[0]: row for row in json.loads(source)["data"]}
    orders = sorted(record["orders"], key=lambda row: (row["Time"], row["Id"]))
    assert len(orders) == len({row["Id"] for row in orders})
    account = record["account"]
    cash, stocks, lots, trades = EQUITY, 0.0, deque(), []
    for row in orders:
        time, amount, average = (row[key] for key in ("Time", "DealAmount", "AvgPrice"))
        assert begin <= time < end and row["Type"] in (0, 1) and row["Symbol"] == feed["symbol"]
        if not amount:
            continue
        assert amount > 0 and average > 0
        step = feed["base_seconds"] * 1000
        candle = market_bars[time // step * step]
        assert candle[5] > 0
        turnover = amount * average
        if row["Type"] == 0:
            costs = turnover * FEE
            if row["Price"] == 0 and not market_buy_fee_on_turnover:
                costs /= 1 - FEE
            lots.append((amount, average, costs / amount))
            cash -= turnover + costs
            stocks += amount
            continue
        cash += turnover * (1 - FEE)
        stocks -= amount
        while amount > 1e-9:
            quantity, price, entry_cost = lots.popleft()
            matched = min(quantity, amount)
            gross = matched * (average - price)
            fee_only = gross - matched * (entry_cost + average * FEE)
            net = fee_only - matched * (price + average) * EXECUTION
            trades.append((time, gross, fee_only, net))
            amount -= matched
            if quantity - matched > 1e-9:
                lots.appendleft((quantity - matched, price, entry_cost))
    cash_error = cash - account["Balance"] - account["FrozenBalance"]
    asset_error = stocks - account["Stocks"] - account["FrozenStocks"]
    assert abs(cash_error) <= 1e-7 and abs(asset_error) <= 1e-9, "Independent cash or stock reconciliation failed"
    if not lots:
        assert math.isclose(sum(row[2] for row in trades), cash - EQUITY, rel_tol=0, abs_tol=1e-7)
    return trades, len(lots), {"cash_error": cash_error, "asset_error": asset_error}


def finalize(work, output):
    items = {int(i): row for i, row in read(work / "native-source-index.json").items()}
    defaults = read(work / "native-public-parameters.json")
    screened = {row["id"]: row["reason"] for row in read(work / "native-enriched-screen.json")}
    candidates = {row["id"]: row for row in read(work / "native-enriched-candidates.json")}
    coverage = {row[0]: row[1:] for row in read(work / "native-source-coverage.json")}
    for i, reason in screened.items():
        coverage[i] = [PENDING, reason or "Complete JavaScript declarations. Needs a reconciled native run with the archived venue and instrument settings."]
    if (work / "native-python-screen.json").exists():
        for row in read(work / "native-python-screen.json"):
            i = int(row["id"])
            candidates[i] = row
            coverage[i] = [PENDING, row.get("reason") or "Standalone Python strategy needs a native historical order replay."]
    coverage.update({i: [PENDING, reason] for i, reason in MODEL_BLOCKS.items() if i in items})
    selections = read(work / "native-evidence-files.json")
    jobs = {(x["id"], x["feed"]["coin"], x["feed"]["start"]): x for x in read(work / "native-jobs.json")}
    records = defaultdict(list)
    for filename in selections:
        filename = work / filename
        for line in filename.read_text(encoding="utf-8").splitlines():
            trial = json.loads(line)
            records[trial["id"]].append(trial)
    evidence, rows = [], []
    for i, trials in records.items():
        reason = []
        maps, used_feeds = {}, []
        for record in trials:
            key = (i, record["coin"], record["start"])
            job = jobs[key]
            used_feeds.append(job["feed"])
            row = {"id": i, "coin": key[1], "start": key[2], "feed": job["feed"]["sha256"]}
            if record.get("reason"):
                why = re.sub(r"\x1b\[[0-9;]*m", "", record["reason"]).splitlines()[0]
                reason.append(why)
                evidence.append({**row, "reason": why})
                continue
            try:
                trades, open_lots, checks = order_metrics(record, {**job, "directory": work})
            except (AssertionError, KeyError, IndexError, TypeError) as e:
                why = str(e) or "Native order ledger lacks fields required for independent reconciliation"
                reason.append(why)
                evidence.append({**row, "reason": why})
                continue
            assert (key[1], key[2]) not in maps
            maps[key[1], key[2]] = (trades, open_lots)
            evidence.append({**row, **checks, "last_snapshot": record["last"]["Time"],
                             "skipped_repeated_polls": record["skipped"], "resting_orders": record["resting"],
                             "orders": record["orders"], "account": record["account"]})
        if i in MODEL_BLOCKS:
            continue
        if set(maps) != {(coin, start) for coin in ("BTC", "ETH") for start in PERIODS}:
            coverage[i] = [PENDING, "; ".join(sorted(set(reason))) or "Native replay incomplete across the two historical windows and assets"]
            continue
        interval = used_feeds[0]["period"]
        item = items[i]
        language = trials[0].get("language", "JavaScript")
        trading = False
        for start, period in PERIODS.items():
            btc, ub = maps["BTC", start]
            eth, ue = maps["ETH", start]
            trading |= bool(btc or eth)
            for market, trades, opened in (("BTCUSDT spot", btc, ub), ("ETHUSDT spot", eth, ue),
                                           ("BTCUSDT + ETHUSDT spot", btc + eth, ub + ue)):
                row = summarize((GROUP, item["name"], market, "Native spot strategy orders"), period, trades, opened)
                row.update(id=i, source=item["source"], source_sha256=item["source_sha256"], interval=interval,
                           archive_interval=candidates[i]["fields"].get("period", ""), market_data="FMZ public Binance spot tape",
                           quote_currency="USDT", language=language)
                rows.append(row)
        coverage[i] = ["Tested · FMZ native expanded" if trading else "Tested · FMZ native expanded, no closes",
                       f"Native {language} {interval} Binance spot simulation with verified public source settings and reconciled broker cash and inventory."]
    assert items.keys() == coverage.keys()
    feeds = {json.dumps(item["feed"], sort_keys=True): item["feed"] for item in jobs.values()}
    specifications = [{"id": job["id"], "feed": job["feed"], "cfg": job["cfg"], "args": job["item"]["args"],
                       "plotting": job["item"].get("plotting", False),
                       "lang": "JavaScript" if JS_MAIN.search(job["item"]["code"]) else "Python",
                       "source_sha256": job["item"]["source_sha256"]} for job in jobs.values()]
    write(output, {
        "source_revision": FMZ_REF, "engine": "Pinned FMZ JavaScript WASM and Python native library",
        "coverage": [[i, *v] for i, v in sorted(coverage.items())],
        "public_parameters": defaults, "market_feeds": list(feeds.values()), "order_evidence": evidence,
        "job_specifications": specifications,
        "coverage_source": "remaining-backtest-coverage.json as of cb4745c", "results": rows,
    })
    print(len(coverage), "dispositions and", len(rows), "reconciled rows")


def stage(report, archive, work):
    from research.fmz_native_spot_replay import ENGINE, ENGINE_SHA, digest, get

    items = {int(i): row for i, row in read(work / "native-source-index.json").items()}
    manifest = read(report)
    source_cache = {}
    jobs = []
    with ZipFile(archive) as fmz:
        for spec in manifest["job_specifications"]:
            i = spec["id"]
            item = items[i]
            expected = spec["source_sha256"]
            if i not in source_cache:
                relative = unquote(item["source"].split(f"/{FMZ_REF}/", 1)[1])
                raw = fmz.read(f"strategies-{FMZ_REF}/{relative}")
                assert digest(raw) == expected
                pattern = JS_MAIN if spec["lang"] == "JavaScript" else re.compile(r"(?m)^def\s+main\s*\(")
                match = [body for _, body in BLOCKS.findall(raw.decode("utf-8")) if pattern.search(body)]
                assert len(match) == 1, i
                source_cache[i] = match[0].lstrip("\ufeff")
            jobs.append({"id": i, "item": {**item, "code": source_cache[i], "args": spec["args"],
                                          "plotting": spec["plotting"]}, "feed": spec["feed"], "cfg": spec["cfg"]})
    for feed in manifest["market_feeds"]:
        for tape in (feed, feed.get("warmup")):
            if not tape:
                continue
            file = work / tape["file"]
            assert file.parent == work and digest(file.read_bytes()) == tape["sha256"]
    original = get(ENGINE, work / "upstream.cjs")
    assert digest(original) == ENGINE_SHA
    before = b"},httpGet=function(url){let options"
    assert original.count(before) == 1
    patched = original.replace(before, b"},httpGet=function(url){return globalThis.__offlineProbe(url);let options")
    (work / "fmz-wasm-engine.cjs").write_bytes(patched)
    for file in ("fmz_native_expanded_worker.cjs", "fmz_native_python_worker.py"):
        (work / file).write_bytes((ROOT / file).read_bytes())
    write(work / "native-jobs.json", jobs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("extract").add_argument("archive", type=Path)
    sub.add_parser("summary")
    sub.add_parser("finalize").add_argument("output", type=Path)
    staging = sub.add_parser("stage")
    staging.add_argument("report", type=Path)
    staging.add_argument("archive", type=Path)
    for action in sub.choices.values():
        action.add_argument("work", type=Path)
    args = parser.parse_args()
    if args.action == "extract":
        extract(args.archive, args.work)
    elif args.action == "finalize":
        finalize(args.work, args.output)
    elif args.action == "stage":
        stage(args.report, args.archive, args.work)
    else:
        summary(args.work)
