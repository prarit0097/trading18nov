"""Retry locally evaluable FMZ Pine strategies from the remaining-coverage checkpoint."""

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pine_compatibility import fixed_default_inputs, plain_pine, recheck
from research.delta_pine_followup import eager_iff, fix_inputs, patch, rename_global
from research.delta_pine_liquid_replay import (
    MARKETS,
    POOLED,
    archived_candles,
    checksum,
    prepare_candles,
)
from research.delta_pine_repair import NO_QUOTED
from research.delta_pinets_catalogue import (
    EXTERNAL,
    FMZ_REF,
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
    rewrite_read_only_legacy,
    safe_input,
    tokens,
)
from research.delta_strategy_replay import ROOT
from research.fmz_marketdata_replay import EXTRA_UNSUPPORTED, historical_tick_setting

GROUP = "FMZ Pine · Binance compatibility"
CHART_ARGS = {"resolution", "timeframe", "resolution_gaps", "timeframe_gaps"}
COMMON_ARGS = {
    "title",
    "shorttitle",
    "overlay",
    "format",
    "precision",
    "scale",
    "max_bars_back",
    "explicit_plot_zorder",
    "max_lines_count",
    "max_labels_count",
    "max_boxes_count",
    "calc_bars_count",
    "max_polylines_count",
    "dynamic_requests",
    "behind_chart",
}
BLOCKS = re.compile(r"(?ms)^\x60{3}[^\n]*\n(.*?)^\x60{3}")
ACTIVE_ORDER = re.compile(r"\bstrategy\s*\.\s*(?:entry|order)\s*\(")
SESSION = re.compile(r"\btime(?:_close)?\s*\([^\n]*,")
DECLARATIONS = re.compile(r"(?m)^(study|indicator|strategy|library)[ \t]*\(")
SWITCH = re.compile(r"(?m)^\w+[ \t]*=[ \t]*switch[ \t]+[A-Za-z_][\w.]*[ \t]*$")
SWITCH_CASE = re.compile(
    r"""^ {4}(?:(?:"[^"\n]*"|'[^'\n]*'|-?\d+)[ \t]+)?=>[ \t]+\S.*$"""
)
TIME_LIMIT_MS = 55_000
ISOLATED_LIMIT_MS = 35_000
MAX_LOOPS = 1500
ORDER_BLOCK = {"entry", "order", "exit", "close", "close_all", "cancel", "cancel_all"}
LITERAL_BOUNDARY = "Source outside the isolated Pine runner's supported syntax"


def chart_broker_declaration(code):
    """Adapt one chart-only indicator declaration with existing active orders."""
    masked = NO_QUOTED.sub(lambda m: " " * len(m.group()), code)
    declarations = list(DECLARATIONS.finditer(masked))
    if not declarations:
        return code, 0
    if len(declarations) != 1:
        raise MigrationBlocked(
            "Multiple active declarations require an explicit source selection"
        )
    declaration = declarations[0]
    if declaration[1] == "strategy":
        return code, 0
    if declaration[1] == "library" or not ACTIVE_ORDER.search(masked):
        raise MigrationBlocked("No standalone chart execution with active Pine orders")
    parts = tokens(code)
    start = next(i for i, t in enumerate(parts) if t.start() == declaration.start())
    end, spans = arguments(parts, start + 1)
    keep = []
    named = set()
    positional = (
        "title",
        "shorttitle",
        "overlay",
        "format",
        "precision",
        "scale",
        "max_bars_back",
    )
    for i, (a, b) in enumerate(spans):
        key, values = keyword(parts, (a, b))
        arg = code[parts[a].start() : parts[b - 1].end()]
        if key is None:
            if i >= len(positional) or named:
                raise MigrationBlocked(
                    "Indicator has ambiguous positional declaration settings"
                )
            keep.append(f"{positional[i]} = {arg}")
            continue
        if key in named:
            raise MigrationBlocked("Indicator repeats a declaration argument")
        named.add(key)
        if key in CHART_ARGS:
            if (
                key.endswith("_gaps") and values in (["true"], ["false"])
            ) or values in (['""'], ["''"]):
                continue
            raise MigrationBlocked(
                "Indicator declaration selects another timeframe or gap policy"
            )
        if key not in COMMON_ARGS:
            raise MigrationBlocked(
                "Indicator has declaration settings without a strategy equivalent"
            )
        keep.append(arg)
    if not keep:
        raise MigrationBlocked("Indicator declaration has no settings to preserve")
    # Keep the first arguments in their original compatible positional form.
    for i, (a, b) in enumerate(spans[:3]):
        if not keyword(parts, (a, b))[0]:
            keep[i] = code[parts[a].start() : parts[b - 1].end()]
    out = "strategy(" + ", ".join(keep) + ")"
    return code[: declaration.start()] + out + code[parts[end].end() :], 1


def specialize_inputs(code):
    """Apply documented typed input variants when the archived arguments prove the type."""
    code, normalized = fix_inputs(code)
    executable = NO_QUOTED.sub("", code)
    declared = local_declarations(executable)
    if "input" in declared or re.search(r"(?m)^\s*input\s*\([^)]*\)\s*=>", executable):
        return code, normalized
    parts = tokens(code)
    edits = []
    variants = 0
    for i, token in enumerate(parts[:-1]):
        if (
            token.group() != "input"
            or parts[i + 1].group() != "("
            or (i and parts[i - 1].group() == ".")
        ):
            continue
        _, spans = arguments(parts, i + 1)
        fields = {keyword(parts, span)[0] for span in spans}
        if not (fields & {"type", "minval", "maxval", "step", "options"}):
            continue
        try:
            variant, changes = safe_input(parts, i + 1)
        except MigrationBlocked:
            continue
        if variant:
            edits.extend(changes)
            edits.append((token.start(), token.end(), f"input.{variant}"))
            variants += 1
    return patch(code, edits), variants + normalized


def switch_commas(code):
    """Remove separators only in an unambiguous single-line switch tree."""
    edits = []
    for match in SWITCH.finditer(code):
        begin = match.end() + 1
        lines = []
        for line in code[begin:].splitlines(keepends=True):
            if not line.startswith(" "):
                break
            lines.append(line)
        if len(lines) < 2 or not all(
            SWITCH_CASE.fullmatch(line.strip("\n").rstrip()) for line in lines
        ):
            continue
        if not lines[-1].startswith("    =>") or lines[-1].rstrip().endswith(","):
            continue
        for line in lines[:-1]:
            if line.rstrip().endswith(","):
                end = begin + len(line.rstrip())
                edits.append((end - 1, end, ""))
            begin += len(line)
    return patch(code, edits), len(edits)


def order_block_indent(code):
    """Normalize a guarded local block made solely of complete order calls."""
    lines = code.splitlines(keepends=True)
    statements = [(i, line) for i, line in enumerate(lines) if tokens(line)]
    changes = 0
    for i, (_, guard) in enumerate(statements[:-1]):
        matched = re.fullmatch(r"( *)(?:else[ \t]+)?if[ \t]+(.+)", guard.rstrip())
        if not matched or len(matched[1]) % 4:
            continue
        guard_tokens = [t.group() for t in tokens(matched[2])]
        if not guard_tokens or guard_tokens[-1] in {
            "and",
            "or",
            "?",
            ":",
            "=",
            "+",
            "-",
            "*",
            "/",
            ",",
        }:
            continue
        if guard_tokens.count("(") != guard_tokens.count(")") or guard_tokens.count(
            "["
        ) != guard_tokens.count("]"):
            continue
        base = len(matched[1])
        width = len(statements[i + 1][1]) - len(statements[i + 1][1].lstrip(" "))
        if width <= base or width == base + 4 or width >= base + 8:
            continue
        accrued = []
        for j, line in statements[i + 1 :]:
            slots = len(line) - len(line.lstrip(" "))
            if slots <= base and not line.startswith("\t"):
                break
            code_parts = tokens(line)
            parts = [t.group() for t in code_parts]
            if (
                slots != width
                or len(parts) < 5
                or parts[:2] != ["strategy", "."]
                or parts[2] not in ORDER_BLOCK
                or parts[3] != "("
            ):
                accrued.clear()
                break
            try:
                end, _ = arguments(code_parts, 3)
            except MigrationBlocked:
                accrued.clear()
                break
            if end != len(parts) - 1:
                accrued.clear()
                break
            accrued.append(j)
        for j in accrued:
            lines[j] = " " * (base + 4) + lines[j][width:]
        changes += len(accrued)
    return "".join(lines), changes


def prepare_source(block, *, isolated_literals=False):
    code = plain_pine(block)
    labels = {}
    for transform, name in (
        (
            chart_broker_declaration,
            "Chart indicator declaration adapted for active archived orders",
        ),
        (switch_commas, "Case separators normalized in flat switch"),
    ):
        code, count = transform(code)
        if count:
            labels[name] = count
    normalized = re.sub(
        r"(?m)^[ \t\u00a0]+", lambda m: m[0].replace("\u00a0", " "), code
    )
    if normalized != code:
        labels["Nonbreaking indentation space normalized"] = 1
        code = normalized
    code, count = order_block_indent(code)
    if count:
        labels["Complete guarded order block indentation normalized"] = count
    code, tick = historical_tick_setting(code)
    if tick:
        labels["Historical bar-close evaluation"] = 1
    declared = VERSION.search(code)
    if not declared or int(declared[1]) >= 5:
        code, count = specialize_inputs(code)
        if count:
            labels["Verified typed input signature"] = count
        code, count = rename_global(code)
        if count:
            labels["Unshadowed reserved name normalized"] = count
        executable = NO_QUOTED.sub("", code)
        if not re.search(r"(?m)^\s*(?:iff|offset)\s*\([^)]*\)\s*=>", executable):
            code, count = eager_iff(code)
            code, rewrites = rewrite_read_only_legacy(code)
            if count or rewrites:
                labels["Legacy read-only Pine calls normalized"] = count + sum(
                    rewrites.values()
                )
    migrated, version, transforms, repairs = recheck(
        code, isolated_literals=isolated_literals
    )
    migrated, count = fixed_default_inputs(migrated)
    if count:
        labels["Fixed-default legacy integer input constraints"] = count
    if why := eligibility(migrated, isolated_literals=isolated_literals):
        raise MigrationBlocked(why)
    return migrated, version, transforms, labels | repairs


def local_blocks(document):
    blocks = source_block(document) or [
        block
        for block in BLOCKS.findall(document)
        if ACTIVE_ORDER.search(NO_QUOTED.sub("", plain_pine(block)))
    ]
    if len(blocks) != 1:
        return []
    masked = NO_QUOTED.sub("", plain_pine(blocks[0]))
    if (
        EXTERNAL.search(masked)
        or EXTRA_UNSUPPORTED.search(masked)
        or SESSION.search(masked)
    ):
        return []
    if re.search(r"\b(?:heikinashi|calc_on_every_history_tick)\b", masked):
        return []
    return blocks


def make_worker(work, time_limit_ms=TIME_LIMIT_MS):
    source = (ROOT / "delta_pinets_worker.mjs").read_text(encoding="utf-8")
    # Only raise resource bounds and retain the original compiler/runtime details.
    substitutions = {
        "const timeLimit = 14_000;": f"const timeLimit = {time_limit_ms};",
        "engine.setMaxLoops(500);": f"engine.setMaxLoops({MAX_LOOPS});",
        "parentPort.postMessage({ id: item.id, reason });": (
            "parentPort.postMessage({ id: item.id, reason, detail: message.slice(0, 350) });"
        ),
    }
    for old, new in substitutions.items():
        assert source.count(old) == 1
        source = source.replace(old, new)
    worker = work / "worker.mjs"
    worker.write_bytes(source.encode())
    return checksum(worker.read_bytes())


def prepare(archive, candle_archive, work, ledger, isolated_literals=False):
    work.mkdir(parents=True, exist_ok=True)
    original = read(ledger)
    coverage, candidates = [], []
    with ZipFile(archive) as source:
        for row in original["disposition"]:
            i, url = row["id"], row["source"]
            if (
                not row["status"].startswith("Pending")
                or "github.com/fmzquant/strategies/" not in url
            ):
                continue
            path = unquote(url.split(FMZ_REF + "/", 1)[1])
            raw = source.read(f"strategies-{FMZ_REF}/{path}")
            blocks = local_blocks(raw.decode())
            if not blocks:
                continue
            block = blocks[0]
            if isolated_literals:
                try:
                    prepare_source(block)
                except MigrationBlocked as exc:
                    if str(exc) != LITERAL_BOUNDARY:
                        continue
                else:
                    continue
            try:
                code, version, transforms, repairs = prepare_source(
                    block, isolated_literals=isolated_literals
                )
            except MigrationBlocked as exc:
                coverage.append([i, "Pending · FMZ Pine compatibility retry", str(exc)])
                continue
            archived = re.search(r"(?m)^period:\s*(\S+)", block)
            candidates.append(
                {
                    "id": i,
                    "name": row["name"],
                    "source": url,
                    "hash": checksum(raw),
                    "archived": archived[1] if archived else "",
                    "old_version": version,
                    "code": code,
                    "transforms": transforms,
                    "repairs": repairs,
                    "migration_sha256": checksum(code.encode()),
                }
            )
    base, files = archived_candles(candle_archive)
    candles, windows = prepare_candles(base, 15)
    labels = {"Binance · " + k: v for k, v in candles.items()}
    time_limit_ms = ISOLATED_LIMIT_MS if isolated_literals else TIME_LIMIT_MS
    write(work / "candles.json", labels)
    write(work / "candidates.json", candidates)
    write(
        work / "preflight.json",
        {
            "coverage": coverage,
            "source_revision": FMZ_REF,
            "bar_archives": files,
            "windows": {"Binance · " + k: v for k, v in windows.items()},
            "worker_sha256": make_worker(work, time_limit_ms),
            "base_disposition_sha256": checksum(ledger.read_bytes()),
            "time_limit_ms": time_limit_ms,
            "max_loop_iterations": MAX_LOOPS,
            "requires_os_isolation": isolated_literals,
        },
    )
    print(Counter(x[2] for x in coverage))
    print(f"{len(candidates)} runnable; {len(coverage)} blocked before execution")


def finalize(work, destination, diagnostics=None):
    report = read(work / "preflight.json")
    if report.get("requires_os_isolation"):
        assert read(work / "isolation-probe.json") == {
            "privateDenied": True,
            "networkDenied": True,
        }
        report["isolation_probe"] = {"privateDenied": True, "networkDenied": True}
    candidates = {r["id"]: r for r in read(work / "candidates.json")}
    assert report["worker_sha256"] == checksum((work / "worker.mjs").read_bytes())
    rows = []
    coverage = report["coverage"]
    attempts = [
        {"id": i, "stage": "source screening", "detail": reason}
        for i, _, reason in coverage
    ]
    values = [
        json.loads(line)
        for line in (work / "out.jsonl").read_text(encoding="utf-8-sig").splitlines()
    ]
    assert (
        len(values) == len(candidates)
        and {r["id"] for r in values} == candidates.keys()
    )
    errors = {}
    if diagnostics:
        errors.update(
            json.loads(line)
            for line in diagnostics.read_text(encoding="utf-8-sig").splitlines()
        )
    for record in sorted(values, key=lambda r: r["id"]):
        i = record["id"]
        item = candidates[i]
        if "reason" in record:
            coverage.append(
                [
                    i,
                    "Pending · FMZ Pine compatibility retry",
                    "Binance 15m: " + record["reason"],
                ]
            )
            detail = errors.get(i) or record.get("detail") or record["reason"]
            attempts.append(
                {"id": i, "stage": "PineTS replay", "interval": "15m", "detail": detail}
            )
            continue
        results = record["results"]
        assert len(results) == 6 and {(r["period"], r["market"]) for r in results} == {
            (p, m) for p in report["windows"] for m in (*MARKETS, POOLED)
        }
        for period in report["windows"]:
            metrics = {r["market"]: r for r in results if r["period"] == period}
            for field in (
                "trades",
                "unsettled",
                "gross_wins",
                "fee_wins",
                "net_wins",
                "gross",
                "after_fees",
                "net",
            ):
                assert math.isclose(
                    metrics[POOLED][field],
                    sum(metrics[m][field] for m in MARKETS),
                    rel_tol=1e-12,
                    abs_tol=1e-6,
                )
        for row in results:
            assert (row["id"], row["interval"], row["source_sha256"]) == (
                i,
                "15m",
                item["hash"],
            )
            row.update(
                group=GROUP,
                quote_currency="USDT",
                market_data="Binance USD-M perpetuals",
                pine_source_version=item["old_version"],
                migration_sha256=item["migration_sha256"],
                transforms=item["transforms"],
                repairs=item["repairs"],
            )
        rows.extend(results)
        close = any(row["trades"] for row in results)
        status = "Tested · Pine Binance compatibility" + (
            "" if close else ", no closes"
        )
        notes = (
            ", ".join(item["repairs"])
            or "Archived rules re-evaluated with bounded runtime"
        )
        coverage.append([i, status, f"Binance USD-M perpetuals, 15m. {notes}"])
        attempts.append(
            {"id": i, "stage": "PineTS replay", "interval": "15m", "result_rows": 6}
        )
    report.update(
        engine="PineTS 0.13.1",
        market_data="Binance USD-M perpetuals",
        candle_files_sha256={"15": checksum((work / "candles.json").read_bytes())},
        coverage=sorted(coverage),
        attempts=sorted(attempts, key=lambda x: x["id"]),
        results=rows,
    )
    write(destination, report)
    print(Counter(r[1] for r in coverage), len(rows), "rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prepare_cli = sub.add_parser("prepare")
    for key in ("archive", "candle_archive", "work"):
        prepare_cli.add_argument(key, type=Path)
    prepare_cli.add_argument(
        "--ledger", type=Path, default=ROOT / "remaining-backtest-coverage.json"
    )
    prepare_cli.add_argument("--isolated-literals", action="store_true")
    done = sub.add_parser("finalize")
    for key in ("work", "destination"):
        done.add_argument(key, type=Path)
    done.add_argument("--diagnostics", type=Path)
    args = vars(parser.parse_args())
    action = args.pop("action")
    (prepare if action == "prepare" else finalize)(**args)
