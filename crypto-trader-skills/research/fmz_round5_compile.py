"""Replay source-audited Pine compiler fixes using the checked round-four broker and candles."""

import argparse
import hashlib
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pine_followup import patch
from research.delta_pine_liquid_replay import checksum
from research.delta_pine_repair import NO_QUOTED
from research.delta_pinets_catalogue import FMZ_REF, read, source_block, write
from research.delta_pinets_migration import MigrationBlocked, tokens
from research.fmz_intrabar_replay import constant_capital
from research.fmz_pine_remaining import (
    ACTIVE_ORDER,
    BLOCKS,
    MAX_LOOPS,
    make_worker,
    plain_pine,
)
from research.fmz_round3_compile import TIME_LIMIT_MS
from research.fmz_round3_compile import finalize as finalize_replay
from research.fmz_round4_compile import LOCAL_TYPES, STATE_TYPES, prepare_source
from research.fmz_round4_compile_fixture import fixture_candles, verify_fixture
from research.fmz_round4_compile_targeted import replace

BASE_COMMIT = "8fc965fe59c1cf0957c1abf09b4277ca9b2b1613"
BASE_LEDGER = "45298d7dd55f5da782e5249e2ea0a9a84f9a7102cdebb52e90632f08b7ab5aa2"
ARCHIVE_SHA256 = "a231a84e9f994446fe8a2ba89a7fda15e804b02f175c0bf608214a7f55295a9f"
CAPITAL_IDS = {173, 1040, 1691, 2181, 2828, 3161, 3190, 4495, 4881, 5097}
BOOLEAN_IDS = {2643, 2863, 3350, 4774}
CONFLICTS = {355: 2, 399: 2, 2386: 1, 2643: 2, 3020: 1}
CHART_NAMES = {
    **dict.fromkeys((385, 1758, 5393, 5705), ("barcolor", 2)),
    **dict.fromkeys((2949, 3396, 3549), ("bgcolor", 2)),
    **dict.fromkeys((270, 462), ("bgcolor", 3)),
}
DISPLAY_TAILS = {
    840: "// MONTHLY TABLE //",
    4748: "// MONTHLY TABLE //",
    3058: "// Plot average entry price",
}
STATE_ADDITIONS = {
    1789: {"pos": "int"},
    2763: dict.fromkeys(("hisup", "hisdown", "conbuy", "consell"), "int"),
    2863: {"lot": "float"},
    3350: {"lot": "float"},
    4486: dict.fromkeys(("curR", "largestR", "rbs", "rss"), "float"),
    5212: dict.fromkeys(
        ("sTR", "sDMPos", "sDMNeg", "xOpen", "m", "TUp", "TDown"), "float"
    )
    | {"trend": "int"},
    5422: dict.fromkeys(
        (
            "trend1",
            "trend2",
            "WOWtrend",
            "BMAtrend",
            "BARtrend",
            "SUPtrend",
            "pos",
            "TTStrend",
            "col",
            "posi",
        ),
        "int",
    )
    | dict.fromkeys(
        (
            "TrendUp",
            "TrendDown",
            "SmoothedTrueRange",
            "SmoothedDirectionalMovementPlus",
            "SmoothedDirectionalMovementMinus",
            "ret",
        ),
        "float",
    ),
}
TARGETS = (
    CAPITAL_IDS
    | BOOLEAN_IDS
    | CONFLICTS.keys()
    | STATE_ADDITIONS.keys()
    | CHART_NAMES.keys()
    | DISPLAY_TAILS.keys()
    | {712, 907, 909, 1096, 1251, 2169, 3658, 4817, 5119, 5704}
)
OTHER_LANE = {1996, 3056, 5517}
CAPITAL = "Archived literal broker capital"
NAMED_DEFAULTS = "Named defaults selected for conflicting legacy inputs"
BOOL_DEFAULTS = "Equivalent duplicate boolean defaults normalized"
BRANCH_VALUE = "Explicit if-expression branch value"
CHART_BINDING = "Chart variable renamed without changing the built-in call"
DISPLAY_OMITTED = "Offline variant omits terminal display-only calculations"
HISTORY_BINDING = "Named crossover history uses the archived default offset"
FIXED_RSI_LENGTH = "Reassigned legacy RSI inputs interpreted as fixed lookbacks"


def selected(row):
    status = row["status"]
    return (
        row["id"] not in OTHER_LANE
        and FMZ_REF in row["source"]
        and not status.startswith("Tested")
        and (
            "compiler" in status
            or (
                "Pine" in status
                and "intrabar" not in status
                and "historical" not in status
            )
        )
        and not any(
            word in row["reason"].lower()
            for word in (
                "verified feed",
                "intrabar",
                "security(",
                "external",
                "chart value",
            )
        )
    )


def explicit_branch_value(code, variable, output, threshold=25000):
    return replace(
        code,
        rf"(?m)^{variable} = if {re.escape(output)} > {threshold}\n"
        rf"    {threshold}\nelse\n    {variable} = {re.escape(output)}[ \t]*$",
        f"{variable} = {output} > {threshold} ? {threshold} : {output}",
        1,
    )


def duplicate_bool(code):
    return re.subn(
        r"(?m)^(\w+[ \t]*=[ \t]*input\((true|false)),[ \t]*defval[ \t]*=[ \t]*\2(?=,|\))",
        r"\1",
        code,
    )


def conflicting_defaults(code, expected):
    pattern = re.compile(
        r"(?m)^(\w+[ \t]*=[ \t]*input\()([+-]?\d+(?:\.\d+)?),"
        r"([^\n]*?\bdefval[ \t]*=[ \t]*)([+-]?\d+(?:\.\d+)?)(?=[ \t]*[,\)])"
    )
    edited = pattern.sub(
        lambda m: m[0] if Decimal(m[2]) == Decimal(m[4]) else m[1] + m[3] + m[4], code
    )
    if (
        sum(a != b for a, b in zip(code.splitlines(), edited.splitlines(), strict=True))
        != expected
    ):
        raise MigrationBlocked(
            "Conflicting default fields no longer match the audited source"
        )
    return edited


def chart_binding(code, name, count):
    parts = tokens(code)
    hits = [(i, item) for i, item in enumerate(parts[:-1]) if item.group() == name]
    reads = [
        (item.start(), item.end(), f"fmz_chart_{name}")
        for i, item in hits
        if parts[i + 1].group() != "("
    ]
    if len(hits) != count + 1 or len(reads) != count or f"fmz_chart_{name}" in code:
        raise MigrationBlocked(
            "Archived chart binding no longer matches the audited source"
        )
    return patch(code, reads)


def omit_terminal_display(code, marker):
    if code.count(marker) != 1:
        raise MigrationBlocked("Audited terminal presentation block is missing")
    orders, display = code.split(marker)
    executable = NO_QUOTED.sub("", display)
    if not ACTIVE_ORDER.search(NO_QUOTED.sub("", orders)) or re.search(
        r"\bstrategy\.(?:entry|order|exit|close|close_all|cancel|cancel_all|risk)\b",
        executable,
    ):
        raise MigrationBlocked("Terminal presentation block contains broker commands")
    return orders


def named_history(code, anchor, expressions, offset, fixed):
    if not re.search(rf"(?m)^{offset}[ \t]*=[ \t]*input(?:\.int)?\({fixed}[,) ]", code):
        raise MigrationBlocked("Archived history offset default is missing")
    assignments = []
    for name, expression in expressions.items():
        archived = f"{expression}[{offset}]"
        code = replace(code, re.escape(archived), f"{name}[{fixed}]", 1)
        assignments.append(f"{name} = {expression}\n")
    return replace(code, r"(?m)^" + re.escape(anchor), "".join(assignments) + anchor, 1)


def source_edits(code, ident):
    notes = Counter()
    capital = None
    if ident in CAPITAL_IDS:
        code, capital = constant_capital(code)
        notes[CAPITAL] = 1
    if ident in BOOLEAN_IDS:
        code, count = duplicate_bool(code)
        if not count:
            raise MigrationBlocked("Audited duplicate boolean defaults are absent")
        notes[BOOL_DEFAULTS] = count
    if ident in CONFLICTS:
        code = conflicting_defaults(code, CONFLICTS[ident])
        notes[NAMED_DEFAULTS] = CONFLICTS[ident]
    if ident == 712:
        code = named_history(
            code,
            "if stratbull and time > stratstart",
            {
                "fmz_overbought": "crossover(rsiVWAP, ovrbgt)",
                "fmz_oversold": "crossunder(rsiVWAP, ovrsld)",
            },
            "lateleave",
            28,
        )
        notes[HISTORY_BINDING] = 1
    if ident in {4817, 5119}:
        code = explicit_branch_value(code, "price", "close[0]")
        notes[BRANCH_VALUE] = 1
    if ident in {907, 909}:
        code = replace(
            code,
            r'(?m)^//@version=5\nindicator\(title="Stochastic RSI"[^\n]*\)\n',
            "",
            1,
        )
        notes[
            "Combined archived indicators retain both formulas under one declaration"
        ] = 1
    if ident in CHART_NAMES:
        code = chart_binding(code, *CHART_NAMES[ident])
        notes[CHART_BINDING] = 1
    if ident in DISPLAY_TAILS:
        code = omit_terminal_display(code, DISPLAY_TAILS[ident])
        notes[DISPLAY_OMITTED] = 1
    if ident == 1096:
        code = replace(
            code,
            r"(?m)^ ((?:strategy\(|takeProfit =|stopLoss =|inputTradingMode =)[^\n]*)$",
            r"\1",
            4,
        )
        code = replace(code, r"(?m)^ {7}(?! )", " " * 8, 6)
        notes["Archived order block and declaration indentation normalized"] = 1
    if ident == 1251:
        code = replace(code, r"rsi\(src, lengthRSI\)", "ta.rsi(src, lengthRSI)", 1)
        notes["Legacy RSI length is an archived positive integer input"] = 1
    if ident == 2169:
        code = replace(
            code,
            r"\brsi\(([^\n]*?),[ \t]*(ShortTermRSI|LongTermRSI)[ \t]*\)",
            r"ta.rsi(\1, \2)",
            2,
        )
        notes[FIXED_RSI_LENGTH] = 2
    if ident == 3658:
        code = replace(
            code,
            r"rsi\(upper_s, lower_s\)",
            "(100.0 - (100.0 / (1.0 + (upper_s / lower_s))))",
            1,
        )
        notes["Legacy two-series RSI uses the documented ratio formula"] = 1
    return code, dict(notes), capital


def prepare(archive, ledger, prior_work, prior_report, work):
    with archive.open("rb") as stream:
        archive_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if archive_digest != ARCHIVE_SHA256 or checksum(ledger.read_bytes()) != BASE_LEDGER:
        raise ValueError("Pinned archive or round-four ledger digest mismatch")
    prior = read(prior_report)
    candles = (prior_work / "candles.json").read_bytes()
    if checksum(candles) != prior["candle_files_sha256"]["15"]:
        raise ValueError("Round-four 15-minute candle digest mismatch")
    work.mkdir(parents=True, exist_ok=True)
    known = prior["pinned_document_sha256"]
    candidates, coverage, pinned, old_reasons = [], [], {}, {}
    with ZipFile(archive) as source:
        for row in read(ledger)["disposition"]:
            if not selected(row):
                continue
            ident, url = row["id"], row["source"]
            path = unquote(url.split(FMZ_REF + "/", 1)[1])
            raw = source.read(f"strategies-{FMZ_REF}/{path}")
            digest = checksum(raw)
            for expected in (known.get(str(ident)), row.get("pinned_document_sha256")):
                if expected and digest != expected:
                    raise ValueError(f"Pinned source SHA-256 mismatch for {ident}")
            pinned[str(ident)] = digest
            old_reasons[str(ident)] = row["reason"]
            document = raw.decode()
            blocks = source_block(document) or BLOCKS.findall(document)
            blocks = [
                plain_pine(block)
                for block in blocks
                if ACTIVE_ORDER.search(NO_QUOTED.sub("", plain_pine(block)))
            ]
            try:
                if ident not in TARGETS:
                    raise MigrationBlocked(row["reason"])
                if len(blocks) != 1:
                    raise MigrationBlocked(
                        f"Pinned archive contains {len(blocks)} active Pine blocks"
                    )
                patched, edits, capital = source_edits(blocks[0], ident)
                migrated, old_version, transforms, repairs = prepare_source(
                    patched,
                    state_types=STATE_ADDITIONS.get(ident, STATE_TYPES.get(ident)),
                    local_types=LOCAL_TYPES.get(ident),
                )
            except MigrationBlocked as error:
                coverage.append(
                    [ident, "Pending · FMZ Pine compiler research", str(error)]
                )
                continue
            migration = checksum(migrated.encode())
            if prior.get("candidate_migration_sha256", {}).get(str(ident)) == migration:
                raise ValueError(f"Candidate {ident} repeats the prior migrated source")
            period = re.search(r"(?m)^period:\s*(\S+)", document)
            candidates.append(
                {
                    "id": ident,
                    "name": row["name"],
                    "source": url,
                    "hash": digest,
                    "archived": period[1] if period else "",
                    "code": migrated,
                    "old_version": old_version,
                    "transforms": transforms,
                    "repairs": repairs | edits,
                    "migration_sha256": migration,
                    **({"initialCapital": capital} if capital else {}),
                }
            )
    (work / "candles.json").write_bytes(candles)
    write(work / "candidates.json", candidates)
    write(
        work / "preflight.json",
        {
            "base_commit": BASE_COMMIT,
            "source_revision": FMZ_REF,
            "base_disposition_sha256": BASE_LEDGER,
            "source_archive_sha256": archive_digest,
            "prior_report_sha256": checksum(prior_report.read_bytes()),
            "expected_engine_sha256": prior["engine_sha256"],
            "pinned_document_sha256": pinned,
            "candidate_migration_sha256": {
                str(item["id"]): item["migration_sha256"] for item in candidates
            },
            "prior_reasons": old_reasons,
            "initial_equity_overrides_usdt": {
                str(item["id"]): item["initialCapital"]
                for item in candidates
                if "initialCapital" in item
            },
            "coverage": coverage,
            "windows": prior["windows"],
            "bar_archives": prior["bar_archives"],
            "worker_sha256": make_worker(work, TIME_LIMIT_MS),
            "time_limit_ms": TIME_LIMIT_MS,
            "max_loop_iterations": MAX_LOOPS,
            "requires_os_isolation": True,
        },
    )
    print(len(candidates), "candidates,", len(coverage), "screened")
    print(Counter(row[2] for row in coverage if row[0] in TARGETS))


FIXTURE = """//@version=5
strategy("Compiler edge fixture", process_orders_on_close=true)
strategy.initial_capital = 50000
enabled = input(true, defval=true)
price = if close > 104
    104
else
    price = close
oscillator = ta.rsi(close, 2)
barcolor = color.green
barcolor(barcolor)
delay = input.int(2)
if enabled and bar_index == 4 and price == 104 and oscillator == 100 and strategy.equity == strategy.initial_capital and ta.crossover(close, 101)[delay]
    strategy.entry("L", strategy.long, qty=strategy.equity / 25000)
if bar_index == 6
    strategy.close("L")
"""
CONTROL = """//@version=5
strategy("Compiler edge control", process_orders_on_close=true)
if bar_index == 4 and math.min(close, 104) == 104 and ta.rsi(close, 2) == 100
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 6
    strategy.close("L")
"""


def prepare_fixture(work):
    fixture_candles(work)
    candidates = read(work / "fixture-candidates.json")
    code, capital = constant_capital(FIXTURE)
    code, count = duplicate_bool(code)
    assert count == 1
    code = explicit_branch_value(code, "price", "close", 104)
    code = chart_binding(code, "barcolor", 2)
    code = named_history(
        code, "if enabled", {"pulse": "ta.crossover(close, 101)"}, "delay", 2
    )
    code, _, _, _ = prepare_source(code)
    for candidate, source in zip(candidates, (code, CONTROL), strict=True):
        candidate.update(code=source, initialCapital=capital)
    write(work / "fixture-candidates.json", candidates)


def finalize(work, destination, fixture_report):
    verify_fixture(work, fixture_report)
    fixture = read(fixture_report)
    fixture["checks"] = [
        "Archived capital becomes broker initial equity and gates qty=2",
        "Removing an identical duplicate boolean default preserves its value",
        "Expressing both if-expression outputs explicitly preserves the price cap",
        "A chart color value and the built-in chart color call keep separate bindings",
        "A crossover two bars earlier gates the same trade as the hand-timed control",
    ]
    write(fixture_report, fixture)
    preflight = read(work / "preflight.json")
    assert preflight["expected_engine_sha256"] == checksum(
        (work / "engine.mjs").read_bytes()
    )
    assert preflight["candidate_migration_sha256"] == {
        str(item["id"]): checksum(item["code"].encode())
        for item in read(work / "candidates.json")
    }
    finalize_replay(work, destination, work / "diagnostics.jsonl")
    report = read(destination)
    assert set(preflight["pinned_document_sha256"]) == {
        str(row[0]) for row in report["coverage"]
    }
    report["fixture_sha256"] = checksum(fixture_report.read_bytes())
    labels = {}
    for row in report["results"]:
        if CAPITAL in row["repairs"]:
            row["group"] = "FMZ · Capital override"
            labels[row["id"]] = (
                row["group"],
                "Archived positive capital literal sets broker equity and drawdown reference.",
            )
        if NAMED_DEFAULTS in row["repairs"]:
            row["group"] = "FMZ · Named input default variant"
            labels[row["id"]] = (
                row["group"],
                "Where defaults conflict, the explicitly named default is used for this variant.",
            )
        if DISPLAY_OMITTED in row["repairs"]:
            row["group"] = "FMZ · Display-free Pine variant"
            labels[row["id"]] = (
                row["group"],
                "Terminal calculations used only by the chart table are omitted.",
            )
        if FIXED_RSI_LENGTH in row["repairs"]:
            row["group"] = "FMZ · Fixed-lookback RSI variant"
            labels[row["id"]] = (
                row["group"],
                "Uses the derived integer defaults as RSI lengths. Pine v4 overload dispatch depends on the second argument type.",
            )
        if HISTORY_BINDING in row["repairs"]:
            row["group"] = "FMZ · Fixed history offset"
            labels[row["id"]] = (
                row["group"],
                "Evaluates crossover history at the archived 28-bar default.",
            )
    for item in report["coverage"]:
        if item[0] in labels:
            group, note = labels[item[0]]
            item[1] = f"Tested · {group}" + (
                ", no closes" if item[1].endswith("no closes") else ""
            )
            item[2] = f"{item[2]} {note}"
    write(destination, report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, function, fields in (
        (
            "prepare",
            prepare,
            ("archive", "ledger", "prior_work", "prior_report", "work"),
        ),
        ("fixture", prepare_fixture, ("work",)),
        ("finalize", finalize, ("work", "destination", "fixture_report")),
    ):
        command = sub.add_parser(name)
        command.set_defaults(function=function)
        for field in fields:
            command.add_argument(field, type=Path)
    args = vars(parser.parse_args())
    args.pop("command")
    function = args.pop("function")
    function(**args)
