"""Migrate a conservative subset of older Pine source for the offline Delta replay."""

import argparse
import ast
import csv
import hashlib
import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pinets_catalogue import (
    FMZ_REF,
    PRIOR,
    datasets,
    eligibility,
    finish,
    merge_retry,
    read,
    source_block,
    write,
)
from research.delta_strategy_replay import ROOT

PREVIOUS = "delta-pinets-catalogue.json"
OLD_REASON = "Pine 2–4 or unversioned source needs a compatible runtime"
VERSION = re.compile(r"(?m)^[ \t]*//[ \t]*@version[ \t]*=[ \t]*(\d+)[ \t]*$")
TOKENS = re.compile(
    r"""//[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[A-Za-z_]\w*|[^\s]"""
)
NAMESPACE = {
    "ta": {
        "atr",
        "alma",
        "barssince",
        "bb",
        "bbw",
        "cci",
        "change",
        "cmo",
        "correlation",
        "cross",
        "crossover",
        "crossunder",
        "cum",
        "dev",
        "dmi",
        "ema",
        "falling",
        "highest",
        "highestbars",
        "hma",
        "kc",
        "kcw",
        "linreg",
        "lowest",
        "lowestbars",
        "macd",
        "median",
        "mfi",
        "mom",
        "percentile_linear_interpolation",
        "percentile_nearest_rank",
        "percentrank",
        "pivothigh",
        "pivotlow",
        "range",
        "rising",
        "rma",
        "roc",
        "rsi",
        "sar",
        "sma",
        "stdev",
        "stoch",
        "supertrend",
        "swma",
        "tr",
        "tsi",
        "valuewhen",
        "variance",
        "vwap",
        "vwma",
        "wma",
        "wpr",
    },
    "math": {
        "abs",
        "acos",
        "asin",
        "atan",
        "avg",
        "ceil",
        "cos",
        "exp",
        "floor",
        "log",
        "log10",
        "max",
        "min",
        "pow",
        "random",
        "round",
        "sign",
        "sin",
        "sqrt",
        "sum",
        "tan",
        "todegrees",
        "toradians",
    },
    "str": {"tostring", "tonumber"},
}
PREFIXES = {name: namespace for namespace, names in NAMESPACE.items() for name in names}
COLORS = {
    "aqua",
    "black",
    "blue",
    "fuchsia",
    "gray",
    "green",
    "lime",
    "maroon",
    "navy",
    "olive",
    "orange",
    "purple",
    "red",
    "silver",
    "teal",
    "white",
    "yellow",
}
PLOT_STYLES = {
    "plot": {
        "line",
        "linebr",
        "stepline",
        "histogram",
        "cross",
        "area",
        "areabr",
        "circles",
        "columns",
    },
    "plotshape": {
        "xcross",
        "cross",
        "triangleup",
        "triangledown",
        "flag",
        "circle",
        "arrowup",
        "arrowdown",
        "labelup",
        "labeldown",
        "square",
        "diamond",
    },
}
SRC = {"open", "high", "low", "close", "hl2", "hlc3", "ohlc4", "hlcc4", "volume"}
INPUT_TYPES = {
    "integer": "int",
    "float": "float",
    "bool": "bool",
    "string": "string",
    "source": "source",
    "color": "color",
    "resolution": "timeframe",
    "session": "session",
    "time": "time",
}
RESERVED_V5 = {
    "catch",
    "class",
    "do",
    "ellipse",
    "in",
    "is",
    "polygon",
    "return",
    "range",
    "struct",
    "text",
    "throw",
    "try",
}
PURE_CALLS = {
    "nz",
    "na",
    "abs",
    "ceil",
    "floor",
    "round",
    "max",
    "min",
    "sign",
    "sqrt",
    "pow",
    "exp",
    "log",
    "log10",
}
READ_ONLY_REASON = "Legacy iff/offset evaluation requires a verified rewrite"


class MigrationBlocked(ValueError):
    """An automatic source transform would change or guess semantics."""


def tokens(code):
    return [x for x in TOKENS.finditer(code) if not x.group().startswith("//")]


def arguments(parts, opening):
    """Return the closing token and the spans of top-level arguments."""
    depth, start, args = 1, opening + 1, []
    for index in range(start, len(parts)):
        value = parts[index].group()
        if value in {"(", "["}:
            depth += 1
        elif value in {")", "]"}:
            depth -= 1
            if not depth:
                if start < index:
                    args.append((start, index))
                return index, args
        elif depth == 1 and value == ",":
            args.append((start, index))
            start = index + 1
    raise MigrationBlocked("Unbalanced legacy function call")


def values(parts, span):
    return [node.group() for node in parts[slice(*span)]]


def keyword(parts, span):
    nodes = values(parts, span)
    if len(nodes) >= 3 and nodes[1] == "=" and nodes[2] != "=":
        return nodes[0], nodes[2:]
    return None, nodes


def rewrite_read_only_legacy(code):
    changes = Counter()
    while True:
        parts = tokens(code)
        possible = [
            i
            for i, node in enumerate(parts[:-1])
            if node.group() in {"iff", "offset"}
            and parts[i + 1].group() == "("
            and not (i and parts[i - 1].group() == ".")
        ]
        if not possible:
            return code, changes
        # Rewrite innermost calls first so nested ternaries remain plain reads.
        index = possible[-1]
        name = parts[index].group()
        end, spans = arguments(parts, index + 1)
        text = [code[parts[a].start() : parts[b - 1].end()] for a, b in spans if a < b]
        if name == "offset":
            if (
                len(text) != 2
                or not re.fullmatch(r"[A-Za-z_]\w*", text[0])
                or not re.fullmatch(r"\d+", text[1])
            ):
                raise MigrationBlocked(
                    "Offset requires a named series and literal nonnegative history"
                )
            replacement = f"{text[0]}[{text[1]}]"
        else:
            if len(text) != 3:
                raise MigrationBlocked("Legacy iff expects exactly three arguments")
            for branch in text[1:]:
                if set(re.findall(r"\b([A-Za-z_]\w*)\s*\(", branch)) - PURE_CALLS:
                    raise MigrationBlocked(
                        "Eager iff branch contains a stateful or unsupported call"
                    )
            replacement = f"(({text[0]}) ? ({text[1]}) : ({text[2]}))"
        changes["read-only " + name] += 1
        code = code[: parts[index].start()] + replacement + code[parts[end].end() :]


def legacy_int(nodes, local_ints):
    return (
        bool(nodes)
        and len(nodes) == 1
        and (nodes[0].isdigit() and int(nodes[0]) > 0 or nodes[0] in local_ints)
    )


def local_declarations(code):
    declared = set(
        re.findall(
            r"(?m)^\s*(?:(?:var|varip)\s+)?(?:(?:float|int|bool|color|string)\s+)?([A-Za-z_]\w*)\s*(?::=|=(?!=|>))",
            code,
        )
    )
    for line in code.splitlines():
        if match := re.match(r"^\s*\w+\s*\((.*?)\)\s*=>", line):
            declared.update(re.findall(r"\b[A-Za-z_]\w*\b", match[1]))
    return declared


def safe_input(parts, opening):
    end, args = arguments(parts, opening)
    defaults, fields = None, {}
    for index, span in enumerate(args):
        name, data = keyword(parts, span)
        if name:
            if name in fields:
                raise MigrationBlocked("Duplicate legacy input field")
            fields[name] = (span, data)
            if name == "defval":
                defaults = data
        elif index == 0:
            defaults = data
        elif index >= 2:
            raise MigrationBlocked(
                "Positional legacy input options require a verified rewrite"
            )
    if not defaults:
        raise MigrationBlocked("Legacy input default is unclear")
    patches = []
    if "type" in fields:
        span, kind = fields["type"]
        if len(kind) != 3 or kind[0:2] != ["input", "."] or kind[2] not in INPUT_TYPES:
            raise MigrationBlocked("Unsupported legacy input type")
        variant = INPUT_TYPES[kind[2]]
        begin, stop = span
        if stop < end and parts[stop].group() == ",":
            patches.append((parts[begin].start(), parts[stop].end(), ""))
        elif parts[begin - 1].group() == ",":
            patches.append((parts[begin - 1].start(), parts[stop - 1].end(), ""))
        else:
            raise MigrationBlocked("Cannot remove legacy input type safely")
    else:
        first = "".join(defaults)
        if len(defaults) == 1 and first in SRC:
            variant = "source"
        elif first in ("true", "false"):
            variant = "bool"
        else:
            try:
                default = ast.literal_eval(first)
            except (SyntaxError, ValueError):
                default = None
            variant = (
                "int"
                if type(default) is int
                else "float"
                if type(default) is float
                else "string"
                if isinstance(default, str)
                else None
            )
        if variant is None and set(fields) & {"minval", "maxval", "step", "options"}:
            raise MigrationBlocked("Constrained input has an unverified inferred type")
    return variant, patches


def migrate(source, *, allow_read_only_legacy=False, resolve_shadowed=False):
    version = VERSION.search(source)
    if not version or version[1] not in {"2", "3", "4"}:
        raise MigrationBlocked("Unversioned source or unsupported source version")
    old = int(version[1])
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    code = VERSION.sub("//@version=5", code, count=1).strip()
    problem = eligibility(code)
    if problem:
        raise MigrationBlocked(problem)
    declaration_check = re.sub(
        r"""//[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'""", "", code
    )
    if re.search(
        r"\b(?:timenow|isrealtime|islastconfirmedhistory|heikinashi|renko|kagi|linebreak|pointfigure|random)\b|\[\s*-\d",
        declaration_check,
    ):
        raise MigrationBlocked("Wall-clock, future or synthetic-chart dependency")
    if re.search(
        r"\b(?:time|time_close)\s*\([^\n]*,", declaration_check
    ) and not re.search(r":(?:1234567|23456)\b", code):
        raise MigrationBlocked("Pine v5 session day defaults differ")
    declared = local_declarations(declaration_check)
    functions = set(re.findall(r"(?m)^\s*(\w+)\s*\([^)]*\)\s*=>", declaration_check))
    if declared & RESERVED_V5:
        raise MigrationBlocked("Legacy identifier is reserved in Pine v5")
    if declared & {"ta", "math", "str", "color", "shape", "input"}:
        raise MigrationBlocked("Legacy local identifier shadows a migration namespace")
    if old == 2:
        for name, rhs in re.findall(
            r"(?m)^\s*([A-Za-z_]\w*)\s*=(?!=)(.+)$", declaration_check
        ):
            if re.search(r"\b" + re.escape(name) + r"\s*\[", rhs):
                raise MigrationBlocked(
                    "Pine v2 implicit recursive series needs explicit state verification"
                )
    if re.search(r"\b(?:iff|offset|rsi)\s*=>", declaration_check) or (
        allow_read_only_legacy and declared & {"iff", "offset"}
    ):
        raise MigrationBlocked("Legacy callable shadowing requires manual review")
    read_only = Counter()
    if allow_read_only_legacy:
        code, read_only = rewrite_read_only_legacy(code)
    parts = tokens(code)
    patches, renamed, int_inputs = [], read_only, set()
    # Static numeric declarations and explicit integer input defaults are sufficient for legacy RSI.
    int_inputs.update(
        re.findall(r"(?m)^\s*(\w+)\s*=\s*[1-9][0-9]*\s*$", declaration_check)
    )
    for i, node in enumerate(parts):
        if (
            node.group() != "input"
            or i + 1 >= len(parts)
            or parts[i + 1].group() != "("
        ):
            continue
        previous = parts[i - 1].group() if i else ""
        if previous == "." or "input" in declared:
            continue
        mode, extras = safe_input(parts, i + 1)
        patches.extend(extras)
        if mode:
            patches.append((node.start(), node.end(), f"input.{mode}"))
            renamed[f"input.{mode}"] += 1
            if (
                mode == "int"
                and i >= 2
                and parts[i - 1].group() == "="
                and re.fullmatch(r"\w+", parts[i - 2].group())
            ):
                int_inputs.add(parts[i - 2].group())
    int_inputs.difference_update(re.findall(r"(?m)\b(\w+)\s*:=", declaration_check))
    for i, node in enumerate(parts):
        key = node.group()
        previous = parts[i - 1].group() if i else ""
        following = parts[i + 1].group() if i + 1 < len(parts) else ""
        shadowed_builtin = (
            resolve_shadowed
            and key in declared
            and key in PREFIXES
            and following == "("
            and key not in functions
        )
        if (key in declared and not shadowed_builtin) or previous == ".":
            continue
        if key in {"iff", "offset"} and following == "(":
            raise MigrationBlocked(READ_ONLY_REASON)
        if key == "rsi" and following == "(":
            _, args = arguments(parts, i + 1)
            if len(args) != 2 or not legacy_int(values(parts, args[1]), int_inputs):
                raise MigrationBlocked(
                    "Cannot rule out the removed overloaded RSI formula"
                )
        if key in PREFIXES and following == "(":
            patches.append((node.start(), node.end(), f"{PREFIXES[key]}.{key}"))
            renamed[PREFIXES[key]] += 1
            if shadowed_builtin:
                renamed["resolved shadowed builtin"] += 1
        elif key == "tr" and following != "=":
            patches.append((node.start(), node.end(), "ta.tr"))
            renamed["ta"] += 1
        elif key in COLORS and following not in ("=", "("):
            patches.append((node.start(), node.end(), f"color.{key}"))
            renamed["color"] += 1
        elif key in ("plot", "plotshape") and following == "(":
            _, args = arguments(parts, i + 1)
            for span in args:
                name, body = keyword(parts, span)
                if name == "style" and len(body) == 1 and body[0] in PLOT_STYLES[key]:
                    target = parts[span[0] + 2]
                    prefix = "plot.style_" if key == "plot" else "shape."
                    patches.append(
                        (target.start(), target.end(), prefix + target.group())
                    )
                    renamed["plot style"] += 1
    out = code
    end = len(code)
    for a, b, replacement in sorted(set(patches), reverse=True):
        if b > end:
            raise MigrationBlocked("Overlapping legacy source conversions")
        out = out[:a] + replacement + out[b:]
        end = a
    problem = eligibility(out)
    if problem:
        raise MigrationBlocked(problem)
    return out, old, dict(renamed)


def prepare(
    archive, reference, later, work, *, expand_read_only=False, recover_from=None
):
    original = read(ROOT / PREVIOUS)
    pending = {i for i, _, why in original["coverage"] if why == OLD_REASON}
    recovery = (
        {}
        if recover_from is None
        else {
            i: reason
            for i, _, reason in read(recover_from)["coverage"]
            if reason == "PineTS could not compile or execute this source"
            or reason == "PineTS lacks an indicator or namespace used by this source"
        }
    )
    if recover_from is not None:
        pending &= recovery.keys()
    windows, metadata = datasets(
        reference, later, [read(ROOT / name) for name in PRIOR], 15 * 60
    )
    entries, coverage = [], []
    with (
        ZipFile(archive) as z,
        (ROOT / "public-strategy-catalogue.csv").open(encoding="utf-8-sig") as stream,
    ):
        for i, row in enumerate(csv.DictReader(stream), 1):
            if i not in pending:
                continue
            path = unquote(row["source_url"].split("/" + FMZ_REF + "/", 1)[1])
            document = z.read("strategies-" + FMZ_REF + "/" + path)
            blocks = source_block(document.decode("utf-8"))
            try:
                if len(blocks) != 1:
                    raise MigrationBlocked("No single Pine strategy in the source")
                if recover_from is not None:
                    try:
                        code, version, changes = migrate(
                            blocks[0], resolve_shadowed=True
                        )
                    except MigrationBlocked as exc:
                        if str(exc) != READ_ONLY_REASON:
                            continue
                        code, version, changes = migrate(
                            blocks[0],
                            allow_read_only_legacy=True,
                            resolve_shadowed=True,
                        )
                    if "resolved shadowed builtin" not in changes:
                        continue
                elif expand_read_only:
                    try:
                        migrate(blocks[0])
                    except MigrationBlocked as exc:
                        if str(exc) != READ_ONLY_REASON:
                            continue
                    else:
                        continue
                if recover_from is None:
                    code, version, changes = migrate(
                        blocks[0], allow_read_only_legacy=expand_read_only
                    )
            except MigrationBlocked as exc:
                if recover_from is not None:
                    continue
                if expand_read_only and (len(blocks) != 1):
                    continue
                coverage.append([i, "FMZ Pine migration pending", str(exc)])
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
                    "transforms": changes,
                    "migration_sha256": hashlib.sha256(code.encode()).hexdigest(),
                }
            )
    if not expand_read_only and recover_from is None:
        assert len(entries) + len(coverage) == len(pending)
    work.mkdir(parents=True, exist_ok=True)
    write(work / "candidates.json", entries)
    write(work / "screening.json", {"coverage": coverage, "windows": metadata})
    write(work / "candles.json", windows)
    print(
        "Migratable candidates",
        len(entries),
        Counter(x["old_version"] for x in entries),
    )
    print("Other sources", Counter(x[2] for x in coverage).most_common(16))


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
            group="FMZ migrated Pine",
            pine_source_version=value["old_version"],
            migration_sha256=value["migration_sha256"],
            transforms=value["transforms"],
        )
    for coverage in result["coverage"]:
        if coverage[1].startswith("Tested"):
            coverage[1] = (
                "Tested · migrated Pine"
                if "no closes" not in coverage[1]
                else "Tested · migrated, no closes"
            )
            coverage[2] = coverage[2].replace("PineTS", "Pine v5 migration")
        else:
            coverage[1] = "FMZ Pine migration pending"
    result["migration_target"] = "Pine v5"
    write(destination, result)
    print(Counter(x[1] for x in result["coverage"]))


def merge_read_only(primary, extension):
    result, extra = read(primary), read(extension)
    coverage = {x[0]: x for x in result["coverage"]}
    for row in extra["coverage"]:
        assert coverage[row[0]][2] == READ_ONLY_REASON
        coverage[row[0]] = row
    result["coverage"] = sorted(coverage.values())
    result["results"].extend(extra["results"])
    result["results"].sort(key=lambda row: (row["id"], row["period"], row["market"]))
    result["read_only_followup"] = {
        "checked": len(extra["coverage"]),
        "replayed": len(extra["results"]) // 6,
    }
    write(primary, result)
    print(Counter(x[1] for x in result["coverage"]))


def merge_recovered(primary, extension):
    result, extra = read(primary), read(extension)
    coverage = {x[0]: x for x in result["coverage"]}
    for row in extra["coverage"]:
        assert coverage[row[0]][2] in {
            "PineTS could not compile or execute this source",
            "PineTS lacks an indicator or namespace used by this source",
        }
        coverage[row[0]] = row
    result["coverage"] = sorted(coverage.values())
    result["results"].extend(extra["results"])
    result["results"].sort(key=lambda row: (row["id"], row["period"], row["market"]))
    result["shadowed_builtin_followup"] = {
        "checked": len(extra["coverage"]),
        "replayed": len(extra["results"]) // 6,
    }
    write(primary, result)
    print(Counter(x[1] for x in result["coverage"]))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    steps = cli.add_subparsers(dest="action", required=True)
    prep = steps.add_parser("prepare")
    for name in ("archive", "reference", "later", "work"):
        prep.add_argument(name, type=Path)
    prep.add_argument("--expand-read-only", action="store_true")
    prep.add_argument("--recover-from", type=Path)
    done = steps.add_parser("finalize")
    done.add_argument("work", type=Path)
    done.add_argument("destination", type=Path)
    done.add_argument("--retry", type=Path)
    merge = steps.add_parser("merge-read-only")
    merge.add_argument("primary", type=Path)
    merge.add_argument("extension", type=Path)
    recovered = steps.add_parser("merge-recovered")
    recovered.add_argument("primary", type=Path)
    recovered.add_argument("extension", type=Path)
    opts = cli.parse_args()
    if opts.action == "prepare":
        prepare(
            opts.archive,
            opts.reference,
            opts.later,
            opts.work,
            expand_read_only=opts.expand_read_only,
            recover_from=opts.recover_from,
        )
    elif opts.action == "finalize":
        finalize(opts.work, opts.retry, opts.destination)
    elif opts.action == "merge-read-only":
        merge_read_only(opts.primary, opts.extension)
    else:
        merge_recovered(opts.primary, opts.extension)
