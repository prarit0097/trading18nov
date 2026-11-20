"""Replay round-three FMZ Pine compile and migration failures in an isolated worker."""

import argparse
import json
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pine_followup import GLOBAL_RENAME, patch, rename_global
from research.delta_pine_liquid_replay import archived_candles, checksum, prepare_candles
from research.delta_pine_repair import NO_QUOTED
from research.delta_pinets_catalogue import EXTERNAL, FMZ_REF, read, source_block, write
from research.delta_pinets_migration import (
    PREFIXES,
    VERSION,
    MigrationBlocked,
    arguments,
    keyword,
    tokens,
)
from research.fmz_pine_remaining import (
    ACTIVE_ORDER,
    BLOCKS,
    EXTRA_UNSUPPORTED,
    MAX_LOOPS,
    finalize as finalize_compatibility,
    make_worker,
    plain_pine,
    prepare_source as compatibility_source,
)

BLOCKERS = re.compile(
    r"isolated Pine runner.s supported syntax|compile or execute|callable shadowing|"
    r"migration namespace|reserved in Pine|recursive|overloaded RSI|eager iff|"
    r"constrained input|lacks an indicator or namespace|source version is absent|"
    r"explicit Pine v1|version directive|positional legacy input|unsupported legacy input|"
    r"duplicate legacy input|overlapping compatibility|legacy session|session day defaults",
    re.I,
)
LEGACY_VERSION = {2, 3, 4}
NAMED_GAP = re.compile(r"(?:[ \t\r\n]|//[^\n]*)*\Z")
PLAIN_ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*[ \t]*=(?!=|>)")
ASSIGNMENT = re.compile(r"(?::=|=(?!=|>))")
TIME_LIMIT_MS = 45_000
IDENTIFIER = re.compile(r"[A-Za-z_]\w*\Z")
NUMBER = re.compile(r"[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)\Z")
DEFAULT_VARIANT = "Archived literal default outside declared bounds"


def normalize_statements(code):
    """Separate globals and join named argument lines without changing tokens."""
    parts = tokens(code)
    nesting = []
    edits = []
    counts = Counter()
    for index, part in enumerate(parts[:-2]):
        value = part.group()
        if value in {"(", "["}:
            nesting.append(value)
        elif value in {")", "]"} and nesting:
            nesting.pop()
        following, second = parts[index + 1 : index + 3]
        gap = code[part.end() : following.start()]
        if (
            nesting and nesting[-1] == "(" and value in {"(", ","}
            and second.group() == "=" and re.fullmatch(r"[A-Za-z_]\w*", following.group())
            and "\n" in gap and NAMED_GAP.fullmatch(gap)
        ):
            edits.append((part.end(), following.start(), " "))
            counts["Wrapped named arguments joined"] += 1
        if value != "," or nesting or not re.fullmatch(r"[ \t]*", gap):
            continue
        line = code.rfind("\n", 0, part.start()) + 1
        prefix = code[line : part.start()]
        if (
            PLAIN_ASSIGNMENT.match(prefix) and "=>" not in prefix
            and re.fullmatch(r"[A-Za-z_]\w*", following.group())
            and ASSIGNMENT.match(code, second.start())
        ):
            edits.append((part.start(), following.start(), "\n"))
            counts["Explicit same-line assignments separated"] += 1
    return patch(code, edits), counts


def rename_custom_functions(code):
    masked = NO_QUOTED.sub(lambda m: " " * len(m[0]), code)
    signatures = re.findall(r"(?m)^([A-Za-z_]\w*)[ \t]*\(([^\n()]*)\)[ \t]*=>", masked)
    definitions = Counter(name for name, _ in signatures)
    collisions = set(PREFIXES) | GLOBAL_RENAME | {"iff", "offset"}
    parts = tokens(code)
    changes, count = [], 0
    for name, signature in signatures:
        new = f"fmz_function_{name}"
        parameters = [p.strip() for p in signature.split(",")] if signature.strip() else []
        if (name not in collisions or definitions[name] != 1
            or re.search(rf"\b{new}\b", masked)
            or not all(IDENTIFIER.fullmatch(p) for p in parameters)):
            continue
        calls = []
        for i, part in enumerate(parts[:-1]):
            if part.group() != name or parts[i + 1].group() != "(" or (i and parts[i - 1].group() == "."):
                continue
            _, spans = arguments(parts, i + 1)
            if len(spans) != len(parameters) or any(
                key is not None and key not in parameters
                for key, _ in (keyword(parts, span) for span in spans)
            ):
                break
            calls.append((part.start(), part.end(), new))
        else:
            changes.extend(calls)
            count += 1
    return patch(code, changes), count


def normalize_input_defaults(code):
    parts = tokens(code)
    edits, counts = [], Counter()
    for i in range(len(parts) - 4):
        prefix = [node.group() for node in parts[i : i + 4]]
        if prefix[:2] != ["input", "."] or prefix[3] != "(" or (i and parts[i - 1].group() == "."):
            continue
        kind = prefix[2]
        if kind not in {"bool", "int", "float"}:
            continue
        end, spans = arguments(parts, i + 3)
        fields = []
        for a, b in spans:
            key, _ = keyword(parts, (a, b))
            value_start = parts[a + 2 if key else a].start()
            fields.append((key, code[value_start : parts[b - 1].end()]))
        if not fields:
            continue
        names = [key for key, _ in fields if key is not None]
        if len(names) != len(set(names)):
            continue
        default_index = next((n for n, (key, _) in enumerate(fields) if key == "defval"), None)
        if default_index is None and fields[0][0] is None:
            default_index = 0
        if default_index is None or (default_index > 0 and fields[0][0] is None):
            continue
        key, default = fields[default_index]
        if kind == "bool" and default in {"0", "1"}:
            fields[default_index] = (key, "true" if default == "1" else "false")
            counts["Literal boolean default normalized"] += 1
        elif kind in {"int", "float"} and NUMBER.fullmatch(default):
            rejected = {
                key for key, value in fields if NUMBER.fullmatch(value) and (
                    (key == "minval" and Decimal(default) < Decimal(value))
                    or (key == "maxval" and Decimal(default) > Decimal(value))
                )
            }
            if not rejected:
                continue
            fields = [(key, value) for key, value in fields if key not in rejected]
            counts[DEFAULT_VARIANT] += 1
        else:
            continue
        replacement = ", ".join(value if key is None else f"{key} = {value}" for key, value in fields)
        edits.append((parts[i + 3].end(), parts[end].start(), replacement))
    return patch(code, edits), counts


def prepare_source(block, *, isolated_literals, initial=False):
    code = plain_pine(block)
    masked = NO_QUOTED.sub("", code)
    external = EXTERNAL.search(masked)
    runtime = EXTRA_UNSUPPORTED.search(masked) or re.search(
        r"\b(?:heikinashi|calc_on_every_history_tick)\b", masked
    )
    if initial and (external or runtime):
        raise MigrationBlocked("Source requires separately verified market data or runtime semantics")
    if external:
        raise MigrationBlocked(f"Source requires a verified feed, import or chart value ({external[0].strip()})")
    if runtime:
        raise MigrationBlocked(f"Source requires historical runtime semantics for {runtime[0].strip()}")
    changes = Counter()
    version = VERSION.search(code)
    if version and int(version[1]) in LEGACY_VERSION:
        code, changes = normalize_statements(code)
        if not initial:
            code, count = rename_custom_functions(code)
            if count:
                changes["Archived function renamed before namespace migration"] = count
        code, count = rename_global(code, GLOBAL_RENAME | {"iff", "offset"})
        if count:
            changes["Unshadowed legacy identifier renamed"] = count
    migrated, old, transforms, repairs = compatibility_source(
        code, isolated_literals=isolated_literals
    )
    if not initial:
        migrated, input_changes = normalize_input_defaults(migrated)
        changes.update(input_changes)
    return migrated, old, transforms, dict(changes) | repairs


def selected(row):
    return (
        not row["status"].startswith("Tested")
        and "github.com/fmzquant/strategies/" in row["source"]
        and FMZ_REF in row["source"]
        and BLOCKERS.search(row["reason"]) is not None
    )


def prepare(archive, candle_archive, work, ledger, previous_work=None, initial=False):
    work.mkdir(parents=True, exist_ok=True)
    coverage, candidates, hashes = [], [], {}
    previous = {}
    if previous_work:
        previous = {item["id"]: item for item in read(previous_work / "candidates.json")}
        for line in (previous_work / "out.jsonl").read_text(encoding="utf-8-sig").splitlines():
            receipt = json.loads(line)
            previous[receipt["id"]]["succeeded"] = "results" in receipt
    with ZipFile(archive) as source:
        for row in read(ledger)["disposition"]:
            if not selected(row):
                continue
            i, url = row["id"], row["source"]
            prior = previous.get(i, {})
            if prior.get("succeeded"):
                continue
            path = unquote(url.split(FMZ_REF + "/", 1)[1])
            raw = source.read(f"strategies-{FMZ_REF}/{path}")
            digest = checksum(raw)
            if row.get("pinned_document_sha256", digest) != digest:
                raise ValueError(f"Source hash mismatch for {i}")
            hashes[str(i)] = digest
            document = raw.decode()
            blocks = source_block(document) or BLOCKS.findall(document)
            blocks = [
                b for b in blocks if ACTIVE_ORDER.search(NO_QUOTED.sub("", plain_pine(b)))
            ]
            try:
                if len(blocks) != 1:
                    raise MigrationBlocked(f"Archive yielded {len(blocks)} active Pine order blocks")
                code, version, transforms, repairs = prepare_source(
                    blocks[0], isolated_literals=True, initial=initial
                )
            except MigrationBlocked as error:
                coverage.append([i, "Pending · FMZ Pine compile research", str(error)])
                continue
            migrated_digest = checksum(code.encode())
            if migrated_digest == prior.get("migration_sha256"):
                continue
            archived = re.search(r"(?m)^period:\s*(\S+)", document)
            candidates.append(
                {
                    "id": i,
                    "name": row["name"],
                    "source": url,
                    "hash": digest,
                    "archived": archived[1] if archived else "",
                    "old_version": version,
                    "code": code,
                    "transforms": transforms,
                    "repairs": repairs,
                    "migration_sha256": migrated_digest,
                }
            )
    base, files = archived_candles(candle_archive)
    candles, windows = prepare_candles(base, 15)
    write(work / "candles.json", {"Binance · " + k: v for k, v in candles.items()})
    write(work / "candidates.json", candidates)
    write(
        work / "preflight.json",
        {
            "coverage": coverage,
            "source_revision": FMZ_REF,
            "pinned_document_sha256": hashes,
            "bar_archives": files,
            "windows": {"Binance · " + k: v for k, v in windows.items()},
            "worker_sha256": make_worker(work, TIME_LIMIT_MS),
            "base_disposition_sha256": checksum(ledger.read_bytes()),
            "time_limit_ms": TIME_LIMIT_MS,
            "max_loop_iterations": MAX_LOOPS,
            "requires_os_isolation": True,
            **({"previous_out_sha256": checksum((previous_work / "out.jsonl").read_bytes())} if previous_work else {}),
        },
    )
    print(len(candidates), "admitted", len(coverage), "screened")
    print(Counter(row[2] for row in coverage))


def finalize(work, destination, diagnostics=None):
    finalize_compatibility(work, destination, diagnostics)
    report = read(destination)
    report["engine_sha256"] = checksum((work / "engine.mjs").read_bytes())
    variants = set()
    for row in report["results"]:
        if DEFAULT_VARIANT in row["repairs"]:
            row["group"] = "FMZ · Archived input default"
            variants.add(row["id"])
    for item in report["coverage"]:
        if item[0] in variants:
            suffix = ", no closes" if item[1].endswith("no closes") else ""
            item[1] = "Tested · FMZ archived input default" + suffix
            item[2] = (
                "Variant retains the archived literal default and drops the contradictory input bound. "
                + item[2]
            )
    write(destination, report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    stages = parser.add_subparsers(dest="stage", required=True)
    for stage, fields in (
        ("prepare", ("archive", "candle_archive", "work", "ledger")),
        ("finalize", ("work", "destination")),
    ):
        subparser = stages.add_parser(stage)
        for field in fields:
            subparser.add_argument(field, type=Path)
        if stage == "finalize":
            subparser.add_argument("--diagnostics", type=Path)
        else:
            subparser.add_argument("--previous-work", type=Path)
            subparser.add_argument("--initial", action="store_true")
    args = vars(parser.parse_args())
    stage = args.pop("stage")
    (prepare if stage == "prepare" else finalize)(**args)
