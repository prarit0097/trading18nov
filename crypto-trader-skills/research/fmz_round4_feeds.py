"""Reconcile pending FMZ Pine cases with verified market and historical-bar inputs."""

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pine_compatibility import plain_pine, session_calls, shell
from research.delta_pine_followup import patch
from research.delta_pine_liquid_replay import MARKETS, WINDOWS, checksum
from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.delta_pinets_migration import MigrationBlocked, VERSION, arguments, keyword, tokens
from research.delta_strategy_replay import ROOT, stamp
from research.fmz_intrabar_replay import expand_chart_alias, follows_fill, snapshot_clock, SNAPSHOT_MS
from research.fmz_marketdata_replay import CONFIRMED_OFFSET, heikin_bars, historical_tick_setting, prepare_source, request_fields, script_blocks
from research.fmz_pine_remaining import chart_broker_declaration
from research.fmz_round3_compile import normalize_input_defaults, normalize_statements
from research.fmz_round3_compile_feeds import legacy_chart_period
from research.fmz_round3_liquid_feeds import reconcile
from research.fmz_round3_symbol_feeds import cross_worker, requests
from research.fmz_round3_timeframe_feeds import complete_feed, read_receipts, reference_bars, worker_for

LEDGER = ROOT / "remaining-backtest-round3-coverage.json"
REPORTS = {
    "fmz-round3-symbols.json", "fmz-round3-timeframes.json",
    "fmz-round3-timeframe-variant.json", "fmz-round3-timeout-15m.json",
    "fmz-round3-utc-alias-check.json",
}
REASONS = (
    "future data", "future-looking", "synthetic", "timenow", "historical runtime",
    "tick or intrabar", "computed alignment", "lookahead", "clock to anchor",
    "verified non-chart-timeframe", "visible chart state",
)
RUNTIME = {
    "runtime15": ("round3/worker15", (558, 1238, 1287, 3309, 3948, 4052, 4082, 4096, 4307, 5004), 15),
    "runtime60": ("round3/worker", (558, 1238, 3309, 3948, 4082, 4307), 60),
    "runtime-symbols": ("round3-feed/symbols", (4044, 5445), 15),
    "runtime-month": ("round3-feed/timeframes-retry", (5441,), 15),
    "runtime-day": ("round3-compile-feeds/alias", (4098,), 15),
}
WORKER_EDITS = {
    "maxOldGenerationSizeMb: 448": "maxOldGenerationSizeMb: 1024",
    "Math.min(65_000, work.timeoutMs)": "Math.min(160_000, work.timeoutMs)",
    "usage >= 30": "usage >= 1",
    'worker.on("error", () => retire("PineTS worker terminated during replay"));':
        'worker.on("error", (error) => retire("PineTS worker terminated during replay: " + error.code));',
}


def amplify(worker):
    for old, new in WORKER_EDITS.items():
        assert worker.count(old) == 1, old
        worker = worker.replace(old, new)
    return worker


def scoped():
    return {
        row["id"]: row for row in read(LEDGER)["disposition"]
        if not row["status"].startswith("Tested")
        and FMZ_REF in row["source"]
        and (row["selected_report"] in REPORTS or any(reason in row["reason"] for reason in REASONS))
    }


def documents(archive, rows):
    for ident, row in rows.items():
        name = unquote(row["source"].split(FMZ_REF + "/", 1)[1])
        raw = archive.read(f"strategies-{FMZ_REF}/{name}")
        digest = checksum(raw)
        assert row.get("pinned_document_sha256", digest) == digest, ident
        yield ident, row, raw.decode("utf-8"), digest


def historical_flags(code, one_pass):
    edits, counts = [], Counter()
    parts = tokens(code)
    for i, part in enumerate(parts):
        if part.group() == "varip" and one_pass:
            edits.append((part.start(), part.end(), "var"))
            counts["Persistence on one historical calculation per bar"] += 1
        if [p.group() for p in parts[i:i + 2]] == ["barstate", "."] and i + 2 < len(parts):
            flag = parts[i + 2]
            if flag.group() == "isrealtime":
                edits.append((part.start(), flag.end(), "false"))
                counts["All replay bars are historical"] += 1
            if flag.group() == "islastconfirmedhistory" and one_pass:
                edits.append((flag.start(), flag.end(), "islast"))
                counts["Final chart bar is confirmed"] += 1
    return patch(code, edits), counts


def simple_requests(code):
    """Resolve immutable chart aliases and literal timeframe defaults."""
    parts = tokens(code)
    masked = re.sub(r"(?m)//.*$", "", code)
    aliases = dict(re.findall(r"(?m)^\s*(\w+)\s*=\s*(syminfo\.(?:tickerid|ticker))\s*$", masked))
    quoted = r"""("|')([0-9]+[DWM]?|[DWM]?)\1"""
    frames = {}
    for match in re.finditer(
        r"(?m)^\s*(\w+)\s*=\s*input(?:\.(?:timeframe|resolution))?\s*\(\s*(?:defval\s*=\s*)?" + quoted,
        masked,
    ):
        frames[match[1]] = f'"{match[3]}"'
    changes, notes = [], Counter()
    for i, part in enumerate(parts[:-1]):
        if part.group() != "security" or parts[i + 1].group() != "(":
            continue
        _, spans = arguments(parts, i + 1)
        fields = request_fields(parts, spans)
        for field, defaults in (("symbol", aliases), ("timeframe", frames)):
            value, (begin, end) = fields[field]
            if value in defaults and not re.search(rf"(?m)\b{re.escape(value)}\s*:=", masked):
                changes.append((parts[begin].start(), parts[end - 1].end(), defaults[value]))
                notes[f"Immutable {field} default within requests"] += 1
            elif field == "timeframe" and value in {'""', "''"}:
                changes.append((parts[begin].start(), parts[end - 1].end(), "timeframe.period"))
                notes["Empty request frame uses chart interval"] += 1
    return patch(code, changes), notes


def causal_requests(code):
    """Use closed higher bars or the last closed lower bar in the variant."""
    version = int(VERSION.search(code)[1])
    edits = []
    parts = tokens(code)
    for i, part in enumerate(parts[:-1]):
        if part.group() != "security" or parts[i + 1].group() != "(":
            continue
        end, spans = arguments(parts, i + 1)
        fields = request_fields(parts, spans)
        frame = fields["timeframe"][0]
        expr = fields["expression"][0]
        setting, span = fields.get("lookahead", ("", None))
        if frame == "timeframe.period" or CONFIRMED_OFFSET.fullmatch(expr):
            continue
        if setting in {"true", "barmerge.lookahead_on"}:
            begin, stop = span
            edits.append((parts[begin].start(), parts[stop - 1].end(), "barmerge.lookahead_off"))
        elif not setting and version < 3:
            first = parts[end].start()
            edits.append((first, first, ", lookahead = barmerge.lookahead_off"))
    return patch(code, edits), len(edits)


def normalize(block, *, legacy_session=False):
    code, declaration_changes = chart_broker_declaration(plain_pine(block))
    notes = Counter()
    if declaration_changes:
        notes["Chart indicator declaration adapted for active archived orders"] += declaration_changes
    if not VERSION.search(code):
        if re.search(r"(?m)//\s*@version\b", code):
            raise MigrationBlocked("Version directive is ambiguous")
        code = "//@version=5\n" + code
        notes["FMZ documented default Pine v5"] += 1
    code, declaration = shell(code)
    notes.update(declaration)
    fill = follows_fill(code)
    one_pass = not fill and not re.search(
        r"\b(?:calc_on_order_fills|calc_on_every_history_tick|use_bar_magnifier)\s*=\s*(?!\s*false\b)",
        re.sub(r"(?m)//.*$", "", code),
    )
    code, flags = historical_flags(code, one_pass)
    notes.update(flags)
    code, _ = historical_tick_setting(code)
    if code != block and re.search(r"\bcalc_on_every_tick\s*=\s*true\b", block):
        notes["Realtime-only tick flag suppressed for historical replay"] += 1
    clock = any(part.group() == "timenow" for part in tokens(code))
    if clock:
        if any(part.group() == str(SNAPSHOT_MS) for part in tokens(code)):
            raise MigrationBlocked("Historical clock sentinel collides with an archived literal")
        code = snapshot_clock(code)
        notes["Execution clock fixed independently at each historical window close"] += 1
    code, count = expand_chart_alias(code)
    if count:
        notes["Immutable chart ticker alias"] += count
    if int(VERSION.search(code)[1]) < 4:
        code, count = legacy_chart_period(code)
        if count:
            notes["Documented chart timeframe variable"] += count
    code, changes = normalize_statements(code)
    notes.update(changes)
    if legacy_session and int(VERSION.search(code)[1]) < 5:
        code, count = session_calls(code)
        if count:
            notes["Preserve legacy weekday default in session checks"] += count
    code, changes = simple_requests(code)
    notes.update(changes)
    code, delayed = causal_requests(code)
    if delayed:
        notes["Request timing changed to close confirmation"] += delayed
    code, version, changes = prepare_source(
        code, isolated_literals=True, with_heikin=True, verified_fill_recalc=fill,
        chart_ticker_alias=True,
    )
    notes.update(changes)
    code, changes = normalize_input_defaults(code)
    notes.update(changes)
    return code, version, dict(notes), fill, clock, bool(delayed)


def preflight(prior, work):
    rows, candidates, stops = scoped(), [], []
    work.mkdir(parents=True, exist_ok=True)
    with ZipFile(prior / "fmz.zip") as archive:
        for ident, row, document, digest in documents(archive, rows):
            try:
                blocks = script_blocks(document, False)
                if len(blocks) != 1:
                    raise MigrationBlocked("Archive lacks one unambiguous Pine block")
                code, version, notes, fill, clock, delayed = normalize(blocks[0])
                if not notes:
                    raise MigrationBlocked("Baseline market or runtime dependency remains")
            except ValueError as exc:
                stops.append([ident, str(exc)])
                continue
            period = re.search(r"(?m)^period:\s*(\S+)", document)
            candidates.append(dict(
                id=ident, name=row["name"], source=row["source"], hash=digest,
                archived=period[1] if period else "", code=code, version=version,
                repairs=notes, allowFillRecalculation=fill, snapshotVariant=clock,
                confirmedVariant=delayed,
            ))
    write(work / "candidates.json", candidates)
    write(work / "preflight.json", {"scoped": sorted(rows), "stops": stops})
    print("Scope", len(rows), "admitted", len(candidates), Counter(reason for _, reason in stops))
    print("Candidate IDs", [row["id"] for row in candidates])


def stage_runtime(prior, work):
    for label, (batch, ids, _) in RUNTIME.items():
        source, destination = prior / batch, work / label
        destination.mkdir(parents=True, exist_ok=True)
        candidates = [r for r in read(source / "candidates.json") if r["id"] in ids]
        assert {r["id"] for r in candidates} == set(ids)
        for candidate in candidates:
            candidate["timeoutMs"] = 160_000
        (destination / "candidates.json").write_text(json.dumps(candidates, ensure_ascii=False), encoding="utf-8")
        (destination / "candles.json").write_bytes((source / "candles.json").read_bytes())
        worker = (source / "worker.mjs").read_text(encoding="utf-8")
        (destination / "worker.mjs").write_bytes(amplify(worker).encode())


def clock_worker(work, *, cross=False):
    if cross:
        cross_worker(work)
    else:
        worker_for(work, timeout=80_000)
    path = work / "worker.mjs"
    worker = path.read_text(encoding="utf-8")
    bounds = {f"Binance · {label}": stamp(end) * 1000 for label, (_, end) in WINDOWS.items()}
    bounds.update({"Fixture A": 1738369800000, "Fixture B": 1738370700000})
    substitutions = {
        "      const indicator = new Indicator(item.code);":
            "      const makeIndicator = (code) => {\n      const indicator = new Indicator(code);",
        "      const results = [];\n      for (const [period, candles] of Object.entries(windows)) {": (
            "      return indicator;\n      };\n"
            "      const results = [];\n"
            "      for (const [period, candles] of Object.entries(windows)) {\n"
            f"        const clock = {json.dumps(bounds, ensure_ascii=False)}[period];\n"
            f"        const code = item.snapshotVariant ? item.code.replace(/\\b{SNAPSHOT_MS}\\b/g, String(clock)) : item.code;\n"
            "        if (item.snapshotVariant && !Number.isSafeInteger(clock)) throw Error('Invalid historical clock');\n"
            "        const indicator = makeIndicator(code);"
        ),
        "maxOldGenerationSizeMb: 448": "maxOldGenerationSizeMb: 768",
        "usage >= 30": "usage >= 1",
    }
    for old, new in substitutions.items():
        assert worker.count(old) == 1, old
        worker = worker.replace(old, new)
    path.write_bytes(worker.encode())
    return bounds


def stage_new(prior, work):
    chosen = set().union(*(set(ids) for _, ids, _ in RUNTIME.values()))
    inputs = read(work / "source15/candidates.json")
    base = read(prior / "round3-feed/timeframes/candles.json")
    short = read(prior / "round3/worker15/candles.json")
    for label, window in base.items():
        for symbol in MARKETS:
            assert window[symbol] == short[label][symbol]
            for field in ("references", "heikinAshi"):
                window["market"][field][symbol] = {
                    **short[label]["market"][field][symbol],
                    **window["market"][field][symbol],
                }
    groups = (
        [item for item in inputs if item["id"] not in chosen and not re.search(r"\bsecurity\s*\(", item["code"])],
        [item for item in inputs if item["id"] not in chosen and re.search(r"\bsecurity\s*\(", item["code"])],
    )
    flat = {label: {**window, "market": {key: value for key, value in window["market"].items()
                                       if key not in {"references", "heikinAshi"}}}
            for label, window in base.items()}
    staged = []
    for group, candles, stem in zip(groups, (flat, base), ("source-base", "source-refs"), strict=True):
        size = 2 if stem == "source-base" else 3
        for index in range(size):
            batch = f"{stem}-{index + 1}"
            destination = work / batch
            destination.mkdir(parents=True, exist_ok=True)
            candidates = group[index::size]
            assert len({item["id"] for item in candidates}) == len(candidates)
            write(destination / "candidates.json", candidates)
            write(destination / "candles.json", candles)
            clock_worker(destination)
            staged.append(batch)
    assert sum(len(read(work / batch / "candidates.json")) for batch in staged) == len(
        [item for item in inputs if item["id"] not in chosen]
    )
    print("Staged", [(batch, len(read(work / batch / "candidates.json"))) for batch in staged])


def inline_confirmed_helper(code):
    pattern = (
        r"(?m)^(f_secureSecurity)\(_symbol, _res, _src(, _offset)?\) =>[ \t]*(?:\n[ \t]+)?"
        r"(?:request\.)?security\(_symbol, _res, _src\[(1|_offset)\],"
        r"\s*lookahead\s*=\s*barmerge.lookahead_on\)\s*$"
    )
    match, = re.finditer(pattern, code)
    helper, offset_parameter, offset = match.groups()
    parts = tokens(code)
    edits = [(match.start(), match.end(), "\n")]
    for i, token in enumerate(parts[:-1]):
        if not (token.group() == helper and token.start() >= match.end()):
            continue
        assert parts[i + 1].group() == "("
        end, args = arguments(parts, i + 1)
        values = [code[parts[a].start():parts[b - 1].end()].strip() for a, b in args]
        if offset_parameter:
            symbol, frame, expression, delay = values
            assert delay == "1"
        else:
            symbol, frame, expression = values
            delay = offset
        assert symbol == "syminfo.tickerid" and expression in {"close", "open", "high", "low"}
        edits.append((
            token.start(), parts[end].end(),
            f"request.security({symbol}, {frame}, {expression}[{delay}], lookahead=barmerge.lookahead_on)",
        ))
    assert len(edits) > 1
    return patch(code, edits), len(edits) - 1


def stage_addon(prior, work):
    scope = scoped()
    preflight = read(work / "source15/preflight.json")
    helper_ids = {1600, 3435, 3530, 4712, 4796}
    session_ids = {ident for ident, reason in preflight["stops"] if reason == "Pine v5 session day defaults differ"}
    requested = {
        ident: row for ident, row in scope.items()
        if ident in helper_ids | session_ids
    }
    inputs = read(work / "source15/candidates.json")
    candidates = [item for item in inputs if item["id"] in {1703, 5651}]
    stops = []
    with ZipFile(prior / "fmz.zip") as archive:
        for ident, row, document, digest in documents(archive, requested):
            try:
                block, = script_blocks(document, False)
                count = 0
                if ident in helper_ids:
                    block, count = inline_confirmed_helper(plain_pine(block))
                code, version, notes, fill, clock, delayed = normalize(block, legacy_session=True)
                if count:
                    notes["Expand previous-candle request helper without shifting alignment"] = count
            except (AssertionError, ValueError) as exc:
                stops.append((ident, str(exc) or "Helper inputs require a separate semantic check"))
                continue
            period = re.search(r"(?m)^period:\s*(\S+)", document)
            candidates.append(dict(
                id=ident, name=row["name"], source=row["source"], hash=digest,
                archived=period[1] if period else "", code=code, version=version,
                repairs=notes, allowFillRecalculation=fill, snapshotVariant=clock,
                confirmedVariant=delayed,
            ))
    destination = work / "source-addon"
    destination.mkdir(parents=True, exist_ok=True)
    candles = read(work / "source-refs-1/candles.json")
    archives = []
    for symbol in MARKETS:
        minute, daily, evidence = complete_feed(symbol, prior / "round3-feed/feeds", prior / "nonpine/binance")
        archives.extend(evidence)
        for label, (first, last) in WINDOWS.items():
            market = candles[f"Binance · {label}"]["market"]
            for frame in ("4D", "105", "300"):
                bars = reference_bars(frame, minute, daily, stamp(first), stamp(last))
                market["references"][symbol][frame] = bars
                market["heikinAshi"][symbol][frame] = heikin_bars(bars)
    write(destination / "candidates.json", candidates)
    write(destination / "candles.json", candles)
    write(destination / "evidence.json", {"bar_archives": archives, "stops": stops})
    clock_worker(destination)
    print("Extra frames, confirmed request helpers and weekday sessions", [item["id"] for item in candidates])
    print("Open session or helper dependencies", Counter(reason for _, reason in stops))


def stage_benchmark(prior, work):
    from research.fmz_round3_feed_fixture import prepare as fixture

    entries, stops = [], []
    scope = {ident: row for ident, row in scoped().items() if ident in {1958, 3433}}
    with ZipFile(prior / "fmz.zip") as archive:
        for ident, row, document, digest in documents(archive, scope):
            try:
                assert re.search(r'(?m)^exchanges:\s*\[\{"eid":"Futures_Binance","currency":"BTC_USDT"', document)
                (block,) = script_blocks(document, False)
                assert re.search(r"(?m)^symb_bench\s*=\s*input\('BTC_USDT:swap',", block)
                ((symbol, span),) = requests(block)
                assert symbol == "symb_bench"
                code, version, notes, fill, clock, delayed = normalize(patch(block, [(*span, "syminfo.tickerid")]))
                ((symbol, span),) = requests(code)
                assert symbol == "syminfo.tickerid"
                code = patch(code, [(*span, '"BTCUSDT"')])
            except (AssertionError, ValueError) as exc:
                stops.append((ident, str(exc) or "Fixed benchmark alias could not be verified"))
                continue
            notes["Exact archived Binance BTC perpetual benchmark on both charts"] = 1
            period = re.search(r"(?m)^period:\s*(\S+)", document)
            entries.append(dict(
                id=ident, name=row["name"], source=row["source"], hash=digest,
                archived=period[1] if period else "", code=code, version=version,
                repairs=notes, allowFillRecalculation=fill, snapshotVariant=clock,
                confirmedVariant=delayed,
            ))
    assert entries, stops
    destination = work / "source-benchmark"
    destination.mkdir(parents=True, exist_ok=True)
    candles = read(work / "source-base-1/candles.json")
    for window in candles.values():
        chart, = window["BTCUSDT"]
        window["market"]["references"] = {"BTCUSDT": {"15": chart}}
        window["market"]["referenceSymbols"] = ["BTCUSDT"]
    write(destination / "candidates.json", entries)
    write(destination / "candles.json", candles)
    clock_worker(destination, cross=True)
    fixture(work / "fixture-benchmark", cross=True)
    (work / "fixture-benchmark/worker.mjs").write_bytes((destination / "worker.mjs").read_bytes())
    print("Verified archived benchmark requests:", [item["id"] for item in entries], "preflight stops:", stops)


def stage_fixtures(work):
    from research.fmz_round3_feed_fixture import prepare as fixture

    for name, worker_batch in (
        ("fixture-runtime", "runtime15"), ("fixture-month", "runtime-month"),
        ("fixture-symbols", "runtime-symbols"), ("fixture-day", "runtime-day"),
        ("fixture-source", "source-base-1"),
    ):
        destination = work / name
        fixture(destination, cross=name == "fixture-symbols")
        if name in {"fixture-runtime", "fixture-day", "fixture-source"}:
            item, = read(destination / "candidates.json")
            code = """//@version=5
strategy("Independently reconciled BTC and ETH fixture")
if bar_index == 0
    strategy.entry("Long", strategy.long, qty=1)
if bar_index == 1
    strategy.close("Long")
"""
            if name == "fixture-source":
                code = """//@version=5
strategy("Historical clock and bar state")
varip int passes = 0
passes += 1
if barstate.isrealtime == false and not barstate.islastconfirmedhistory and passes == 1 and (timenow - time) == 1800000
    strategy.entry("Long", strategy.long, qty=1)
if passes == 2
    strategy.close("Long")
"""
                code, _, notes, _, clock, _ = normalize(code)
                assert len(notes) == 4 and clock, notes
                item["snapshotVariant"] = True
            item.update(code=code, hash=checksum(code.encode()))
            write(destination / "candidates.json", [item])
        (destination / "worker.mjs").write_bytes((work / worker_batch / "worker.mjs").read_bytes())


def artifact_hashes(path, files):
    return {file: checksum((path / file).read_bytes()) for file in files}


def fixture_receipts(work, titles, isolation):
    checks = {}
    for title in sorted(titles):
        batch = work / title
        (item,) = read(batch / "candidates.json")
        (receipt,) = read_receipts(batch).values()
        rows = receipt["results"]
        assert item["hash"] == checksum(item["code"].encode())
        assert (work / f"{title}-node.exit").read_text().strip() == "0"
        reconcile(rows, ("Fixture A", "Fixture B"), item, 15)
        for row in rows:
            lots = 2 if row["market"] == "BTCUSDT + ETHUSDT" else 1
            if item.get("snapshotVariant") and row["period"] == "Fixture B":
                lots = 0
            assert row["trades"] == lots and row["unsettled"] == 0, row
            assert math.isclose(row["gross"], lots * 50, abs_tol=1e-8), row
            assert math.isclose(row["net"], lots * 48.1755, abs_tol=1e-8), row
        checks[title] = {
            "sha256": artifact_hashes(batch, ("candidates.json", "candles.json", "worker.mjs", "out.jsonl")),
            "isolation_probe": isolation,
            "results": rows,
        }
    return checks


def disposition(item, batch, minutes):
    flags = []
    if minutes != 15:
        flags.append(f"{minutes}m chart variant")
    if item.get("snapshotVariant"):
        flags.append("window-end clock snapshot")
    if item.get("confirmedVariant", item.get("confirmed_variant")):
        flags.append("confirmation-timing variant")
    if item.get("allowFillRecalculation"):
        flags.append("historical OHLC fill recalculation")
    if "ticker.heikinashi" in item["code"]:
        flags.append("Heikin-Ashi signals")
    if item.get("initialCapital"):
        flags.append("archived initial capital")
    name = "FMZ Pine · " + ("archived runtime retry" if batch in RUNTIME else "historical bar replay")
    group = " · ".join([name, *flags])
    detail = {
        "runtime-symbols": "Exact archived symbol routes with verified Binance references",
        "runtime-month": "Verified Binance extended timeframe references",
        "runtime-day": "Confirmed equivalence of Binance UTC 1440m and daily candles",
        "source-benchmark": "Exact archived fixed BTC perpetual benchmark on both fill charts",
    }.get(batch, "Binance USD-M perpetual historical candles")
    return group, ". ".join([detail, *flags]) + "."


def finalize(prior, work, output, fixture_output, *, runtime_only=False):
    scope = scoped()
    with ZipFile(prior / "fmz.zip") as archive:
        hashes = {ident: digest for ident, _, _, digest in documents(archive, scope)}
    isolation = read(work / "isolation-probe.json")
    assert isolation == {"privateDenied": True, "networkDenied": True}
    stems = list(RUNTIME)
    fixture_titles = {"fixture-runtime", "fixture-symbols", "fixture-month", "fixture-day"}
    if not runtime_only:
        stems.extend(sorted(path.name for path in work.glob("source-*") if path.is_dir()))
        fixture_titles.add("fixture-source")
        if "source-benchmark" in stems:
            fixture_titles.add("fixture-benchmark")
    fixtures = fixture_receipts(work, fixture_titles, isolation)
    matched_workers = {f["sha256"]["worker.mjs"] for f in fixtures.values()}
    batches, attempts, selected, results = {}, {}, {}, []
    for stem in stems:
        path = work / stem
        prior_batch, ids, minutes = RUNTIME.get(stem, ("", (), 15))
        assert (work / f"{stem}-node.exit").read_text().strip() == "0"
        batch_hashes = artifact_hashes(path, ("candles.json", "candidates.json", "worker.mjs", "out.jsonl"))
        assert batch_hashes["worker.mjs"] in matched_workers
        candidates = {row["id"]: row for row in read(path / "candidates.json")}
        receipts = read_receipts(path)
        assert receipts.keys() == candidates.keys()
        if ids:
            assert candidates.keys() == set(ids)
        evidence = {}
        if prior_batch:
            old = prior / prior_batch
            before = {row["id"]: row for row in read(old / "candidates.json")}
            for ident, row in candidates.items():
                assert row == {**before[ident], "timeoutMs": 160_000}
            prior_hashes = artifact_hashes(old, ("candles.json", "worker.mjs", "candidates.json", "out.jsonl"))
            assert prior_hashes["candles.json"] == batch_hashes["candles.json"]
            assert checksum(amplify((old / "worker.mjs").read_text(encoding="utf-8")).encode()) == batch_hashes["worker.mjs"]
            evidence = {"prior_batch": prior_batch, "prior_batch_sha256": prior_hashes}
        if (path / "evidence.json").is_file():
            evidence["reference_archives"] = read(path / "evidence.json")["bar_archives"]
            batch_hashes.update(artifact_hashes(path, ("evidence.json",)))
        batches[stem] = {"sha256": batch_hashes, "attempted_ids": sorted(candidates), **evidence}
        for ident, item in candidates.items():
            assert item["source"] == scope[ident]["source"] and item["hash"] == hashes[ident]
            receipt = receipts[ident]
            code = item["code"]
            code_hash = checksum(code.encode())
            for field in ("migration_sha256", "adapted_sha256", "replay_sha256"):
                if field in item and item[field]:
                    assert code_hash == item[field], (ident, field)
            attempt = {"batch": stem, "interval_minutes": minutes, "source_sha256": code_hash}
            if item.get("snapshotVariant") and stem.startswith("source-"):
                attempt["period_source_sha256"] = {
                    "Binance · " + label: checksum(
                        re.sub(rf"\b{SNAPSHOT_MS}\b", str(stamp(end) * 1000), code).encode()
                    ) for label, (_, end) in WINDOWS.items()
                }
            attempts.setdefault(ident, []).append(attempt)
            if "reason" in receipt:
                attempt["reason"] = receipt["reason"]
                continue
            group, detail = disposition(item, stem, minutes)
            rows = receipt["results"]
            reconcile(rows, tuple("Binance · " + label for label in WINDOWS), item, minutes)
            for row in rows:
                row.update(
                    group=group,
                    quote_currency="USDT",
                    market_data="Binance USD-M BTCUSDT and ETHUSDT perpetuals",
                    funding_model="Historical funding is outside this Pine replay",
                    pine_source_version=item.get("version", item.get("old_version")),
                    repairs=item.get("repairs", {}),
                    migration_sha256=code_hash,
                )
            attempt["trades"] = sum(row["trades"] for row in rows if row["market"] in MARKETS)
            if ident in selected:
                continue
            suffix = "" if attempt["trades"] else ", no closes"
            selected[ident] = [ident, "Tested · " + group + suffix, detail]
            results.extend(rows)
    checks = []
    if not runtime_only:
        pre = read(work / "source15/preflight.json")
        checks = pre["stops"]
        if (work / "source-addon/evidence.json").is_file():
            checks = checks + read(work / "source-addon/evidence.json")["stops"]
        assert set(pre["scoped"]) == scope.keys()
        in_scope = scope.keys()
    else:
        in_scope = attempts.keys()
    prior_stops = dict(checks)
    coverage = []
    for ident in sorted(in_scope):
        if ident in selected:
            coverage.append(selected[ident])
            continue
        reason = next((row["reason"] for row in reversed(attempts.get(ident, [])) if "reason" in row), None)
        coverage.append([ident, "Pending · FMZ historical data replay", reason or prior_stops.get(ident, scope[ident]["reason"])])
    write(fixture_output, {
        "engine": "PineTS 0.13.1",
        "engine_sha256": checksum((work / "engine.mjs").read_bytes()),
        "fixtures": fixtures,
    })
    write(output, {
        "engine": "PineTS 0.13.1",
        "engine_sha256": checksum((work / "engine.mjs").read_bytes()),
        "archive_revision": FMZ_REF,
        "source_archive_sha256": checksum((prior / "fmz.zip").read_bytes()),
        "baseline_ledger_sha256": checksum(LEDGER.read_bytes()),
        "isolated_process": isolation,
        "fixture_sha256": checksum(fixture_output.read_bytes()),
        "windows": WINDOWS,
        "resource_bounds": {"runtime_timeout_ms": 160000, "runtime_max_old_heap_mb": 1024,
                            "historical_timeout_ms": 80000, "historical_max_old_heap_mb": 768},
        "bar_provenance": {name: checksum((ROOT / name).read_bytes()) for name in (
            "fmz-round3-symbols.json", "fmz-round3-timeframes.json", "fmz-round3-timeout-15m.json",
            "fmz-round3-timeframe-variant.json", "fmz-round3-utc-alias-check.json"
        )},
        "runtime_only": runtime_only,
        "document_sha256": {ident: hashes[ident] for ident in sorted(in_scope)},
        "inputs_and_receipts": batches,
        "attempts": attempts,
        "coverage": coverage,
        "results": sorted(results, key=lambda row: row["id"]),
    })
    assert len(results) == len(selected) * 6
    print(f"{len(coverage)} scoped, {len(attempts)} attempted, {len(selected)} tested with {len(results)} rows")
    print("Verified IDs", sorted(selected))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action", choices=("preflight", "stage-runtime", "stage-new", "stage-addon", "stage-benchmark", "stage-fixtures", "finalize"))
    cli.add_argument("prior", type=Path)
    cli.add_argument("work", type=Path)
    cli.add_argument("--output", type=Path)
    cli.add_argument("--fixture", type=Path)
    cli.add_argument("--runtime-only", action="store_true")
    args = cli.parse_args()
    if args.action == "preflight":
        preflight(args.prior, args.work / "source15")
    elif args.action == "stage-runtime":
        stage_runtime(args.prior, args.work)
    elif args.action == "stage-new":
        stage_new(args.prior, args.work)
    elif args.action == "stage-addon":
        stage_addon(args.prior, args.work)
    elif args.action == "stage-benchmark":
        stage_benchmark(args.prior, args.work)
    elif args.action == "stage-fixtures":
        stage_fixtures(args.work)
    else:
        if not args.output or not args.fixture:
            cli.error("finalize requires --output and --fixture")
        finalize(args.prior, args.work, args.output, args.fixture, runtime_only=args.runtime_only)
