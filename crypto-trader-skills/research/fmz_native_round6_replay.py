"""Prepare isolated FMZ spot retries and reconcile archived native receipts."""

import argparse
import json
import re
from collections import defaultdict, deque
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from urllib.parse import urlencode
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.delta_strategy_replay import EQUITY, EXECUTION, FEE, stamp, summarize
from research.fmz_native_expanded_replay import order_metrics
from research.fmz_native_public_params import StrategyPage, normalized
from research.fmz_native_round3 import KEYS, WINDOWS
from research.fmz_native_round5 import ORDER_FIELDS, assert_source, replace_once
from research.fmz_native_round6_audit import BASE, ROOT, SCOPE, digest

JS_CASES = {
    619: "Source-matched value-averaging parameters. Supply the quote-denominated minimum notional checked by the archived loop, with empty persistence and no operator deposits or commands.",
    739: "Source RSI limit rules and original inner retry cadence. Evaluate the outer decision loop at intervals of at least one minute.",
    4345: "Use the prior Bollinger-rule adaptation and public daily warm-up. Set the unavailable polling input to a labeled one-hour scenario.",
    4543: "Source-matched balance-grid defaults. Allocate half of the initial capital to BTC or ETH at the previous complete candle, use empty persistence and poll once per minute.",
    4922: "Source-matched ratio and grid defaults. Seed the original required inventory ratio from the previous complete candle, otherwise preserve the candle-mode quote branch and use one-minute polling.",
    4927: "Use the source-matched 9,000/9,500 input prices, empty persistence, native candle-mode quotes and one-minute polling.",
    5140: "Preserve the configured 15-minute moving averages and published sizes. Pace the virtual branch with its original configured interval.",
    5632: "Seed the archived random Martingale with 5632 and use one-minute polling. Native simulation accepts some market buys below the public spot minimum, so the results describe a simulator-only size variant.",
    5686: "Preserve native alternating limit prices and sizing. Poll once per minute.",
}
FIRST_JS_PASS = {739, 4345, 5140, 5632, 5686}
PY_CASES = {
    472: "Keep the archived hourly decision record, sizes and original waits. Retry the same pinned Spot engine.",
    697: "Preserve the archived momentum threshold and order decisions. Observe the simulated ticker once per minute.",
    1098: "Keep archived indicators and original sizes. Replay source-matched one-minute records with one-minute decision pacing.",
}
DAY_STARTS = (1703462400000, 1781308800000, 1793923200000)
LOCAL_STATE = {619, 4543, 4922, 4927}
OPENING_INVENTORY = {4543, 4922}


def public_settings(path, item):
    raw = path.read_bytes()
    page = StrategyPage()
    page.feed(raw.decode("utf-8"))
    source = normalized(item["code"])
    matched = max(
        (
            len(line)
            for preview in page.previews
            if len(line := normalized(preview)) >= 70 and source.startswith(line)
        ),
        default=0,
    )
    assert matched and page.values
    return {
        "url": item["parameter_page"],
        "page_sha256": digest(raw),
        "preview_chars": matched,
        "args": page.values,
    }


def daily(work, target, data, coin):
    rows, receipts = [], []
    for first, end in pairwise(DAY_STARTS):
        params = urlencode(
            {
                "symbol": coin + "USDT",
                "interval": "1d",
                "startTime": first,
                "endTime": end - 1,
                "limit": 1000,
            }
        )
        raw = (work / f"native-{coin}USDT-1d-{first}.json").read_bytes()
        receipts.append(
            {
                "url": "https://data-api.binance.vision/api/v3/klines?" + params,
                "sha256": digest(raw),
            }
        )
        page = json.loads(raw)
        stamps = [r[0] for r in page]
        assert stamps == list(range(first, end, 86_400_000))
        for opened, o, h, l, c, v, *_ in page:
            o, h, l, c, v = map(Decimal, (o, h, l, c, v))
            assert 0 < l <= min(o, c) <= max(o, c) <= h and v >= 0
            scale = Decimal(10) ** data["detail"]["quotePrecision"]
            size = Decimal(10) ** data["detail"]["basePrecision"]
            rows.append(
                [opened, *[int(x * scale) for x in (o, h, l, c)], int(v * size)]
            )
    name = f"round6-warm-binance-{coin}-1d.json"
    write(target / name, {**data, "data": rows})
    return {
        "file": name,
        "sha256": digest((target / name).read_bytes()),
        "providers": receipts,
    }


def stage_js(scratch, work, target, scope, checks, initial=False):
    prior = read(target / "round5-native-javascript-jobs.json")
    feeds = {
        (x["feed"]["coin"], x["feed"]["start"], x["feed"]["base_seconds"]): x["feed"]
        for x in prior
    }
    candidates = {
        row["id"]: row
        for row in read(scratch / "native-expanded" / "native-enriched-candidates.json")
    }
    specs, trials = [], []
    with ZipFile(scratch / "fmz.zip") as archive:
        for id_, notes in JS_CASES.items():
            if initial and id_ not in FIRST_JS_PASS:
                continue
            item = candidates[id_]
            assert id_ in scope
            assert_source({"item": item}, archive, {**scope[id_], **checks[id_]})
            period = {4345: "1h", 5140: "1d"}.get(id_, "15m")
            step = 900 if id_ in {4345, 5140} else 300
            for coin, start in sorted(KEYS):
                if id_ in {739, 4345, 5686}:
                    [old] = [
                        x
                        for x in prior
                        if x["item"]["id"] == id_
                        and x["feed"]["coin"] == coin
                        and x["feed"]["start"] == start
                    ]
                    code, args = old["item"]["code"], old["item"]["args"]
                    params, template = old.get("parameters", {}), old.get("template")
                    feed = {**old["feed"], "period": period}
                    cfg = {**old["cfg"], "timeout": 100_000}
                else:
                    code, args = item["code"], item["args"]
                    params, template = {}, None
                    feed = {**feeds[coin, start, step], "period": period}
                    cfg = {
                        "balance": EQUITY,
                        "fee": FEE,
                        "timeout": 100_000,
                        "minOrderSize": False,
                    }
                if id_ in LOCAL_STATE:
                    params = public_settings(work / f"fmz-param-{id_}.html", item)
                    args = {**params["args"], **args}
                    cfg["empty_state"] = True
                if id_ == 4543:
                    code = replace_once(code, "Sleep(5000)", "Sleep(60000)")
                if id_ in {4922, 4927}:
                    code = replace_once(
                        code,
                        "        if(!IsVirtual()){\n            Sleep(Intervel)\n        }",
                        "        Sleep(Math.max(Intervel, 60000));",
                    )
                if id_ in OPENING_INVENTORY:
                    raw = (target / feed["file"]).read_bytes()
                    assert digest(raw) == feed["sha256"]
                    book = json.loads(raw)
                    eligible = [
                        r
                        for r in book["data"]
                        if r[0] + feed["base_seconds"] * 1000 <= stamp(start) * 1000
                    ]
                    last = eligible[-1]
                    price = last[4] / (10 ** book["detail"]["quotePrecision"])
                    ratio = args.get("Ratio", 0.5)
                    size = 10 ** book["detail"]["basePrecision"]
                    amount = int(EQUITY * ratio / price * size) / size
                    cfg["opening"] = {
                        "timestamp": last[0],
                        "price": price,
                        "base": amount,
                        "cash": EQUITY - amount * price,
                    }
                if id_ == 4345 and not initial:
                    assert "Interval" not in args
                    args = {**args, "Interval": 3600}
                if id_ == 739:
                    code = replace_once(
                        code,
                        "        Sleep(Interval);\n    }\n}",
                        "        Sleep(Math.max(Interval, 60000));\n    }\n}",
                    )
                if id_ == 5140:
                    params = next(
                        x
                        for x in read(
                            scratch
                            / "native-expanded"
                            / "native-public-parameters.json"
                        )
                        if x["id"] == id_
                    )
                    args = {**params["args"], **args}
                    code = replace_once(
                        code,
                        "        if(!IsVirtual()){\n            Sleep(Interval*1000)\n        }",
                        "        Sleep(Interval*1000);",
                    )
                if id_ in {5632, 5686}:
                    code = replace_once(
                        code, "        Sleep(1000);", "        Sleep(60000);"
                    )
                if id_ == 5632:
                    code = (
                        "let seed = 5632;\nMath.random = () => (seed = (1664525 * seed + 1013904223) >>> 0) / 4294967296;\n"
                        + code
                    )
                market = {k: feed[k] for k in ("file", "sha256")}
                if id_ == 4345:
                    raw = (target / market["file"]).read_bytes()
                    assert digest(raw) == market["sha256"]
                    feed["daily"] = daily(work, target, json.loads(raw), coin)
                specs.append(
                    {
                        "item": {**item, "code": code, "args": args},
                        "feed": feed,
                        "cfg": cfg,
                        "parameters": params,
                        "template": template,
                        "adaptation": notes,
                    }
                )
                trials.append(
                    {
                        "id": id_,
                        "code": code,
                        "args": args,
                        "cfg": cfg,
                        "feed": {
                            **feed,
                            "market": market,
                            "eid": "Binance",
                            "step": step,
                        },
                    }
                )
    worker = (
        (target / "round5-native-worker.cjs")
        .read_text(encoding="utf-8")
        .replace("round5-native", "round6-native")
    )
    worker = replace_once(
        worker,
        "    assert.equal(Number(q.get('period')), feed.step * 1000);",
        "    const step = Number(q.get('period'));\n"
        "    assert.ok(step === feed.step * 1000 || (feed.daily && event === 'fill' && step === 86400000));",
    )
    worker = replace_once(
        worker,
        "    const tape = funding ? openTape(feed.funding) : index ? openTape(feed.index) : source;",
        "    const tape = step === 86400000 ? openTape(feed.daily) : "
        "funding ? openTape(feed.funding) : index ? openTape(feed.index) : source;",
    )
    worker = replace_once(worker, "      const step = feed.step * 1000;\n", "")
    if not initial:
        worker = replace_once(
            worker,
            "balance: cfg.balance, stocks: 0,",
            "balance: cfg.opening?.cash ?? cfg.balance, stocks: cfg.opening?.base ?? 0,",
        )
        worker = replace_once(
            worker,
            "  scope.EnableLog(false);",
            """  scope.EnableLog(false);
  if (cfg.empty_state) {
    const local = new Map();
    scope.GetCommand = () => null;
    scope._G = (key, ...data) => {
      if (data.length === 0) return local.has(key) ? structuredClone(local.get(key)) : null;
      if (data[0] === null) local.delete(key);
      else local.set(key, structuredClone(data[0]));
      return true;
    };
  }""",
        )
    (target / "round6-native-worker.cjs").write_text(
        worker, encoding="utf-8", newline="\n"
    )
    if not initial:
        minimum_worker = replace_once(
            worker,
            "    if (cfg.minOrderSize) exchange.GetMinStock = () => {",
            """    if (id === 619) {
      assert.ok(source.detail.minNotional > 0);
      exchange.GetMinPrice = () => source.detail.minNotional;
    }
    if (cfg.minOrderSize) exchange.GetMinStock = () => {""",
        )
        (target / "round6-native-minimum-worker.cjs").write_text(
            minimum_worker, encoding="utf-8", newline="\n"
        )
    write(target / "round6-native-javascript-jobs.json", specs)
    write(target / "round6-native-jobs.json", trials)


def stage_python(scratch, target, scope, checks):
    found = set()
    specs = []
    with ZipFile(scratch / "fmz.zip") as archive:
        for spec in read(target / "round5-native-python-jobs.json"):
            item = spec["item"]
            id_ = item["id"]
            if id_ not in PY_CASES:
                continue
            assert id_ in scope
            assert_source(spec, archive, {**scope[id_], **checks[id_]})
            found.add(id_)
            for marker in {
                697: ("        Sleep(500)\n", "        Sleep(60000)\n"),
                1098: ("\t\tSleep(30000)\n", "\t\tSleep(60000)\n"),
            }.get(id_, (None, None))[:1]:
                if marker:
                    code = item["code"].replace("\r\n", "\n")
                    item["code"] = replace_once(
                        code,
                        marker,
                        marker.replace("500)", "60000)").replace("30000)", "60000)"),
                    )
            specs.append({**spec, "adaptation": PY_CASES[id_]})
    assert found == PY_CASES.keys()
    worker = (
        (target / "fmz_native_python_round5_worker.py")
        .read_text(encoding="utf-8")
        .replace("round5-native", "round6-native")
    )
    worker = replace_once(
        worker,
        'meta = {"id": item["id"], "coin": feed["coin"], "start": feed["start"], "worker_sha256": worker_sha}',
        'meta = {"id": item["id"], "coin": feed["coin"], "start": feed["start"], "worker_sha256": worker_sha,'
        ' "code_sha256": hashlib.sha256(item["code"].encode()).hexdigest()}',
    )
    (target / "fmz_native_python_round6_worker.py").write_text(
        worker, encoding="utf-8", newline="\n"
    )
    write(target / "round6-native-python-jobs.json", specs)


def stage(scratch, work, target, language, initial=False):
    scope = {r["id"]: r for r in read(BASE)["disposition"] if r["status"] in SCOPE}
    checks = {
        r["id"]: r
        for r in read(ROOT / "fmz-native-round6-audit.json")["source_evidence"]
    }
    assert scope.keys() == checks.keys()
    if language == "javascript":
        stage_js(scratch, work, target, scope, checks, initial)
    else:
        stage_python(scratch, target, scope, checks)


def stage_fee_fixture(target):
    worker = (target / "round6-native-worker.cjs").read_text(encoding="utf-8")
    code = worker.split("async function main() {", 1)[0]
    code += """
async function main() {
  await new Promise(resolve => setTimeout(resolve, 500));
  const trial = read('round6-native-jobs.json').find(row => row.id === 5632);
  assert.ok(trial);
  const result = replay({...trial, code: 'function main() { exchange.Buy(-1, 32); }', args: {}});
  const [order] = result.orders;
  assert.equal(result.orders.length, 1);
  assert.equal(order.Price, 0);
  assert.ok(order.DealAmount > 0);
  const turnover = order.DealAmount * order.AvgPrice;
  const amount = trial.cfg.balance - result.account.Balance;
  assert.ok(Math.abs(amount - (1 + trial.cfg.fee) * turnover) < 1e-8);
  assert.ok(Math.abs(result.account.Stocks - order.DealAmount) < 1e-12);
  const input = {fee: trial.cfg.fee, turnover, cash_debited: amount, deal_amount: order.DealAmount,
                 closing_inventory: result.account.Stocks, feed_sha256: trial.feed.market.sha256};
  fs.writeFileSync(path.join(root, 'round6-native-market-fee.json'), JSON.stringify(input));
}
main().catch(error => {
  fs.writeFileSync(path.join(root, 'round6-native-market-fee-error.txt'), String(error));
  process.exitCode = 1;
});
"""
    (target / "round6-native-market-fee.cjs").write_text(
        code, encoding="utf-8", newline="\n"
    )


def opening_metrics(receipt, directory, feed, opening):
    raw = (directory / feed["file"]).read_bytes()
    assert digest(raw) == feed["sha256"]
    bars = {r[0]: r for r in json.loads(raw)["data"]}
    start, end = (stamp(feed[x]) * 1000 for x in ("start", "end"))
    assert (
        0 < opening["base"]
        and opening["timestamp"] < start
        and end - 60000 <= receipt["last"]["Time"] <= end
    )
    cash, stocks = opening["cash"], opening["base"]
    lots = deque([(stocks, opening["price"], 0)])
    trades = []
    orders = sorted(receipt["orders"], key=lambda r: (r["Time"], r["Id"]))
    assert len({r["Id"] for r in orders}) == len(orders)
    for order in orders:
        at, qty, price = (order[k] for k in ("Time", "DealAmount", "AvgPrice"))
        assert (
            start <= at < end
            and order["Symbol"] == feed["symbol"]
            and order["Type"] in (0, 1)
        )
        if not qty:
            continue
        step = feed["base_seconds"] * 1000
        assert qty > 0 and price > 0 and bars[at // step * step][5] > 0
        turnover = qty * price
        if order["Type"] == 0:
            fees = turnover * FEE / (1 - FEE if order["Price"] == 0 else 1)
            cash -= turnover + fees
            stocks += qty
            lots.append((qty, price, fees / qty))
            continue
        cash += turnover * (1 - FEE)
        stocks -= qty
        while qty > 1e-9:
            amount, entry, entry_fee = lots.popleft()
            matched = min(amount, qty)
            gross = matched * (price - entry)
            fee_only = gross - matched * (entry_fee + price * FEE)
            trades.append(
                (at, gross, fee_only, fee_only - matched * (price + entry) * EXECUTION)
            )
            qty -= matched
            if amount - matched > 1e-9:
                lots.appendleft((amount - matched, entry, entry_fee))
    account = receipt["account"]
    cash_error = cash - account["Balance"] - account["FrozenBalance"]
    asset_error = stocks - account["Stocks"] - account["FrozenStocks"]
    assert abs(cash_error) <= 1e-7 and abs(asset_error) <= 1e-9, (
        "Seeded native wallet did not reconcile"
    )
    return trades, len(lots), {"cash_error": cash_error, "asset_error": asset_error}


def no_breakout_proof(directory, feed):
    raw = (directory / feed["file"]).read_bytes()
    assert digest(raw) == feed["sha256"]
    frame = json.loads(raw)
    begin, end = (stamp(feed[key]) * 1000 for key in ("start", "end"))
    chunk = [row for row in frame["data"] if begin <= row[0] < end]
    assert chunk[0][0] == begin and len(chunk) == (end - begin) // 60_000
    initial_low = chunk[0][3]
    max_high = max(row[2] for row in chunk)
    assert 0 < initial_low and max_high / initial_low - 1 < 0.05
    return {
        "first_min_price_integer": initial_low,
        "max_price_integer": max_high,
        "price_scale": 10 ** frame["detail"]["quotePrecision"],
        "source_breakout_ratio": 0.05,
    }


def finish(target, output, language):
    javascript = language == "javascript"
    short = "js" if javascript else language
    worker = (
        "round6-native-worker.cjs"
        if javascript
        else "fmz_native_python_round6_worker.py"
    )
    worker_sha = digest((target / worker).read_bytes())
    minimum = target / "round6-native-minimum-worker.cjs"
    minimum_sha = (
        digest(minimum.read_bytes()) if javascript and minimum.exists() else None
    )
    fixture_path = target / "round6-native-market-fee.json"
    fixture = read(fixture_path) if javascript and fixture_path.is_file() else {}
    if fixture:
        assert fixture["fee"] == FEE
        assert abs(fixture["cash_debited"] - (1 + FEE) * fixture["turnover"]) < 1e-8
        assert fixture["closing_inventory"] == fixture["deal_amount"]
    probe = read(target / f"round3-isolation-{short}.json")
    if javascript:
        assert (
            probe["privateRead"] == "ERR_ACCESS_DENIED" and probe["network"] == "EACCES"
        )
    else:
        assert probe["file_error"][0] == probe["network_error"][0] == "PermissionError"
    receipts = {}
    for doc in sorted(
        target.glob(f"round6-native-{short}-*.jsonl"),
        key=lambda p: p.stat().st_mtime_ns,
    ):
        for line in doc.read_bytes().splitlines(keepends=True):
            if not line.endswith(b"\n"):
                continue
            row = json.loads(line)
            if row["worker_sha256"] == worker_sha or (
                row["id"] == 619 and row["worker_sha256"] == minimum_sha
            ):
                key = row["id"], row["coin"], row["start"]
                if key not in receipts or "orders" in row:
                    receipts[key] = row, digest(line.rstrip(b"\r\n"))
    groups = defaultdict(list)
    attempted = {id_ for id_, _, _ in receipts}
    for spec in read(target / f"round6-native-{language}-jobs.json"):
        id_ = spec["item"]["id"]
        if id_ in attempted:
            groups[id_].append(spec)
    coverage, results, evidence = [], [], []
    label = "JavaScript" if javascript else "Python"
    for id_, specs in sorted(groups.items()):
        scenarios, issues = {}, set()
        active_market, no_fill_proofs = False, 0
        notes = (JS_CASES if javascript else PY_CASES)[id_]
        for spec in specs:
            item, feed = spec["item"], spec["feed"]
            key = feed["coin"], feed["start"]
            receipt, receipt_sha = receipts.get((id_, *key), ({}, None))
            code_sha = digest(item["code"].encode())
            audit_row = {
                "id": id_,
                "coin": key[0],
                "start": key[1],
                "source_sha256": item["source_sha256"],
                "feed": feed,
                "code_sha256": code_sha,
                "receipt_sha256": receipt_sha,
                "args": item["args"],
                "adaptation": notes,
            }
            if spec.get("parameters"):
                audit_row["public_parameters"] = spec["parameters"]
            try:
                if not receipt or "reason" in receipt:
                    raise ValueError(
                        receipt.get("reason", "Isolated run has no complete receipt")
                    )
                assert receipt["code_sha256"] == code_sha
                if javascript:
                    receipt = {**receipt, "last": {"Time": receipt["snapshotTime"]}}
                opening = spec.get("cfg", {}).get("opening")
                if opening:
                    trades, opened, recon = opening_metrics(
                        receipt, target, feed, opening
                    )
                    audit_row["opening_inventory"] = opening
                else:
                    trades, opened, recon = order_metrics(
                        receipt,
                        {"feed": feed, "directory": target},
                        market_buy_fee_on_turnover=not javascript or id_ == 5632,
                    )
                if id_ == 5632:
                    assert fixture, "Missing isolated market-order fee fixture"
                    assert all(
                        o["Price"] == 0 for o in receipt["orders"] if o["DealAmount"]
                    )
                    audit_row["market_buy_fee_basis"] = "filled turnover"
                active_market |= any(row["DealAmount"] > 0 for row in receipt["orders"])
                if id_ == 697 and not receipt["orders"]:
                    audit_row["zero_fill_proof"] = no_breakout_proof(target, feed)
                    no_fill_proofs += 1
                scenarios[key] = trades, opened
                audit_row.update(
                    reconciliation=recon,
                    orders=len(receipt["orders"]),
                    settled_lots=len(trades),
                    open_lots=opened,
                    account=receipt["account"],
                    snapshot=receipt["last"]["Time"],
                    order_field_sha256=digest(
                        json.dumps(
                            [
                                [o.get(k) for k in ORDER_FIELDS]
                                for o in receipt["orders"]
                            ],
                            separators=(",", ":"),
                        ).encode()
                    ),
                )
            except (AssertionError, IndexError, KeyError, ValueError) as exc:
                audit_row["reason"] = reason = (
                    re.sub(r"\x1b\[[0-9;]*m", "", str(exc)).splitlines()[0]
                    if str(exc)
                    else "Native order history did not reconcile"
                )
                issues.add(reason)
            evidence.append(audit_row)
        validated_no_fill = id_ == 697 and no_fill_proofs == len(KEYS)
        if scenarios.keys() != KEYS or (not active_market and not validated_no_fill):
            coverage.append(
                [
                    id_,
                    "Pending · FMZ native round-six trial",
                    " | ".join(sorted(issues))
                    or "Four reconciled boundaries completed with no fill to validate the source lifecycle.",
                ]
            )
            continue
        closes = any(trades for trades, _ in scenarios.values())
        for start, (_, window) in WINDOWS.items():
            btc, ob = scenarios["BTC", start]
            eth, oe = scenarios["ETH", start]
            for market, fills, opened in (
                ("BTCUSDT", btc, ob),
                ("ETHUSDT", eth, oe),
                ("BTCUSDT + ETHUSDT", btc + eth, ob + oe),
            ):
                row = summarize(
                    (
                        f"FMZ native {label} · Binance spot",
                        item["name"],
                        market + " spot",
                        "Native archived order rule",
                    ),
                    window,
                    fills,
                    opened,
                )
                row.update(
                    id=id_,
                    interval=feed["period"],
                    source=item["source"],
                    source_sha256=item["source_sha256"],
                    archive_interval=item["fields"].get("period"),
                    starting_equity=EQUITY,
                    quote_currency="USDT",
                    adaptation=notes,
                )
                results.append(row)
        coverage.append(
            [
                id_,
                f"Tested · FMZ native {label} variant"
                + (
                    ", no fills"
                    if validated_no_fill
                    else ""
                    if closes
                    else ", no closes"
                ),
                notes
                + (
                    " All four observed highs stayed within the source's 5% initial entry threshold."
                    if validated_no_fill
                    else ""
                ),
            ]
        )
    write(
        output,
        {
            "baseline": "91ad53db",
            "coverage": coverage,
            "results": results,
            "isolation": probe,
            "worker_sha256": worker_sha,
            "minimum_compatibility_worker_sha256": minimum_sha,
            "market_fee_fixture": fixture,
            "engine_sha256": digest(
                (
                    target
                    / (
                        "fmz-wasm-engine.cjs"
                        if javascript
                        else "depends/backtest_py_windows_64bit.so"
                    )
                ).read_bytes()
            ),
            "snapshots": evidence,
        },
    )
    print(len(results), "verified rows", [(i, s) for i, s, _ in coverage])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "finish", "stage-fee-fixture"))
    parser.add_argument("language", choices=("javascript", "python"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--scratch", type=Path)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--initial", action="store_true")
    args = parser.parse_args()
    if args.action == "stage":
        stage(args.scratch, args.work, args.directory, args.language, args.initial)
    elif args.action == "stage-fee-fixture":
        stage_fee_fixture(args.directory)
    else:
        finish(args.directory, args.output, args.language)
