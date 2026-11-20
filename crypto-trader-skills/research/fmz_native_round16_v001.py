"""Replay the pinned Martingale V001 source and reconstruct observed spot cycles."""

import argparse
import json
from itertools import combinations, pairwise
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.delta_strategy_replay import (
    EQUITY,
    EXECUTION,
    FEE,
    drawdown,
    stamp,
    summarize,
)
from research.fmz_native_expanded_replay import BLOCKS
from research.fmz_native_round3 import KEYS, WINDOWS
from research.fmz_native_round6_audit import ROOT, digest

IDENT = 5687
PREVIOUS = "round14-legacy-spot-timed"
BASE = "round15-native-v001"
STEM = BASE + "-account-timed-bounded"
AUTHOR = "https://www.fmz.com/strategy/288966"
CONFIG = {
    "DF": "0,1,2,3,4,5,6,7",
    "JYD": "$$$__enc__$$$BTC",
    "startNum": True,
    "minWin": 1.3,
}


def stage(archive, target):
    source = next(
        r
        for r in read(ROOT / "remaining-backtest-round12-coverage.json")["disposition"]
        if r["id"] == IDENT
    )["source"]
    with ZipFile(archive) as z:
        raw = z.read(f"strategies-{FMZ_REF}/" + unquote(source.rsplit("/", 1)[-1]))
    doc = raw.decode()
    [code] = [b for tag, b in BLOCKS.findall(doc) if tag.strip() == "javascript"]
    code = code.lstrip("\r\n")
    assert code.count("JYDlist") == 1 and AUTHOR in doc
    for key, value in CONFIG.items():
        literal = json.dumps(value) if type(value) is bool else value
        assert f"|{key}|{literal}|" in doc
    jobs = []
    for exemplar in read(target / (PREVIOUS + "-jobs.json")):
        if exemplar["id"] != 1847:
            continue
        jobs.append(
            {
                "id": IDENT,
                "source": source,
                "name": "FMZ Martingale V001",
                "code": code,
                "source_sha256": digest(raw),
                "args": CONFIG,
                "cfg": {
                    "balance": EQUITY,
                    "fee": FEE,
                    "timeout": 75_000,
                    "empty_state": True,
                },
                "feed": exemplar["feed"],
            }
        )
    assert len(jobs) == 4
    worker = (target / (PREVIOUS + "-worker.cjs")).read_text(encoding="utf-8")
    worker = worker.replace(PREVIOUS, STEM)
    marker = "    const recent = [];"
    assert worker.count(marker) == 1
    worker = worker.replace(
        marker,
        marker
        + """
    const accountMarks = [];
    let priorAccountTime = null;
    const nativeAccount = exchange.GetAccount;
    exchange.GetAccount = (...args) => {
      const a = nativeAccount(...args);
      if (a) {
        const time = scope.Date.now();
        const cash = a.Balance + a.FrozenBalance, stock = a.Stocks + a.FrozenStocks;
        const prev = accountMarks.at(-1);
        if (!prev || Math.abs(prev[1]-cash)>1e-8 || Math.abs(prev[2]-stock)>1e-12) {
          assert.ok(accountMarks.length <= 5000);
          accountMarks.push([time,cash,stock,priorAccountTime]);
        }
        priorAccountTime = time;
      }
      return a;
    };
""",
    ).replace(
        "return {sourceFailure, recent,", "return {sourceFailure, accountMarks, recent,"
    )
    write(target / (STEM + "-jobs.json"), jobs)
    (target / (STEM + "-worker.cjs")).write_text(worker, encoding="utf-8", newline="\n")


def amounts(order):
    qty = order["DealAmount"] * (1 if order["Type"] == 0 else -1)
    gross = -qty * order["AvgPrice"]
    fee = abs(gross) * FEE
    return qty, gross, fee


def match_group(waiting, bounds, before, at, cash, stock):
    candidates = [
        oid
        for oid, order in waiting.items()
        if order["Time"] <= at and bounds[oid][0] <= at and before <= bounds[oid][1]
    ]
    must_fill = {oid for oid in waiting if bounds[oid][1] <= at}
    assert 0 < len(candidates) <= 16
    choices = []
    for count in range(1, len(candidates) + 1):
        for selected in combinations(candidates, count):
            if not must_fill.issubset(selected):
                continue
            qty, gross, fees = map(
                sum, zip(*(amounts(waiting[oid]) for oid in selected))
            )
            if abs(qty - stock) < 1e-9 and abs(gross - fees - cash) < 1e-7:
                choices.append((selected, gross, fees))
    [result] = choices
    return result


def reconcile(record, job):
    feed = job["feed"]
    start, end = (stamp(feed[k]) * 1000 for k in ("start", "end"))
    assert end - 60000 <= record["snapshotTime"] <= end and not record["sourceFailure"]
    assert (
        record["observedHistoryOrders"] + record["resting"]
        == record["attempts"]["accepted"]
    )
    filled = [o for o in record["orders"] if o["DealAmount"]]
    waiting = {o["Id"]: o for o in filled}
    assert len(waiting) == len(filled)
    bounds = dict(record["fillIntervals"])
    assert waiting.keys() == bounds.keys()
    for o in filled:
        a, b = bounds[o["Id"]]
        assert (
            o["Status"] == 1 and o["Price"] > 0 and o["Amount"] == o["DealAmount"] > 0
        )
        assert o["Type"] in (0, 1) and o["Symbol"] == feed["coin"] + "_USDT"
        assert start <= o["Time"] <= a < b <= end
    marks = record["accountMarks"]
    assert marks[0][1:] == [EQUITY, 0, None]
    ledger = []
    mixed = maximum = 0
    gross = simulated_fees = turnover = 0.0
    opening_cash = EQUITY
    for past, active in pairwise(marks):
        at, cash, stock, before = active
        assert past[0] <= before < at <= end and stock >= 0
        matched, change, fees = match_group(
            waiting, bounds, before, at, cash - past[1], stock - past[2]
        )
        maximum = max(maximum, len(matched))
        mixed += len({waiting[oid]["Type"] for oid in matched}) > 1
        gross += change
        simulated_fees += fees
        turnover += sum(abs(amounts(waiting.pop(oid))[1]) for oid in matched)
        if stock:
            continue
        fee_only = gross - simulated_fees
        assert abs(cash - opening_cash - fee_only) < 1e-7
        ledger.append((at, gross, fee_only, fee_only - turnover * EXECUTION))
        gross = simulated_fees = turnover = 0.0
        opening_cash = cash
    assert not waiting and marks[-1][2] == 0
    account = record["account"]
    assert account["Stocks"] == account["FrozenStocks"] == 0
    closing_cash = account["Balance"] + account["FrozenBalance"]
    cash_error = EQUITY + sum(row[2] for row in ledger) - closing_cash
    assert abs(cash_error) < 1e-7 and closing_cash == marks[-1][1]
    return ledger, {
        "filled_orders": len(filled),
        "flat_to_flat_episodes": len(ledger),
        "market_marks": len(marks),
        "largest_observed_fill_group": maximum,
        "mixed_side_groups": mixed,
        "resting_unfilled_orders": record["resting"],
        "submission_totals": record["attempts"],
        "native_wallet": account,
        "fee_accounting_error_usdt": cash_error,
        "snapshot_time": record["snapshotTime"],
    }


def load_receipts(path):
    with path.open("rb") as stream:
        records = []
        for line in stream:
            assert line.endswith(b"\n")
            records.append((json.loads(line), digest(line.rstrip())))
    return {(r["coin"], r["start"]): (r, h) for r, h in records}


def finish(target, output):
    jobs = read(target / (STEM + "-jobs.json"))
    probe = read(target / "round3-isolation-js.json")
    assert probe["privateRead"] == "ERR_ACCESS_DENIED" and probe["network"] == "EACCES"
    worker_hash = digest((target / (STEM + "-worker.cjs")).read_bytes())
    receipts = load_receipts(target / f"{STEM}-js-{IDENT}.jsonl")
    assert receipts.keys() == KEYS
    prior_path = target / f"{BASE}-js-{IDENT}.jsonl"
    original = load_receipts(prior_path) if prior_path.is_file() else {}
    ledgers, evidence, results = {}, [], []
    for job in jobs:
        feed = job["feed"]
        key = feed["coin"], feed["start"]
        record, sha = receipts[key]
        assert record["worker_sha256"] == worker_hash
        assert record["code_sha256"] == digest(job["code"].encode())
        assert digest((target / feed["file"]).read_bytes()) == feed["sha256"]
        if original:
            assert original[key][0]["historySha256"] == record["historySha256"]
        ledgers[key], proof = reconcile(record, job)
        evidence.append(
            {
                **proof,
                "markets": feed,
                "source_sha256": job["source_sha256"],
                "code_sha256": record["code_sha256"],
                "raw_receipt_sha256": sha,
                "native_order_history_sha256": record["historySha256"],
                "sample_final_order_attempts": record["recent"],
            }
        )
    assert all(not ledgers["BTC", start] for start in WINDOWS)
    for start, (_, label) in WINDOWS.items():
        btc, eth = (ledgers[asset, start] for asset in ("BTC", "ETH"))
        for market, trades, cash in (
            ("BTCUSDT", btc, EQUITY),
            ("ETHUSDT", eth, EQUITY),
            ("BTCUSDT + ETHUSDT", btc + eth, 2 * EQUITY),
        ):
            row = summarize(
                (
                    "FMZ native spot martingale V001",
                    job["name"],
                    market + " spot",
                    "Observed flat-to-flat cycles",
                ),
                label,
                trades,
                0,
            )
            ratio = EQUITY / cash
            for name, i in (("gross", 1), ("fee", 2), ("net", 3)):
                dd, pct = drawdown((t[0], t[i] * ratio) for t in trades)
                row[name + "_dd"], row[name + "_dd_pct"] = dd / ratio, pct
            row.update(
                id=IDENT,
                source=job["source"],
                quote_currency="USDT",
                interval="15m",
                base_interval="5m",
                polling_interval="1m",
            )
            results.append(row)
    write(
        output,
        {
            "coverage": [
                [
                    IDENT,
                    "Tested · FMZ native observed flat-to-flat spot cycles",
                    "Four native BTC/ETH Binance spot scopes with the exact archived literal settings. BTC stayed flat. ETH had uniquely matched order and account states. One mixed buy/sell observation had no observed flat state, so returns use conservative observed flat-to-flat episode counting.",
                ]
            ],
            "results": results,
            "native_evidence": evidence,
            "source_settings": CONFIG,
            "publisher": AUTHOR,
            "worker_sha256": worker_hash,
            "independent_history_repeat_verified": bool(original),
            "isolation": probe,
            "execution_model": {
                "tape": "Binance public 5-minute OHLCV with native synthetic ticks. Source polls once per minute. The archive contained no saved chart settings.",
                "fee_rate": FEE,
                "slippage_rate": EXECUTION,
                "classification": "Match every actual filled order uniquely to native wallet observations using cash, inventory and order-time constraints. Count a trade on an observed positive inventory episode returning to zero. Unfilled resting bids pay zero fees.",
                "seed": "All scopes start flat with 10,000 USDT. The archived JYD default is unused after parsing.",
            },
        },
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    p.add_argument("target", type=Path)
    p.add_argument("--finish", type=Path)
    a = p.parse_args()
    if a.finish:
        finish(a.target, a.finish)
    else:
        stage(a.archive, a.target)
