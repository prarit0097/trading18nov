"""Replay recoverable Pine reference symbols with pinned public Binance data."""

import argparse
import csv
import io
import re
from collections import Counter
from pathlib import Path
from shutil import copyfile
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pine_compatibility import rsi_calls
from research.delta_pine_followup import key_cells, patch
from research.delta_pine_liquid_replay import MARKETS, WINDOWS, checksum
from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.delta_pinets_migration import arguments, tokens
from research.delta_strategy_replay import ROOT, stamp
from research.fmz_intrabar_replay import (
    constant_capital,
    expand_chart_alias,
    follows_fill,
)
from research.fmz_marketdata_replay import (
    heikin_bars,
    prepare_source,
    request_fields,
    script_blocks,
)
from research.fmz_round3_liquid_feeds import LEDGER, reconcile
from research.fmz_round3_timeframe_feeds import (
    DAY,
    complete_feed,
    read_receipts,
    reference_bars,
    rollup,
    valid_values,
    worker_for,
)

GROUP = "FMZ Pine · Binance reference feeds"
PLAN = {
    572: ("D",),
    602: (),
    860: ("15",),
    1554: ("D",),
    2410: ("W",),
    2989: ("30",),
    3107: (),
    3158: (),
    3524: ("W",),
    3656: (),
    4044: ("1", "3", "5"),
    4575: ("D",),
    4645: ("60",),
    4808: (),
    5023: (),
    5175: (),
    5281: ("15",),
    5445: ("3",),
    5588: ("15",),
}
FUTURES = '"BTCUSDT"'
SPOT = '"BTCUSDT_SPOT"'
SYMBOL_PARAMS = {
    602: ("sym", FUTURES),
    3158: ("comparativeTickerId", FUTURES),
    3524: ("inputSymbol", FUTURES),
    3656: ("b", FUTURES),
    4645: ("sym", SPOT),
    4808: ("b", FUTURES),
    5023: ("symbol", FUTURES),
    5175: ("sym", SPOT),
    5445: ("sym", FUTURES),
}
HA = "ticker.heikinashi(syminfo.tickerid)"
REPAIRS = {602, 860, 3107, 4645, 5175, 5281}


def requests(code):
    parts = tokens(code)
    calls = []
    for i, token in enumerate(parts[:-1]):
        if token.group() != "security" or parts[i + 1].group() != "(":
            continue
        _, spans = arguments(parts, i + 1)
        fields = request_fields(parts, spans)
        value, span = fields["symbol"]
        calls.append((value, key_cells(parts, span)))
    return calls


def verified_source(block, ident):
    block, alias_count = expand_chart_alias(block)
    changes = []
    routed = {}
    fill = follows_fill(block)
    capital = None
    if ident == 572:
        block, capital = constant_capital(block)
    for ordinal, (symbol, span) in enumerate(requests(block)):
        canonical = None
        if symbol in {'"BTC_USDT:swap"', "'BTCUSDT'"}:
            canonical = FUTURES
        if (params := SYMBOL_PARAMS.get(ident)) and symbol == params[0]:
            literal = "BINANCE:BTCUSDT" if params[1] == SPOT else "BTC_USDT:swap"
            param = "symbol" if ident == 3524 else symbol
            assert re.search(rf"(?m)^{param}\s*=\s*[^\n]+[\"']{literal}[\"']", block)
            if ident == 3524:
                assert re.search(
                    r'(?m)^inputSymbol\s*=\s*symbol\s*==\s*""\s*\?\s*syminfo\.tickerid\s*:\s*symbol\s*$',
                    block,
                )
            canonical = params[1]
        if (
            ident == 4575
            and symbol == 'syminfo.type=="forex"?"BTC_USDT:swap":"BTC_USDT:swap"'
        ):
            canonical = FUTURES
        if canonical:
            routed[ordinal] = canonical
            changes.append((*span, "syminfo.tickerid"))
        elif symbol in {
            "heikenashi(tickerid)",
            "heikinashi(syminfo.ticker)",
        } and ident in {860, 5281, 5588}:
            changes.append((*span, HA))
        elif symbol == "a" and ident in {3656, 4808}:
            assert re.search(r"(?m)^a\s*=\s*syminfo\.tickerid\s*$", block)
            changes.append((*span, "syminfo.tickerid"))
    assert changes
    if routed:
        assert re.search(
            r'(?m)^exchanges:\s*\[\{"eid":"Futures_Binance","currency":"BTC_USDT"',
            block,
        )
    parts = tokens(block)
    input_count = 0
    for i in range(len(parts) - 2):
        if [part.group() for part in parts[i : i + 3]] == ["input", ".", "symbol"]:
            field = parts[i + 2]
            changes.append((field.start(), field.end(), "string"))
            input_count += 1
    block = patch(block, changes)
    code, version, notes = prepare_source(
        block,
        with_heikin=True,
        isolated_literals=True,
        verified_fill_recalc=fill,
        chart_ticker_alias=True,
    )
    resolved = requests(code)
    assert all(resolved[n][0] == "syminfo.tickerid" for n in routed)
    code = patch(code, [(*resolved[n][1], symbol) for n, symbol in routed.items()])
    if routed:
        notes["fixed archived Binance BTC benchmark reference"] = len(routed)
    if input_count:
        notes["symbol input retained as fixed-default text"] = input_count
    if alias_count:
        notes["immutable chart ticker alias"] = alias_count
    if capital is not None:
        notes[f"archived constant capital {capital:g} USDT"] = 1
    if fill:
        notes["native OHLC recalculation after fills"] = 1
    return code, version, notes, fill, capital


def spot_minutes(cache):
    minutes, evidence = {}, []
    known = read(ROOT / "nonpine_replay.json")["market_data"]
    for date in ("2026-09", "2026-10", "2026-11-01", "2026-11-02", "2026-11-03"):
        name = f"klines-spot-BTCUSDT-1m-{date}.zip"
        raw = (cache / name).read_bytes()
        rec = known[name]
        assert checksum(raw) == rec["sha256_or_error"]
        evidence.append(
            {
                "market": "BTCUSDT spot",
                "url": rec["url"],
                "sha256": checksum(raw),
                "kind": "archive checksum",
            }
        )
        with (
            ZipFile(io.BytesIO(raw)) as archive,
            archive.open(
                name.removeprefix("klines-spot-").removesuffix(".zip") + ".csv"
            ) as stream,
        ):
            for line in csv.reader(io.TextIOWrapper(stream, encoding="ascii")):
                at = int(line[0])
                assert at % 60_000_000 == 0 and at // 1_000_000 not in minutes
                assert int(line[6]) == at + 59_999_999
                minutes[at // 1_000_000] = valid_values(line[1:6], line[8])
    assert len(minutes) == (max(minutes) + 60 - min(minutes)) // 60
    return minutes, evidence


def cross_worker(work):
    worker_for(work)
    path = work / "worker.mjs"
    code = path.read_text(encoding="utf-8")
    substitutions = {
        """          const requested = synthetic ? ticker.slice(0, -";heikinashi".length) : ticker;
          if (requested === symbol || (extra && requested === extra.prefix + ":" + symbol)) {
            if (!synthetic && key === interval) return candles;
            const feeds = synthetic ? extra?.heikinAshi : extra?.references;
            const secondary = feeds?.[symbol]?.[key]?.filter(row => row.openTime < lastTime);""": """          const raw = synthetic ? ticker.slice(0, -";heikinashi".length) : ticker;
          const requested = typeof raw === "string" && raw.startsWith("BINANCE:") ? raw.slice(8) : raw;
          if (requested === symbol || extra?.referenceSymbols?.includes(requested)) {
            if (requested === symbol && !synthetic && key === interval) return candles;
            const feeds = synthetic ? extra?.heikinAshi : extra?.references;
            const secondary = feeds?.[requested]?.[key]?.filter(row => row.openTime < lastTime);""",
        """        async getSymbolInfo() {
          return { ticker: symbol, tickerid: symbol, currency: extra?.currency ?? "USD", basecurrency: symbol.slice(0, 3),""": """        async getSymbolInfo(ticker) {
          const reference = String(ticker).replace(/^BINANCE:/, "").replace(/;heikinashi$/, "");
          const actual = extra?.referenceSymbols?.includes(reference) ? reference : symbol;
          return { ticker: actual, tickerid: actual, currency: extra?.currency ?? "USD", basecurrency: actual.slice(0, 3),""",
    }
    for before, after in substitutions.items():
        assert code.count(before) == 1
        code = code.replace(before, after)
    path.write_bytes(code.encode())
    return checksum(path.read_bytes())


def normalize_source(block, ident):
    if ident in {860, 5281}:
        block, count = re.subn(
            r"(\bsecurity\(heikenashi\(tickerid\),\s*)period(,)",
            r"\1timeframe.period\2",
            block,
        )
        assert count == 1
        return block, "legacy request timeframe uses the chart interval"
    if ident == 602:
        assert re.search(r"\bres\s*=\s*timeframe\.period\b", block)
        block, count = re.subn(
            r"(\brequest\.security\(sym,\s*)res(,)", r"\1timeframe.period\2", block
        )
        assert count == 1
        return block, "immutable chart timeframe alias"
    if ident == 3107:
        assert re.search(r"(?m)^context\s*=\s*request\.security\(", block)
        name_cells = [
            (t.start(), t.end(), "benchmarkPrice")
            for t in tokens(block)
            if t.group() == "context"
        ]
        assert len(name_cells) == 2
        return patch(block, name_cells), "unshadowed runtime-reserved variable name"
    if ident in {4645, 5175}:
        block, count = rsi_calls(block)
        if count > 0:
            return block, "classic RSI with proven archived integer length"
    return block, ""


def candidates(archive, recover=False):
    entries, coverage = [], []
    targets = {
        row["id"]: row
        for row in read(LEDGER)["disposition"]
        if row["reason"].startswith("Request needs another symbol")
        and not row["status"].startswith("Tested")
    }
    assert PLAN.keys() <= targets.keys()
    with ZipFile(archive) as z:
        for ident, item in targets.items():
            if recover and ident not in REPAIRS:
                continue
            source = item["source"]
            ref, path = unquote(source.split("/blob/", 1)[1]).split("/", 1)
            assert ref == FMZ_REF
            if ident not in PLAN:
                coverage.append(
                    [
                        ident,
                        "Pending · FMZ reference feeds",
                        "No archive-verified public feed or deterministic request routing in this pass",
                    ]
                )
                continue
            raw = z.read(f"strategies-{ref}/{path}")
            doc = raw.decode()
            blocks = script_blocks(doc, allow_fmz_shell=True)
            try:
                if len(blocks) != 1:
                    raise ValueError("No unique standalone Pine block")
                block, declaration = (
                    (blocks[0], {}) if isinstance(blocks[0], str) else blocks[0]
                )
                block, repair = (
                    normalize_source(block, ident) if recover else (block, "")
                )
                code, version, notes, fill, capital = verified_source(block, ident)
            except ValueError as exc:
                coverage.append([ident, "Pending · FMZ reference feeds", str(exc)])
                continue
            notes.update(declaration)
            if repair:
                notes[repair] = 1
            match = re.search(r"(?m)^period:\s*(\S+)", doc)
            entries.append(
                {
                    "id": ident,
                    "name": item["name"],
                    "source": source,
                    "hash": checksum(raw),
                    "archived": match[1] if match else "",
                    "code": code,
                    "old_version": version,
                    "repairs": notes,
                    "migration_sha256": checksum(code.encode()),
                    "allowFillRecalculation": fill,
                    **({"initialCapital": capital} if capital is not None else {}),
                }
            )
    return entries, coverage


def prepare(archive, previous_cache, cache, timeframes, work):
    work.mkdir(parents=True, exist_ok=True)
    entries, coverage = candidates(archive)
    base = read(timeframes / "preflight.json")
    data = read(timeframes / "candles.json")
    assert base["candles_sha256"] == checksum(
        (timeframes / "candles.json").read_bytes()
    )
    spot, spot_evidence = spot_minutes(previous_cache)
    for market in MARKETS:
        minutes, days, _ = complete_feed(market, cache, previous_cache)
        for period, (begin, end) in WINDOWS.items():
            start, stop = stamp(begin), stamp(end)
            meta = data["Binance · " + period]["market"]
            meta["referenceSymbols"] = ["BTCUSDT", "BTCUSDT_SPOT"]
            feed = {
                frame: reference_bars(
                    frame,
                    minutes,
                    days,
                    start + (28 * DAY if frame in {"1", "3", "5"} else 0),
                    stop,
                )
                for frame in ("1", "3", "5", "15", "30", "60", "D", "W")
            }
            meta["references"][market] = feed
            meta["heikinAshi"][market] = {f: heikin_bars(feed[f]) for f in ("15", "5")}
            if market == "BTCUSDT":
                meta["references"]["BTCUSDT_SPOT"] = {
                    str(length): [
                        rollup((spot[t] for t in range(at, c, 60)), at, c)
                        for at in range(min(spot), stop, length * 60)
                        if (c := min(stop, at + length * 60)) == at + length * 60
                    ]
                    for length in (15, 60)
                }
                # The terminal 60m span is needed for gaps-off carry-forward.
                if stop % 3600:
                    a = stop // 3600 * 3600
                    meta["references"]["BTCUSDT_SPOT"]["60"].append(
                        rollup((spot[t] for t in range(a, stop, 60)), a, a + 3600)
                    )
    write(work / "candles.json", data)
    write(work / "candidates.json", entries)
    write(
        work / "preflight.json",
        {
            "coverage": coverage,
            "windows": base["windows"],
            "bar_archives": base["bar_archives"] + spot_evidence,
            "base_disposition_sha256": checksum(LEDGER.read_bytes()),
            "source_revision": FMZ_REF,
            "minutes": 15,
            "reference_frames_by_id": PLAN,
            "candles_sha256": checksum((work / "candles.json").read_bytes()),
            "worker_sha256": cross_worker(work),
        },
    )
    print(f"{len(entries)} executable sources, {len(coverage)} pending preflight")


def prepare_recovery(archive, work, retry):
    entries, coverage = candidates(archive, recover=True)
    existing = {row["id"]: row for row in read(work / "candidates.json")}
    unchanged = {row["id"] for row in entries if row == existing.get(row["id"])}
    entries = [row for row in entries if row["id"] not in unchanged]
    retry.mkdir(parents=True, exist_ok=True)
    for name in ("candles.json", "worker.mjs", "isolation-probe.json"):
        copyfile(work / name, retry / name)
    write(retry / "candidates.json", entries)
    write(
        retry / "preflight.json",
        {"coverage": coverage, "retry_ids": [row["id"] for row in entries]},
    )
    print(f"{len(entries)} repaired sources, {len(coverage)} pending preflight")


def finalize(work, output, fixture, retry=None):
    report = read(work / "preflight.json")
    isolation = read(work / "isolation-probe.json")
    assert isolation == {"privateDenied": True, "networkDenied": True}
    for field, file in (
        ("candles_sha256", "candles.json"),
        ("worker_sha256", "worker.mjs"),
    ):
        assert report[field] == checksum((work / file).read_bytes())
    assert report["base_disposition_sha256"] == checksum(LEDGER.read_bytes())
    assert read(fixture)["worker_sha256"] == report["worker_sha256"]
    items = {row["id"]: row for row in read(work / "candidates.json")}
    receipts = read_receipts(work)
    assert receipts.keys() == items.keys()
    if retry is not None:
        assert (
            checksum((retry / "candles.json").read_bytes()) == report["candles_sha256"]
        )
        assert checksum((retry / "worker.mjs").read_bytes()) == report["worker_sha256"]
        assert read(retry / "isolation-probe.json") == isolation
        retried = read(retry / "preflight.json")
        ids = set(retried["retry_ids"])
        values = read_receipts(retry)
        replacements = {row["id"]: row for row in read(retry / "candidates.json")}
        assert values.keys() == replacements.keys() == ids
        assert all(i not in receipts or "reason" in receipts[i] for i in ids)
        report["coverage"] = [row for row in report["coverage"] if row[0] not in ids]
        report["recovery"] = retried
        items.update(replacements)
        receipts.update(values)
    results = []
    for ident, receipt in sorted(receipts.items()):
        item = items[ident]
        assert item["migration_sha256"] == checksum(item["code"].encode())
        if reason := receipt.get("reason"):
            report["coverage"].append([ident, "Pending · FMZ reference feeds", reason])
            continue
        samples = receipt["results"]
        reconcile(samples, report["windows"], item, 15)
        for row in samples:
            row.update(
                group=GROUP,
                quote_currency="USDT",
                market_data="Binance USD-M perpetuals",
                pine_source_version=item["old_version"],
                repairs=item["repairs"],
                migration_sha256=item["migration_sha256"],
            )
        results.extend(samples)
        status = f"Tested · {GROUP}" + (
            "" if any(row["trades"] for row in samples) else ", no closes"
        )
        note = "15m Binance USD-M charts; archived BTC benchmarks fixed to their public BTC derivatives or spot feed as declared."
        if ident in {860, 5281, 5588}:
            note = "15m Binance USD-M charts with source-directed Heikin-Ashi reference prices and real candle fills."
        report["coverage"].append([ident, status, note])
    report.update(
        coverage=sorted(report["coverage"]),
        results=results,
        engine="PineTS 0.13.1",
        engine_sha256=checksum((work.parent / "engine.mjs").read_bytes()),
        isolation_probe=isolation,
        requires_os_isolation=True,
        alignment_fixture_sha256=checksum(fixture.read_bytes()),
    )
    write(output, report)
    print(Counter(x[1] for x in report["coverage"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    steps = parser.add_subparsers(dest="stage", required=True)
    staging = steps.add_parser("prepare")
    for field in ("archive", "previous_cache", "cache", "timeframes", "work"):
        staging.add_argument(field, type=Path)
    recovery = steps.add_parser("prepare-recovery")
    for field in ("archive", "work", "retry"):
        recovery.add_argument(field, type=Path)
    final = steps.add_parser("finalize")
    final.add_argument("work", type=Path)
    final.add_argument("output", type=Path)
    final.add_argument("fixture", type=Path)
    final.add_argument("--retry", type=Path)
    args = vars(parser.parse_args())
    stage = args.pop("stage")
    {"prepare": prepare, "prepare-recovery": prepare_recovery, "finalize": finalize}[
        stage
    ](**args)
