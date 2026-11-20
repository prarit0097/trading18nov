"""Replay unresolved, pinned Pine sources with verified historical reference feeds."""

import argparse
import math
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

from research.delta_pine_liquid_replay import MARKET, MARKETS, POOLED, WINDOWS, checksum
from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.delta_pine_compatibility import plain_pine, rsi_calls
from research.delta_pine_followup import patch, rename_global
from research.delta_pine_repair import NO_QUOTED
from research.delta_pinets_migration import MigrationBlocked, VERSION, arguments, keyword, tokens
from research.delta_strategy_replay import ROOT, stamp
from research.fmz_marketdata_replay import heikin_bars, request_fields, script_blocks
from research.fmz_pine_remaining import order_block_indent, specialize_inputs
from research.fmz_intrabar_replay import SNAPSHOT_MS, constant_capital
from research.fmz_round3_compile import rename_custom_functions
from research.fmz_round3_feed_fixture import candle, prepare as prepare_fixture
from research.fmz_round3_liquid_feeds import reconcile
from research.fmz_round3_symbol_feeds import requests
from research.fmz_round3_timeframe_feeds import complete_feed, read_receipts, reference_bars
from research.fmz_round4_feeds import artifact_hashes, clock_worker, documents, fixture_receipts, normalize

LEDGER = ROOT / "remaining-backtest-round4-coverage.json"
PRIOR_FEEDS = ROOT / "fmz-round4-feed-replay.json"
BASE = "8fc965fe59c1cf0957c1abf09b4277ca9b2b1613"
FIXED_BTC = {1821: "market", 3656: "b", 4808: "b"}
LATE_CAPITAL = {2758, 4432, 4881}
PHASES = ("batch", "sessions", "repair", "followup")
SCOPE = (
    "Request needs", "verified feed", "non-chart-timeframe", "computed alignment",
    "tick or intrabar", "per-source time", "external APIs", "visible chart state",
    "Legacy session is computed", "Baseline market", "Unavailable market",
    "Broker fees or",
)


def scoped():
    return {
        row["id"]: row for row in read(LEDGER)["disposition"]
        if not row["status"].startswith("Tested") and FMZ_REF in row["source"]
        and (row["id"] in LATE_CAPITAL | {3056} or any(term in row["reason"] for term in SCOPE))
    }


def replace_once(code, pattern, replacement):
    code, count = re.subn(pattern, replacement, code)
    if count != 1:
        raise MigrationBlocked("Expected one verified archived source pattern")
    return code


def session_defaults(code, ident):
    changes = {}
    if ident in {2016, 2046, 2058, 2206, 2584, 3172, 3496, 4715, 5599, 5799}:
        # Verify the helper is used exclusively on this 15-minute chart grid.
        calls = re.findall(r"\btimeinrange\s*\(([^,]+),", NO_QUOTED.sub("", code))
        chart_args = {"timeframe.period", "timeframe"} if ident == 2058 else {"timeframe.period"}
        if calls[:1] != ["res"] or any(call.strip() not in chart_args for call in calls[1:]):
            raise MigrationBlocked("Session helper does not consistently use the chart timeframe")
        if ident == 2058 and not re.search(r'(?m)^timeframe\s*=\s*input\(title="Time Frame", defval="15"\)', code):
            raise MigrationBlocked("Session timeframe default is not 15 minutes")
        code = replace_once(code, r"\btime\(res,\s*sess\)", "time(timeframe.period, sess)")
        changes["Session helper uses its archived chart-interval argument"] = 1
    if ident in {1127, 1881, 1889, 2142, 3164, 3245}:
        # The only consumers test whether an open minute is inside the UTC session.
        code = replace_once(code, r"(not na\(time\()(['\"])1\2\s*,", r"\1timeframe.period,")
        changes["UTC chart-open session variant for one-minute membership"] = 1
    if ident in {3109, 5289}:
        assert re.search(r'(?m)^sess = input\(defval = "0000-0000",', code)
        assert re.search(r"(?m)^session_open\s*=\s*na\(t\)\s*\?\s*false\s*:\s*true", code)
        code = replace_once(code, r"time\('(240|60)', sess\)", "time(timeframe.period, sess)")
        changes["Full UTC day membership retains legacy weekdays"] = 1
    if ident == 5517:
        code = replace_once(code, r'time\(timeframe\.period, sess \+ ":" \+ days\)', 'fmz_explicit_time(sess + ":" + days)')
        pos = VERSION.search(code).end()
        code = code[:pos] + '\nfmz_explicit_time(spec) => time(timeframe.period, str.contains(spec, ":") ? spec : spec + ":23456")\n' + code[pos:]
        changes["Explicit archived days retained in computed session"] = 1
    return code, changes


def request_alignment(code):
    edits = []
    parts = tokens(code)
    for i, node in enumerate(parts[:-1]):
        if node.group() != "security" or parts[i + 1].group() != "(":
            continue
        _, spans = arguments(parts, i + 1)
        fields = request_fields(parts, spans)
        value, span = fields.get("gaps", ("", None))
        if value not in {"barmerge.lookahead_on", "barmerge.lookahead_off"}:
            continue
        if "lookahead" in fields or len(spans) < 4 or keyword(parts, spans[3])[0] is not None:
            raise MigrationBlocked("Legacy request alignment argument is ambiguous")
        edits.append((parts[span[0]].start(), parts[span[0]].start(), "lookahead="))
    return patch(code, edits), len(edits)


def observed_repairs(code, ident):
    notes = {}
    if ident == 235:
        code, count = rename_global(code, {"hour", "minute"})
        assert count == 2
        notes["Unshadowed chart-time variables"] = count
    if ident in {1349, 3172, 5599}:
        code, count = rename_custom_functions(code)
        if count:
            notes["Archived function name retained across migration"] = count
    if ident == 1996:
        code = replace_once(code, r"\brange = time\(", "fmzSessionRange = time(")
        notes["Local name now valid in Pine v5"] = 1
    if ident in {2509, 4137, 5297}:
        settings = {2509: "stopMultiplyer|reentryStopMultiplyer", 4137: "stoploss|tp[1-4]", 5297: "ForecastBiasMagnitude"}
        pattern = rf"(?m)^((?:{settings[ident]})\s*=\s*)input\((?=[^\n]*\b(?:minval|step)\s*=\s*(?:0\.\d+))"
        code, count = re.subn(pattern, r"\1input.float(", code)
        if count:
            notes["Float input keeps exact fractional range"] = count
    if ident == 2517:
        code = replace_once(code, r'"0000-2400"', '"0000-0000"')
        notes["Full-day midnight boundary in Pine session syntax"] = 1
    if ident in {2855, 2864}:
        name, argument = ("crossover", "ovrbgt") if ident == 2855 else ("crossunder", "ovrsld")
        expr = f"{name}(rsiVWAP, {argument})"
        code = replace_once(code, rf"(?m)^(strategy\.close\([^\n]*){re.escape(expr)}\[lateleave\]",
                            rf"fmzLateCross = {expr}\n\1fmzLateCross[lateleave]")
        notes["Eager crossover history retained on each chart bar"] = 1
    if ident == 3634:
        for label, field in (("Close", "close"), ("Open", "open")):
            name = "getPrevDay" + label
            code = replace_once(code, rf'(?m)^{name}\(\) =>\s+(request\.security\(syminfo\.tickerid, "D", {field}\[1\]\))',
                                rf"{name} = \1")
            code = code.replace(f"{name}()", name)
        notes["Previous-day requests evaluated once per chart bar"] = 2
    if ident == 3664:
        for name, timeframe in (("getVolume", "D"), ("getVolume2", "39")):
            code = replace_once(code, rf'(?m)^{name}\(symbol, bar\) =>\s+(request\.security\(syminfo\.tickerid, "{timeframe}", volume\))\[bar\]',
                                rf"{name} = \1")
            code, count = re.subn(rf"\b{name}\(syminfo\.tickerid, (\d+)\)", rf"{name}[\1]", code)
            assert count == 4
        notes["Volume request retained with source chart-series offsets"] = 2
    if ident == 3855:
        match, = re.finditer(r'(?m)^strategy\(title="LT Strategy",[^\n]+\)$', code)
        pos = VERSION.search(code).end()
        code = patch(code, [(pos, pos, "\n" + match[0]), (match.start(), match.end(), "")])
        notes["Strategy declaration precedes instrument context evaluation"] = 1
    if ident == 4016:
        code = patch(code, [(node.start(), node.end(), "fmzValue") for node in tokens(code) if node.group() == "return"])
        notes["Two local return bindings now valid in Pine v5"] = 2
    if ident == 4074:
        assert sum(node.group() == "tpmtf4" for node in tokens(code)) == 1
        code = replace_once(code, r"(?m)^tpmtf4 = array\.min\(a, 4\)\s*$", "")
        notes["Unused unreachable fourth array rank removed"] = 1
    if ident in {4089, 5518}:
        if ident == 4089:
            assert re.search(r"(?m)^entry_position = input\([^\n]+defval=5,", code)
            # The request series are routed from these mutually consistent archived defaults.
            for name, value in {"entry_position": "5", "med_term": "20", "long_term": "80"}.items():
                code = code.replace(f"tostring({name})", f'"{value}"')
        else:
            value = '"180"'
            code = replace_once(code, r"(security\(ha_t,\s*)res1(,)", rf"\g<1>{value}\2")
        notes["Verified archived reference intervals"] = 1
    return code, notes


def late_repairs(code, ident):
    notes = {}
    if ident in {1821, 2046, 3056}:
        before, after, label = {
            1821: ("input   (title=\"Market\"", 'input(title="Market"', "Normalize market input whitespace"),
            2046: ("2400-1600", "0000-1600", "UTC midnight corrected in legacy session"),
            3056: ('time("1", "UTC")', 'time("1", "0000-0000:1234567", "UTC")', "Full-day UTC session variant"),
        }[ident]
        assert code.count(before) == 1
        code = code.replace(before, after)
        notes[label] = 1
    if ident == 859:
        code, count = order_block_indent(code)
        assert count == 1
        notes["Archived one-order block indented correctly"] = count
    if ident in {2058, 3504}:
        names = "TakeProfit|StopLoss" if ident == 2058 else "dl|mpl"
        code, count = re.subn(rf"(?m)^((?:{names})\s*=\s*)input\((?=[^\n]*step\s*=\s*0\.01)", r"\1input.float(", code)
        assert count == 2
        notes["Float input keeps exact hundredth step"] = count
        if ident == 2058:
            code, count = rename_global(code, {"timeframe"})
            assert count == 1
            notes["Local timeframe input no longer aliases namespace"] = count
    if ident in {3656, 4808}:
        edits = [(node.start(), node.end(), "chartPrice") for node in tokens(code) if node.group() == "as"]
        assert len(edits) >= 2
        code = patch(code, edits)
        notes["Archived chart price binding now valid in Pine v5"] = 1
    if ident == 4881:
        code, count = rsi_calls(code)
        if count:
            notes["Proven classic RSI integer length"] = count
    return code, notes


def prepare_source(ident, block, advanced=True, late=False):
    code, repairs = session_defaults(plain_pine(block), ident)
    if advanced:
        code, observed = observed_repairs(code, ident)
        repairs.update(observed)
    if late:
        code, observed = late_repairs(code, ident)
        repairs.update(observed)
    btc_slots = []
    if advanced and (alias := FIXED_BTC.get(ident)):
        code = replace_once(code, rf'(?m)^({alias}\s*=\s*)input\([^\n]*"BTC_USDT:swap"[^\n]*\)', r'\1"BTC_USDT:swap"')
        edits = []
        for index, (symbol, span) in enumerate(requests(code)):
            if symbol == alias or (ident == 3656 and symbol == "a"):
                edits.append((*span, "syminfo.tickerid"))
                if symbol == alias:
                    btc_slots.append(index)
        assert btc_slots
        code = patch(code, edits)
    if ident in {2247, 2473, 3504}:
        code, count = request_alignment(code)
        repairs["Explicit legacy positional lookahead constant"] = count
    if ident == 2476:
        assert re.search(r"(?m)^repaint = input\.bool\(defval = false,", code)
        code = replace_once(code, r"\brepaint\s*\?\s*barmerge\.lookahead_on\s*:\s*barmerge\.lookahead_off", "barmerge.lookahead_off")
        repairs["Archived false repaint default"] = 1
    if ident == 5740:
        default, = re.findall(r"(?m)^timeframe_gaps\s*=\s*input\.bool\(\s*(true|false)\b", code)
        code = replace_once(code, r",\s*gapFillMode\)", ", gaps=barmerge.gaps_" + ("on" if default == "true" else "off") + ")")
        repairs["Archived fixed input gap policy"] = 1
    if ident in {859, 1089, 2953, 1781, 4142}:
        if ident == 859:
            code = replace_once(code, r"\bheikenashi\(tickerid\)", "heikinashi(syminfo.tickerid)")
        else:
            alias = "_ticker" if ident in {1089, 2953} else "data2"
            setting = "useHA" if alias == "_ticker" else "isHA"
            assert re.search(rf"(?m)^{setting}\s*=\s*input\(false,", code)
            code = replace_once(code, rf"(?m)^{alias}\s*=\s*{setting}\s*\?[^\n]+\n", "")
            if ident == 4142:
                code = replace_once(code, r"(?m)^heikenashi_1\s*=\s*ticker\.heikinashi\(syminfo\.tickerid\)\s*\n", "")
            code, count = re.subn(rf"(\bsecurity\s*\(\s*){alias}(\s*,)", r"\1syminfo.tickerid\2", code)
            assert count > 0 and not re.search(rf"\b{alias}\b", NO_QUOTED.sub("", code))
        repairs["Archived chart-symbol or Heikin-Ashi ticker binding"] = 1
    if ident in {5128, 5386}:
        if ident == 5128:
            assert re.search(r"(?m)^calc_on_every_tick = true$", code)
            code = replace_once(code, r"(calc_on_every_tick\s*=\s*)calc_on_every_tick\b", r"\1true")
            if advanced:
                code = replace_once(code, r"(?m)^calc_on_every_tick = true\n", "")
                repairs["Realtime-only strategy tick option suppressed on historical bars"] = 1
        else:
            assert re.search(r"(?m)^bool BAR_MAGNIFIER = false$", code)
            code = replace_once(code, r"(use_bar_magnifier\s*=\s*)BAR_MAGNIFIER\b", r"\1false")
        repairs["Immutable strategy calculation option"] = 1
    if ident in {2253, 3309}:
        code, count = rsi_calls(code)
        if count:
            repairs["Proven classic RSI integer length"] = count
    if ident in {5128, 3301}:
        if ident == 5128:
            assert re.search(r"(?m)^length_val = 2$", code)
            code = replace_once(code, r"defval=length_val\)", "defval=length_val, type=input.integer)")
        code, count = specialize_inputs(code)
        repairs["Proven archived input type"] = count
    if ident == 2351:
        for title in ("K", "Smooth", "D"):
            code = re.sub(rf'title="{title}", minval=1, title=', "minval=1, title=", code)
        repairs["Duplicated input display title removed"] = 5
    result, version, changes, fill, clock, delayed = normalize(code, legacy_session=ident not in {1996, 5517})
    if btc_slots:
        routed = requests(result)
        assert all(routed[i][0] == "syminfo.tickerid" for i in btc_slots)
        result = patch(result, [(*routed[i][1], '"BTCUSDT"') for i in btc_slots])
        repairs["Fixed archived Binance BTC perpetual reference"] = len(btc_slots)
    return result, version, {**changes, **repairs}, fill, clock, delayed


def targets(archive, prefix):
    with ZipFile(archive) as source:
        for ident, row, document, digest in documents(source, scoped()):
            if (prefix == "batch" and ident == 3056) or (prefix != "followup" and ident in LATE_CAPITAL):
                continue
            try:
                blocks = script_blocks(document, False)
                if len(blocks) != 1:
                    raise MigrationBlocked("Archive lacks one active Pine block")
                block, capital = blocks[0], None
                advanced = prefix in {"repair", "followup"}
                if advanced and ident in LATE_CAPITAL | {4052, 5004}:
                    block, capital = constant_capital(plain_pine(block))
                if advanced and ident in FIXED_BTC and not re.search(r'(?m)^exchanges: \[\{"eid":"Futures_Binance","currency":"BTC_USDT"', document):
                    raise MigrationBlocked("Archive does not verify the fixed BTC perpetual product")
                if prefix == "batch":
                    code, version, changes, fill, clock, delayed = normalize(block, legacy_session=True)
                else:
                    code, version, changes, fill, clock, delayed = prepare_source(
                        ident, block, advanced=advanced, late=prefix == "followup",
                    )
            except (ValueError, AssertionError) as exc:
                yield ident, str(exc) or "Archived source did not match the verified adaptation"
                continue
            period = re.search(r"(?m)^period:\s*(\S+)", document)
            item = dict(
                id=ident, name=row["name"], source=row["source"], hash=digest,
                archived=period[1] if period else "", code=code, version=version, repairs=changes,
                allowFillRecalculation=fill, snapshotVariant=clock, confirmedVariant=delayed,
            )
            if capital is not None:
                item["initialCapital"] = capital
                item["repairs"]["Archived positive constant starting capital"] = 1
            yield ident, item


def stage(prior, round4, work, prefix="batch"):
    candidates, stops = [], []
    previous = set()
    for earlier in PHASES:
        if prefix == earlier:
            break
        for label in read(work / f"{earlier}-manifest.json")["batches"]:
            previous.update((item["id"], item["code"]) for item in read(work / label / "candidates.json"))
    for ident, item in targets(prior / "fmz.zip", prefix):
        if isinstance(item, str):
            stops.append([ident, item])
        elif (ident, item["code"]) not in previous:
            candidates.append(item)
    work.mkdir(parents=True, exist_ok=True)
    source_batch = "source-addon"
    data_root = round4
    if prefix == "followup":
        source_batch = next(label for label in read(work / "repair-manifest.json")["batches"] if label.startswith("repair-refs-"))
        data_root = work
    candles_path = data_root / source_batch / "candles.json"
    candles = read(candles_path)
    base_frames = set.intersection(*[set(window["market"]["references"][market]) for window in candles.values() for market in MARKETS])
    groups = defaultdict(list)
    for item in candidates:
        # Without a dynamic timeframe filter the full verified reference set is required.
        has_fixed = "Fixed archived Binance BTC perpetual reference" in item["repairs"]
        has_refs = ("request.security(" in item["code"] if prefix == "batch"
                    else re.search(r"\brequest\.security\s*\(", item["code"]))
        groups["cross" if has_fixed else "refs" if has_refs else "plain"].append(item)
    extended = ("12", "39", "80", "12M") if prefix == "batch" else ("12", "20", "39", "80", "180", "12M")
    evidence = read(round4 / "source-addon/evidence.json")["bar_archives"]
    for market in (MARKETS if set(extended) - base_frames else ()):
        minutes, days, _ = complete_feed(market, prior / "round3-feed/feeds", prior / "nonpine/binance")
        for label, (first, last) in WINDOWS.items():
            window = candles["Binance · " + label]["market"]
            for frame in set(extended) - base_frames:
                bars = reference_bars(frame, minutes, days, stamp(first), stamp(last))
                window["references"][market][frame] = bars
                window["heikinAshi"][market][frame] = heikin_bars(bars)
    batches = {}
    for tag, entries in sorted(groups.items()):
        inputs = candles if tag in {"refs", "cross"} else {
            label: {**window, "market": {key: value for key, value in window["market"].items()
                                         if key not in {"references", "heikinAshi"}}}
            for label, window in candles.items()
        }
        if tag == "cross":
            for window in inputs.values():
                window["market"]["referenceSymbols"] = ["BTCUSDT"]
                window["market"]["references"]["BTCUSDT"]["15"], = window["BTCUSDT"]
        for number in range(min(3, len(entries))):
            name = f"{prefix}-{tag}-{number + 1}"
            batch = work / name
            batch.mkdir(exist_ok=True)
            items = entries[number::min(3, len(entries))]
            write(batch / "candidates.json", items)
            write(batch / "candles.json", inputs)
            clock_worker(batch, cross=tag == "cross")
            batches[name] = [item["id"] for item in items]
    fixture_names = []
    for tag in ("cross", "plain", "refs"):
        matching = next((label for label in batches if label.startswith(f"{prefix}-{tag}-")), None)
        if not matching or (tag == "refs" and "plain" in groups):
            continue
        fixture = work / (prefix + ("-cross" if tag == "cross" else "") + "-fixture")
        prepare_fixture(fixture, cross=tag == "cross")
        (fixture / "worker.mjs").write_bytes((work / matching / "worker.mjs").read_bytes())
        fixture_names.append(fixture.name)
    if prefix == "sessions":
        session_fixture(work, work / (prefix + "-fixture"))
    manifest = {
        "baseline_commit": BASE, "prior_disposition_sha256": checksum(LEDGER.read_bytes()),
        "prior_candles_sha256": checksum(candles_path.read_bytes()), "prior_candles_batch": source_batch, "extended_frames": extended,
        "input_archives": evidence, "batches": batches, "stops": stops, "fixture_names": fixture_names,
    }
    write(work / f"{prefix}-manifest.json", manifest)
    print("Staged", batches, flush=True)


def session_fixture(work, control):
    path = work / "session-check"
    path.mkdir(exist_ok=True)
    windows = {}
    for period, day in (("Fixture A", 3), ("Fixture B", 8)):
        start = int(datetime(2025, 2, day, 3, 45, tzinfo=UTC).timestamp()) * 1000
        bars = [candle(start + i * 900_000, start + (i + 1) * 900_000, price)
                for i, price in enumerate((990, 995, 1000, 1050))]
        windows[period] = {**{market: [bars] for market in MARKETS}, "market": MARKET}
    code = '''//@version=4
strategy("Legacy weekday session fixture")
inside = not na(time('1', '0400-0415'))
outside = not inside
compared = time(timeframe.period, '0400-0415') != 0
if compared and outside
    runtime.error("Outside the session must never produce a true comparison")
if inside and compared and not inside[1] and bar_index == 1
    strategy.entry("Long", strategy.long, qty=1)
if outside and inside[1] and bar_index == 2
    strategy.close("Long")
'''
    source, _, _, _, _, _ = prepare_source(1127, code)
    item, = read(control / "candidates.json")
    item.update(code=source, hash=checksum(source.encode()), name="Legacy weekday session fixture")
    write(path / "candidates.json", [item])
    write(path / "candles.json", windows)
    (path / "worker.mjs").write_bytes((control / "worker.mjs").read_bytes())


def verify_session_fixture(work, isolation):
    path = work / "session-check"
    assert (work / "session-check-node.exit").read_text().strip() == "0"
    item, = read(path / "candidates.json")
    receipt, = read_receipts(path).values()
    rows = receipt["results"]
    reconcile(rows, ("Fixture A", "Fixture B"), item, 15)
    for row in rows:
        lots = (2 if row["market"] == POOLED else 1) if row["period"] == "Fixture A" else 0
        assert row["trades"] == lots and row["unsettled"] == 0, row
        assert math.isclose(row["gross"], lots * 50, abs_tol=1e-8), row
        assert math.isclose(row["net"], lots * 48.1755, abs_tol=1e-8), row
    return {"sha256": artifact_hashes(path, ("candidates.json", "candles.json", "worker.mjs", "out.jsonl")),
            "isolation_probe": isolation, "results": rows}


def finalize(archive, work, output, prefixes):
    scope = scoped()
    prior = read(PRIOR_FEEDS)
    archive_sha = checksum(archive.read_bytes())
    engine_sha = checksum((work / "engine.mjs").read_bytes())
    assert archive_sha == prior["source_archive_sha256"]
    assert engine_sha == prior["engine_sha256"]
    with ZipFile(archive) as source:
        hashes = {i: h for i, _, _, h in documents(source, scope)}
    isolation = read(work / "isolation-probe.json")
    assert isolation == {"privateDenied": True, "networkDenied": True}
    manifests = {prefix: read(work / f"{prefix}-manifest.json") for prefix in prefixes}
    fixture_names = {name for prefix, manifest in manifests.items() for name in manifest.get("fixture_names", [prefix + "-fixture"])}
    fixtures = fixture_receipts(work, fixture_names, isolation)
    if "sessions" in prefixes:
        fixtures["session-check"] = verify_session_fixture(work, isolation)
    workers = {receipt["sha256"]["worker.mjs"] for receipt in fixtures.values()}
    results, selected, attempts, artifacts, stops = [], {}, defaultdict(list), {}, {}
    for prefix, manifest in manifests.items():
        assert manifest["prior_disposition_sha256"] == checksum(LEDGER.read_bytes())
        before = manifest.get("prior_candles_batch", "source-addon")
        if before == "source-addon":
            assert manifest["prior_candles_sha256"] == prior["inputs_and_receipts"][before]["sha256"]["candles.json"]
        else:
            assert manifest["prior_candles_sha256"] == artifacts[before]["candles.json"]
        stops.update(manifest["stops"])
        for label, ids in manifest["batches"].items():
            path = work / label
            assert (work / (label + "-node.exit")).read_text().strip() == "0"
            artifact_hash = artifact_hashes(path, ("candles.json", "candidates.json", "worker.mjs", "out.jsonl"))
            assert artifact_hash["worker.mjs"] in workers
            artifacts[label] = artifact_hash
            candidates = {item["id"]: item for item in read(path / "candidates.json")}
            receipts = read_receipts(path)
            assert set(ids) == candidates.keys() == receipts.keys()
            for ident, item in candidates.items():
                assert item["source"] == scope[ident]["source"] and item["hash"] == hashes[ident]
                receipt = receipts[ident]
                source_hash = checksum(item["code"].encode())
                attempt = {"batch": label, "source_sha256": source_hash}
                if item["snapshotVariant"]:
                    attempt["window_source_sha256"] = {
                        label: checksum(re.sub(rf"\b{SNAPSHOT_MS}\b", str(stamp(end) * 1000), item["code"]).encode())
                        for label, (_, end) in WINDOWS.items()
                    }
                attempts[ident].append(attempt)
                if "reason" in receipt:
                    attempt.update({key: receipt[key] for key in ("reason", "detail") if key in receipt})
                    continue
                rows = receipt["results"]
                reconcile(rows, tuple("Binance · " + label for label in WINDOWS), item, 15)
                attempt["trades"] = sum(row["trades"] for row in rows if row["market"] in MARKETS)
                if ident in selected:
                    continue
                group = "FMZ Pine · verified historical feeds"
                for flag, suffix in (
                    (item["snapshotVariant"], "window-end clock snapshot"),
                    (item["confirmedVariant"], "confirmation-timing variant"),
                    (item["allowFillRecalculation"], "historical OHLC fill recalculation"),
                    ("ticker.heikinashi" in item["code"], "Heikin-Ashi reference"),
                    ("UTC chart-open session variant for one-minute membership" in item["repairs"], "UTC chart-open session variant"),
                    ("Full-day UTC session variant" in item["repairs"], "full-day UTC session variant"),
                    ("Fixed archived Binance BTC perpetual reference" in item["repairs"], "fixed BTC perpetual reference"),
                    ("initialCapital" in item, "archived starting capital"),
                ):
                    if flag:
                        group += " · " + suffix
                for row in rows:
                    row.update(group=group, quote_currency="USDT",
                               market_data="Binance USD-M BTCUSDT and ETHUSDT perpetuals",
                               funding_model="Historical funding excluded", pine_source_version=item["version"],
                               repairs=item["repairs"], migration_sha256=source_hash)
                detail = "Pinned Pine source and verified public Binance chart/reference candles."
                selected[ident] = [ident, "Tested · " + group + ("" if attempt["trades"] else ", no closes"), detail]
                results.extend(rows)
    coverage = []
    for ident, row in scope.items():
        if ident in selected:
            coverage.append(selected[ident])
            continue
        reason = next((trial["detail"] if "detail" in trial else trial["reason"]
                       for trial in reversed(attempts[ident]) if "reason" in trial), stops.get(ident, row["reason"]))
        coverage.append([ident, "Pending · FMZ historical feeds", reason])
    write(output, dict(baseline_commit=BASE, isolation_probe=isolation, manifests=manifests,
                       engine_sha256=engine_sha, source_archive_sha256=archive_sha, archive_revision=FMZ_REF,
                       prior_report_sha256=checksum(PRIOR_FEEDS.read_bytes()), windows=WINDOWS, batches=artifacts,
                       fixtures=fixtures, source_sha256=hashes, attempts=dict(attempts), coverage=coverage,
                       results=results, newly_tested=len(selected)))
    print("Reconciled", len(selected), "tested IDs and", len(results), "results")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    staging = commands.add_parser("stage")
    for argument in ("prior", "round4", "work"):
        staging.add_argument(argument, type=Path)
    staging.add_argument("--prefix", choices=PHASES, default="batch")
    reporting = commands.add_parser("finalize")
    for argument in ("archive", "work", "output"):
        reporting.add_argument(argument, type=Path)
    reporting.add_argument("--prefixes", nargs="+", default=["batch"])
    parameters = vars(parser.parse_args())
    (stage if parameters.pop("command") == "stage" else finalize)(**parameters)
