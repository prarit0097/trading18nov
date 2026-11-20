"""Recheck the legacy Pine backlog with narrow fixes and archived intervals."""

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pine_repair import NO_QUOTED, compiler_rewrites, repair_recursion
from research.delta_pinets_catalogue import (
    FMZ_REF,
    PRIOR,
    datasets,
    read,
    source_block,
    write,
)
from research.delta_pinets_migration import (
    INPUT_TYPES,
    RESERVED_V5,
    VERSION,
    MigrationBlocked,
    arguments,
    keyword,
    local_declarations,
    migrate,
    tokens,
)
from research.delta_strategy_replay import ROOT

INPUT_OPTION = re.compile(r"(-?)0+([0-9]+)|(-?[0-9]+)\.0+")
IDENTIFIER = re.compile(r"\b[A-Za-z_]\w*\b")
GLOBAL_RENAME = RESERVED_V5 | {"ta", "math", "str", "color", "shape", "input"}
EAGER_CALLS = {"highest", "lowest", "sma", "ema", "wma", "rma", "stdev", "atr"}
JOBS = "batches.json"


def patch(code, changes):
    last = len(code)
    for begin, end, value in sorted(changes, reverse=True):
        if end > last:
            raise MigrationBlocked("Overlapping compatibility edits")
        code = code[:begin] + value + code[end:]
        last = begin
    return code


def key_cells(parts, span):
    begin, end = span
    return parts[begin].start(), parts[end - 1].end()


def input_args(fields):
    """Convert only literal decimal syntax, known types and redundant defaults."""
    if not fields:
        return None
    if len(fields) > 2 and fields[2][0] is None:
        if fields[2][1] not in {f"input.{x}" for x in INPUT_TYPES} | INPUT_TYPES.keys():
            return None
        fields[2] = ("type", fields[2][1])
    if any(k is None for k, _ in fields[2:]):
        return None
    named = {k: v for k, v in fields if k}
    if len(named) != sum(k is not None for k, _ in fields):
        return None
    if "defval" in named and fields[0][0] is None:
        if named["defval"] != fields[0][1] or not re.fullmatch(
            r"-?[0-9]+(?:\.[0-9]+)?|true|false", named["defval"]
        ):
            return None
        fields = [x for x in fields if x[0] != "defval"]
    default = named.get("defval", fields[0][1] if fields[0][0] is None else "")
    integer = named.get("type") in {"integer", "input.integer"} or (
        not named.get("type") and re.fullmatch(r"-?[0-9]+", default)
    )
    if integer and any(
        k in named and not re.fullmatch(r"-?[0-9]+(?:\.0+)?", named[k])
        for k in ("minval", "maxval", "step")
    ):
        return None
    updated = []
    for k, v in fields:
        if k == "type" and v in INPUT_TYPES:
            v = "input." + v
        if integer and (
            k in {"defval", "minval", "maxval", "step"} or not updated and k is None
        ):
            if match := INPUT_OPTION.fullmatch(v):
                v = str(int(match[3] or match[1] + match[2]))
        updated.append((k, v))
    return updated


def fix_inputs(code):
    parts = tokens(code)
    changes = []
    for i, node in enumerate(parts[:-1]):
        if (
            node.group() != "input"
            or parts[i + 1].group() != "("
            or (i and parts[i - 1].group() == ".")
        ):
            continue
        _, args = arguments(parts, i + 1)
        if not args or any(
            any(x.group() in {"(", "["} for x in parts[slice(*s)]) for s in args
        ):
            continue
        fields = []
        for span in args:
            name, _ = keyword(parts, span)
            a, b = key_cells(parts, (span[0] + 2, span[1]) if name else span)
            fields.append((name, code[a:b]))
        normalized = input_args(fields.copy())
        if normalized is not None and normalized != fields:
            a, _ = key_cells(parts, args[0])
            _, b = key_cells(parts, args[-1])
            changes.append(
                (a, b, ", ".join(f"{k} = {v}" if k else v for k, v in normalized))
            )
    return patch(code, changes), len(changes)


def rename_global(code):
    """Rename one unshadowed global binding without touching labels or callees."""
    masked = NO_QUOTED.sub(lambda m: " " * len(m.group()), code)
    declarations = local_declarations(masked)
    parts = tokens(code)
    key_slots = set()
    for i, item in enumerate(parts[:-1]):
        if item.group() != "(":
            continue
        _, args = arguments(parts, i)
        key_slots.update(
            parts[span[0]].start() for span in args if keyword(parts, span)[0]
        )
    changes, renamed = [], 0
    for name in sorted(GLOBAL_RENAME & declarations):
        word = re.escape(name)
        fresh = "fmz_global_" + name
        if re.search(r"\b" + fresh + r"\b", masked):
            continue
        binding = list(
            re.finditer(
                rf"(?m)^([ \t]*(?:(?:var|float|int|bool|color|string) +)*)({word})\s*(?::=|=(?!=|>))",
                masked,
            )
        )
        binding = [x for x in binding if x.start(2) not in key_slots]
        if len(binding) != 1 or binding[0][1].startswith((" ", "\t")):
            continue
        if re.search(rf"(?m)^\s*\w+\s*\([^\n)]*\b{word}\b[^\n)]*\)\s*=>", masked):
            continue
        if re.search(
            rf"(?m)^\s*(?:{word}\s*\([^\n)]*\)\s*=>|for\s+{word}\b|[^\n]*\[[^\n\]]*\b{word}\b[^\n\]]*\]\s*=)",
            masked,
        ):
            continue
        uses = [
            node
            for i, node in enumerate(parts)
            if node.group() == name
            and node.start() not in key_slots
            and not (i and parts[i - 1].group() == ".")
            and not (i + 1 < len(parts) and parts[i + 1].group() in {".", "("})
        ]
        if not uses or uses[0].start() != binding[0].start(2):
            continue
        changes.extend((x.start(), x.end(), fresh) for x in uses)
        renamed += 1
    return patch(code, changes), renamed


def eager_iff(code):
    """Preserve eager evaluation for a whole-bar assignment with indicator branches."""
    changes = []
    parts = tokens(code)
    declared = local_declarations(NO_QUOTED.sub("", code))
    for i, node in enumerate(parts[:-1]):
        if node.group() != "iff" or parts[i + 1].group() != "(" or i < 2:
            continue
        line = code.rfind("\n", 0, node.start()) + 1
        name = parts[i - 2].group()
        if not re.fullmatch(r"[A-Za-z_]\w*[ \t]*=[ \t]*", code[line : node.start()]):
            continue
        stop, args = arguments(parts, i + 1)
        tail = code[parts[stop].end() :].split("\n", 1)[0].strip()
        if len(args) != 3 or (tail and not tail.startswith("//")):
            continue
        spans = [key_cells(parts, span) for span in args]
        condition, first, second = (code[a:b] for a, b in spans)
        calls = set(re.findall(r"\b([A-Za-z_]\w*)\s*\(", first + " " + second))
        if not calls or calls - EAGER_CALLS or calls & declared:
            continue
        if any(
            re.search(r"(?m)^\s*" + re.escape(call) + r"\s*\([^)\n]*\)\s*=>", code)
            for call in calls
        ):
            continue
        stem = f"fmz_eager_{len(changes)}"
        if stem in code or re.search(
            r"\b" + re.escape(name) + r"\b", condition + " " + first + " " + second
        ):
            continue
        if re.search(r"\b(?:iff|strategy)\b|[.\n]", first + second) or "(" in condition:
            continue
        replacement = f"{stem}_yes = {first}\n{stem}_no = {second}\n{name} = ({condition}) ? {stem}_yes : {stem}_no"
        changes.append((line, parts[stop].end(), replacement))
    return patch(code, changes), len(changes)


def followup(source):
    clean = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    executable = NO_QUOTED.sub("", clean)
    if not re.search(r"(?m)^strategy\s*\(", executable):
        raise MigrationBlocked("No active source strategy declaration")
    if re.search(r"(?m)^\s*strategy\.initial_capital\s*(?::=|=(?!=))", executable):
        raise MigrationBlocked("Source writes a read-only strategy wallet field")
    if not (version := VERSION.search(clean)) or version[1] not in {"2", "3", "4"}:
        raise MigrationBlocked("Unversioned source or unsupported source version")
    fixed, inputs = fix_inputs(clean)
    fixed, renamed = rename_global(fixed)
    fixed, eager = eager_iff(fixed)
    fixed, recursion = repair_recursion(fixed)
    fixed, labels = compiler_rewrites(fixed)
    for key, count in (
        ("equivalent legacy input syntax", inputs),
        ("unshadowed global renamed", renamed),
        ("eager indicator evaluation retained", eager),
        ("explicit prior-bar recursive state", recursion),
    ):
        if count:
            labels[key] = count
    final, old, transforms = migrate(
        fixed, allow_read_only_legacy=True, resolve_shadowed=True
    )
    return final, old, transforms, dict(labels)


def archived_minutes(value):
    match = re.fullmatch(r"([1-9]\d*)([mhd])", value)
    if not match:
        return 0
    minutes = int(match[1]) * {"m": 1, "h": 60, "d": 1440}[match[2]]
    if minutes not in {15, 30} and minutes % 5 == 0 and 5 <= minutes <= 1440:
        return minutes
    return 0


def pending():
    coverage = {}
    for filename in ("delta-pinets-migration.json", "delta-pine-repair.json"):
        coverage.update({i: why for i, _, why in read(ROOT / filename)["coverage"]})
    tested = {
        row["id"]
        for filename in ("delta-pinets-migration.json", "delta-pine-repair.json")
        for row in read(ROOT / filename)["results"]
    }
    return {i: why for i, why in coverage.items() if i not in tested}


def prepare(archive, reference, later, work):
    targets = pending()
    coverage, jobs = [], defaultdict(list)
    with (
        ZipFile(archive) as z,
        (ROOT / "public-strategy-catalogue.csv").open(encoding="utf-8-sig") as stream,
    ):
        for i, row in enumerate(csv.DictReader(stream), 1):
            if i not in targets:
                continue
            prior = targets[i]
            path = unquote(row["source_url"].split("/" + FMZ_REF + "/", 1)[1])
            document = z.read("strategies-" + FMZ_REF + "/" + path)
            blocks = source_block(document.decode("utf-8"))
            interval = 15
            try:
                if len(blocks) != 1:
                    raise MigrationBlocked("No single Pine strategy in the source")
                block = blocks[0]
                archived = re.search(r"(?m)^period:\s*(\S+)", block)
                archived = archived[1] if archived else ""
                if prior.startswith("15m: untraded fill"):
                    interval = archived_minutes(archived)
                    if not interval:
                        raise MigrationBlocked(prior)
                code, version, changes, repairs = followup(block)
                if (
                    interval == 15
                    and not repairs
                    and "resolved shadowed builtin" not in changes
                ):
                    raise MigrationBlocked(prior)
                if interval == 1440 and re.search(
                    r"\b(?:timeframe|period|interval|isdaily|isintraday|time|time_close)\b",
                    NO_QUOTED.sub("", code),
                ):
                    raise MigrationBlocked(
                        "Archived 1d replay requires verified daily timeframe metadata"
                    )
            except (MigrationBlocked, ValueError) as exc:
                coverage.append([i, "FMZ Pine follow-up pending", str(exc)])
                continue
            if interval != 15:
                repairs["archived interval replay"] = 1
            jobs[interval].append(
                {
                    "id": i,
                    "name": row["name"],
                    "source": row["source_url"],
                    "hash": hashlib.sha256(document).hexdigest(),
                    "archived": archived,
                    "code": code,
                    "old_version": version,
                    "transforms": changes,
                    "repairs": repairs,
                    "migration_sha256": hashlib.sha256(code.encode()).hexdigest(),
                }
            )
    assert len(coverage) + sum(map(len, jobs.values())) == len(targets)
    reports = [read(ROOT / f) for f in PRIOR]
    manifest = {"coverage": coverage, "windows": {}}
    for minutes, items in sorted(jobs.items()):
        folder = work / str(minutes)
        folder.mkdir(parents=True, exist_ok=True)
        candles, windows = datasets(
            reference, later, reports, minutes * 60, align_epoch=minutes != 15
        )
        write(folder / "candidates.json", items)
        write(folder / "candles.json", candles)
        manifest["windows"][str(minutes)] = windows
    write(work / JOBS, manifest)
    print("Candidates by interval", {m: len(r) for m, r in jobs.items()})
    print("Screening", Counter(x[2] for x in coverage).most_common())


def records_from(folder):
    records = [
        json.loads(line)
        for line in (folder / "out.jsonl").read_text(encoding="utf-8-sig").splitlines()
    ]
    received = {x["id"]: x for x in records}
    assert len(received) == len(records)
    return received


def retry(reference, later, work):
    manifest = read(work / JOBS)
    folder = work / "15"
    blocked = {
        i
        for i, x in records_from(folder).items()
        if x.get("reason") == "Broker used an untraded candle"
    }
    if not blocked:
        return
    items = [x for x in read(folder / "candidates.json") if x["id"] in blocked]
    candles, windows = datasets(
        reference, later, [read(ROOT / f) for f in PRIOR], 30 * 60
    )
    folder = work / "30"
    folder.mkdir(exist_ok=False)
    write(folder / "candidates.json", items)
    write(folder / "candles.json", candles)
    manifest["windows"]["30"] = windows
    write(work / JOBS, manifest)
    print("30m zero-volume fill retry candidates", len(items))


def finalize(work, destination):
    manifest = read(work / JOBS)
    coverage, rows = list(manifest["coverage"]), []
    retried = (
        {x["id"] for x in read(work / "30" / "candidates.json")}
        if "30" in manifest["windows"]
        else set()
    )
    for interval in manifest["windows"]:
        folder = work / interval
        candidates = {x["id"]: x for x in read(folder / "candidates.json")}
        received = records_from(folder)
        assert received.keys() == candidates.keys()
        for i, record in sorted(received.items()):
            if interval == "15" and i in retried:
                assert record["reason"] == "Broker used an untraded candle"
                continue
            if "reason" in record:
                coverage.append(
                    [
                        i,
                        "FMZ Pine follow-up pending",
                        f"{interval}m: {record['reason']}",
                    ]
                )
                continue
            item = candidates[i]
            values = record["results"]
            assert (
                len(values) == 6
                and len({(x["period"], x["market"]) for x in values}) == 6
            )
            assert all(
                x["interval"] == f"{interval}m"
                and x["source_sha256"] == item["hash"]
                and x["id"] == i
                for x in values
            )
            for row in values:
                row.update(
                    group="FMZ Pine follow-up",
                    pine_source_version=item["old_version"],
                    migration_sha256=item["migration_sha256"],
                    transforms=item["transforms"],
                    repairs=item["repairs"],
                )
            rows.extend(values)
            status = (
                "Tested · Pine follow-up"
                if any(x["trades"] for x in values)
                else "Tested · Pine follow-up, no closes"
            )
            coverage.append(
                [
                    i,
                    status,
                    f"{interval}m PineTS replay. "
                    + ", ".join(item["repairs"] or ["resolved shadowed builtin"]),
                ]
            )
    assert (
        len(coverage) == len(pending()) and {x[0] for x in coverage} == pending().keys()
    )
    write(
        destination,
        {
            "engine": "PineTS 0.13.1",
            "source_revision": FMZ_REF,
            "windows_by_minutes": manifest["windows"],
            "coverage": sorted(coverage),
            "results": rows,
        },
    )
    print(Counter(x[1] for x in coverage), "result rows", len(rows))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for action, params in (
        ("prepare", ("archive", "reference", "later", "work")),
        ("retry", ("reference", "later", "work")),
    ):
        stage = sub.add_parser(action)
        for key in params:
            stage.add_argument(key, type=Path)
    done = sub.add_parser("finalize")
    for key in ("work", "destination"):
        done.add_argument(key, type=Path)
    options = parser.parse_args()
    if options.command == "prepare":
        prepare(options.archive, options.reference, options.later, options.work)
    elif options.command == "retry":
        retry(options.reference, options.later, options.work)
    else:
        finalize(options.work, options.destination)
