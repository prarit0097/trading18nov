"""Recover pinned Python spot templates and original FMZ source settings."""

import argparse
import ast
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.delta_strategy_replay import EQUITY, drawdown, stamp, summarize
from research.fmz_native_expanded_replay import BLOCKS, order_metrics
from research.fmz_native_public_params import StrategyPage, normalized
from research.fmz_native_round3 import KEYS, WINDOWS
from research.fmz_native_round5 import replace_once
from research.fmz_native_round6_audit import BASE, ROOT, digest
from research.fmz_native_round6_replay import opening_metrics

CASES = {
    486: "Use native Binance spot and source 20-minute polling. The original chart is daily, but calculations read only the ticker.",
    693: "Use user-visible FMZ settings and the archived one-unit opening inventory with 10,000 USDT cash.",
    705: "Use the exact archived Python spot template and a syntax-only Python 3 migration. Sample the outer decision loop once a minute.",
    2453: "Use a one-minute native market tape for the original explicit one-minute records. The source sizing and limit order loop remain native.",
    2465: "Use the exact archived Python spot template, source-matched defaults and a syntax-only Python 3 migration.",
    2519: "Use the exact archived Python spot template and source-matched defaults on a 15-minute replay scenario. Seed half the study equity in base inventory to give the original sizing function its starting holdings.",
    5304: "Keep the source-matched grid and state parameters. Scope persistence to each run and sample its main loop once per minute.",
}
LEGACY = {705, 2465, 2519}


def legacy_python(code):
    code = re.sub(
        r"(\bexcept (?:Exception|ValueError|TypeError)),\s*([a-zA-Z_]\w*):",
        r"\1 as \2:",
        code,
    )
    for old, new in {
        "types.ListType": "list",
        "types.IntType": "int",
        "types.FloatType": "float",
    }.items():
        code = code.replace(old, new)
    return code


def source(archive, url):
    assert url.startswith(f"https://github.com/fmzquant/strategies/blob/{FMZ_REF}/")
    name = unquote(url.rsplit("/", 1)[1])
    data = archive.read(f"strategies-{FMZ_REF}/{name}")
    [original] = [
        s
        for tag, s in BLOCKS.findall(data.decode("utf-8"))
        if tag.strip().lower() == "python"
    ]
    return data, original.lstrip("\ufeff").replace("\r\n", "\n")


def display_settings(work, ident, original):
    raw = (work / f"{ident}.html").read_bytes()
    page = StrategyPage()
    html = raw.decode("utf-8")
    page.feed(html)
    nailed = normalized(original)
    match = max(
        (
            len(t)
            for text in page.previews
            if len(t := normalized(text)) >= 90 and t in nailed
        ),
        default=0,
    )
    assert match
    values = {k: v for k, v in page.values.items() if type(v) in (bool, int, float)}
    if ident == 2465:
        assert re.search(r"scriptArgList_MAType.{0,2500}>TA\.EMA<", html, re.DOTALL)
        assert re.search(r"\barray\s*=\s*\[\s*TA\.EMA\s*,\s*TA\.MA\s*\]", original)
        values["MAType"] = 0
    return {"preview_chars": match, "sha256": digest(raw), "args": values}


def template(archive, work):
    with (ROOT / "public-strategy-catalogue.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        library = list(csv.DictReader(stream))[1117]
    data, code = source(archive, library["source_url"])
    assert b"https://www.fmz.com/strategy/21104" in data
    raw = (work / "python-spot-template.html").read_bytes()
    page = StrategyPage()
    html = raw.decode("utf-8")
    page.feed(html)
    assert any(
        len(t := normalized(p)) > 5000 and t in normalized(code) for p in page.previews
    )
    for field, text in (("OpMode", "吃单"), ("MAType", "TA.EMA")):
        assert re.search(
            rf"scriptArgList_{field}.{{0,2500}}>{re.escape(text)}<", html, re.DOTALL
        )
    assert "mode == 0" in code and "_MACalcMethod = [TA.EMA,TA.MA][MAType]" in code
    settings = {
        k: page.values[k]
        for k in ("MaxSpace", "SlidePrice", "MaxAmount", "RetryDelay", "_GetMinStocks")
    }
    settings |= {"OpMode": 0, "MAType": 0}
    code = code[: code.index("\ndef main():")]
    ast.parse(code)
    evidence = {
        "document_sha256": digest(data),
        "source": library["source_url"],
        "page": "https://www.fmz.com/strategy/21104",
        "page_sha256": digest(raw),
        "runtime_sha256": digest(code.encode()),
        "args": settings,
    }
    return code, evidence


def header_settings(code):
    tree = ast.parse(code)
    text = ast.get_docstring(tree) or ""
    found = re.search(r"(?m)^exchanges:\s*(\[.*\])\s*$", text)
    if not found:
        return code, {}
    [market] = json.loads(found[1])
    settings = {name: market[name] for name in ("stocks", "balance") if name in market}
    lines = code.splitlines(keepends=True)
    # Venue and wallet fields in the archive's inert metadata stay out of the worker.
    return "".join(lines[tree.body[0].end_lineno :]), settings


def file_opening(target, feed, memory, ident):
    raw = (target / feed["file"]).read_bytes()
    assert digest(raw) == feed["sha256"]
    data = json.loads(raw)
    start = stamp(feed["start"]) * 1000
    ready = [r for r in data["data"] if r[0] + feed["base_seconds"] * 1000 <= start]
    prior = ready[-1]
    price = prior[4] / 10 ** data["detail"]["quotePrecision"]
    cash = memory.get("balance", EQUITY)
    qty = memory.get("stocks", 0)
    if ident == 2519 and qty == 0:
        size = 10 ** data["detail"]["basePrecision"]
        qty = int(EQUITY * 0.5 / price * size) / size
        cash = EQUITY - qty * price
    return {"price": price, "base": qty, "cash": cash, "timestamp": prior[0]}


def build_worker(target):
    path = target / "fmz_native_python_round6_worker.py"
    code = path.read_text(encoding="utf-8").replace("round6-native", "round7-native")
    code = replace_once(
        code, "import time\n", "import time\nfrom types import SimpleNamespace\n"
    )
    code = replace_once(
        code,
        "balance=10000, stocks=0, fee=[.059, .059]",
        'balance=options["opening"]["cash"], stocks=options["opening"]["base"], fee=[.059, .059]',
    )
    marker = '        runtime["Sleep"] = sleep\n'
    code = replace_once(
        code,
        marker,
        marker
        + """
        if options.get("empty_state"):
            memory = {}

            def persistent(key, *values):
                if not values:
                    value = memory.get(key)
                    return json.loads(value) if value is not None else None
                if values[0] is None:
                    memory.pop(key, None)
                else:
                    memory[key] = json.dumps(values[0])

            runtime["_G"] = persistent
            runtime["GetCommand"] = lambda: None
        if "template" in options:
            raw_template = (ROOT / "round7-native-spot-library.py").read_bytes()
            assert hashlib.sha256(raw_template).hexdigest() == options["template"]["runtime_sha256"]
            exported = SimpleNamespace()
            local = {**runtime, **options["template"]["args"], "ext": exported, "null": None}
            exec(compile(raw_template, "pinned-spot-library.py", "exec"), local)
            runtime["ext"] = exported
""",
    )
    (target / "fmz_native_python_round7_worker.py").write_text(
        code, encoding="utf-8", newline="\n"
    )


def stage(archive, work, target):
    byid = {r["id"]: r for r in read(BASE)["disposition"]}
    known = {
        r["id"]: r
        for r in read(ROOT / "fmz-native-round6-audit.json")["source_evidence"]
    }
    prior = read(target / "round5-native-python-jobs.json")
    jobs = []
    with ZipFile(archive) as pinned:
        template_bytes, template_info = template(pinned, work)
        (target / "round7-native-spot-library.py").write_bytes(template_bytes.encode())
        for ident, note in CASES.items():
            strategy = byid[ident]
            raw, original = source(pinned, strategy["source"])
            assert digest(raw) == known[ident]["document_sha256"]
            public = display_settings(work, ident, original)
            src = legacy_python(original) if ident in LEGACY else original
            src, memory = header_settings(src)
            if ident == 5304:
                src = replace_once(
                    src,
                    "    while True:\n        Sleep(1000)\n        manager.LoadData()",
                    "    while True:\n        Sleep(60000)\n        manager.LoadData()",
                )
            if ident == 705:
                start = src.index("\ndef main():")
                src = src[:start] + replace_once(
                    src[start:], "Sleep(1000)", "Sleep(60000)"
                )
            ast.parse(src)
            feed_case = 1098 if ident in {486, 693, 2453, 5304} else 1107
            feeds = [q["feed"] for q in prior if q["item"]["id"] == feed_case]
            assert len(feeds) == 4
            for feed in feeds:
                options = {
                    "opening": file_opening(target, feed, memory, ident),
                    "empty_state": ident == 5304,
                }
                if ident in LEGACY:
                    options["template"] = template_info
                code = {
                    "id": ident,
                    "name": strategy["name"],
                    "source": strategy["source"],
                    "code": src,
                    "source_sha256": digest(raw),
                    "args": public["args"],
                }
                jobs.append(
                    {
                        "item": code,
                        "feed": feed,
                        "options": options,
                        "public": public,
                        "note": note,
                    }
                )
    build_worker(target)
    write(target / "round7-native-python-jobs.json", jobs)
    print("Staged", len(jobs), "source-bound cases across both markets and windows.")


def retry_worker_text(original, stem, ident):
    retry = f"{stem}-retry-{ident}"
    code = replace_once(original, f'"{stem}-jobs.json"', f'"{retry}-jobs.json"')
    return replace_once(code, f'"{stem}-"', f'"{retry}-"')


def stage_retry(target, ident):
    stem = "round7-native-python"
    complete = set()
    for artifact in target.glob(stem + "-*.jsonl"):
        for line in artifact.read_bytes().splitlines(keepends=True):
            if not line.endswith(b"\n"):
                continue
            row = json.loads(line)
            if row["id"] == ident and "reason" not in row:
                complete.add((row["coin"], row["start"]))
    jobs = [
        job
        for job in read(target / (stem + "-jobs.json"))
        if job["item"]["id"] == ident
        and (job["feed"]["coin"], job["feed"]["start"]) not in complete
    ]
    if not jobs:
        return
    retry = f"{stem}-retry-{ident}"
    original = (target / "fmz_native_python_round7_worker.py").read_text(
        encoding="utf-8"
    )
    (target / (retry + ".py")).write_text(
        retry_worker_text(original, stem, ident), encoding="utf-8", newline="\n"
    )
    write(target / (retry + "-jobs.json"), jobs)
    print(
        f"#{ident}: staged {len(jobs)} unfinished receipts without repeating completed trials."
    )


def finish(
    target,
    output,
    *,
    stem="round7-native-python",
    worker="fmz_native_python_round7_worker.py",
):
    worker_bytes = (target / worker).read_bytes()
    worker_sha = digest(worker_bytes)
    isolation = read(target / "round3-isolation-python.json")
    assert (
        isolation["file_error"][0] == isolation["network_error"][0] == "PermissionError"
    )
    receipts = defaultdict(dict)
    retry_hashes = {}
    for doc in sorted(
        target.glob(stem + "-*.jsonl"), key=lambda p: p.stat().st_mtime_ns
    ):
        for line in doc.read_bytes().splitlines(keepends=True):
            if not line.endswith(b"\n"):
                continue
            r = json.loads(line)
            if r["worker_sha256"] != worker_sha:
                ident = r["id"]
                assert doc.name == f"{stem}-retry-{ident}-{ident}.jsonl"
                if ident not in retry_hashes:
                    retry_hashes[ident] = digest(
                        retry_worker_text(worker_bytes.decode(), stem, ident).encode()
                    )
                assert r["worker_sha256"] == retry_hashes[ident]
            receipts[r["id"]][r["coin"], r["start"]] = r, digest(line.rstrip(b"\r\n"))
    groups = defaultdict(list)
    for job in read(target / (stem + "-jobs.json")):
        if job["item"]["id"] in receipts:
            groups[job["item"]["id"]].append(job)
    coverage, results, evidence = [], [], []
    for ident, specs in sorted(groups.items()):
        scenarios, issues = {}, set()
        active = False
        item, notes = specs[0]["item"], specs[0]["note"]
        for spec in specs:
            feed, opts = spec["feed"], spec["options"]
            key = feed["coin"], feed["start"]
            row, sha = receipts[ident].get(key, ({}, None))
            seed = opts["opening"]
            equity = seed["cash"] + seed["base"] * seed["price"]
            audit = {
                "id": ident,
                "feed": feed,
                "source_sha256": item["source_sha256"],
                "initial_inventory": seed,
                "public_settings": spec["public"],
                "worker_code_sha256": digest(item["code"].encode()),
                "raw_receipt_sha256": sha,
                "template": opts.get("template"),
            }
            if "daily" in opts:
                audit["daily_history"] = opts["daily"]
            try:
                if not row or "reason" in row:
                    raise ValueError(row.get("reason", "No complete isolated receipt"))
                assert row["code_sha256"] == audit["worker_code_sha256"]
                if seed["base"]:
                    trades, opened, recon = opening_metrics(row, target, feed, seed)
                else:
                    # The shared verifier starts at EQUITY. Translating both
                    # ends of the cash ledger leaves fills and P&L unchanged.
                    standard = {
                        **row,
                        "account": {
                            **row["account"],
                            "Balance": row["account"]["Balance"]
                            + EQUITY
                            - seed["cash"],
                        },
                    }
                    trades, opened, recon = order_metrics(
                        standard,
                        {"directory": target, "feed": feed},
                        market_buy_fee_on_turnover=True,
                    )
                audit.update(
                    order_count=len(row["orders"]),
                    closing_account=row["account"],
                    accounting=recon,
                    close_count=len(trades),
                    open_count=opened,
                    scheduled_sleeps=row["calls"],
                )
                active |= any(r["DealAmount"] > 0 for r in row["orders"])
                scenarios[key] = trades, opened, equity
            except (AssertionError, IndexError, KeyError, ValueError) as exc:
                reason = (
                    str(exc).splitlines()[0]
                    if str(exc)
                    else "Accounting or code-binding check failed"
                )
                audit["reason"] = reason
                issues.add(reason)
            evidence.append(audit)
        evaluated_exit = specs[0]["options"].get("fully_evaluated_exit_overlay", False)
        if scenarios.keys() != KEYS or not (active or evaluated_exit):
            coverage.append(
                [
                    ident,
                    "Pending · FMZ original-template trial",
                    " | ".join(sorted(issues))
                    or "No reconciled market fill in either test window.",
                ]
            )
            continue
        multiframe = "daily" in specs[0]["options"]
        label = "FMZ historical Python native" + (
            " multiframe variant" if multiframe else ""
        )
        if evaluated_exit:
            label = "FMZ seeded BTC/USD and ETH/USD daily exit variant"
        status = (
            "Tested · "
            + label
            + ("" if any(x[0] for x in scenarios.values()) else ", no closes")
        )
        archive_interval = "Legacy API"
        if multiframe:
            archive_interval = "Daily signals and hourly order reference"
        elif ident in {486, 693, 2453, 5304}:
            archive_interval = "Pinned source chart"
        symbols = {
            spec["feed"]["coin"]: spec["feed"]["symbol"].replace("_", "")
            for spec in specs
        }
        [quote] = {spec["feed"].get("quote_currency", "USDT") for spec in specs}
        for start, (_, window) in WINDOWS.items():
            b, bo, be = scenarios["BTC", start]
            e, eo, ee = scenarios["ETH", start]
            for market, ledger, opened, equity in (
                (symbols["BTC"], b, bo, be),
                (symbols["ETH"], e, eo, ee),
                (symbols["BTC"] + " + " + symbols["ETH"], b + e, bo + eo, be + ee),
            ):
                row = summarize(
                    (
                        "FMZ Python · archived native spot",
                        item["name"],
                        market + " spot",
                        "Archived Python venue orders",
                    ),
                    window,
                    ledger,
                    opened,
                )
                ratio = EQUITY / equity
                for name, idx in (("gross", 1), ("fee", 2), ("net", 3)):
                    loss, pct = drawdown(
                        [(event[0], event[idx] * ratio) for event in ledger]
                    )
                    row[name + "_dd"], row[name + "_dd_pct"] = loss / ratio, pct
                row.update(
                    id=ident,
                    source=item["source"],
                    interval=specs[0]["feed"]["period"],
                    archive_interval=archive_interval,
                    starting_equity=equity,
                    quote_currency=quote,
                )
                results.append(row)
        coverage.append([ident, status, notes])
    write(
        output,
        {
            "source_revision": FMZ_REF,
            "coverage": coverage,
            "results": results,
            "isolation": isolation,
            "worker_sha256": worker_sha,
            "retry_worker_sha256": retry_hashes,
            "broker_sha256": digest(
                (target / "depends/backtest_py_windows_64bit.so").read_bytes()
            ),
            "evidence": evidence,
        },
    )
    print(len(coverage), "tried strategies,", len(results), "result rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "finish", "retry"))
    parser.add_argument("target", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--id", type=int)
    args = parser.parse_args()
    if args.action == "stage":
        stage(args.archive, args.work, args.target)
    elif args.action == "retry":
        stage_retry(args.target, args.id)
    else:
        finish(args.target, args.output)
