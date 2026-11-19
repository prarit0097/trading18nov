"""Repair only provable legacy recursion and compiler incompatibilities."""

import argparse
import ast
import csv
import hashlib
import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_fmz_replay import Unsupported, expression
from research.delta_pinets_catalogue import (
    FMZ_REF,
    PRIOR,
    datasets,
    finish,
    merge_retry,
    read,
    source_block,
    write,
)
from research.delta_pinets_migration import (
    MigrationBlocked,
    arguments,
    keyword,
    migrate,
    tokens,
)
from research.delta_strategy_replay import ROOT

PREVIOUS = "delta-pinets-migration.json"
RECURSION = "Pine v2 implicit recursive series needs explicit state verification"
COMPILER = {
    "PineTS could not compile or execute this source",
    "PineTS lacks an indicator or namespace used by this source",
}
TOP_ASSIGN = re.compile(r"(?m)^([A-Za-z_]\w*)[ \t]*=[ \t]*(?![=>])([^\r\n]+)$")
TYPED_ASSIGN = re.compile(
    r"(?m)^(?:var[ \t]+)?(float|int|bool)[ \t]+([A-Za-z_]\w*)[ \t]*="
)
NO_QUOTED = re.compile(r"""//[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'""")

FLOAT_SERIES = {
    "open",
    "high",
    "low",
    "close",
    "volume",
    "hl2",
    "hlc3",
    "ohlc4",
    "hlcc4",
    "tr",
}
INT_SERIES = {
    "time",
    "time_close",
    "bar_index",
    "dayofmonth",
    "dayofweek",
    "month",
    "year",
    "hour",
    "minute",
    "second",
}
FLOAT_FUNCTIONS = {
    "atr",
    "sma",
    "ema",
    "wma",
    "vwma",
    "rma",
    "roc",
    "rsi",
    "sar",
    "stdev",
    "highest",
    "lowest",
    "linreg",
    "correlation",
    "macd",
    "cci",
    "mom",
    "vwap",
    "alma",
    "obv",
    "avg",
    "log",
    "log10",
    "exp",
    "sqrt",
    "pow",
    "sin",
    "cos",
    "tan",
    "dev",
}
INT_FUNCTIONS = {
    "barssince",
    "highestbars",
    "lowestbars",
    "dayofmonth",
    "dayofweek",
    "hour",
    "minute",
    "year",
    "month",
    "timestamp",
}
BOOL_FUNCTIONS = {"crossover", "crossunder", "cross", "na", "falling", "rising"}
NUMERIC = {"int", "float"}
UNKNOWN = "unknown"
MISSING = "history"


def unify(types):
    kinds = set(types) - {MISSING}
    if not kinds:
        return MISSING
    if UNKNOWN in kinds:
        return UNKNOWN
    if kinds <= NUMERIC:
        return "float" if "float" in kinds else "int"
    if len(kinds) == 1:
        return kinds.pop()
    return UNKNOWN


def call_type(node, lookup):
    name = ast.unparse(node.func)
    bare = name.rsplit(".", 1)[-1]
    if name in {"input.int", "input.integer", "input.float", "input.bool"}:
        return name.split(".")[-1].replace("integer", "int")
    if name == "input":
        fields = {k.arg: k.value for k in node.keywords}
        if "type" in fields:
            declared = ast.unparse(fields["type"]).removeprefix("input.")
            return {"integer": "int", "float": "float", "bool": "bool"}.get(
                declared, UNKNOWN
            )
        default = fields.get("defval", node.args[0] if node.args else None)
        return lookup(default)
    if bare in FLOAT_FUNCTIONS:
        return "float"
    if bare in INT_FUNCTIONS:
        return "int"
    if bare in BOOL_FUNCTIONS:
        return "bool"
    if bare in {"min", "max", "abs", "nz"}:
        return unify(lookup(x) for x in node.args)
    if bare in {"change", "valuewhen"}:
        index = 1 if bare == "valuewhen" else 0
        return lookup(node.args[index]) if len(node.args) > index else UNKNOWN
    if name == "iff" and len(node.args) == 3:
        return unify(lookup(x) for x in node.args[1:])
    return UNKNOWN


def value_type(node, known, name=None):
    def lookup(x):
        return value_type(x, known, name)

    if isinstance(node, ast.Constant):
        return {int: "int", float: "float", bool: "bool"}.get(type(node.value), UNKNOWN)
    if isinstance(node, ast.Name):
        if node.id == name or node.id == "na":
            return MISSING
        if node.id in {"false", "true"}:
            return "bool"
        if node.id in FLOAT_SERIES:
            return "float"
        if node.id in INT_SERIES:
            return "int"
        return known.get(node.id, UNKNOWN)
    if isinstance(node, ast.Attribute) and ast.unparse(node) in {
        "strategy.equity",
        "strategy.position_size",
        "strategy.position_avg_price",
        "strategy.initial_capital",
        "syminfo.mintick",
    }:
        return "float"
    if isinstance(node, ast.Subscript):
        return lookup(node.value)
    if isinstance(node, ast.IfExp):
        return unify((lookup(node.body), lookup(node.orelse)))
    if isinstance(node, (ast.BoolOp, ast.Compare)):
        return "bool"
    if isinstance(node, ast.UnaryOp):
        return "bool" if isinstance(node.op, ast.Not) else lookup(node.operand)
    if isinstance(node, ast.BinOp):
        kinds = (lookup(node.left), lookup(node.right))
        if isinstance(node.op, ast.Div):
            return (
                "float"
                if "float" in kinds and UNKNOWN not in kinds and "bool" not in kinds
                else UNKNOWN
            )
        return unify(kinds) if set(kinds) <= NUMERIC | {MISSING} else UNKNOWN
    if isinstance(node, ast.Call):
        return call_type(node, lookup)
    return UNKNOWN


def positive_prior_reads(rhs, name):
    mentions = list(re.finditer(r"\b" + re.escape(name) + r"\b", rhs))
    return mentions and all(
        re.match(r"[ \t]*\[[ \t]*[1-9][0-9]*[ \t]*\]", rhs[m.end() :]) for m in mentions
    )


def expression_stop(masked, start):
    depth = 0
    for index in range(start, len(masked)):
        char = masked[index]
        if char == "\n" and depth == 0:
            return index
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
            if depth < 0:
                return index
    return len(masked)


def repair_recursion(code):
    known = {}
    typed = [(m.start(), m[2], m[1]) for m in TYPED_ASSIGN.finditer(code)]
    masked = NO_QUOTED.sub(lambda m: " " * len(m.group()), code)
    changes = []
    previous_end = 0
    for match in TOP_ASSIGN.finditer(masked):
        if match.start() < previous_end:
            continue
        while typed and typed[0][0] < match.start():
            _, name, kind = typed.pop(0)
            known[name] = kind
        start = match.start(2)
        previous_end = expression_stop(masked, start)
        name, rhs = match[1], code[start:previous_end]
        masked_rhs = masked[start:previous_end]
        cleaned = " ".join(re.sub(r"(?m)//.*$", "", rhs).splitlines()).strip()
        own = re.search(r"\b" + re.escape(name) + r"[ \t]*\[", masked_rhs)
        if own:
            if not positive_prior_reads(masked_rhs, name):
                raise MigrationBlocked(
                    "Recursive variable uses a current, future or computed self-read"
                )
            binding = (
                r"(?m)^[ \t]*(?:(?:var|float|int|bool)[ \t]+)*"
                + re.escape(name)
                + r"[ \t]*(?::=|=(?!=|>))"
            )
            if len(re.findall(binding, masked)) != 1:
                raise MigrationBlocked(
                    "Recursive state has multiple assignments or nested definitions"
                )
            prior = masked[: match.start()]
            if re.search(r"\b" + re.escape(name) + r"\b", prior):
                raise MigrationBlocked(
                    "Recursive state is referenced before its declaration"
                )
        try:
            rhs_ast = expression(cleaned)
        except Unsupported as exc:
            if own:
                raise MigrationBlocked(
                    "Recursive expression type is not provable"
                ) from exc
            continue
        kind = value_type(rhs_ast, known, name if own else None)
        if own:
            if kind not in {"float", "int", "bool"}:
                raise MigrationBlocked("Recursive expression type is not provable")
            original = code[match.start() : match.start(2)]
            changes.append(
                (
                    match.start(),
                    match.start(2),
                    f"var {kind} {name} = na\n" + original.replace("=", ":=", 1),
                )
            )
        if kind not in {UNKNOWN, MISSING}:
            known[name] = kind
    for a, b, text in reversed(changes):
        code = code[:a] + text + code[b:]
    return code, len(changes)


def compiler_rewrites(code):
    parts = tokens(code)
    changes = []
    labels = Counter()
    for i in range(len(parts) - 3):
        prefix = [x.group() for x in parts[i : i + 4]]
        if prefix[:2] != ["strategy", "."] or prefix[3] != "(":
            continue
        action = prefix[2]
        if action not in {"entry", "order", "exit"}:
            continue
        end, args = arguments(parts, i + 3)
        fields = {keyword(parts, s)[0] for s in args}
        if action == "exit":
            # Pine v2–4 accepted a price-less exit call and ignored it. Preserve
            # that no-op where statement scope and all argument reads are clear.
            if fields - {None, "id", "from_entry", "when", "comment"}:
                continue
            if sum(keyword(parts, s)[0] is None for s in args) > 2:
                continue
            has_call = any("(" in keyword(parts, span)[1] for span in args)
            begin = parts[i].start()
            line_begin = code.rfind("\n", 0, begin) + 1
            line_end = code.find("\n", parts[end].end())
            if line_end < 0:
                line_end = len(code)
            remainder = code[parts[end].end() : line_end].strip()
            if (
                has_call
                or code[line_begin:begin].strip()
                or (remainder and not remainder.startswith("//"))
            ):
                continue
            if not re.search(
                r"(?m)^[ \t]*//[ \t]*@version[ \t]*=[ \t]*[234][ \t]*$", code
            ):
                continue
            value = f"int fmz_legacy_noop_{i} = 0"
            if value.split()[1] in code:
                continue
            changes.append((begin, parts[end].end(), value))
            labels["documented no-op exit"] += 1
            continue
        if "direction" in fields:
            continue
        for number, span in enumerate(args):
            key, body = keyword(parts, span)
            if (key == "long" or (number == 1 and key is None)) and body in (
                ["true"],
                ["false"],
            ):
                value = "strategy.long" if body == ["true"] else "strategy.short"
                if key == "long":
                    value = "direction = " + value
                a, b = span
                changes.append((parts[a].start(), parts[b - 1].end(), value))
                labels["constant legacy direction"] += 1
    for a, b, text in sorted(changes, reverse=True):
        code = code[:a] + text + code[b:]
    return code, labels


def repair(source):
    # Drop the descriptive FMZ archive header early, but retain the original code lines.
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    executable = NO_QUOTED.sub("", code)
    if not re.search(r"(?m)^strategy\s*\(", executable):
        raise MigrationBlocked("No active source strategy declaration")
    if re.search(r"(?m)^\s*strategy\.initial_capital\s*(?::=|=(?!=))", executable):
        raise MigrationBlocked("Source writes a read-only strategy wallet field")
    fixed, count = repair_recursion(code)
    fixed, labels = compiler_rewrites(fixed)
    final, version, transforms = migrate(
        fixed, allow_read_only_legacy=True, resolve_shadowed=True
    )
    if count:
        labels["explicit prior-bar recursive state"] = count
    if not labels and "resolved shadowed builtin" not in transforms:
        raise MigrationBlocked("No independently justified compiler repair identified")
    return final, version, dict(transforms), dict(labels)


def prepare(archive, reference, later, work):
    original = read(ROOT / PREVIOUS)
    targets = {
        i: why
        for i, _, why in original["coverage"]
        if why == RECURSION or why in COMPILER
    }
    windows, metadata = datasets(
        reference, later, [read(ROOT / name) for name in PRIOR], 15 * 60
    )
    entries, coverage = [], []
    with (
        ZipFile(archive) as z,
        (ROOT / "public-strategy-catalogue.csv").open(encoding="utf-8-sig") as stream,
    ):
        for i, row in enumerate(csv.DictReader(stream), 1):
            if i not in targets:
                continue
            path = unquote(row["source_url"].split("/" + FMZ_REF + "/", 1)[1])
            document = z.read("strategies-" + FMZ_REF + "/" + path)
            blocks = source_block(document.decode("utf-8"))
            try:
                if len(blocks) != 1:
                    raise MigrationBlocked("No single Pine strategy in the source")
                code, version, transforms, repairs = repair(blocks[0])
            except (MigrationBlocked, ValueError) as exc:
                coverage.append([i, "FMZ Pine repair pending", str(exc)])
                continue
            archived = re.search(r"(?m)^period:\s*(\S+)", blocks[0])
            entries.append(
                {
                    "id": i,
                    "name": row["name"],
                    "source": row["source_url"],
                    "hash": hashlib.sha256(document).hexdigest(),
                    "archived": archived[1] if archived else "",
                    "code": code,
                    "old_version": version,
                    "transforms": transforms,
                    "repairs": repairs,
                    "migration_sha256": hashlib.sha256(code.encode()).hexdigest(),
                }
            )
    assert len(entries) + len(coverage) == len(targets)
    work.mkdir(parents=True, exist_ok=True)
    write(work / "candidates.json", entries)
    write(work / "screening.json", {"coverage": coverage, "windows": metadata})
    write(work / "candles.json", windows)
    print("Repair candidates", len(entries), "blocked", len(coverage))
    print("Repair counts", Counter(k for x in entries for k in x["repairs"]))
    print("Pending", Counter(x[2] for x in coverage).most_common(16))


def finalize(work, retry, destination):
    report = work / "initial-replay.json"
    finish(work, report)
    if retry:
        retried = retry / "retry-replay.json"
        finish(retry, retried)
        merge_retry(report, retried)
    result = read(report)
    by_id = {x["id"]: x for x in read(work / "candidates.json")}
    for row in result["results"]:
        value = by_id[row["id"]]
        row.update(
            group="FMZ repaired Pine",
            pine_source_version=value["old_version"],
            migration_sha256=value["migration_sha256"],
            transforms=value["transforms"],
            repairs=value["repairs"],
        )
    for coverage in result["coverage"]:
        if coverage[1].startswith("Tested"):
            coverage[1] = (
                "Tested · repaired Pine"
                if "no closes" not in coverage[1]
                else "Tested · repaired, no closes"
            )
            coverage[2] = coverage[2].replace("PineTS", "repaired Pine v5")
        else:
            coverage[1] = "FMZ Pine repair pending"
    result["migration_target"] = "Pine v5"
    write(destination, result)
    print(Counter(x[1] for x in result["coverage"]))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    steps = cli.add_subparsers(dest="action", required=True)
    prep = steps.add_parser("prepare")
    for name in ("archive", "reference", "later", "work"):
        prep.add_argument(name, type=Path)
    done = steps.add_parser("finalize")
    done.add_argument("work", type=Path)
    done.add_argument("destination", type=Path)
    done.add_argument("--retry", type=Path)
    opts = cli.parse_args()
    if opts.action == "prepare":
        prepare(opts.archive, opts.reference, opts.later, opts.work)
    else:
        finalize(opts.work, opts.retry, opts.destination)
