"""Stage the pinned #1320 FMZ ATR strategy with a fully local Binance futures tape."""

import argparse
import json
import re
from collections import deque
from itertools import pairwise
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.delta_strategy_replay import EQUITY, EXECUTION, drawdown, stamp, summarize
from research.fmz_native_expanded_replay import BLOCKS, source_config
from research.fmz_native_round3 import KEYS, WINDOWS
from research.fmz_native_round6_audit import ROOT, digest

IDENT = 1320
STEM = "round12-atr-perpetual"
WORKER = STEM + "-worker.cjs"
FEES = [0.018, 0.036]
SETBASE_DOC = "https://www.fmz.com/syntax-guide/fun/exchange/exchange.setbase"
NOTES = (
    "Native archived one-day ATR rules on Binance perpetual records generated "
    "from hourly historical candles, including Binance index and funding records. "
    "ETH/USDT preserves the author's instrument. BTC/USDT is a separately "
    "identified port. Both samples start from a flat 10,000 USDT wallet and use "
    "the published maker/taker fees. Test windows are the project's Reference and "
    "Later samples and the ledger is observed near their ends."
)


def bind(archive):
    row = next(
        r
        for r in read(ROOT / "remaining-backtest-round7-coverage.json")["disposition"]
        if r["id"] == IDENT
    )
    with ZipFile(archive) as source_zip:
        filename = unquote(row["source"].rsplit("/", 1)[-1])
        raw = source_zip.read(f"strategies-{FMZ_REF}/{filename}")
    assert digest(raw) == row["pinned_document_sha256"]
    [code] = [
        b for tag, b in BLOCKS.findall(raw.decode()) if tag.strip() == "javascript"
    ]
    fields, args = source_config(code)
    assert fields["period"] == "1d" and fields["basePeriod"] == "1h" and not args
    [venue] = json.loads(fields["exchanges"])
    assert venue == {"eid": "Futures_Binance", "currency": "ETH_USDT", "fee": FEES}
    assert set(re.findall(r"\b_\.(\w+)\(", code)) == {"each"}
    assert all(
        re.fullmatch(r'_G\("[\w]+", \w+\)', call)
        for call in re.findall(r"\b_G\([^\r\n]+\)", code)
    )
    assert code.count("exchange.SetBase(") == 1 and code.count("isTest") == 2
    return row, code, fields


def tape(directory, target, entries):
    data, schema, detail = {}, None, None
    for record in entries:
        raw = (directory / record["file"]).read_bytes()
        assert digest(raw) == record["sha256"]
        frame = json.loads(raw)
        assert len(frame["data"]) == record["rows"]
        if detail is None:
            schema, detail = frame["schema"], frame["detail"]
        assert schema == frame["schema"] and detail == frame["detail"]
        for row in frame["data"]:
            if row[0] in data:
                if record["kind"] == "funding":
                    assert row == data[row[0]]
                else:
                    assert row[0] == frame["data"][0][0] and row[1] == data[row[0]][1]
            data[row[0]] = row
    ordered = [data[t] for t in sorted(data)]
    step = entries[0]["period"] * 1000
    if entries[0]["kind"] == "funding":
        assert all(27_900_000 < b[0] - a[0] < 29_700_000 for a, b in pairwise(ordered))
    else:
        assert all(b[0] - a[0] == step for a, b in pairwise(ordered))
    assert all(
        0 < x[3] <= min(x[1], x[4]) <= max(x[1], x[4]) <= x[2]
        or entries[0]["kind"] == "funding"
        for x in ordered
    )
    out = target / f"{STEM}-{entries[0]['coin']}-{entries[0]['kind']}-{step}.json"
    write(out, {"schema": schema, "detail": detail, "data": ordered})
    return {"file": out.name, "sha256": digest(out.read_bytes()), "providers": entries}


def replacement(source, original, selected):
    assert source.count(original) == 1, original
    return source.replace(original, selected)


def stage(archive, directory, target):
    row, original_code, fields = bind(archive)
    manifest = read(directory / "manifest.json")
    tapes = {}
    for coin, start in sorted(KEYS):
        if coin not in tapes:
            tapes[coin] = {
                name: tape(
                    directory,
                    target,
                    [
                        r
                        for r in manifest
                        if r["coin"] == coin
                        and r["kind"] == kind
                        and r["period"] == step
                    ],
                )
                for name, kind, step in (
                    ("market", "swap", 3600),
                    ("daily", "swap", 86400),
                    ("index", "index", 3600),
                    ("funding", "funding", 3600),
                )
            }
    jobs = [
        {
            "id": IDENT,
            "source": row["source"],
            "name": row["name"],
            "source_sha256": row["pinned_document_sha256"],
            "fields": fields,
            "code": original_code,
            "args": {},
            "feed": {
                **tapes[coin],
                "coin": coin,
                "start": start,
                "end": WINDOWS[start][0],
                "eid": "Futures_Binance",
                "base": "1h",
                "step": 3600,
                "period": "1d",
            },
            "cfg": {
                "balance": EQUITY,
                "fee": FEES[1] / 100,
                "timeout": 240_000,
                "empty_state": True,
            },
        }
        for coin, start in sorted(KEYS)
    ]
    worker = (target / "round6-native-worker.cjs").read_text(encoding="utf-8")
    worker = worker.replace("round6-native", STEM)
    worker = replacement(
        worker, "end: feed.end + ' 00:05:00'", "end: feed.end + ' 01:05:00'"
    )
    worker = replacement(
        worker, "fee: [cfg.fee * 100, cfg.fee * 100]", "fee: [0.018, 0.036]"
    )
    worker = worker.replace("end - 55000", "end - 3600000")
    worker = replacement(
        worker,
        "  const exchange = scope.exchange;",
        """  const exchange = scope.exchange;
  let baseOverride = null;
  exchange.SetBase = url => {
    assert.equal(url, 'https://testnet.binancefuture.com');
    assert.equal(baseOverride, null);
    baseOverride = url;
  };
  scope._ = Object.freeze({each(collection, visit) {
    for (const key of Object.keys(collection)) {
      visit(collection[key], Array.isArray(collection) ? Number(key) : key, collection);
    }
    return collection;
  }});
  const nativeSetContract = exchange.SetContractType;
  assert.ok(nativeSetContract('swap'));""",
    )
    marker = "    const snapshotTime = scope.Date.now();"
    a = worker.index(marker)
    b = worker.index("    const account = exchange.GetAccount();", a)
    worker = (
        worker[:a]
        + marker
        + "\n    assert.ok(end - 7200000 <= snapshotTime && snapshotTime < end, "
        "'Final observation outside two-hour collection interval ' + JSON.stringify({snapshotTime,end}));\n"
        + worker[b:]
    )
    worker = replacement(
        worker,
        "    return {last, snapshotTime,",
        "    const ledgerTime = scope.Date.now();\n"
        "    assert.ok(snapshotTime <= ledgerTime && ledgerTime < end);\n"
        "    assert.equal(baseOverride, 'https://testnet.binancefuture.com');\n"
        "    return {snapshotTime, ledgerTime, baseOverride,",
    )
    write(target / (STEM + "-jobs.json"), jobs)
    (target / WORKER).write_text(worker, encoding="utf-8", newline="\n")


def frame(target, feed, kind):
    spec = feed[kind]
    raw = (target / spec["file"]).read_bytes()
    assert digest(raw) == spec["sha256"]
    doc = json.loads(raw)
    return {r[0]: r for r in doc["data"]}, 10 ** doc["detail"]["quotePrecision"]


def reconcile(record, job, target):
    feed, cfg = job["feed"], job["cfg"]
    start, end = (stamp(feed[k]) * 1000 for k in ("start", "end"))
    close_time = record["ledgerTime"]
    assert end - 7200000 <= record["snapshotTime"] <= close_time < end
    assert record["baseOverride"] == "https://testnet.binancefuture.com"
    assert not record["positions"] and not record["resting"]
    assert {q["symbol"].rsplit(".", 1)[-1] for q in record["requests"]} == {
        "swap",
        "index",
        "funding",
    }
    swap, _ = frame(target, feed, "market")
    index, index_scale = frame(target, feed, "index")
    funding, funding_scale = frame(target, feed, "funding")
    step = feed["step"] * 1000
    payments = [
        (t, index[t // step * step][1] / index_scale * row[4] / funding_scale)
        for t, row in funding.items()
        if start <= t < close_time
    ]
    fees = cfg["fee"]
    ledger, lots = [], deque()
    orders = sorted(record["orders"], key=lambda r: (r["Time"], r["Id"]))
    assert len({o["Id"] for o in orders}) == len(orders)
    for order in orders:
        at, p, qty = (order[k] for k in ("Time", "AvgPrice", "DealAmount"))
        assert start <= at <= close_time and swap[at // step * step][5] > 0
        assert order["Symbol"] == feed["coin"] + "_USDT.swap"
        assert order["Status"] == 1 and order["Price"] == 0
        assert qty == order["Amount"] and qty > 0 and p > 0
        if order["Offset"] == 0:
            assert order["Type"] == 0
            lots.append((at, p, qty))
            continue
        assert order["Offset"] == 1 and order["Type"] == 1
        gross = turnover = carry = 0.0
        while qty > 1e-9:
            entry, basis, amount = lots.popleft()
            assert entry < at
            units = min(qty, amount)
            gross += units * (p - basis)
            turnover += units * (p + basis)
            carry -= units * sum(value for t, value in payments if entry < t < at)
            qty -= units
            if amount - units > 1e-9:
                lots.appendleft((entry, basis, amount - units))
        after_fee = gross - turnover * fees
        slippage = turnover * EXECUTION
        ledger.append(
            (at, gross, after_fee, after_fee - slippage + carry, carry, slippage)
        )
    assert not lots
    account = record["account"]
    assert all(
        account[name] == 0
        for name in ("FrozenBalance", "Stocks", "FrozenStocks", "UPnL")
    )
    assert account["Balance"] == account["Equity"]
    documented_funding = sum(r[4] for r in ledger)
    native_funding = account["Balance"] - cfg["balance"] - sum(r[2] for r in ledger)
    assert abs(native_funding - documented_funding) < 0.001, (
        "Sub-cent funding tolerance exceeded"
    )
    return ledger, {
        "native_closing_balance": account["Balance"],
        "reconstructed_closing_balance": cfg["balance"]
        + sum(r[2] + r[4] for r in ledger),
        "native_funding_inferred_from_settled_cash": native_funding,
        "reconstructed_funding": documented_funding,
        "funding_accounting_residual_usdt": native_funding - documented_funding,
    }


def finish(target, output):
    jobs = read(target / (STEM + "-jobs.json"))
    worker_hash = digest((target / WORKER).read_bytes())
    raw = (target / f"{STEM}-js-{IDENT}.jsonl").read_bytes()
    receipts = {}
    for line in raw.splitlines(keepends=True):
        if line.endswith(b"\n"):
            record = json.loads(line)
            assert record["worker_sha256"] == worker_hash
            receipts[record["coin"], record["start"]] = record, digest(line.rstrip())
    probe = read(target / "round3-isolation-js.json")
    assert probe["privateRead"] == "ERR_ACCESS_DENIED" and probe["network"] == "EACCES"
    outcomes, evidence, results, reasons = {}, [], [], set()
    for job in jobs:
        feed = job["feed"]
        key = feed["coin"], feed["start"]
        record, raw_hash = receipts.get(key, ({}, None))
        evidence_row = {
            "feed": feed,
            "source_sha256": job["source_sha256"],
            "code_sha256": digest(job["code"].encode()),
            "receipt_sha256": raw_hash,
        }
        try:
            if not record or record.get("reason"):
                raise ValueError(record.get("reason", "Native receipt missing"))
            assert record["code_sha256"] == evidence_row["code_sha256"]
            ledger, recon = reconcile(record, job, target)
            outcomes[key] = ledger
            evidence_row.update(
                snapshot_time=record["snapshotTime"],
                ledger_time=record["ledgerTime"],
                order_count=len(record["orders"]),
                closed_trades=len(ledger),
                accounting=recon,
                native_history_queries=record["requests"],
            )
        except (AssertionError, IndexError, KeyError, ValueError) as exc:
            reason = str(exc) or "Independent fill and funding ledger failed"
            evidence_row["reason"] = reason
            reasons.add(reason)
        evidence.append(evidence_row)
    if outcomes.keys() == KEYS and any(outcomes.values()):
        for start, (_, label) in WINDOWS.items():
            btc, eth = (outcomes[coin, start] for coin in ("BTC", "ETH"))
            for market, ledger, equity in (
                ("BTCUSDT", btc, EQUITY),
                ("ETHUSDT", eth, EQUITY),
                ("BTCUSDT + ETHUSDT", btc + eth, 2 * EQUITY),
            ):
                stats = summarize(
                    (
                        "FMZ native Binance ATR perpetual",
                        job["name"],
                        market + " perp",
                        "Archived ATR grid rule",
                    ),
                    label,
                    [step[:4] for step in ledger],
                    0,
                )
                ratio = EQUITY / equity
                for col, ix in (("gross", 1), ("fee", 2), ("net", 3)):
                    dd, pct = drawdown((step[0], step[ix] * ratio) for step in ledger)
                    stats[col + "_dd"], stats[col + "_dd_pct"] = dd / ratio, pct
                stats.update(
                    id=IDENT,
                    source=job["source"],
                    interval="1d",
                    quote_currency="USDT",
                    starting_equity=equity,
                    funding=sum(x[4] for x in ledger),
                    execution=sum(x[5] for x in ledger),
                    slippage=sum(x[5] for x in ledger),
                )
                results.append(stats)
        status, note = "Tested · FMZ native ATR perpetual", NOTES
    else:
        status, note = "Pending · FMZ native ATR perpetual", " | ".join(sorted(reasons))
    write(
        output,
        {
            "coverage": [[IDENT, status, note]],
            "results": results,
            "evidence": evidence,
            "source_settings": job["fields"],
            "launcher": {
                "worker_sha256": worker_hash,
                "engine_sha256": digest((target / "fmz-wasm-engine.cjs").read_bytes()),
                "base_override": SETBASE_DOC,
                "state": "Source writes two chart structures to in-memory _G; both writes are retained and never read for trading.",
                "isolation": probe,
            },
            "execution_model": {
                "maker_fee_percent": FEES[0],
                "taker_fee_percent": FEES[1],
                "slippage_each_side": EXECUTION,
                "funding": "Apply observed rates to position exposure and hourly index opens, independently matching native settled cash within 0.001 USDT per market/window.",
                "sample_exit": "Count each native exit order once across matched FIFO entries. All four scenarios finish with explicitly flat native accounts.",
                "snapshot": "Stop strategy decisions one hour before the named window end to bound the simulated hourly clock; receipts record the actual observation time.",
            },
        },
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    p.add_argument("directory", type=Path)
    p.add_argument("target", type=Path)
    p.add_argument("--finish", type=Path)
    a = p.parse_args()
    if a.finish:
        finish(a.target, a.finish)
    else:
        stage(a.archive, a.directory, a.target)
