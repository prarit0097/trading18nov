"""Replay the archived sell-first grid using public successor-venue data."""

import argparse
import json
import re
from collections import deque
from itertools import pairwise
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.delta_strategy_replay import EQUITY, EXECUTION, FEE, drawdown, summarize
from research.fmz_native_expanded_replay import BLOCKS
from research.fmz_native_public_params import StrategyPage, normalized
from research.fmz_native_round3 import KEYS, WINDOWS
from research.fmz_native_round6_audit import ROOT, digest
from research.fmz_native_round7 import file_opening, stamp

IDENT = 5194
STEM = "round11-htx-grid-hourly-boundary"
WORKER = STEM + "-worker.cjs"
ENGINE = STEM + "-engine.cjs"
REFERENCE_STEM = STEM + "-reference-hour"
AUTHOR = "https://www.fmz.com/strategy/311968"
REBRAND = "https://square.htx.com/huobi-rebrands-to-htx-at-token2049/"
NOTES = (
    "Preserve the archived sell-first override and daily/hourly configuration, and use "
    "the source-matched public order settings. The study uses later reported HTX data after "
    "Huobi's rebrand, with one seeded base unit to meet the full ten 0.1-unit sell grid. "
    "BTC/USDT is the archived instrument. ETH/USDT is a separate market port. Each initial "
    "wallet has 10,000 USDT plus its one base unit."
)


def bind_source(archive, cache):
    item = next(
        r
        for r in read(ROOT / "remaining-backtest-round7-coverage.json")["disposition"]
        if r["id"] == IDENT
    )
    with ZipFile(archive) as pin:
        raw = pin.read(
            f"strategies-{FMZ_REF}/" + unquote(item["source"].rsplit("/", 1)[-1])
        )
    assert digest(raw) == item["pinned_document_sha256"] and AUTHOR.encode() in raw
    [code] = [
        body
        for tag, body in BLOCKS.findall(raw.decode())
        if tag.strip().lower() == "javascript"
    ]
    assert '"eid":"Huobi"' in code and '"currency":"BTC_USDT"' in code
    assert "period: 1d" in code and "basePeriod: 1h" in code
    assert not re.search(r"\bGetRecords\b", code)
    [overrides] = re.findall(r"(?m)^args:\s*(\[.*\])\s*$", code)
    config = dict(json.loads(overrides))
    assert config == {"OpType": 1}
    page_bytes = (cache / f"{IDENT}.html").read_bytes()
    page = StrategyPage()
    page.feed(page_bytes.decode())
    expected = normalized(code)
    matched = max(
        len(r)
        for preview in page.previews
        if len(r := normalized(preview)) >= 90 and r in expected
    )
    args = {**page.values, **config}
    assert args["AllNum"] == 10 and args["AmountOnce"] == 0.1
    assert args["AmountCoefficient"] == "*1" and args["EnableAccountCheck"]
    assert args["EnableStopLoss"] is False and args["EnableStopWin"] is False
    assert "AmountType = 0;" in code
    return (
        item,
        code,
        args,
        {
            "page": AUTHOR,
            "sha256": digest(page_bytes),
            "preview_chars": matched,
            "archive_overrides": config,
        },
    )


def make_tape(work, target, providers):
    rows, chart = [], None
    for receipt in providers:
        raw = (work / receipt["file"]).read_bytes()
        assert digest(raw) == receipt["sha256"]
        data = json.loads(raw)
        assert data["detail"]["eid"] == "HTX" and len(data["data"]) == receipt["rows"]
        if chart:
            assert (
                chart["detail"] == data["detail"]
                and rows[-1][:2] == data["data"][0][:2]
            )
            rows.pop()
        rows.extend(data["data"])
        chart = data
    step = providers[0]["period"] * 1000
    assert all(b[0] - a[0] == step for a, b in pairwise(rows))
    name = f"round11-htx-{providers[0]['coin']}-{step}.json"
    write(target / name, {**chart, "data": rows})
    return {
        "file": name,
        "sha256": digest((target / name).read_bytes()),
        "providers": providers,
    }


def stage(archive, work, cache, target):
    item, code, args, public = bind_source(archive, cache)
    manifest = read(work / "htx-spots-round11-manifest.json")
    jobs = []
    for coin in ("BTC", "ETH"):
        tapes = {
            step: make_tape(
                work,
                target,
                [r for r in manifest if r["coin"] == coin and r["period"] == step],
            )
            for step in (3600, 86400)
        }
        for start, (end, _) in WINDOWS.items():
            feed = {
                **tapes[3600],
                "coin": coin,
                "symbol": coin + "_USDT",
                "start": start,
                "end": end,
                "base_seconds": 3600,
                "eid": "HTX",
                "base": "1h",
                "step": 3600,
                "period": "1d",
                "market": tapes[3600],
                "daily": tapes[86400],
            }
            seed = file_opening(target, feed, {"stocks": 1}, IDENT)
            assert seed["base"] == 1 and seed["cash"] == EQUITY
            jobs.append(
                {
                    "id": IDENT,
                    "source": item["source"],
                    "name": item["name"],
                    "source_sha256": item["pinned_document_sha256"],
                    "code": code,
                    "args": args,
                    "public": public,
                    "feed": feed,
                    "cfg": {
                        "balance": EQUITY,
                        "opening": seed,
                        "fee": FEE,
                        "timeout": 200_000,
                        "empty_state": True,
                    },
                }
            )
    engine = (target / "fmz-wasm-engine.cjs").read_bytes()
    default = b"DepthAmount:20,FaultTolerant:0,PreBarLen:1e3"
    selected = b"DepthAmount:20,FaultTolerant:0,PreBarLen:200"
    assert engine.count(default) == 1
    (target / ENGINE).write_bytes(engine.replace(default, selected))
    worker = (target / "round6-native-worker.cjs").read_text(encoding="utf-8")
    worker = worker.replace("round6-native", STEM).replace(
        "./fmz-wasm-engine.cjs", "./" + ENGINE
    )
    worker = worker.replace(
        "end: feed.end + ' 00:05:00'",
        "end: feed.end + ' 01:05:00'",
    ).replace("end - 55000", "end - 420000")
    before = worker.index("    const snapshotTime = scope.Date.now();")
    after = worker.index("    const account = exchange.GetAccount();", before)
    worker = (
        worker[:before]
        + "    const snapshotTime = scope.Date.now();\n"
        + "    assert.ok(end - 420000 <= snapshotTime && snapshotTime < end, "
        + "'Snapshot falls outside the final seven-minute observation interval');\n"
        + worker[after:]
    )
    worker = worker.replace(
        "    return {last, snapshotTime,",
        "    const ledgerTime = scope.Date.now();\n"
        "    assert.ok(snapshotTime <= ledgerTime && ledgerTime < end, "
        "'Reading wallet and history crossed the window boundary');\n"
        "    return {snapshotTime, ledgerTime,",
    )
    (target / WORKER).write_text(worker, encoding="utf-8", newline="\n")
    write(target / (STEM + "-jobs.json"), jobs)
    reference = worker.replace(STEM + "-js", REFERENCE_STEM + "-js")
    reference = reference.replace("end - 420000", "end - 3600000")
    reference = reference.replace(
        "assert.ok(end - 3600000 <= snapshotTime",
        "assert.ok(end - 4800000 <= snapshotTime",
    ).replace(
        "'Snapshot falls outside the final seven-minute observation interval'",
        "'Snapshot outside observation interval ' + JSON.stringify({snapshotTime, end})",
    )
    reference = reference.replace(
        "    if (selection.size && !selection.has(trial.id)) continue;",
        "    if (trial.feed.start !== '2026-09-23') continue;\n"
        "    if (selection.size && !selection.has(trial.id)) continue;",
    )
    (target / (REFERENCE_STEM + "-worker.cjs")).write_text(
        reference, encoding="utf-8", newline="\n"
    )


def reconcile(record, target, feed, seed):
    raw = (target / feed["file"]).read_bytes()
    assert digest(raw) == feed["sha256"]
    bars = {r[0]: r for r in json.loads(raw)["data"]}
    start, end = (stamp(feed[name]) * 1000 for name in ("start", "end"))
    assert seed["timestamp"] < start
    tolerance = {"2026-09-23": 4800000, "2026-10-21": 420000}[feed["start"]]
    assert end - tolerance <= record["snapshotTime"] <= record["ledgerTime"] < end
    cash, stock = seed["cash"], seed["base"]
    lots = deque([(stock, seed["price"], 0)])
    closed = []
    orders = sorted(record["orders"], key=lambda o: (o["Time"], o["Id"]))
    assert len({o["Id"] for o in orders}) == len(orders)
    for order in orders:
        at, qty, price = (order[k] for k in ("Time", "DealAmount", "AvgPrice"))
        assert start <= at <= record["ledgerTime"] and order["Symbol"] == feed["symbol"]
        assert order["Type"] in (0, 1)
        if not qty:
            continue
        step = feed["base_seconds"] * 1000
        assert qty > 0 and price > 0 and bars[at // step * step][5] > 0
        if order["Type"] == 0:
            fee = price * FEE / (1 - FEE if order["Price"] == 0 else 1)
            cash -= qty * (price + fee)
            stock += qty
            lots.append((qty, price, fee))
            continue
        cash += qty * price * (1 - FEE)
        stock -= qty
        while qty > 1e-9:
            amount, entry, entry_fee = lots.popleft()
            matched = min(amount, qty)
            gross = matched * (price - entry)
            fee_only = gross - matched * (entry_fee + price * FEE)
            closed.append(
                (at, gross, fee_only, fee_only - matched * (price + entry) * EXECUTION)
            )
            qty -= matched
            if amount - matched > 1e-9:
                lots.appendleft((amount - matched, entry, entry_fee))
    account = record["account"]
    cash_error = cash - account["Balance"] - account["FrozenBalance"]
    asset_error = stock - account["Stocks"] - account["FrozenStocks"]
    assert abs(cash_error) <= 1e-7 and abs(asset_error) <= 1e-9, (
        "Seeded native wallet did not reconcile"
    )
    return closed, len(lots), {"cash_error": cash_error, "asset_error": asset_error}


def finish(target, output):
    jobs = read(target / (STEM + "-jobs.json"))
    probe = read(target / "round3-isolation-js.json")
    assert probe["privateRead"] == "ERR_ACCESS_DENIED" and probe["network"] == "EACCES"
    receipts, worker_hashes = {}, {}
    for start, stem in (("2026-09-23", REFERENCE_STEM), ("2026-10-21", STEM)):
        worker_hash = digest((target / (stem + "-worker.cjs")).read_bytes())
        worker_hashes[start] = worker_hash
        for line in (
            (target / f"{stem}-js-{IDENT}.jsonl").read_bytes().splitlines(keepends=True)
        ):
            if line.endswith(b"\n"):
                record = json.loads(line)
                assert record["worker_sha256"] == worker_hash
                if record["start"] == start:
                    receipts[record["coin"], start] = record, digest(line.rstrip())
    outcomes, evidence, results, reasons = {}, [], [], set()
    for trial in jobs:
        feed = trial["feed"]
        seed = trial["cfg"]["opening"]
        key = feed["coin"], feed["start"]
        record, receipt_hash = receipts.get(key, ({}, None))
        row = {
            "id": IDENT,
            "feed": feed,
            "opening_inventory": seed,
            "raw_receipt_sha256": receipt_hash,
            "public": trial["public"],
            "args": trial["args"],
            "source_sha256": trial["source_sha256"],
        }
        try:
            if not record or "reason" in record:
                raise ValueError(record.get("reason", "Incomplete native ledger"))
            assert record["code_sha256"] == digest(trial["code"].encode())
            trades, open_lots, recon = reconcile(record, target, feed, seed)
            outcomes[key] = (
                trades,
                open_lots,
                seed["cash"] + seed["price"] * seed["base"],
            )
            row.update(
                order_count=len(record["orders"]),
                closed_fifo=len(trades),
                accounting=recon,
                closing_account=record["account"],
                snapshot_time=record["snapshotTime"],
                ledger_time=record["ledgerTime"],
            )
        except (AssertionError, IndexError, KeyError, ValueError) as exc:
            why = (
                str(exc).splitlines()[0]
                if str(exc)
                else "Independent native ledger failed"
            )
            reasons.add(why)
            row["reason"] = why
        evidence.append(row)
    if outcomes.keys() == KEYS and any(v[0] for v in outcomes.values()):
        for start, (_, label) in WINDOWS.items():
            btc, bo, be = outcomes["BTC", start]
            eth, eo, ee = outcomes["ETH", start]
            for market, trades, opened, equity in (
                ("BTCUSDT", btc, bo, be),
                ("ETHUSDT", eth, eo, ee),
                ("BTCUSDT + ETHUSDT", btc + eth, bo + eo, be + ee),
            ):
                row = summarize(
                    (
                        "FMZ HTX sell-first grid variant",
                        trial["name"],
                        market + " spot",
                        "Archived grid orders",
                    ),
                    label,
                    trades,
                    opened,
                )
                scale = EQUITY / equity
                for field, i in (("gross", 1), ("fee", 2), ("net", 3)):
                    value, pct = drawdown(
                        (entry[0], entry[i] * scale) for entry in trades
                    )
                    row[field + "_dd"], row[field + "_dd_pct"] = value / scale, pct
                row.update(
                    id=IDENT,
                    source=trial["source"],
                    interval="1d",
                    quote_currency="USDT",
                    starting_equity=equity,
                )
                results.append(row)
        status, why = "Tested · FMZ HTX seeded grid variant", NOTES
    else:
        status, why = (
            "Pending · HTX grid native replay",
            " | ".join(sorted(reasons)) or "No realized native closes",
        )
    write(
        output,
        {
            "coverage": [[IDENT, status, why]],
            "results": results,
            "evidence": evidence,
            "worker_sha256": worker_hashes,
            "isolation": probe,
            "venue_provenance": REBRAND,
            "snapshot_policy": (
                "Capture the wallet and order history in the last 80 minutes of the "
                "Reference window and the last seven minutes of the Later window. FMZ "
                "simulates coarse intrahour ticks from the source hourly candles. "
                "Final reads never cross the session end."
            ),
            "execution_model": {
                "fee_each_side": FEE,
                "friction_each_side": EXECUTION,
                "fees_and_balances": (
                    "Native simulated fees reconcile to each closing wallet. "
                    "Reported net additionally deducts the shared research "
                    "friction from entry and exit notional. The seeded opening "
                    "inventory has a pre-window mark as cost basis."
                ),
                "drawdown": "Realized FIFO lot P&L divided by marked starting equity.",
            },
            "ticker_only_warmup": {
                "max_bars": 200,
                "original_wrapper_sha256": digest(
                    (target / "fmz-wasm-engine.cjs").read_bytes()
                ),
                "configured_wrapper_sha256": digest((target / ENGINE).read_bytes()),
                "reason": "The archived program reads tickers and account state. The documented maximum K-line history setting bounds unused bootstrap data.",
            },
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("work", type=Path)
    parser.add_argument("cache", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--finish", type=Path)
    args = parser.parse_args()
    if args.finish:
        finish(args.target, args.finish)
    else:
        stage(args.archive, args.work, args.cache, args.target)
