"""Stage and reconcile selected fifth-round FMZ native spot replays."""

import argparse
import json
import re
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.delta_strategy_replay import EQUITY, FEE, summarize
from research.fmz_native_expanded_replay import BLOCKS, order_metrics
from research.fmz_native_public_params import StrategyPage
from research.fmz_native_round3 import KEYS, PENDING, WINDOWS
from research.fmz_native_round4 import NOTES, sha
from research.fmz_native_spot_replay import ENGINE_SHA

HERE = Path(__file__).parent
BASE = "8fc965fe"
SPOT_JS = {
    31: ("15m", 300, "Use the published spot template in the source's long grid branch, poll once per minute and discard grid entries whose entry order did not fill."),
    424: ("1m", 60, "Use the published cap and sizing parameters, seed 424 and the instrument's quote precision."),
    739: ("15m", 300, "Retry the pinned RSI strategy with the original order conditions and isolated Binance spot data."),
    1379: ("1m", 60, "Use the published cap and displayed sizing parameters with seed 1379."),
    4345: ("1h", 900, "Substitute each study instrument for archived LTC and use the published spot trade template."),
    5134: ("15m", 300, "Use the matched public EMA and trailing-stop settings. Size the long entry from starting cash converted at the current ask because starting spot inventory is zero."),
    5170: ("15m", 300, "Use matched public EMA durations and the published spot trade template's limit mode."),
    5171: ("15m", 300, "Use a 15-minute chart with matched public EMA durations and the archived market mode in the published spot trade template."),
    5686: ("15m", 300, "Keep archived Martingale sizing and its limit-order lifecycle on Binance spot."),
}
PY_IDS = {472, 696, 697, 1098, 1107, 4860, 5162}
ORDER_FIELDS = ("Id", "Time", "Amount", "Price", "AvgPrice", "DealAmount", "Symbol", "Type", "Offset", "Status")


def replace_once(code, original, updated):
    assert code.count(original) == 1, original
    return code.replace(original, updated)


def assert_source(job, archived, expected):
    item = job["item"]
    assert item["source"] == expected["source"]
    name = unquote(item["source"].split(f"/{FMZ_REF}/", 1)[1])
    raw = archived.read(f"strategies-{FMZ_REF}/{name}")
    assert sha(raw) == item["source_sha256"] == expected["document_sha256"]
    assert item["code"] in {body.lstrip("\ufeff") for _, body in BLOCKS.findall(raw.decode("utf-8"))}


def warm_tape(scratch, target, feed, span):
    prior = read(HERE / "fmz-native-round3.json")["specs"]
    [tape] = [row["feed"]["market"] for row in prior if row["id"] == 2515 and
              row["feed"]["coin"] == feed["coin"] and row["feed"]["start"] == feed["start"]]
    raw = (scratch / "round3-native" / tape["file"]).read_bytes()
    assert sha(raw) == tape["sha256"]
    original = json.loads(raw)
    milliseconds = span * 1000
    grouped = {}
    for row in original["data"]:
        assert len(row) == 6 and row[0] % 3600000 == 0
        grouped.setdefault(row[0] // milliseconds * milliseconds, []).append(row)
    data = []
    for start, rows in grouped.items():
        if len(rows) != span // 3600:
            continue
        data.append([start, rows[0][1], max(row[2] for row in rows), min(row[3] for row in rows),
                     rows[-1][4], sum(row[5] for row in rows)])
    assert data and all(b[0] - a[0] == milliseconds for a, b in zip(data, data[1:]))
    output = target / f"round5-warm-{feed['coin']}-{feed['start']}-{span}.json"
    write(output, {**original, "data": data})
    return {"file": output.name, "sha256": sha(output.read_bytes()), "period_ms": milliseconds, "source_tape": tape}


def stage(scratch, target, language):
    audit = {r["id"]: r for r in read(HERE / "fmz-native-round4-coverage.json")["disposition"]}
    pending = {r["id"] for r in read(HERE / "remaining-backtest-round4-coverage.json")["disposition"]
               if not r["status"].startswith("Tested")}
    previous = read(target / "round4-native-python-jobs.json")
    specs = []
    with ZipFile(scratch / "fmz.zip") as archive:
        if language == "python":
            for job in previous:
                item = job["item"]
                id_ = item["id"]
                if id_ not in PY_IDS:
                    continue
                assert id_ in pending and audit[id_]["scope"] != "pine"
                assert_source(job, archive, audit[id_])
                job["adaptation"] = NOTES[id_]
                if id_ == 1107:
                    code = item["code"]
                    code = "from bisect import bisect_left, bisect_right\n" + code
                    item["code"] = replace_once(code, "for i in range(len(line)):",
                        "left, right = sorted(last_tick[-2:])\n"
                        "    for i in range(bisect_right(line, left), bisect_left(line, right)):")
                    job["adaptation"] += " Scan only grid lines strictly between consecutive quotes."
                if id_ == 5162:
                    item["code"] = replace_once(item["code"], "        i = i + 1\n", "        Sleep(60_000)\n        i = i + 1\n")
                    job["adaptation"] += " Add one-minute loop pacing to the source's four-minute post-order waits."
                if id_ in (4860, 5162):
                    job["feed"]["warmup"] = warm_tape(scratch, target, job["feed"], 86400 if id_ == 4860 else 14400)
                specs.append(job)
            worker = (HERE / "fmz_native_python_round4_worker.py").read_text(encoding="utf-8").replace("round4-native-", "round5-native-")
            worker = replace_once(worker, "    engine.httpGet = offline", "    engine.httpGet = offline\n    engine.readCache = lambda _: None\n    engine.writeAtomic = lambda *_: None")
            (target / "fmz_native_python_round5_worker.py").write_text(worker, encoding="utf-8")
            marker = '        assert q["event"][0] in ("feed", "fill") and int(q["period"][0]) == feed["base_seconds"] * 1000, url'
            worker = replace_once(worker, marker, '''
        step = int(q["period"][0])
        assert q["event"][0] in ("feed", "fill"), url
        selected = history
        if step != feed["base_seconds"] * 1000:
            warm = feed["warmup"]
            assert q["event"][0] == "fill" and warm["period_ms"] == step, url
            old = (ROOT / warm["file"]).read_bytes()
            assert hashlib.sha256(old).hexdigest() == warm["sha256"]
            selected = json.loads(old)''')
            worker = replace_once(worker, '        step = feed["base_seconds"] * 1000\n', '')
            worker = replace_once(worker, 'history["data"][0][0] <= start + step - 1 and history["data"][-1][0] >= stop - step',
                                  'selected["data"][0][0] <= start + step - 1 and selected["data"][-1][0] >= stop - step')
            worker = replace_once(worker, 'json.dumps({**history, "data": [r for r in history["data"] if start <= r[0] <= stop]})',
                                  'json.dumps({**selected, "data": [r for r in selected["data"] if start <= r[0] <= stop]})')
            (target / "fmz_native_python_round5_warm_worker.py").write_text(worker, encoding="utf-8")
        else:
            specs = stage_js(scratch, target, previous, pending, audit, archive)
    assert {job["item"]["id"] for job in specs} == (PY_IDS if language == "python" else SPOT_JS.keys())
    write(target / f"round5-native-{language}-jobs.json", specs)


def stage_js(scratch, target, previous, pending, audit, archive):
    params = {r["id"]: r for r in read(target / "parameter-receipts.json")}
    html = (target / "fmz-template-tutorial.html").read_bytes()
    page = StrategyPage()
    page.feed(html.decode("utf-8"))
    [pre] = [pre for pre in page.previews if "function StripOrders" in pre]
    template = pre.split("// 仅调试模板策略用", 1)[0].strip()
    assert template.startswith("function CancelPendingOrders") and "$.Cross = function" in template
    library = {"url": "https://www.fmz.com/bbs-topic/483", "page_sha256": sha(html), "code_sha256": sha(template.encode())}
    defaults = {"OpMode": 0, "SlidePrice": .1, "MaxAmount": 1, "MaxSpace": 1, "RetryDelay": 1000, "MAType": 0}
    feeds = {(j["feed"]["coin"], j["feed"]["start"], j["feed"]["base_seconds"]): j["feed"] for j in previous}
    candidates = read(scratch / "native-expanded" / "native-enriched-candidates.json")
    specs, trials = [], []
    for row in candidates:
        id_ = row["id"]
        if id_ not in SPOT_JS:
            continue
        assert id_ in pending and audit[id_]["scope"] != "pine"
        assert_source({"item": row}, archive, audit[id_])
        code = row["code"]
        args = {**params.get(id_, {}).get("args", {}), **row["args"]}
        period, step, adaptation = SPOT_JS[id_]
        uses_template = bool(re.search(r"\$\.(Buy|Sell|Cross)\(", code))
        if uses_template:
            assert set(re.findall(r"\$\.(\w+)", code)) <= {"GetAccount", "CancelPendingOrders", "Buy", "Sell", "Cross", "PlotFlag", "PlotRecords"}
            args = {**defaults, **args}
            code = "var $ = { PlotFlag() {}, PlotRecords() {} };\n" + template + "\n" + code
        if id_ == 31:
            args["direction"] = -1
            code = replace_once(code, "        _Grid[_Grid.length - 1].hold.price = tradeInfo.price",
                                "        if (!tradeInfo) { _Grid.pop(); return; }\n"
                                "        _Grid[_Grid.length - 1].hold.price = tradeInfo.price")
            marker = "        Sleep(500)\n    }\n}"
            code = replace_once(code, marker, "        Sleep(60000)\n    }\n}")
        if id_ == 4345:
            code = replace_once(code, 'exchange.SetCurrency("LTC_USDT")', 'exchange.SetCurrency(exchange.GetCurrency())')
        if id_ == 5134:
            code = replace_once(code, "initAccount.Stocks * PositionRatio", "(n > 0 ? initAccount.Balance / exchange.GetTicker().Sell : initAccount.Stocks) * PositionRatio")
        if id_ in {424, 1379}:
            code = f"let replaySeed = {id_};\nMath.random = () => (replaySeed = (1664525 * replaySeed + 1013904223) >>> 0) / 4294967296;\n" + code
        for coin, start in sorted(KEYS):
            feed = {**feeds[coin, start, step], "period": period}
            cfg = {"balance": EQUITY, "fee": FEE, "timeout": 100_000, "minOrderSize": uses_template}
            case_args = args
            if id_ == 424:
                tape = (target / feed["file"]).read_bytes()
                assert sha(tape) == feed["sha256"]
                case_args = {**args, "PricePerision": json.loads(tape)["detail"]["quotePrecision"]}
            spec = {"item": {**row, "args": case_args, "code": code}, "feed": feed, "cfg": cfg,
                    "adaptation": adaptation, "parameters": params.get(id_, {}),
                    "template": library if uses_template else None}
            specs.append(spec)
            market = {"file": feed["file"], "sha256": feed["sha256"]}
            trials.append({"id": id_, "code": code, "args": case_args, "cfg": cfg,
                           "feed": {**feed, "eid": "Binance", "step": step, "market": market}})
    upstream = (target / "upstream.cjs").read_bytes()
    assert sha(upstream) == ENGINE_SHA
    hook = b"},httpGet=function(url){let options"
    assert upstream.count(hook) == 1
    (target / "fmz-wasm-engine.cjs").write_bytes(upstream.replace(hook, b"},httpGet=function(url){return globalThis.__offlineProbe(url);let options"))
    worker = (HERE / "fmz_native_round3_worker.cjs").read_text(encoding="utf-8").replace("round3-native", "round5-native")
    worker = worker.replace("end - 10000", "end - 55000")
    worker = replace_once(worker, "  const {scope} = ctx;", "  const {scope} = ctx;\n  scope.EnableLog(false);")
    marker = "if (!exchange.GetMinStock) exchange.GetMinStock = () => source.detail.minQty;"
    worker = replace_once(worker, marker, marker + """
    if (cfg.minOrderSize) exchange.GetMinStock = () => {
      const quote = ticker();
      const scale = 10 ** source.detail.basePrecision;
      const leastPrice = Math.min(quote.Buy, quote.Sell) - Math.abs(args.SlidePrice);
      assert.ok(leastPrice > 0);
      return Math.max(source.detail.minQty, Math.ceil(source.detail.minNotional / leastPrice * scale) / scale);
    };""")
    marker = "const id = {id: trial.id, coin: trial.feed.coin, start: trial.feed.start};"
    worker = replace_once(worker, marker, "const id = {id: trial.id, coin: trial.feed.coin, start: trial.feed.start, "
                          "worker_sha256: createHash('sha256').update(fs.readFileSync(__filename)).digest('hex'), "
                          "code_sha256: createHash('sha256').update(trial.code).digest('hex')};")
    (target / "round5-native-worker.cjs").write_text(worker, encoding="utf-8")
    write(target / "round5-native-jobs.json", trials)
    return specs


def finish(target, output, language):
    prefix = "js" if language == "javascript" else language
    worker_name = "round5-native-worker.cjs" if prefix == "js" else "fmz_native_python_round5_worker.py"
    worker_sha = sha((target / worker_name).read_bytes())
    allowed_workers = {worker_sha}
    if language == "python":
        allowed_workers.add(sha((target / "fmz_native_python_round5_warm_worker.py").read_bytes()))
    isolation = read(target / f"round3-isolation-{prefix}.json")
    if prefix == "js":
        assert isolation["privateRead"] == "ERR_ACCESS_DENIED" and isolation["network"] == "EACCES"
    else:
        assert isolation["file_error"][0] == isolation["network_error"][0] == "PermissionError"
    receipts = {}
    for path in sorted(target.glob(f"round5-native-{prefix}-*.jsonl"), key=lambda p: p.stat().st_mtime_ns):
        for line in path.read_text(encoding="utf-8").splitlines():
            receipt = json.loads(line)
            if receipt["worker_sha256"] in allowed_workers:
                key = receipt["id"], receipt["coin"], receipt["start"]
                if "reason" not in receipt or "reason" in receipts.get(key, {"reason": ""}):
                    receipts[key] = receipt
    groups = {}
    for spec in read(target / f"round5-native-{language}-jobs.json"):
        groups.setdefault(spec["item"]["id"], []).append(spec)
    results, coverage, evidence = [], [], []
    for id_, specs in sorted(groups.items()):
        scenarios, issues = {}, set()
        for spec in specs:
            item, feed = spec["item"], spec["feed"]
            key = feed["coin"], feed["start"]
            receipt = receipts.get((id_, *key))
            evidence_row = {"id": id_, "coin": key[0], "start": key[1], "source_sha256": item["source_sha256"],
                            "worker_code_sha256": sha(item["code"].encode()), "args": item["args"],
                            "feed": feed, "parameters": spec["parameters"]}
            if receipt and "orders" in receipt:
                fields = ("account", "last", "snapshotTime", "requests", "calls", "sleepCalls", "resting",
                          "ended_early", "endedEarly", "worker_sha256", "code_sha256")
                evidence_row["receipt"] = {key: receipt[key] for key in fields if key in receipt}
                evidence_row["receipt"]["orders"] = [[order.get(field) for field in ORDER_FIELDS] for order in receipt["orders"]]
            if spec.get("template"):
                evidence_row["template"] = spec["template"]
            try:
                if receipt is None or receipt.get("reason"):
                    raise ValueError(receipt.get("reason") if receipt else "No complete isolated snapshot")
                if prefix == "js":
                    assert receipt["code_sha256"] == evidence_row["worker_code_sha256"]
                accounting = {**receipt, "last": {"Time": receipt["snapshotTime"]}} if prefix == "js" else receipt
                fills, opened, recon = order_metrics(accounting, {"feed": feed, "directory": target},
                                                       market_buy_fee_on_turnover=prefix == "python")
                evidence_row["reconciliation"] = recon
                scenarios[key] = fills, opened
            except (AssertionError, KeyError, ValueError, IndexError) as exc:
                message = re.sub(r"\x1b\[[0-9;]*m", "", str(exc)) or "Native order ledger did not reconcile"
                issues.add(message)
                evidence_row["reason"] = message
            evidence.append(evidence_row)
        if scenarios.keys() != KEYS or not any(fills or opened for fills, opened in scenarios.values()):
            coverage.append([id_, PENDING, " | ".join(sorted(issues)) or "Four reconciled boundaries and no completed fill"])
            continue
        has_close = any(fills for fills, _ in scenarios.values())
        adaptation = specs[0]["adaptation"]
        for start, (_, window) in WINDOWS.items():
            btc, ob = scenarios["BTC", start]
            eth, oe = scenarios["ETH", start]
            for label, fills, opened in (("BTCUSDT", btc, ob), ("ETHUSDT", eth, oe), ("BTCUSDT + ETHUSDT", btc + eth, ob + oe)):
                result = summarize((f"FMZ native {language.title()} · Binance spot", item["name"], label + " spot",
                                    "Native archived order rule"), window, fills, opened)
                result.update(id=id_, source=item["source"], source_sha256=item["source_sha256"], interval=feed["period"],
                              starting_equity=EQUITY, adaptation=adaptation, market_data="Binance spot candles",
                              quote_currency="USDT", funding=0.0)
                results.append(result)
        coverage.append([id_, f"Tested · FMZ native {language.title()} variant" + ("" if has_close else ", no closes"), adaptation])
    display = "JavaScript" if prefix == "js" else "Python"
    for row in results:
        row["group"] = row["group"].replace(language.title(), display)
    for row in coverage:
        row[1] = row[1].replace(language.title(), display)
    engine = ({"engine_sha256": ENGINE_SHA} if prefix == "js" else
              {"engine_loader_sha256": sha((target / "official_fmz_python.py").read_bytes()),
               "engine_binary_sha256": sha((target / "depends" / "backtest_py_windows_64bit.so").read_bytes())})
    write(output, {"baseline": BASE, "source_revision": FMZ_REF, "isolation": isolation, "worker_sha256": sorted(allowed_workers),
                   **engine, "coverage": coverage, "order_fields": ORDER_FIELDS, "order_evidence": evidence, "results": results})
    print(len(groups), "dispositions and", len(results), "native result rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "finish"))
    parser.add_argument("language", choices=("javascript", "python"))
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    options = parser.parse_args()
    (stage if options.action == "stage" else finish)(options.source, options.target, options.language)
