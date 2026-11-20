"""Stage source-bound single-market variants of the archived spot EMA study."""

import argparse
import json
import re
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.delta_strategy_replay import EQUITY, FEE, summarize
from research.fmz_native_expanded_replay import BLOCKS, order_metrics
from research.fmz_native_round3 import KEYS, WINDOWS
from research.fmz_native_round5 import replace_once
from research.fmz_native_round6_audit import ROOT, digest
from research.fmz_native_round6_replay import public_settings

IDENT = 4687
STEM = "round11-native-ema-depth20"
WORKER = STEM + "-worker.cjs"
ENGINE = STEM + "-engine.cjs"
AUTHOR = "https://www.fmz.com/strategy/333783"
NOTES = (
    "Replay the published ETH slot's 10/15 closed-bar EMA and one-base-unit order size "
    "in individual spot portfolios. BTC applies the same slot settings. The author suite "
    "uses shared quote cash across three symbols; this study uses separate 10,000 USDT "
    "accounts, a benchmark 15m chart, one-minute decision polling and FMZ's simulated depth. "
    "The published one-BTC order can exceed the study's starting cash."
)


def archived(archive, public):
    source = next(
        x
        for x in read(ROOT / "remaining-backtest-round7-coverage.json")["disposition"]
        if x["id"] == IDENT
    )
    with ZipFile(archive) as pin:
        raw = pin.read(
            f"strategies-{FMZ_REF}/" + unquote(source["source"].rsplit("/", 1)[-1])
        )
    assert digest(raw) == source["pinned_document_sha256"] and AUTHOR.encode() in raw
    [code] = [
        body
        for tag, body in BLOCKS.findall(raw.decode())
        if tag.strip().lower() == "javascript"
    ]
    code = code.lstrip("\ufeff").replace("\r\n", "\n")
    params = public_settings(
        public / f"{IDENT}.html", {"code": code, "parameter_page": AUTHOR}
    )
    fields = params["args"]
    assert fields == {
        "symbols": "ETH_USDT,ETC_USDT,LTC_USDT",
        "ema1Periods": "10,15,20",
        "ema2Periods": "15,20,25",
        "orderAmounts": "1,1,1",
        "takeLevel": 10,
        "isReset": False,
    }
    code = replace_once(
        code, "            Sleep(1000)\n    \t})", "            Sleep(60000)\n    \t})"
    )
    assert set(re.findall(r"\b_\.(\w+)\(", code)) == {"each"}
    code = (
        """const _ = Object.freeze({each(collection, visit) {
    for (const key of Object.keys(collection)) {
        visit(collection[key], Array.isArray(collection) ? Number(key) : key, collection);
    }
    return collection;
}});
"""
        + code
    )
    return source, digest(raw), code, params


def make_worker(target):
    engine = (target / "fmz-wasm-engine.cjs").read_bytes()
    original = b"DepthDeep:5,DepthAmount:20,FaultTolerant:0"
    adjusted = b"DepthDeep:20,DepthAmount:20,FaultTolerant:0"
    assert engine.count(original) == 1
    (target / ENGINE).write_bytes(engine.replace(original, adjusted))
    old = (target / "round6-native-worker.cjs").read_text(encoding="utf-8")
    code = old.replace("round6-native", STEM).replace(
        "./fmz-wasm-engine.cjs", "./" + ENGINE
    )
    key = "    for (const key of ['GetDepth', 'GetTrades', 'GetIndex', 'GetTickers', 'IO', 'Go', 'SetProxy']) {"
    code = replace_once(
        code,
        key,
        """    const nativeDepth = exchange.GetDepth;
    assert.equal(typeof nativeDepth, 'function');
    exchange.GetDepth = endGuard(() => {
      const book = nativeDepth();
      assert.ok(book.Asks.length > args.takeLevel && book.Bids.length > args.takeLevel,
        'Insufficient native simulated book depth for the published index');
      return book;
    });
    scope.Chart = () => ({add() {}, reset() {}});
    for (const key of ['GetTrades', 'GetIndex', 'GetTickers', 'IO', 'Go', 'SetProxy']) {""",
    )
    (target / WORKER).write_text(code, encoding="utf-8", newline="\n")


def stage(archive, public, target):
    item, source_hash, code, params = archived(archive, public)
    historical = read(target / "round5-native-javascript-jobs.json")
    feeds = {}
    for trial in historical:
        feed = trial["feed"]
        if feed["base_seconds"] == 300:
            feeds.setdefault((feed["coin"], feed["start"]), feed)
    jobs = []
    for key in sorted(KEYS):
        common = feeds[key]
        bound = {name: common[name] for name in ("file", "sha256")}
        market = target / bound["file"]
        assert digest(market.read_bytes()) == bound["sha256"]
        coin = common["coin"]
        options = {
            **params["args"],
            "symbols": coin + "_USDT",
            "ema1Periods": "10",
            "ema2Periods": "15",
            "orderAmounts": "1",
        }
        jobs.append(
            {
                "id": IDENT,
                "name": item["name"],
                "source": item["source"],
                "source_sha256": source_hash,
                "code": code,
                "args": options,
                "cfg": {
                    "balance": EQUITY,
                    "fee": FEE,
                    "timeout": 170_000,
                    "empty_state": True,
                },
                "feed": {
                    **common,
                    "period": "15m",
                    "market": bound,
                    "eid": "Binance",
                    "step": 300,
                },
                "public": params,
            }
        )
    make_worker(target)
    write(target / (STEM + "-jobs.json"), jobs)


def finish(target, output):
    trial_data = read(target / (STEM + "-jobs.json"))
    worker_digest = digest((target / WORKER).read_bytes())
    probe = read(target / "round3-isolation-js.json")
    assert probe["privateRead"] == "ERR_ACCESS_DENIED" and probe["network"] == "EACCES"
    receipts = {}
    for line in (
        (target / f"{STEM}-js-{IDENT}.jsonl").read_bytes().splitlines(keepends=True)
    ):
        if line.endswith(b"\n"):
            record = json.loads(line)
            assert record["worker_sha256"] == worker_digest
            receipts[record["coin"], record["start"]] = record, digest(line.rstrip())
    evidence, results, reasons, outcomes = [], [], set(), {}
    any_fill = False
    for trial in trial_data:
        feed = trial["feed"]
        key = feed["coin"], feed["start"]
        record, sha = receipts.get(key, ({}, None))
        item = {k: trial[k] for k in ("source_sha256", "args", "public")}
        proof = {**item, "feed": feed, "receipt_sha256": sha, "id": IDENT}
        try:
            if not record or "reason" in record:
                raise ValueError(record.get("reason", "Incomplete native receipt"))
            assert record["code_sha256"] == digest(trial["code"].encode())
            receipt = {**record, "last": {"Time": record["snapshotTime"]}}
            trades, opened, ledger = order_metrics(
                receipt, {"feed": feed, "directory": target}
            )
            assert all(order["Price"] != 0 for order in record["orders"])
            outcomes[key] = trades, opened
            any_fill |= any(order["DealAmount"] > 0 for order in record["orders"])
            proof.update(
                accounting=ledger,
                order_count=len(record["orders"]),
                closing_account=record["account"],
            )
        except (AssertionError, IndexError, KeyError, ValueError) as error:
            reason = (
                re.sub(r"\x1b\[[0-9;]*m", "", str(error))
                or "Native ledger evidence is incomplete"
            )
            reasons.add(reason)
            proof["reason"] = reason
        evidence.append(proof)
    if outcomes.keys() == KEYS and any_fill:
        for start, (_, window) in WINDOWS.items():
            b, bo = outcomes["BTC", start]
            e, eo = outcomes["ETH", start]
            for market, trades, opened in (
                ("BTCUSDT", b, bo),
                ("ETHUSDT", e, eo),
                ("BTCUSDT + ETHUSDT", b + e, bo + eo),
            ):
                row = summarize(
                    (
                        "FMZ native JavaScript EMA variant",
                        trial["name"],
                        market + " spot",
                        "Archived EMA crossings",
                    ),
                    window,
                    trades,
                    opened,
                )
                row.update(
                    id=IDENT,
                    source=trial["source"],
                    interval="15m",
                    quote_currency="USDT",
                )
                results.append(row)
        status = "Tested · FMZ native EMA single-market variant"
        why = NOTES
    else:
        status = "Pending · FMZ EMA native depth/input study"
        why = " | ".join(sorted(reasons)) or "No order fill validated the strategy."
    write(
        output,
        {
            "coverage": [[IDENT, status, why]],
            "results": results,
            "evidence": evidence,
            "worker_sha256": worker_digest,
            "isolation": probe,
            "simulated_book": {
                "original_wrapper_sha256": digest(
                    (target / "fmz-wasm-engine.cjs").read_bytes()
                ),
                "configured_wrapper_sha256": digest((target / ENGINE).read_bytes()),
                "levels": 20,
                "amount_per_level": 20,
                "reference": "https://www.fmz.com/user-guide/backtesting-system/overview-and-starting-a-backtest",
            },
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("public_cache", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--finish", type=Path)
    args = parser.parse_args()
    if args.finish:
        finish(args.target, args.finish)
    else:
        stage(args.archive, args.public_cache, args.target)
