"""Replay compile-residual FMZ strategies with verified same-market references."""

import argparse
import json
from collections import Counter
import re
import shutil
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pine_compatibility import (
    fixed_default_inputs,
    namespace_rewrites,
    plain_pine,
    rsi_calls,
    session_calls,
    shell,
)
from research.delta_pine_followup import GLOBAL_RENAME, patch, rename_global
from research.delta_pine_liquid_replay import checksum
from research.delta_pine_repair import NO_QUOTED
from research.delta_pinets_catalogue import FMZ_REF, read, source_block, write
from research.delta_pinets_migration import MigrationBlocked, VERSION, local_declarations, tokens
from research.fmz_intrabar_replay import expand_chart_alias, market_data
from research.fmz_marketdata_replay import prepare_source as checked_source
from research.fmz_pine_remaining import (
    ACTIVE_ORDER,
    BLOCKS,
    MAX_LOOPS,
    chart_broker_declaration,
    make_worker,
)
from research.fmz_round3_compile import (
    DEFAULT_VARIANT,
    LEGACY_VERSION,
    finalize as finalize_compile,
    normalize_input_defaults,
    normalize_statements,
    rename_custom_functions,
    selected,
)

SECURITY = re.compile(r"\bsecurity\s*\(")
TIME_LIMIT_MS = 50_000


def legacy_chart_period(code):
    masked = NO_QUOTED.sub("", code)
    if "period" in local_declarations(masked) or re.search(
        r"(?m)\bperiod[ \t]*(?::=|=(?!=|>))|\bfor\s+period\b|\[[^\n\]]*\bperiod\b[^\n\]]*\]\s*=",
        masked,
    ):
        return code, 0
    parts = tokens(code)
    edits = [
        (node.start(), node.end(), "timeframe.period")
        for i, node in enumerate(parts)
        if node.group() == "period" and not (i and parts[i - 1].group() == ".")
        and not (i + 1 < len(parts) and parts[i + 1].group() == "(")
    ]
    return patch(code, edits), len(edits)


def prepare_source(block, *, initial=False):
    code = plain_pine(block)
    changes = Counter()
    code, count = chart_broker_declaration(code)
    if count:
        changes["Chart indicator declaration adapted for active archived orders"] = count
    if not VERSION.search(code):
        if re.search(r"(?m)//\s*@version\b", code):
            raise MigrationBlocked("Version directive is ambiguous")
        code = "//@version=5\n" + code
        changes["FMZ documented default Pine v5"] += 1
    code, declarations = shell(code)
    changes.update(declarations)
    version = int(VERSION.search(code)[1])
    if version not in LEGACY_VERSION | {5, 6}:
        raise MigrationBlocked(f"Explicit Pine v{version} needs a verified migration")
    code, count = expand_chart_alias(code)
    if count:
        changes["Immutable chart ticker alias"] = count
    if version in LEGACY_VERSION:
        code, edits = normalize_statements(code)
        changes.update(edits)
        if not initial and version < 4:
            code, count = legacy_chart_period(code)
            if count:
                changes["Documented chart timeframe variable"] = count
        for name, transform in (
            ("Archived function renamed before namespace migration", rename_custom_functions),
            (
                "Unshadowed legacy identifier renamed",
                lambda text: rename_global(text, GLOBAL_RENAME | {"iff", "offset"}),
            ),
            ("Documented legacy builtin namespace", namespace_rewrites),
            ("Legacy weekday session default", session_calls),
            ("Proven classic RSI integer length", rsi_calls),
        ):
            code, count = transform(code)
            if count:
                changes[name] = count
    code, _, feed = checked_source(
        code,
        isolated_literals=True,
        with_heikin=True,
        chart_ticker_alias=True,
    )
    if "confirmed same-symbol timeframe data" not in feed:
        raise MigrationBlocked("No verified chart-symbol historical request")
    changes.update(feed)
    if not initial:
        code, count = fixed_default_inputs(code)
        if count:
            changes["Fixed-default legacy integer input constraints"] = count
    code, edits = normalize_input_defaults(code)
    changes.update(edits)
    return code, version, dict(changes)


def prepare(archive, five, minute, work, ledger, reports, previous_work=None, initial=False):
    work.mkdir(parents=True, exist_ok=True)
    tested = {
        i for report in reports for i, status, _ in read(report)["coverage"]
        if status.startswith("Tested")
    }
    coverage, candidates, hashes = [], [], {}
    prior = {}
    if previous_work:
        receipts = [
            json.loads(line) for line in (previous_work / "out.jsonl").read_text().splitlines()
        ]
        failed = {r["id"] for r in receipts if "reason" in r}
        prior = {
            item["id"]: item["migration_sha256"]
            for item in read(previous_work / "candidates.json") if item["id"] in failed
        }
    with ZipFile(archive) as source:
        for row in read(ledger)["disposition"]:
            if not selected(row) or row["id"] in tested:
                continue
            ident, url = row["id"], row["source"]
            if previous_work and ident not in prior:
                continue
            path = unquote(url.split(FMZ_REF + "/", 1)[1])
            raw = source.read(f"strategies-{FMZ_REF}/{path}")
            document = raw.decode()
            blocks = source_block(document) or BLOCKS.findall(document)
            blocks = [b for b in blocks if ACTIVE_ORDER.search(NO_QUOTED.sub("", b))]
            if len(blocks) != 1 or not SECURITY.search(NO_QUOTED.sub("", blocks[0])):
                continue
            digest = checksum(raw)
            if row.get("pinned_document_sha256", digest) != digest:
                raise ValueError(f"Source hash mismatch for {ident}")
            hashes[str(ident)] = digest
            try:
                code, version, repairs = prepare_source(blocks[0], initial=initial)
            except MigrationBlocked as error:
                coverage.append([ident, "Pending · FMZ compile and feeds", str(error)])
                continue
            period = re.search(r"(?m)^period:\s*(\S+)", document)
            migration = checksum(code.encode())
            if migration == prior.get(ident):
                continue
            candidates.append({
                "id": ident,
                "name": row["name"],
                "source": url,
                "hash": digest,
                "archived": period[1] if period else "",
                "code": code,
                "old_version": version,
                "transforms": {},
                "repairs": repairs,
                "migration_sha256": migration,
            })
    print(len(candidates), "admitted", len(coverage), "screened", flush=True)
    if previous_work:
        prior_metadata = read(previous_work / "preflight.json")
        windows = prior_metadata["windows"]
        archived = prior_metadata["bar_archives"]
        minute_evidence = prior_metadata["minute_archives"]
        shutil.copyfile(previous_work / "candles.json", work / "candles.json")
    else:
        data, windows, archived, minute_evidence = market_data(five, minute)
        write(work / "candles.json", data)
    write(work / "candidates.json", candidates)
    write(work / "preflight.json", {
        "coverage": coverage,
        "source_revision": FMZ_REF,
        "pinned_document_sha256": hashes,
        "bar_archives": archived,
        "minute_archives": minute_evidence,
        "windows": windows,
        "worker_sha256": make_worker(work, TIME_LIMIT_MS),
        "base_disposition_sha256": checksum(ledger.read_bytes()),
        "previous_reports": {p.name: checksum(p.read_bytes()) for p in reports},
        "time_limit_ms": TIME_LIMIT_MS,
        "max_loop_iterations": MAX_LOOPS,
        "requires_os_isolation": True,
        **({"previous_out_sha256": checksum((previous_work / "out.jsonl").read_bytes())} if previous_work else {}),
    })


def finalize(work, destination, diagnostics=None):
    finalize_compile(work, destination, diagnostics)
    report = read(destination)
    for row in report["results"]:
        if DEFAULT_VARIANT not in row["repairs"]:
            row["group"] = "FMZ · Confirmed same-market data"
    for item in report["coverage"]:
        if item[1].startswith("Tested · Pine"):
            suffix = ", no closes" if item[1].endswith("no closes") else ""
            item[1] = "Tested · FMZ confirmed same-market data" + suffix
    write(destination, report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="stage", required=True)
    p = subparsers.add_parser("prepare")
    for field in ("archive", "five", "minute", "work", "ledger"):
        p.add_argument(field, type=Path)
    p.add_argument("reports", nargs="+", type=Path)
    p.add_argument("--initial", action="store_true")
    p.add_argument("--previous-work", type=Path)
    f = subparsers.add_parser("finalize")
    for field in ("work", "destination"):
        f.add_argument(field, type=Path)
    f.add_argument("--diagnostics", type=Path)
    args = vars(parser.parse_args())
    stage = args.pop("stage")
    (prepare if stage == "prepare" else finalize)(**args)
