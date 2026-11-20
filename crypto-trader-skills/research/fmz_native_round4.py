"""Stage and reconcile fourth-round isolated FMZ native spot trials."""

import argparse
import csv
import hashlib
import io
import json
import math
import shutil
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.delta_strategy_replay import EQUITY, FEE, summarize
from research.fmz_native_expanded_replay import BLOCKS, order_metrics
from research.fmz_native_round3 import KEYS, PENDING, WINDOWS
from research.fmz_native_public_params import StrategyPage
from research.fmz_native_spot_replay import ENGINE_SHA

HERE = Path(__file__).parent
SETTINGS = {
    472: ("1h", 300, {}),
    696: ("1m", 60, {}),
    697: ("1m", 60, {}),
    1098: ("1m", 60, {}),
    1107: ("15m", 300, {}),
    1530: ("15m", 300, {"wall_sleep": True}),
    4371: ("15m", 300, {"market_cash_trace": True}),
    4372: ("15m", 300, {"market_cash_trace": True}),
    4860: ("1d", 900, {"pandas_append": True}),
    5162: ("4h", 900, {}),
    5510: ("1m", 60, {}),
}
NOTES = {
    472: "Spot broker on a 1h chart with 5m simulated ticks.",
    696: "Archived OKEX rule on one-minute Binance spot, whose candle path models grid fills.",
    697: "Archived OKEX rule on one-minute Binance spot.",
    1098: "Public Bollinger parameters and source one-minute records with native TA-Lib.",
    1107: "Native candle-derived fills on the study's 15m chart.",
    1530: "Map time.sleep to the native virtual clock without changing the source's intervals.",
    4371: "Use source-matched public grid ratios and investment amount.",
    4372: "Use source-matched public grid ratios and investment amount.",
    4860: "Binance spot replaces archived OKEX. Use pandas concat for the removed append method.",
    5162: "Use the archived four-hour RSI interval with the native chart cache.",
    5510: "The source's public settings fix the interval and history length. Native spot minimums apply.",
}
PY_TIMEOUT_BATCHES = ((472, 4860), (696, 697, 1098), (1107, 5162))
JS_SETTINGS = {
    23: ("15m", 300),
    62: ("15m", 300),
    1309: ("15m", 300),
    1840: ("1d", 900),
    1849: ("1d", 900),
    5140: ("1d", 900),
}
JS_NOTES = {
    23: "Use FMZ's published trade-template code and stated limit-mode assumptions.",
    62: "Use archived RSI/ATR rules and BCH settings on the workbook's BTC and ETH markets.",
    1309: "Use the published trade template with Binance minimum notional converted to base quantity at the current quote.",
    1840: "Use the archived 1d logic, a 15m base and the documented candidate trade template.",
    1849: "Use the archived 1d logic and the documented candidate trade template.",
    5140: "Preserve requested 15m historical records and the daily chart.",
}
PREVIOUS = "remaining-backtest-round3-coverage.json"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def spot_minutes(scratch, target, coin, template):
    market = scratch / "nonpine" / "binance"
    manifest = read(market / "manifest.json")
    raw = read(scratch / "round3-native" / template["file"])
    price_scale = Decimal(10) ** raw["detail"]["quotePrecision"]
    volume_scale = Decimal(10) ** raw["detail"]["basePrecision"]
    rows, providers = [], []
    for path in sorted(market.glob(f"klines-spot-{coin}USDT-1m-*.zip")):
        payload = path.read_bytes()
        provider = manifest[path.name]
        assert sha(payload) == provider["sha256_or_error"], path
        providers.append(provider)
        with ZipFile(io.BytesIO(payload)) as archive:
            [member] = archive.namelist()
            with archive.open(member) as file:
                for row in csv.reader(io.TextIOWrapper(file, encoding="ascii")):
                    t, a, h, l, c, v = row[:6]
                    assert len(t) == 16
                    o, h, l, c = (int(Decimal(value) * price_scale) for value in (a, h, l, c))
                    v = int(Decimal(v) * volume_scale)
                    assert 0 < l <= min(o, c) <= max(o, c) <= h and v >= 0
                    rows.append([int(t) // 1000, o, h, l, c, v])
    assert len(providers) == 7 and all(b[0] - a[0] == 60_000 for a, b in zip(rows, rows[1:]))
    tape = {k: raw[k] for k in ("detail", "schema")}
    assert tape["detail"]["symbol"] == f"{coin}_USDT"
    assert sha((scratch / "round3-native" / template["file"]).read_bytes()) == template["sha256"]
    tape["data"] = rows
    output = target / f"round4-Binance-{coin}-60.json"
    write(output, tape)
    return {"file": output.name, "sha256": sha(output.read_bytes()), "providers": providers,
            "detail_receipt": template}


def prepare(scratch, target):
    prev = scratch / "round3-native"
    old = [r for r in read(prev / "native-jobs.json") if r["id"] == 1530]
    spot_5m = {(r["feed"]["coin"], r["feed"]["start"]): r["feed"]["market"] for r in old}
    js = read(prev / "round3-native-jobs.json")
    spot_15m = {(r["feed"]["coin"], r["feed"]["start"]): r["feed"]["market"] for r in js if r["id"] == 5140}
    sources = [r for r in read(scratch / "native-expanded" / "native-python-screen.json") if r["id"] in SETTINGS]
    assert {r["id"] for r in sources} == SETTINGS.keys()
    entries = {r["id"]: r for r in read(HERE / PREVIOUS)["disposition"]}
    public = read(prev / "round3-parameter-checks.json") + read(scratch / "round4" / "native-params" / "receipt.json")
    params = {r["id"]: r for r in public if "args" in r}
    feeds = {}
    for step, group in ((300, spot_5m), (900, spot_15m)):
        assert group.keys() == KEYS
        for key, meta in group.items():
            assert sha((prev / meta["file"]).read_bytes()) == meta["sha256"]
            shutil.copyfile(prev / meta["file"], target / meta["file"])
            feeds[(*key, step)] = meta
    for coin in ("BTC", "ETH"):
        tape = spot_minutes(scratch, target, coin, spot_5m[coin, min(WINDOWS)])
        for start in WINDOWS:
            feeds[(coin, start, 60)] = tape
    jobs = []
    with ZipFile(scratch / "fmz.zip") as archive:
        for row in sources:
            id_ = row["id"]
            assert entries[id_]["status"] == PENDING
            name = unquote(row["source"].split(f"/{FMZ_REF}/", 1)[1])
            content = archive.read(f"strategies-{FMZ_REF}/{name}")
            assert sha(content) == row["source_sha256"]
            assert row["code"] in {code.lstrip("\ufeff") for _, code in BLOCKS.findall(content.decode())}
            period, step, options = SETTINGS[id_]
            param = params.get(id_, {})
            item = {**row, "args": {**param.get("args", {}), **row["args"]}}
            for coin, start in sorted(KEYS):
                end = WINDOWS[start][0]
                meta = feeds[coin, start, step]
                feed = {**meta, "coin": coin, "start": start, "end": end,
                        "period": period, "base": f"{step // 60}m", "base_seconds": step,
                        "symbol": f"{coin}_USDT"}
                jobs.append({"item": item, "feed": feed, "options": options, "parameters": param})
    write(target / "round4-native-python-jobs.json", jobs)
    print(len(jobs), "staged Python jobs")


def prepare_js(scratch, target):
    prev = scratch / "round3-native"
    archive = scratch / "fmz.zip"
    html = (target / "fmz-template-tutorial.html").read_bytes()
    page = StrategyPage()
    page.feed(html.decode("utf-8"))
    [pre] = [pre for pre in page.previews if "function StripOrders" in pre]
    template = pre.split("var _MACalcMethod", 1)[0].strip()
    assert template.startswith("function CancelPendingOrders") and "function Trade" in template
    assert all(f"$.{name} = function" in template for name in ("Buy", "Sell", "GetAccount", "CancelPendingOrders"))
    defaults = {"OpMode": 0, "SlidePrice": 0.10, "MaxAmount": 1, "MaxSpace": 1, "RetryDelay": 1000}
    library = {"url": "https://www.fmz.com/bbs-topic/483", "page_sha256": sha(html),
               "template_sha256": sha(template.encode()), "assumed_defaults": defaults}
    stored = read(target / "round4-native-python-jobs.json")
    feeds = {(r["feed"]["coin"], r["feed"]["start"], r["feed"]["base_seconds"]): r["feed"] for r in stored}
    entries = {r["id"]: r for r in read(HERE / PREVIOUS)["disposition"]}
    public = read(prev / "round3-parameter-checks.json")
    public += read(scratch / "native-expanded" / "native-public-parameters.json")
    params = {r["id"]: r for r in public if "args" in r}
    sources = read(scratch / "native-expanded" / "native-enriched-candidates.json")
    trials, specs = [], []
    with ZipFile(archive) as pinned:
        for row in sources:
            id_ = row["id"]
            if id_ not in JS_SETTINGS:
                continue
            assert entries[id_]["status"] == PENDING
            name = unquote(row["source"].split(f"/{FMZ_REF}/", 1)[1])
            raw = pinned.read(f"strategies-{FMZ_REF}/{name}")
            assert sha(raw) == row["source_sha256"]
            assert row["code"] in {code.lstrip("\ufeff") for _, code in BLOCKS.findall(raw.decode())}
            args = {**params.get(id_, {}).get("args", {}), **row["args"]}
            uses_library = "$." in row["code"]
            code = row["code"]
            if uses_library:
                args = {**defaults, **args}
                code = "var $ = {};\n" + template + "\n" + code
            interval, step = JS_SETTINGS[id_]
            for coin, start in sorted(KEYS):
                feed = {**feeds[coin, start, step], "period": interval}
                market = {"file": feed["file"], "sha256": feed["sha256"]}
                worker_feed = {**feed, "eid": "Binance", "step": step, "market": market}
                cfg = {"balance": EQUITY, "fee": .00059, "timeout": 100_000, "minOrderSize": id_ == 1309}
                trials.append({"id": id_, "args": args, "code": code, "cfg": cfg, "feed": worker_feed})
                specs.append({"item": {**row, "args": args}, "feed": feed,
                              "options": {**({"template": library} if uses_library else {}),
                                          "min_order_size": cfg["minOrderSize"]},
                              "parameters": params.get(id_, {}), "worker_code_sha256": sha(code.encode())})
    assert {r["id"] for r in trials} == JS_SETTINGS.keys()
    upstream = (target / "upstream.cjs").read_bytes()
    assert sha(upstream) == ENGINE_SHA
    marker = b"},httpGet=function(url){let options"
    assert upstream.count(marker) == 1
    adapted = upstream.replace(marker, b"},httpGet=function(url){return globalThis.__offlineProbe(url);let options")
    (target / "fmz-wasm-engine.cjs").write_bytes(adapted)
    worker = (HERE / "fmz_native_round3_worker.cjs").read_text(encoding="utf-8").replace("round3-native", "round4-native")
    worker = worker.replace("end - 10000", "end - 55000")
    marker = "if (!exchange.GetMinStock) exchange.GetMinStock = () => source.detail.minQty;"
    assert worker.count(marker) == 1
    worker = worker.replace(marker, marker + """
    if (cfg.minOrderSize) exchange.GetMinStock = () => {
      const quote = ticker();
      const scale = 10 ** source.detail.basePrecision;
      const leastPrice = Math.min(quote.Buy, quote.Sell) - Math.abs(args.SlidePrice);
      assert.ok(leastPrice > 0);
      return Math.max(source.detail.minQty, Math.ceil(source.detail.minNotional / leastPrice * scale) / scale);
    };
""")
    marker = "const id = {id: trial.id, coin: trial.feed.coin, start: trial.feed.start};"
    assert worker.count(marker) == 1
    worker = worker.replace(marker, "const id = {id: trial.id, coin: trial.feed.coin, start: trial.feed.start,\n"
                            "      worker_sha256: createHash('sha256').update(fs.readFileSync(__filename)).digest('hex')};")
    (target / "round4-native-worker.cjs").write_text(worker, encoding="utf-8")
    write(target / "round4-native-jobs.json", trials)
    write(target / "round4-native-javascript-jobs.json", specs)
    print(len(trials), "staged JavaScript jobs")


def finish(target, output, js=False):
    language = "javascript" if js else "python"
    settings, notes = (JS_SETTINGS, JS_NOTES) if js else (SETTINGS, NOTES)
    specs = {}
    for job in read(target / f"round4-native-{language}-jobs.json"):
        item, feed = job["item"], job["feed"]
        specs[(item["id"], feed["coin"], feed["start"])] = job
    trials = {}
    prefix = "js" if js else "python"
    for path in sorted(target.glob(f"round4-native-{prefix}-*.jsonl"), key=lambda file: file.stat().st_mtime_ns):
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            trials[row["id"], row["coin"], row["start"]] = row
    results, evidence, coverage = [], [], []
    display_language = "JavaScript" if js else "Python"
    for id_ in settings:
        runs = {}
        blocked = set()
        for coin, start in sorted(KEYS):
            key = id_, coin, start
            job = specs[key]
            trial = trials.get(key, {"reason": "No complete bounded worker receipt"})
            descriptor = {"id": id_, "coin": coin, "start": start,
                          "tape_sha256": job["feed"]["sha256"], "receipt": trial}
            try:
                if "reason" in trial:
                    raise ValueError(trial["reason"])
                accounting = {**trial, "last": {"Time": trial["snapshotTime"]}} if js else trial
                fills, opened, recon = order_metrics(
                    accounting, {**job, "directory": target}, market_buy_fee_on_turnover=not js,
                )
                if job["options"].get("market_cash_trace"):
                    recon["max_trade_delta_error"] = trace_error(trial)
                runs[coin, start] = fills, opened
                evidence.append({**descriptor, "reconciliation": recon})
            except (AssertionError, ValueError, KeyError, TypeError, IndexError) as exc:
                reason = str(exc) or "Native order ledger lacks verifiable trade or settlement data"
                evidence.append({**descriptor, "reason": reason})
                blocked.add(reason)
        if runs.keys() != KEYS:
            batch = next((group for group in PY_TIMEOUT_BATCHES if not js and id_ in group), None)
            reason = f"Isolated Python batch {batch} reached its 175-second limit before all four reconciled snapshots." if batch else " | ".join(sorted(blocked))
            coverage.append([id_, PENDING, reason])
            continue
        if not any(fills or opened for fills, opened in runs.values()):
            coverage.append([id_, PENDING, "All four boundary snapshots reconciled. No native fill validated the source's order lifecycle."])
            continue
        has_close = any(fills for fills, _ in runs.values())
        item = next(job["item"] for key, job in specs.items() if key[0] == id_)
        for start, (_, label) in WINDOWS.items():
            btc, ob = runs["BTC", start]
            eth, oe = runs["ETH", start]
            for scope, fills, opened in (("BTCUSDT", btc, ob), ("ETHUSDT", eth, oe), ("BTCUSDT + ETHUSDT", btc + eth, ob + oe)):
                row = summarize((f"FMZ native {display_language} · Binance spot", item["name"], scope + " spot",
                                 "Native archived order rule"), label, fills, opened)
                row.update(id=id_, source=item["source"], source_sha256=item["source_sha256"],
                           interval=settings[id_][0], starting_equity=EQUITY, adaptation=notes[id_],
                           market_data="Binance spot one-minute or FMZ public spot history", quote_currency="USDT", funding=0.0)
                results.append(row)
        coverage.append([id_, f"Tested · FMZ native {display_language} variant" + ("" if has_close else ", no closes"), notes[id_]])
    clean_specs = [
        {"id": key[0], "feed": job["feed"], "options": job["options"], "args": job["item"]["args"],
         "parameter_evidence": job["parameters"], "source": job["item"]["source"],
         "source_sha256": job["item"]["source_sha256"], "code_sha256": sha(job["item"]["code"].encode()),
         "worker_code_sha256": job.get("worker_code_sha256")}
        for key, job in specs.items()
    ]
    engine = ({"engine_sha256": ENGINE_SHA, "worker_sha256": sha((target / "round4-native-worker.cjs").read_bytes())} if js else
              {"engine_loader_sha256": sha((target / "official_fmz_python.py").read_bytes()),
               "engine_binary_sha256": sha((target / "depends" / "backtest_py_windows_64bit.so").read_bytes()),
               "worker_sha256": sha((target / "fmz_native_python_round4_worker.py").read_bytes())})
    write(output, {"baseline": "fd4ad038", "source_revision": FMZ_REF, **engine,
                   "isolation": read(target / f"round3-isolation-{prefix}.json"), "specs": clean_specs,
                   "bounded_batch_exits": [] if js else [
                       {"ids": group, "launcher_exit": 124, "wall_limit_seconds": 175} for group in PY_TIMEOUT_BATCHES
                   ],
                   "coverage": coverage, "order_evidence": evidence, "results": results})
    print(len(coverage), "dispositions,", len(results), "result rows")


def trace_error(trial):
    errors = []
    for fill in trial["orders"]:
        if not fill["DealAmount"]:
            continue
        before, after = trial["trade_account"][str(fill["Id"])]
        assert not (before["FrozenBalance"] or after["FrozenBalance"] or before["FrozenStocks"] or after["FrozenStocks"])
        direction = 1 if fill["Type"] == 0 else -1
        qty = fill["DealAmount"]
        cash = -qty * fill["AvgPrice"] * (direction + FEE)
        errors.append(abs(after["Balance"] - before["Balance"] - cash))
        assert math.isclose(after["Stocks"] - before["Stocks"], direction * qty, abs_tol=1e-9, rel_tol=0)
    maximum = max(errors, default=0.0)
    assert maximum < 1e-8, "Native per-order cash debits and credits differ from the fee model"
    return maximum


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "stage-js", "finish", "finish-js"))
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    options = parser.parse_args()
    if options.action == "stage":
        prepare(options.source, options.target)
    elif options.action == "stage-js":
        prepare_js(options.source, options.target)
    else:
        finish(options.source, options.target, js=options.action == "finish-js")
