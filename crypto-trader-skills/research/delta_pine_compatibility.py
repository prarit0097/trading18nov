"""Replay FMZ Pine sources with documented, narrow compatibility changes."""

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pine_followup import followup, patch, records_from, retry
from research.delta_pine_repair import NO_QUOTED
from research.delta_pinets_catalogue import (
    FMZ_REF,
    PRIOR,
    datasets,
    eligibility,
    read,
    source_block,
    write,
)
from research.delta_pinets_migration import (
    VERSION,
    MigrationBlocked,
    arguments,
    keyword,
    local_declarations,
    safe_input,
    tokens,
)
from research.delta_strategy_replay import ROOT

GROUP = "FMZ Pine compatibility"
PRIORITY = ("external", "source requires tick", "archived", "wall-clock")
TIMEFRAME_SCOPE = {"timeframe.period", '""', "''"}
SESSION_VALUE = re.compile(r"[0-9]{4}-[0-9]{4}(?:,[0-9]{4}-[0-9]{4})*(?::[1-7]+)?")
DECIMAL_LITERAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")
LEGACY_VARIABLES = {"accdist", "iii", "nvi", "obv", "pvi", "pvt", "vwap", "wad", "wvad"}
PINE_COMMENTS_AND_STRINGS = re.compile(
    r"""//[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|(?P<block>/\*.*?\*/)""",
    re.DOTALL,
)


def plain_pine(block):
    block = block.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    return PINE_COMMENTS_AND_STRINGS.sub(
        lambda token: "" if token["block"] else token[0], block
    )


def shell(code):
    executable = NO_QUOTED.sub("", code)
    if re.search(r"(?m)^strategy\s*\(", executable):
        return code, {}
    if re.search(r"(?m)^\s*(?:strategy|study|indicator|library)\s*\(", executable):
        raise MigrationBlocked(
            "Source has a conflicting or non-top-level Pine declaration"
        )
    if not re.search(r"\bstrategy\.(?:entry|order)\s*\(", executable):
        raise MigrationBlocked("Source has no active strategy entry or order call")
    version = VERSION.search(code)
    if version is None:
        raise MigrationBlocked("Source has no verified version directive")
    # FMZ accepts no declaration. Keep inactive FMZ/TradingView settings inactive.
    adapted = (
        code[: version.end()]
        + '\nstrategy("FMZ archived strategy")'
        + code[version.end() :]
    )
    return adapted, {"FMZ implicit strategy declaration": 1}


def int_length(code, parts, span):
    a, b = span
    value = code[parts[a].start() : parts[b - 1].end()].strip()
    while value.startswith("(") and parts[a].group() == "(":
        end, spans = arguments(parts, a)
        if end != b - 1 or len(spans) != 1:
            break
        a, b = spans[0]
        value = code[parts[a].start() : parts[b - 1].end()].strip()
    if re.fullmatch(r"[1-9][0-9]*", value):
        return True
    if b - a < 3 or parts[a].group() != "input":
        return False
    if [x.group() for x in parts[a + 1 : a + 4]] == [".", "int", "("]:
        opening = a + 3
        kind = "int"
    elif parts[a + 1].group() == "(":
        opening = a + 1
        kind = None
    else:
        return False
    try:
        end, _ = arguments(parts, opening)
        if kind is None:
            kind, _ = safe_input(parts, opening)
    except MigrationBlocked:
        return False
    return end == b - 1 and kind == "int"


def global_integer_bindings(code, parts):
    assignments = {}
    level = 0
    for i, node in enumerate(parts[:-2]):
        token = node.group()
        if token in ("(", "["):
            level += 1
        elif token in (")", "]"):
            level -= 1
        if (
            level
            or not re.fullmatch(r"[A-Za-z_]\w*", token)
            or parts[i + 1].group() != "="
        ):
            continue
        prefix = code[code.rfind("\n", 0, node.start()) + 1 : node.start()]
        if prefix.strip() and (
            prefix[:1].isspace() or not prefix.rstrip().endswith(",")
        ):
            continue
        if not prefix.strip() and prefix:
            continue
        start, end = i + 2, i + 2
        line_end = code.find("\n", node.end())
        line_end = len(code) if line_end < 0 else line_end
        while (
            end < len(parts)
            and parts[end].start() < line_end
            and parts[end].group() != ","
        ):
            if parts[end].group() in {"(", "["}:
                end, _ = arguments(parts, end)
            end += 1
        if start == end:
            continue
        assignments[token] = assignments.get(token, []) + [
            int_length(code, parts, (start, end))
        ]
    return {name for name, probes in assignments.items() if probes == [True]}


def rsi_calls(code):
    executable = NO_QUOTED.sub("", code)
    if re.search(r"(?m)^\s*(?:rsi|input)\s*\([^)]*\)\s*=>", executable):
        return code, 0
    parts = tokens(code)
    lengths = global_integer_bindings(code, parts)
    lengths.difference_update(re.findall(r"\b(\w+)\s*:=", executable))
    lengths.difference_update(re.findall(r"(?m)^[ \t]+(\w+)\s*=(?!=|>)", executable))
    for params in re.findall(r"(?m)^\s*\w+\s*\(([^)]*)\)\s*=>", executable):
        lengths.difference_update(re.findall(r"\b[A-Za-z_]\w*\b", params))
    changes = []
    for i, node in enumerate(parts[:-1]):
        if (
            node.group() != "rsi"
            or parts[i + 1].group() != "("
            or (i and parts[i - 1].group() == ".")
        ):
            continue
        _, args = arguments(parts, i + 1)
        if len(args) != 2:
            continue
        a, b = args[1]
        if keyword(parts, args[1])[0] == "length":
            a += 2
        if (b - a == 1 and parts[a].group() in lengths) or int_length(
            code, parts, (a, b)
        ):
            changes.append((node.start(), node.end(), "ta.rsi"))
    return patch(code, changes), len(changes)


def session_calls(code):
    """Keep TradingView legacy weekdays for session opens on the chart interval."""
    parts = tokens(code)
    changes = []
    use_helper = False
    for i, node in enumerate(parts[:-1]):
        if (
            node.group() not in {"time", "time_close"}
            or parts[i + 1].group() != "("
            or (i and parts[i - 1].group() == ".")
        ):
            continue
        end, args = arguments(parts, i + 1)
        if len(args) <= 1:
            continue
        if [t.group() for t in parts[end + 1 : end + 3]] == ["=", ">"]:
            raise MigrationBlocked(
                "Source defines a function named like a session built-in"
            )
        parsed_args = [keyword(parts, arg) for arg in args]
        fields = {
            name: index
            for index, (name, _) in enumerate(parsed_args)
            if name is not None
        }
        timeframe = fields.get("timeframe", 0)
        session = fields.get("session", 1)
        tf = "".join(parsed_args[timeframe][1])
        if node.group() == "time_close" or tf not in TIMEFRAME_SCOPE:
            raise MigrationBlocked(
                "Legacy session needs verified non-chart-timeframe or close-time semantics"
            )
        key, _ = parsed_args[session]
        if key not in {None, "session"}:
            raise MigrationBlocked("Legacy session argument binding is ambiguous")
        a, b = args[session]
        a += 2 if key else 0
        start, stop = parts[a].start(), parts[b - 1].end()
        value = code[start:stop]
        if value in {'""', "''", '"24x7"', "'24x7'"}:
            continue
        if value[0] in {"'", '"'} and value[-1] == value[0]:
            if not SESSION_VALUE.fullmatch(value[1:-1]):
                raise MigrationBlocked(
                    "Source has an unsupported legacy session literal"
                )
            if ":" in value:
                continue
            replacement = value[:-1] + ":23456" + value[-1]
        else:
            if not re.fullmatch(r"[A-Za-z_]\w*", value):
                raise MigrationBlocked(
                    "Legacy session is computed by an unsupported expression"
                )
            use_helper = True
            replacement = f"fmz_legacy_session({value})"
        changes.append((start, stop, replacement))
    if use_helper:
        if re.search(r"\bfmz_legacy_session\b", code):
            raise MigrationBlocked(
                "Legacy session compatibility name collides with source"
            )
        version = VERSION.search(code)
        changes.append(
            (
                version.end(),
                version.end(),
                (
                    '\nfmz_legacy_session(string spec) => spec == "" or spec == "24x7" or '
                    'str.contains(spec, ":") ? spec : spec + ":23456"'
                ),
            )
        )
    return patch(code, changes), len(changes) - use_helper


def fixed_default_inputs(code):
    """Retain valid integer defaults and the exact set of admissible integers."""
    parts = tokens(code)
    changes = []
    for i in range(len(parts) - 4):
        if [x.group() for x in parts[i : i + 4]] != ["input", ".", "int", "("]:
            continue
        close, spans = arguments(parts, i + 3)
        fields = []
        for a, b in spans:
            key, _ = keyword(parts, (a, b))
            start = parts[a + 2 if key else a].start()
            fields.append((key, code[start : parts[b - 1].end()]))
        named = {key: value for key, value in fields if key}
        if (
            not fields
            or len(named) != sum(key is not None for key, _ in fields)
            or "options" in named
            or any(key is None for key, _ in fields[2:])
            or (fields[0][0] is None and "defval" in named)
        ):
            continue
        default = named.get("defval", fields[0][1] if fields[0][0] is None else "")
        if not re.fullmatch(r"[+-]?[0-9]+", default):
            continue
        numeric = {
            key: named[key] for key in ("minval", "maxval", "step") if key in named
        }
        if not all(DECIMAL_LITERAL.fullmatch(v) for v in numeric.values()):
            continue
        numeric = {key: Decimal(value) for key, value in numeric.items()}
        if (
            "minval" in numeric
            and int(default) < numeric["minval"]
            or "maxval" in numeric
            and int(default) > numeric["maxval"]
            or "step" in numeric
            and numeric["step"] <= 0
        ):
            continue
        updated = []
        for key, value in fields:
            if key in numeric and "." in value:
                number = numeric[key]
                if key == "step" and number != number.to_integral_value():
                    continue  # The widget step does not affect the pinned default.
                rounding = ROUND_CEILING if key == "minval" else ROUND_FLOOR
                value = str(int(number.to_integral_value(rounding=rounding)))
            updated.append((key, value))
        if updated != fields:
            text = ", ".join(
                value if key is None else f"{key} = {value}" for key, value in updated
            )
            changes.append((parts[i + 3].end(), parts[close].start(), text))
    return patch(code, changes), len(changes)


def namespace_rewrites(code):
    executable = NO_QUOTED.sub("", code)
    shadowed = local_declarations(executable)
    shadowed.update(re.findall(r"(?m)^\s*(\w+)\s*\([^)]*\)\s*=>", executable))
    parts = tokens(code)
    changes = []
    for i, node in enumerate(parts[:-1]):
        name, suffix = node.group(), parts[i + 1].group()
        if name in shadowed or (i and parts[i - 1].group() == ".") or suffix == "=":
            continue
        if name in LEGACY_VARIABLES and suffix != "(":
            changes.append((node.start(), node.end(), "ta." + name))
        elif name == "round_to_mintick" and suffix == "(":
            changes.append((node.start(), node.end(), "math." + name))
    return patch(code, changes), len(changes)


def recheck(block, *, isolated_literals=False):
    code = plain_pine(block)
    original_version = VERSION.search(block)
    normalized = VERSION.search(code)
    labels = Counter()
    if not normalized:
        if re.search(r"(?m)//\s*@version\b", code):
            raise MigrationBlocked(
                "Source version directive appears outside a standalone line"
            )
        code = "//@version=5\n" + code
        labels["FMZ documented default Pine v5"] += 1
        normalized = VERSION.search(code)
    elif not original_version:
        labels["Source version line-ending normalization"] += 1
    code, declaration = shell(code)
    labels.update(declaration)
    version = int(normalized[1])
    if version in {2, 3, 4}:
        code, count = namespace_rewrites(code)
        if count:
            labels["Documented legacy builtin namespace"] += count
        code, count = session_calls(code)
        if count:
            labels["Legacy weekday session default"] += count
        code, count = rsi_calls(code)
        if count:
            labels["Proven classic RSI integer length"] += count
        code, _, transforms, repairs = followup(
            code, isolated_literals=isolated_literals
        )
        labels.update(repairs)
        code, count = fixed_default_inputs(code)
        if count:
            labels["Fixed-default legacy integer input constraints"] += count
    elif version in {5, 6}:
        transforms = {}
        if why := eligibility(code, isolated_literals=isolated_literals):
            raise MigrationBlocked(why)
    else:
        raise MigrationBlocked(f"Explicit Pine v{version} needs a verified migration")
    return code, version, transforms, dict(labels)


def targets():
    return {
        i: why
        for i, status, why in read(ROOT / "delta-pine-followup.json")["coverage"]
        if "pending" in status
        and not why.lower().startswith(PRIORITY)
        and "untraded" not in why.lower()
    }


def prepare(archive, reference, later, work):
    prior = targets()
    coverage, entries = [], []
    with (
        ZipFile(archive) as source,
        (ROOT / "public-strategy-catalogue.csv").open(encoding="utf-8-sig") as handle,
    ):
        for i, row in enumerate(csv.DictReader(handle), 1):
            if i not in prior:
                continue
            path = unquote(row["source_url"].split("/" + FMZ_REF + "/", 1)[1])
            document = source.read("strategies-" + FMZ_REF + "/" + path)
            blocks = source_block(document.decode("utf-8"))
            try:
                if len(blocks) != 1:
                    raise MigrationBlocked(
                        "No single archived Pine code block with an order call"
                    )
                code, version, transforms, repairs = recheck(blocks[0])
            except (MigrationBlocked, ValueError) as exc:
                coverage.append([i, GROUP + " pending", str(exc)])
                continue
            archived = re.search(r"(?m)^period:\s*(\S+)", blocks[0])
            entries.append(
                {
                    "id": i,
                    "name": row["name"],
                    "source": row["source_url"],
                    "hash": hashlib.sha256(document).hexdigest(),
                    "archived": archived[1] if archived else "",
                    "old_version": version,
                    "code": code,
                    "transforms": transforms,
                    "repairs": repairs,
                    "migration_sha256": hashlib.sha256(code.encode()).hexdigest(),
                }
            )
    assert len(coverage) + len(entries) == len(prior)
    folder = work / "15"
    folder.mkdir(parents=True, exist_ok=True)
    candles, windows = datasets(reference, later, [read(ROOT / f) for f in PRIOR], 900)
    write(folder / "candidates.json", entries)
    write(folder / "candles.json", candles)
    write(work / "batches.json", {"coverage": coverage, "windows": {"15": windows}})
    print(f"{len(entries)} runnable, {len(coverage)} blocked")
    print(Counter(x[2] for x in coverage).most_common())


def finalize(work, destination, compiler_diagnostics=None):
    manifest = read(work / "batches.json")
    coverage, rows = list(manifest["coverage"]), []
    tried = defaultdict(list)
    diagnostics = {}
    if compiler_diagnostics:
        diagnostics.update(
            json.loads(line)
            for line in compiler_diagnostics.read_text(
                encoding="utf-8-sig"
            ).splitlines()
        )
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
            attempt = {"interval": interval + "m"}
            if "reason" in record:
                attempt["reason"] = record["reason"]
                detail = diagnostics.get(i) or record.get("detail")
                if detail and detail != record["reason"]:
                    attempt["engine_detail"] = detail
            else:
                attempt["result_rows"] = len(record["results"])
            tried[i].append(attempt)
            if interval == "15" and i in retried:
                assert record["reason"] == "Broker used an untraded candle"
                continue
            if "reason" in record:
                prefix = "15m: untraded fill. " if interval == "30" else ""
                coverage.append(
                    [i, GROUP + " pending", f"{prefix}{interval}m: {record['reason']}"]
                )
                continue
            item = candidates[i]
            values = record["results"]
            assert (
                len(values) == 6
                and len({(r["period"], r["market"]) for r in values}) == 6
            )
            for row in values:
                assert (
                    row["id"] == i
                    and row["interval"] == interval + "m"
                    and row["source_sha256"] == item["hash"]
                )
                row.update(
                    group=GROUP,
                    pine_source_version=item["old_version"],
                    migration_sha256=item["migration_sha256"],
                    transforms=item["transforms"],
                    repairs=item["repairs"],
                )
            rows.extend(values)
            status = "Tested · Pine compatibility"
            if not any(x["trades"] for x in values):
                status += ", no closes"
            reason = (
                ", ".join(item["repairs"] or item["transforms"]) or "unmodified source"
            )
            coverage.append([i, status, f"{interval}m PineTS replay. {reason}"])
    prior = targets()
    assert len(coverage) == len(prior) and {x[0] for x in coverage} == prior.keys()
    attempts = [
        {
            "id": i,
            "previous_reason": prior[i],
            "status": status,
            "reason": reason,
            "runs": tried.get(i, []),
        }
        for i, status, reason in sorted(coverage)
    ]
    write(
        destination,
        {
            "engine": "PineTS 0.13.1",
            "source_revision": FMZ_REF,
            "windows_by_minutes": manifest["windows"],
            "coverage": sorted(coverage),
            "attempts": attempts,
            "results": rows,
        },
    )
    print(Counter(x[1] for x in coverage), "result rows", len(rows))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for action in ("prepare", "retry"):
        stage = sub.add_parser(action)
        for key in (("archive",) if action == "prepare" else ()) + (
            "reference",
            "later",
            "work",
        ):
            stage.add_argument(key, type=Path)
    done = sub.add_parser("finalize")
    for key in ("work", "destination"):
        done.add_argument(key, type=Path)
    done.add_argument("--compiler-diagnostics", type=Path)
    options = parser.parse_args()
    params = vars(options)
    command = params.pop("command")
    {"prepare": prepare, "retry": retry, "finalize": finalize}[command](**params)
