"""Stage and check selected FMZ round-three native simulations."""

import argparse
import json
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.delta_strategy_replay import EXECUTION, FEE, drawdown, stamp, summarize
from research.fmz_native_expanded_replay import BLOCKS, order_metrics
from research.fmz_native_spot_replay import ENGINE_SHA, digest

BASE = Path(__file__).parent
WINDOWS = {"2026-09-23": ("2026-10-21", "Reference"), "2026-10-21": ("2026-11-04", "Later")}
BASELINE = BASE / "remaining-backtest-round2-coverage.json"
PENDING = "FMZ native offline replay pending"
# Preserve original candle resolutions unless the previous archived base cannot expose the requested chart.
# A 15m base is necessary for 5140's GetRecords(PERIOD_M15).
JS_SETTINGS = {
    539: ("Binance", "15m", 300, 10000, {}),
    739: ("Binance", "15m", 300, 10000, {}),
    1183: ("Futures_Binance", "1h", 900, 300, {}),
    1528: ("Binance", "15m", 300, 10000, {"print": True}),
    2515: ("Binance", "1d", 3600, 10000, {"gate": 86400}),
    4899: ("Futures_Binance", "30m", 900, 100000, {}),
    5140: ("Binance", "1d", 900, 10000, {}),
    5146: ("Binance", "15m", 300, 10000, {}),
    5480: ("Binance", "15m", 300, 10000, {}),
    5686: ("Binance", "15m", 300, 10000, {}),
}
PY_SETTINGS = {
    1530: ("Binance", "15m", 300, 10000, {}),
    4371: ("Binance", "15m", 300, 10000, {}),
    4372: ("Binance", "15m", 300, 10000, {}),
}
NOTES = {
    2515: "Skip repeated polling only while the source's newest daily bar has the same timestamp.",
    1183: "Preserve the archived 300 USDT capital, 0.04 base quantity, and defaults. BTC is margin constrained.",
    5146: "Retain the source absolute 6,200 buy and 6,400 sell limits.",
    1528: "Map the obsolete print logging function to native Log.",
    5140: "Use 15m base candles to support the source's explicit 15m record request on a daily chart.",
    5480: "Run the archived Bitfinex BTC/USD rules on USDT spot with unchanged sizes and distances.",
}
KEYS = {(coin, start) for coin in ("BTC", "ETH") for start in WINDOWS}


def tape(work, records):
    market = records["suffix"] != ".funding"
    data, providers, schema, detail = {}, [], None, None
    for spec in records["files"]:
        content = (work / spec["file"]).read_bytes()
        original = json.loads(content)
        if schema is None:
            schema, detail = original["schema"], original["detail"]
        assert schema == original["schema"] and detail == original["detail"], spec["file"]
        providers.append({**spec, "sha256": digest(content)})
        for row in original["data"]:
            if row[0] in data:
                previous = data[row[0]]
                if market:
                    assert row[0] == original["data"][0][0], spec["file"]
                    assert row[1] == previous[1] and row[2] >= previous[2] and row[3] <= previous[3] and row[5] >= previous[5]
                else:
                    assert row == previous, (spec["file"], row[0])
            data[row[0]] = row
    rows = [data[k] for k in sorted(data)]
    if market:
        step = records["step"] * 1000
        assert list(range(rows[0][0], rows[-1][0] + step, step)) == sorted(data)
        assert all(0 < x[3] <= min(x[1], x[4]) <= max(x[1], x[4]) <= x[2] and x[5] >= 0 for x in rows)
    name = f'round3-{detail["eid"]}-{detail["symbol"]}-{records["step"]}-{records["start"]}.json'
    write(work / name, {"schema": schema, "detail": detail, "data": rows})
    return {"file": name, "sha256": digest((work / name).read_bytes()), "providers": providers}


def sources(archive, old):
    items = {}
    with ZipFile(archive) as fmz:
        for file in ("native-enriched-candidates.json", "native-python-screen.json"):
            for row in read(old / file):
                id_ = row["id"]
                if id_ not in (JS_SETTINGS if file.startswith("native-enriched") else PY_SETTINGS):
                    continue
                prefix, name = row["source"].split(f"/{FMZ_REF}/", 1)
                assert prefix == "https://github.com/fmzquant/strategies/blob"
                raw = fmz.read(f"strategies-{FMZ_REF}/{unquote(name)}")
                assert row["source_sha256"] == digest(raw)
                assert row["code"] in {code.lstrip("\ufeff") for _, code in BLOCKS.findall(raw.decode("utf-8"))}
                items[id_] = row
    return items


def stage(scratch):
    work, old = scratch / "round3-native", scratch / "native-expanded"
    parameters = {r["id"]: r for r in read(work / "round3-parameter-checks.json")}
    items = sources(scratch / "fmz.zip", old)
    assert items.keys() == JS_SETTINGS.keys() | PY_SETTINGS.keys()
    q = {(r["eid"], r["suffix"], r["step"], r["coin"], r["start"]): r for r in read(work / "round3-q-inputs.json")}
    feeds = {}
    jobs, py = [], []
    for id_, item in items.items():
        args = {**parameters.get(id_, {}).get("args", {}), **item["args"]}
        eid, period, step, balance, options = (JS_SETTINGS | PY_SETTINGS)[id_]
        suffix = ".swap" if eid == "Futures_Binance" else ""
        for coin, start in sorted(KEYS):
            key = (eid, suffix, step, coin, start)
            if key not in feeds:
                if key[0] == "Binance" and step == 300:
                    previous = next(
                        x for x in read(old / "native-jobs.json")
                        if x["id"] == 539 and x["feed"]["start"] == start and x["feed"]["coin"] == coin
                    )["feed"]
                    data = (old / previous["file"]).read_bytes()
                    assert digest(data) == previous["sha256"]
                    (work / previous["file"]).write_bytes(data)
                    market = {"file": previous["file"], "sha256": previous["sha256"], "providers": [previous]}
                else:
                    market = tape(work, q[key])
                feeds[key] = {"eid": eid, "coin": coin, "start": start, "end": WINDOWS[start][0],
                                  "step": step, "base": f"{step // 60}m", "market": market}
                if suffix:
                    feeds[key]["funding"] = tape(work, q[eid, ".funding", step, coin, start])
                    feeds[key]["index"] = tape(work, q[eid, ".index", step, coin, start])
            feed = {**feeds[key], "period": period}
            cfg = dict(balance=balance, fee=FEE, timeout=65000, **options)
            jobs.append({"id": id_, "code": item["code"], "args": args, "cfg": cfg, "feed": feed})
            if id_ in PY_SETTINGS:
                feed = {**feed, **feed["market"], "base_seconds": step, "symbol": f"{coin}_USDT"}
                py.append({"id": id_, "item": {**item, "args": args}, "cfg": cfg, "feed": feed})
    assert digest((work / "upstream.cjs").read_bytes()) == ENGINE_SHA
    before = b"},httpGet=function(url){let options"
    package = (work / "upstream.cjs").read_bytes()
    assert package.count(before) == 1
    (work / "fmz-wasm-engine.cjs").write_bytes(package.replace(before, b"},httpGet=function(url){return globalThis.__offlineProbe(url);let options"))
    (work / "round3-worker.cjs").write_bytes((BASE / "fmz_native_round3_worker.cjs").read_bytes())
    worker = (BASE / "fmz_native_python_worker.py").read_text(encoding="utf-8")
    assert worker.count("calls <= 200_000") == 1
    (work / "round3-worker.py").write_text(worker.replace("calls <= 200_000", "calls <= 6_000_000"), encoding="utf-8")
    write(work / "native-jobs.json", py)
    write(work / "round3-native-jobs.json", [job for job in jobs if job["id"] in JS_SETTINGS])
    print("Native scopes", len(jobs), len(py))


def finish(scratch, output):
    work, old = scratch / "round3-native", scratch / "native-expanded"
    items = sources(scratch / "fmz.zip", old)
    specs = {(job["id"], job["feed"]["coin"], job["feed"]["start"]): job
             for name in ("round3-native-jobs.json", "native-jobs.json") for job in read(work / name)}
    trials = {}
    for file in sorted(work.glob("round3-native-js-*.jsonl")) + sorted((scratch / "round3-native-python").glob("native-trials-python.jsonl")):
        for line in file.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            key = row["id"], row["coin"], row["start"]
            previous = trials.get(key)
            if previous is None or row.get("snapshotTime", 0) > previous.get("snapshotTime", 0) or previous.get("reason") and row.get("reason"):
                trials[key] = row
    coverage = {row["id"]: [row["status"], row["reason"]] for row in read(BASELINE)["disposition"]
                if row["status"] == PENDING and not any(language in row["reason"] for language in ("pinescript", "pascal"))}
    for id_, reason in {
        181: "C++ API teaching exercise invokes depth and asynchronous exchange operations. No complete trading lifecycle.",
        217: "C++ OKEX high-frequency calendar hedge needs the original synchronized expiry contracts, bid/ask depth and socket/order execution state.",
        218: "C++ chart example reads tickers to display prices. No archived entry or exit rule.",
    }.items():
        assert id_ in coverage
        coverage[id_] = [PENDING, reason]
    rows, evidence = [], []
    for id_, item in items.items():
        runs = {}
        depend = []
        for coin, start in sorted(KEYS):
            key = (id_, coin, start)
            job = specs[key]
            feed = job["feed"]
            record = trials.get(key)
            check = {"id": id_, "coin": coin, "start": start, "market": feed["market"]["sha256"]}
            if not record or record.get("reason"):
                reason = record.get("reason") if record else "No complete isolated worker receipt"
                depend.append(reason)
                evidence.append({**check, "reason": reason})
                continue
            try:
                if feed["eid"] == "Futures_Binance":
                    trades, opened, checks = perp_metrics(record, job, work)
                else:
                    spot_feed = {**feed, **feed["market"], "symbol": coin + "_USDT", "base_seconds": feed["step"]}
                    account_at = record.get("snapshotTime", record["last"]["Time"])
                    accounting = {**record, "last": {**record["last"], "Time": account_at}}
                    trades, opened, checks = order_metrics(accounting, {"feed": spot_feed, "directory": work})
                runs[coin, start] = trades, opened
                evidence.append({**check, "native": record, "reconciliation": checks})
            except (AssertionError, KeyError, ValueError, IndexError) as exc:
                reason = str(exc) or "Native ledger did not reconcile"
                evidence.append({**check, "reason": reason})
                depend.append(reason)
        if set(runs) != KEYS:
            coverage[id_] = [PENDING, "; ".join(sorted(set(depend)))[:650]]
            continue
        opened_or_closed = sum(len(x) + y for x, y in runs.values())
        is_position_rule = id_ not in (5146, 5686)
        if not opened_or_closed and not is_position_rule:
            coverage[id_] = [PENDING, "Source execution-only limit sequence did not complete a fill in the two study windows"]
            continue
        settings = (JS_SETTINGS | PY_SETTINGS)[id_]
        platform, interval, step, capital, _ = settings
        label = "spot" if platform == "Binance" else "perp"
        for start, (_, period) in WINDOWS.items():
            btc, ob = runs["BTC", start]
            eth, oe = runs["ETH", start]
            for market, trades, open_count in (("BTCUSDT", btc, ob), ("ETHUSDT", eth, oe), ("BTCUSDT + ETHUSDT", btc + eth, ob + oe)):
                report = summarize(("FMZ native · Binance " + label, item["name"], f"{market} {label}", "Archived native order rule"), period, [trade[:4] for trade in trades], open_count)
                for column, index in (("gross", 1), ("fee", 2), ("net", 3)):
                    scale = 10000 / capital
                    dd, percent = drawdown((x[0], x[index] * scale) for x in trades)
                    report[column + "_dd"], report[column + "_dd_pct"] = dd / scale, percent
                report.update(id=id_, source=item["source"], source_sha256=item["source_sha256"], market_data="Public FMZ Binance history",
                              interval=interval, starting_equity=capital, quote_currency="USDT",
                              funding=sum(t[4] for t in trades) if label == "perp" else 0.0,
                              adaptation=NOTES.get(id_, ""))
                report["execution"] += report["funding"]
                rows.append(report)
        status = "Tested · FMZ native round 3" if any(len(x) for x, _ in runs.values()) else "Tested · FMZ native round 3, no closes"
        coverage[id_] = [status, f"{interval} Binance {label}, {step // 60}m base data, reconciled native order history. " + NOTES.get(id_, "")]
    write(output, {
        "baseline": "f66984c", "source_revision": FMZ_REF, "engine_sha256": ENGINE_SHA,
        "coverage": [[id_, *outcome] for id_, outcome in sorted(coverage.items())],
        "public_parameters": read(work / "round3-parameter-checks.json"),
        "isolation": {
            "javascript": read(work / "round3-isolation-js.json"),
            "python": read(scratch / "round3-native-python" / "round3-isolation-python.json"),
        },
        "order_evidence": evidence, "results": rows,
        "specs": [{"id": key[0], "feed": job["feed"], "cfg": job["cfg"], "args": job.get("args", job.get("item", {}).get("args"))}
                  for key, job in sorted(specs.items())],
    })
    print(len(coverage), "dispositions and", len(rows), "native result rows")


def perp_metrics(record, job, work):
    feed, cfg = job["feed"], job["cfg"]
    assert not record["resting"] and not record["account"]["FrozenBalance"], "Resting or frozen futures orders need a separate ledger"
    begin, end = (stamp(feed[k]) * 1000 for k in ("start", "end"))
    assert end - 60_000 <= record["snapshotTime"] <= end
    step = feed["step"] * 1000

    def load(name):
        source = (work / feed[name]["file"]).read_bytes()
        assert digest(source) == feed[name]["sha256"]
        frame = json.loads(source)
        return {row[0]: row for row in frame["data"]}, 10 ** frame["detail"]["quotePrecision"]

    market, _ = load("market")
    index, index_scale = load("index")
    funding, funding_scale = load("funding")

    def carry(entry, exit_, side, qty):
        return sum(-side * qty * index[t // step * step][1] / index_scale * row[4] / funding_scale
                   for t, row in funding.items() if entry < t < exit_)

    trades, held = [], None
    fees = gross = closed_carry = open_carry = 0.0
    for order in sorted(record["orders"], key=lambda o: (o["Time"], o["Id"])):
        if not order["DealAmount"]:
            continue
        t, price, qty = (order[k] for k in ("Time", "AvgPrice", "DealAmount"))
        assert begin <= t < end and order["Symbol"] == feed["coin"] + "_USDT.swap"
        assert order["Price"] == 0 and order["Type"] in (0, 1) and order["Offset"] in (0, 1), "Limit-order fill timestamps are unavailable"
        assert qty > 0 and price > 0 and market[t // step * step][5] > 0
        fees += price * qty * cfg["fee"]
        side = 1 if order["Type"] == 0 else -1
        if order["Offset"] == 0:
            assert held is None, "Multiple concurrent futures positions need separate lot and margin accounting"
            held = t, price, qty, side
            continue
        assert held is not None, "Native close has no reconstructed entry"
        at, basis, size, direction = held
        assert side == -direction and qty == size and t > at
        funding_cash = carry(at, t, direction, qty)
        raw = direction * qty * (price - basis)
        turnover = qty * (basis + price)
        after = raw - turnover * cfg["fee"]
        trades.append((t, raw, after, after - turnover * EXECUTION + funding_cash, funding_cash))
        gross += raw
        closed_carry += funding_cash
        held = None
    positions = record["positions"]
    assert len(positions) == int(held is not None)
    margin = 0.0
    if held:
        at, basis, qty, side = held
        [position] = positions
        assert position["Price"] == basis and position["Amount"] == qty
        assert position["Type"] == (0 if side == 1 else 1) and position["FrozenAmount"] == 0
        margin = basis * qty / position["MarginLevel"]
        assert abs(position["Margin"] - margin) <= 1e-7
        open_carry = carry(at, record["snapshotTime"], side, qty)
    account = record["account"]
    reconstructed = cfg["balance"] + gross - fees + closed_carry + open_carry - margin
    cash_error = account["Balance"] - reconstructed
    assert abs(cash_error) < .00001, "Native funding and margin do not reconcile within 0.00001 USDT"
    assert abs(account["Equity"] - (account["Balance"] + margin + account["UPnL"])) < 1e-6
    return trades, len(positions), {"cash_error": cash_error, "closed_funding": closed_carry, "open_funding": open_carry}


if __name__ == "__main__":
    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument("action", choices=("stage", "finish"))
    arg.add_argument("scratch", type=Path)
    arg.add_argument("output", type=Path, nargs="?")
    options = arg.parse_args()
    if options.action == "stage":
        stage(options.scratch)
    else:
        finish(options.scratch, options.output)
