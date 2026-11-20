"""Replay verified legacy Pine compiler repairs on the pinned offline 15-minute feed."""

import argparse
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pine_followup import GLOBAL_RENAME, patch
from research.delta_pine_liquid_replay import checksum
from research.delta_pine_repair import (
    NO_QUOTED,
    expression_stop,
    positive_prior_reads,
    repair_recursion,
)
from research.delta_pinets_catalogue import FMZ_REF, read, source_block, write
from research.delta_pinets_migration import (
    INPUT_TYPES,
    VERSION,
    MigrationBlocked,
    arguments,
    keyword,
    tokens,
)
from research.fmz_pine_remaining import (
    ACTIVE_ORDER,
    BLOCKS,
    MAX_LOOPS,
    make_worker,
    plain_pine,
)
from research.fmz_round3_compile import TIME_LIMIT_MS, finalize, normalize_statements
from research.fmz_round3_compile import prepare_source as previous_prepare
from research.fmz_round4_compile_targeted import TARGETS, V1_IDS, amend

REASONS = re.compile(
    r"compile or execute|indicator or namespace|eager iff|recursive|overloaded RSI|"
    r"constrained input|reserved in Pine|migration namespace|standalone line|input field|"
    r"input type|explicit Pine v1|positional legacy|compatibility edits|declaration",
    re.IGNORECASE,
)
SCOPE = re.compile(
    r"(?m)^(\w+)\(([A-Za-z0-9_, \t]*)\)[ \t]*=>[^\n]*(?:\n(?:[ \t]+[^\n]+|[ \t]*$))*"
)
INPUT_KEYS = {
    "title",
    "defval",
    "type",
    "minval",
    "maxval",
    "step",
    "options",
    "confirm",
    "inline",
    "group",
    "tooltip",
}
INTEGER = re.compile(r"[+-]?\d+\Z")
DECIMAL = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)\Z")
VOLATILITY_STATE = {
    "max_": "float",
    "min_": "float",
    "is_uptrend": "bool",
    "vstop": "float",
}
STATE_TYPES = {
    **dict.fromkeys((64, 952, 1944, 3102), VOLATILITY_STATE),
    74: {"xATRTrailingStop": "float", "pos": "int"},
    1688: {"xMU": "float", "xMD": "float"},
    1779: {"bcount": "int", "scount": "int"},
    2602: {"upperband": "float", "lowerband": "float", "xATRTrailingStop": "float"},
    2659: dict.fromkeys(("i2", "q2", "re", "im", "p", "spp", "mama", "fama"), "float"),
    2700: dict.fromkeys(("i2", "q2", "re", "im", "p", "spp", "mama", "fama"), "float"),
    2701: {"out": "float"},
    2760: {"ret": "float", "pos": "int"},
    3153: {"out": "float"},
    4774: {"up": "float", "dn": "float", "lot": "float"},
    3641: {
        "longband": "float",
        "shortband": "float",
        "trend": "int",
        "QQEclong": "int",
        "QQEcshort": "int",
        "buy": "int",
        "sell": "int",
    },
    5527: {"AUC": "float", "ADC": "float"},
    5704: dict.fromkeys(("ret", "ret2", "ret3"), "float"),
}
BASE_STATE_TYPES = {
    **{i: v for i, v in STATE_TYPES.items() if i not in {2760, 3641, 5704}},
    4567: {"data": "float"},
    4599: {"kama": "float"},
}
LOCAL_TYPES = {
    1395: {"fractalUp": {"res": "float"}, "fractalDn": {"res": "float"}},
    3015: {"f_fisher": {"_value0": "float", "_fisher": "float"}},
    3019: {"fractalUp": {"res": "float"}, "fractalDn": {"res": "float"}},
    3021: {"calc_csf": {"csf": "float"}},
    3641: {"variant": {"v5": "float"}},
    4567: {"calc_evwma": {"data": "float"}},
    4599: {"kama": {"kama": "float"}},
}


def masked_pine(code):
    return NO_QUOTED.sub(lambda m: " " * len(m[0]), code)


def rename_function_locals(code):
    """Rename simple function-local bindings that collide with v5 namespaces or reserved words."""
    masked = masked_pine(code)
    changes = []
    names = 0
    for match in SCOPE.finditer(masked):
        function = match[1]
        params = {p.strip() for p in match[2].split(",") if p.strip()}
        if any(not re.fullmatch(r"[A-Za-z_]\w*", p) for p in params):
            continue
        scope = code[match.start() : match.end()]
        local = re.findall(
            r"(?m)^[ \t]+([A-Za-z_]\w*)[ \t]*=(?!=|>)",
            masked[match.start() : match.end()],
        )
        parts = tokens(scope)
        named = {
            parts[x[0]].start()
            for i, node in enumerate(parts)
            if node.group() == "("
            for x in arguments(parts, i)[1]
            if keyword(parts, x)[0]
        }
        for name in (params | set(local)) & GLOBAL_RENAME:
            canonical = f"fmz_local_{name}"
            if re.search(rf"\b{canonical}\b", masked) or local.count(name) > 1:
                continue
            if name in params and re.search(
                rf"\b{function}\s*\([^\n)]*\b{name}\s*=(?!=)", masked
            ):
                continue
            for i, node in enumerate(parts):
                if node.group() != name or node.start() in named:
                    continue
                previous = parts[i - 1].group() if i else ""
                following = parts[i + 1].group() if i + 1 < len(parts) else ""
                if previous == "." or following in {".", "("}:
                    continue
                changes.append(
                    (
                        match.start() + node.start(),
                        match.start() + node.end(),
                        canonical,
                    )
                )
            names += 1
    return patch(code, changes), names


def input_literals(code, *, expanded=True):
    """Preserve unambiguous literal inputs through legacy widget syntax changes."""
    parts = tokens(code)
    assignments = re.findall(r"(?m)^(?:var[ \t]+)?(\w+)\s*=\s*(\S[^\n]*)", code)
    strings = {
        name: literal.strip()
        for name, literal in assignments
        if re.fullmatch(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'", literal.strip())
        and len(
            re.findall(
                rf"(?m)^[ \t]*(?:var[ \t]+)?{name}[ \t]*(?::=|=(?!=))",
                masked_pine(code),
            )
        )
        == 1
    }
    enums = re.compile(
        r"(?:strategy\.direction\.(?:long|short|all)|size\.(?:auto|tiny|small|normal|large|huge))\Z"
    )
    edits = []
    for i, node in enumerate(parts[:-1]):
        if (
            node.group() != "input"
            or parts[i + 1].group() != "("
            or (i and parts[i - 1].group() == ".")
        ):
            continue
        end, args = arguments(parts, i + 1)
        fields = []
        for a, b in args:
            if a == b:
                break
            name, _ = keyword(parts, (a, b))
            fields.append(
                (name, code[parts[a + 2 if name else a].start() : parts[b - 1].end()])
            )
        if len(fields) != len(args) or not fields:
            continue
        values = dict(fields)
        default = values.get("defval", fields[0][1] if fields[0][0] is None else "")
        if not expanded and not DECIMAL.fullmatch(default):
            continue
        updated = fields.copy()
        if (
            expanded
            and len(updated) > 2
            and updated[2][0] is None
            and updated[2][1] in {"input." + kind for kind in INPUT_TYPES}
        ):
            updated[2] = ("type", updated[2][1])
        options = {key for key, _ in updated if key}
        if options - INPUT_KEYS or any(key is None for key, _ in updated[2:]):
            continue
        if expanded and enums.fullmatch(default) and "options" in options:
            values = dict(updated)
            choices = [
                x.strip()
                for x in values["options"]
                .removeprefix("[")
                .removesuffix("]")
                .split(",")
            ]
            if default in choices and all(enums.fullmatch(x) for x in choices):
                edits.append((node.start(), parts[end].end(), default))
                continue
        normalized = []
        for index, (key, value) in enumerate(updated):
            if (
                expanded
                and key == "title"
                and any(k == "title" for k, _ in updated[index + 1 :])
            ):
                continue
            if key == "defval" and fields[0][0] is None:
                if not DECIMAL.fullmatch(fields[0][1]) or Decimal(
                    fields[0][1]
                ) != Decimal(value):
                    raise MigrationBlocked("Legacy input contains conflicting defaults")
                continue
            if key in {"minval", "maxval", "step", "defval"} or (
                index == 0 and key is None
            ):
                if INTEGER.fullmatch(value):
                    value = str(int(value))
                if expanded:
                    value = strings.get(value, value)
            if (
                expanded
                and key == "options"
                and value.startswith("[")
                and value.endswith("]")
            ):
                choices = [x.strip() for x in value[1:-1].split(",")]
                if all(x in strings for x in choices):
                    value = "[" + ", ".join(strings[x] for x in choices) + "]"
            if key == "type" and value in INPUT_TYPES:
                value = f"input.{value}"
            normalized.append((key, value))
        if normalized != fields:
            replacement = ", ".join(
                f"{key} = {value}" if key else value for key, value in normalized
            )
            edits.append((parts[i + 1].end(), parts[end].start(), replacement))
    return patch(code, edits), len(edits)


def explicit_state(code, declarations, *, wrapped=True):
    """Predeclare source-audited recursive series before their first positive history read."""
    if not declarations:
        return code, 0
    masked = masked_pine(code)
    inserts = {}
    edits = []
    for name, kind in declarations.items():
        pattern = re.compile(rf"(?m)^{name}[ \t]*(=)(?!=|>)")
        bindings = list(pattern.finditer(masked))
        if len(bindings) != 1 or kind not in {"int", "float", "bool"}:
            raise MigrationBlocked(f"Ambiguous recursive binding for {name}")
        bind = bindings[0]
        last = (
            expression_stop(masked, bind.end())
            if wrapped
            else masked.find("\n", bind.end())
        )
        if last < 0:
            last = len(masked)
        occurrences = list(
            re.finditer(
                rf"\b{name}\b",
                masked[: bind.start()] + " " * len(bind[0]) + masked[bind.end() : last],
            )
        )
        if not occurrences or any(
            not re.match(r"[ \t]*\[[ \t]*[1-9]\d*[ \t]*\]", masked[m.end() :])
            for m in occurrences
        ):
            raise MigrationBlocked(
                f"Unverified current or forward value read for {name}"
            )
        earliest = min(bind.start(), occurrences[0].start())
        first_line = masked.rfind("\n", 0, earliest) + 1
        if masked[first_line : first_line + 1].isspace():
            raise MigrationBlocked(
                f"Recursive binding first used inside a local block for {name}"
            )
        inserts.setdefault(first_line, []).append(f"var {kind} {name} = na\n")
        edits.append((bind.start(1), bind.end(1), ":="))
    edits.extend((pos, pos, "".join(variants)) for pos, variants in inserts.items())
    return patch(code, edits), len(declarations)


def local_state(code, declarations):
    """Retain the prior value of an audited recursive variable in its original function."""
    if not declarations:
        return code, 0
    masked = masked_pine(code)
    edits = []
    for scope in SCOPE.finditer(masked):
        for name, kind in declarations.get(scope[1], {}).items():
            pattern = rf"(?m)^([ \t]+)({name})[ \t]*(=)(?!=|>)"
            bindings = list(re.finditer(pattern, masked[scope.start() : scope.end()]))
            if len(bindings) != 1:
                raise MigrationBlocked(
                    f"Ambiguous function state for {scope[1]} . {name}"
                )
            bind = bindings[0]
            start = scope.start() + bind.start()
            end = scope.start() + bind.end()
            until = expression_stop(masked, end)
            rhs = masked[end:until]
            if re.search(
                rf"\b{name}\b", masked[scope.start(2) : start]
            ) or not positive_prior_reads(rhs, name):
                raise MigrationBlocked(f"Unverified function history for {name}")
            edits.extend(
                (
                    (start, start, f"{bind[1]}var {kind} {name} = na\n"),
                    (end - 1, end, ":="),
                )
            )
    if len(edits) != 2 * sum(len(types) for types in declarations.values()):
        raise MigrationBlocked("An audited function state was not found")
    return patch(code, edits), len(edits) // 2


def fixed_rsi(code):
    masked = masked_pine(code)
    if re.search(r"(?m)^rsi\s*\([^\n)]*\)\s*=>", masked):
        return code, 0
    float_series = {
        name
        for name in re.findall(r"(?m)^(\w+)\s*=\s*[^\n]*\bsum\(volume\s*\*", masked)
        if len(re.findall(rf"(?m)^[ \t]*{name}[ \t]*(?::=|=(?!=))", masked)) == 1
    }
    parts = tokens(code)
    edits = []
    for i, node in enumerate(parts[:-1]):
        if (
            node.group() != "rsi"
            or parts[i + 1].group() != "("
            or (i and parts[i - 1].group() == ".")
        ):
            continue
        end, spans = arguments(parts, i + 1)
        if len(spans) != 2 or not all(
            b - a == 1 and parts[a].group() in float_series for a, b in spans
        ):
            continue
        x, y = (parts[a].group() for a, _ in spans)
        edits.append(
            (
                node.start(),
                parts[end].end(),
                f"(100.0 - (100.0 / (1.0 + (({x}) / ({y})))))",
            )
        )
    return patch(code, edits), len(edits)


def eager_legacy_calls(code):
    """Evaluate both archived iff arguments at each invocation, keeping Pine scope."""
    name = "fmz_eager_if"
    masked = masked_pine(code)
    if re.search(rf"\b{name}\b|(?m:^iff\s*\([^\n)]*\)\s*=>)", masked):
        return code, 0
    parts = tokens(code)
    edits = []
    for i, node in enumerate(parts[:-1]):
        if (
            node.group() != "iff"
            or parts[i + 1].group() != "("
            or (i and parts[i - 1].group() == ".")
        ):
            continue
        _, args = arguments(parts, i + 1)
        if len(args) != 3 or any(keyword(parts, span)[0] for span in args):
            return code, 0
        edits.append((node.start(), node.end(), name))
    if not edits:
        return code, 0
    new_code = patch(code, edits)
    declaration = f"{name}(condition, yes, no) => condition ? yes : no\n"
    if version := VERSION.search(new_code):
        return new_code[: version.end()] + "\n" + declaration + new_code[
            version.end() :
        ], len(edits)
    return declaration + new_code, len(edits)


def pre_migration(code, *, state_types=None, local_types=None, initial=False):
    code = plain_pine(code)
    version = VERSION.search(code)
    source_version = int(version[1]) if version else None
    labels = Counter()
    code, changes = normalize_statements(code)
    labels.update(changes)
    edits = [
        (rename_function_locals, "Function-local v5 collision renamed"),
        (
            lambda text: input_literals(text, expanded=not initial),
            "Legacy literal input normalized",
        ),
        (
            lambda text: explicit_state(text, state_types, wrapped=not initial),
            "Audited prior-bar recursive state",
        ),
    ]
    if not initial:
        edits.extend(
            [
                (
                    lambda text: local_state(text, local_types),
                    "Audited function-local recursive state",
                ),
                (fixed_rsi, "Documented legacy float RSI overload"),
            ]
        )
    for transform, label in edits:
        code, count = transform(code)
        if count:
            labels[label] = count
    if not source_version or source_version >= 5:
        code, count = repair_recursion(code)
        if count:
            labels["Explicit prior-bar recursive state"] = count
    return code, labels


def prepare_source(code, *, state_types=None, local_types=None, initial=False):
    code, labels = pre_migration(
        code, state_types=state_types, local_types=local_types, initial=initial
    )
    try:
        migrated, old, transforms, repairs = previous_prepare(
            code, isolated_literals=True
        )
    except MigrationBlocked as error:
        if initial or "Eager iff branch" not in str(error):
            raise
        code, count = eager_legacy_calls(code)
        if not count:
            raise
        labels["Archived eager iff argument evaluation"] = count
        migrated, old, transforms, repairs = previous_prepare(
            code, isolated_literals=True
        )
    return migrated, old, transforms, dict(labels) | repairs


def selected(row):
    return (
        not row["status"].startswith("Tested")
        and FMZ_REF in row["source"]
        and REASONS.search(row["reason"])
    )


def prepare(
    archive, work, ledger, prior_work, previous_reports, targeted=False, initial=False
):
    previous_hashes = {
        (int(i), digest)
        for report in previous_reports
        for i, digest in read(report).get("candidate_migration_sha256", {}).items()
    }
    previous_hashes |= {
        (candidate["id"], candidate["migration_sha256"])
        for folder in prior_work
        if (folder / "candidates.json").exists()
        for candidate in read(folder / "candidates.json")
    }
    completed_ids = {
        row["id"] for report in previous_reports for row in read(report)["results"]
    }
    coverage, candidates, pinned = [], [], {}
    with ZipFile(archive) as zip_file:
        for row in read(ledger)["disposition"]:
            if (
                not selected(row)
                or row["id"] in completed_ids
                or (targeted and row["id"] not in TARGETS)
            ):
                continue
            i, url = row["id"], row["source"]
            relative = unquote(url.split(FMZ_REF + "/", 1)[1])
            raw = zip_file.read(f"strategies-{FMZ_REF}/{relative}")
            digest = checksum(raw)
            if row.get("pinned_document_sha256", digest) != digest:
                raise ValueError(f"Pinned source mismatch for {i}")
            pinned[str(i)] = digest
            document = raw.decode()
            blocks = source_block(document) or BLOCKS.findall(document)
            blocks = [
                b
                for b in blocks
                if ACTIVE_ORDER.search(NO_QUOTED.sub("", plain_pine(b)))
            ]
            try:
                if len(blocks) != 1:
                    raise MigrationBlocked(
                        f"Pinned archive contains {len(blocks)} active strategy blocks"
                    )
                block = plain_pine(blocks[0])
                if targeted:
                    block, targeted_label = amend(block, i)
                states = BASE_STATE_TYPES if initial else STATE_TYPES
                code, version, transforms, repairs = prepare_source(
                    block,
                    state_types=states.get(i),
                    local_types=LOCAL_TYPES.get(i),
                    initial=initial,
                )
                if targeted:
                    repairs[targeted_label] = 1
                    if i in V1_IDS:
                        version = 1
                migration_digest = checksum(code.encode())
                if (i, migration_digest) in previous_hashes:
                    raise MigrationBlocked(
                        "Prior compiler replay used this exact migrated source"
                    )
            except MigrationBlocked as error:
                coverage.append([i, "Pending · FMZ Pine compiler research", str(error)])
                continue
            archived = re.search(r"(?m)^period:\s*(\S+)", document)
            candidates.append(
                {
                    "id": i,
                    "name": row["name"],
                    "source": url,
                    "hash": digest,
                    "archived": archived[1] if archived else "",
                    "code": code,
                    "old_version": version,
                    "transforms": transforms,
                    "repairs": repairs,
                    "migration_sha256": migration_digest,
                }
            )
    candle_receipt = read(prior_work[0] / "preflight.json")
    source_candles = (prior_work[0] / "candles.json").read_bytes()
    if previous_reports:
        candle_digest = read(previous_reports[0])["candle_files_sha256"]["15"]
        assert checksum(source_candles) == candle_digest
    (work / "candles.json").write_bytes(source_candles)
    write(work / "candidates.json", candidates)
    write(
        work / "preflight.json",
        {
            "coverage": coverage,
            "source_revision": FMZ_REF,
            "pinned_document_sha256": pinned,
            "windows": candle_receipt["windows"],
            "bar_archives": candle_receipt["bar_archives"],
            "worker_sha256": make_worker(work, TIME_LIMIT_MS),
            "base_disposition_sha256": checksum(ledger.read_bytes()),
            "time_limit_ms": TIME_LIMIT_MS,
            "max_loop_iterations": MAX_LOOPS,
            "requires_os_isolation": True,
            "candidate_migration_sha256": {
                str(c["id"]): c["migration_sha256"] for c in candidates
            },
        },
    )
    print(len(candidates), "new candidates", len(coverage), "screened")
    print(Counter(r[2] for r in coverage))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="action", required=True)
    stage = commands.add_parser("prepare")
    for key in ("archive", "work", "ledger"):
        stage.add_argument(key, type=Path)
    stage.add_argument("--prior-work", type=Path, action="append", required=True)
    stage.add_argument("--previous-report", type=Path, action="append", default=[])
    variant = stage.add_mutually_exclusive_group()
    variant.add_argument("--targeted", action="store_true")
    variant.add_argument("--initial", action="store_true")
    stage = commands.add_parser("finalize")
    stage.add_argument("work", type=Path)
    stage.add_argument("destination", type=Path)
    args = cli.parse_args()
    if args.action == "prepare":
        prepare(
            args.archive,
            args.work,
            args.ledger,
            args.prior_work,
            args.previous_report,
            args.targeted,
            args.initial,
        )
    else:
        finalize(args.work, args.destination, args.work / "diagnostics.jsonl")
