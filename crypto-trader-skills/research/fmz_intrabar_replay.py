"""Retry pending Pine strategies with verified order-fill evaluation and minute feeds."""

import argparse
import csv
import hashlib
import io
import json
import math
import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pine_liquid_replay import MARKETS, WINDOWS, archived_candles
from research.delta_pine_followup import key_cells, patch
from research.delta_pine_repair import NO_QUOTED
from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.delta_pinets_migration import (
    VERSION,
    MigrationBlocked,
    arguments,
    keyword,
    tokens,
)
from research.delta_strategy_replay import ROOT, stamp
from research.fmz_marketdata_replay import (
    CONFIRMED_OFFSET,
    market_windows,
    prepare_source,
    request_fields,
    script_blocks,
)

SCOPE = (
    "Source requires tick or intrabar",
    "Source requires intrabar evaluation",
    "Request needs another symbol",
    "External data, visible chart",
    "Legacy session needs verified",
    "Unavailable market-data dependency:",
)
SERIES_HINT = re.compile(
    r"\b(?:calc_on_order_fills|heikinashi|security|security_lower_tf)\s*(?:\(|=)"
)
ALIAS = re.compile(
    r"(?m)^([A-Za-z_]\w*)\s*=\s*(?:(ticker\.)?heikinashi\(\s*"
    r"(?:syminfo\.ticker(?:id)?|tickerid)\s*\)|"
    r"syminfo\.ticker(?:id)?)\s*(?://[^\n]*)?$"
)
CAPITAL_LINE = re.compile(
    r"(?m)^strategy\.initial_capital[ \t]*=[ \t]*([1-9]\d*(?:\.\d+)?)[ \t]*(?://[^\n]*)?(?=\n|$)"
)
SNAPSHOT_MS = stamp(WINDOWS["Later"][1]) * 1000


def minute_archive(directory):
    source = read(ROOT / "nonpine_replay.json")["market_data"]
    start, stop = stamp(WINDOWS["Reference"][0]), stamp(WINDOWS["Later"][1])
    markets, evidence = {}, []
    for market in MARKETS:
        data = {}
        for date in ("2026-09", "2026-10", "2026-11-01", "2026-11-02", "2026-11-03"):
            name = f"klines-futures-{market}-1m-{date}.zip"
            path = directory / name
            spec = source[name]
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != spec["sha256_or_error"]:
                raise ValueError(f"Minute archive checksum mismatch: {name}")
            evidence.append({"name": name, "sha256": digest, "url": spec["url"]})
            with ZipFile(path) as archive:
                (name_in_zip,) = archive.namelist()
                with archive.open(name_in_zip) as stream:
                    for row in csv.DictReader(
                        io.TextIOWrapper(stream, encoding="ascii")
                    ):
                        time_ms = int(row["open_time"])
                        at = time_ms // 1000
                        if not start <= at < stop:
                            continue
                        opened, high, low, closed, volume = (
                            float(row[k])
                            for k in ("open", "high", "low", "close", "volume")
                        )
                        assert time_ms % 60_000 == 0 and at not in data
                        assert int(row["close_time"]) == time_ms + 59_999
                        assert all(
                            map(math.isfinite, (opened, high, low, closed, volume))
                        )
                        assert (
                            0
                            < low
                            <= min(opened, closed)
                            <= max(opened, closed)
                            <= high
                        )
                        assert volume >= 0 and (volume > 0) == (int(row["count"]) > 0)
                        data[at] = (opened, high, low, closed, volume)
        assert set(data) == set(range(start, stop, 60)), market
        markets[market] = data
    return markets, evidence


def minute_bars(data, first, stop, minutes):
    seconds = 60 * minutes
    for at in range(first, stop, seconds):
        parts = [data[t] for t in range(at, at + seconds, 60)]
        traded = [p for p in parts if p[4] > 0] or parts
        yield {
            "open": traded[0][0],
            "high": max(p[1] for p in traded),
            "low": min(p[2] for p in traded),
            "close": traded[-1][3],
            "volume": sum(p[4] for p in traded),
            "openTime": at * 1000,
            "closeTime": (at + seconds) * 1000,
        }


def market_data(five_path, minute_path):
    five, archived = archived_candles(five_path)
    one, minutes = minute_archive(minute_path)
    data, windows = market_windows(five, with_heikin=True)
    for period, (start, end) in WINDOWS.items():
        row = data["Binance · " + period]
        for market in MARKETS:
            for period_minutes in (1, 3):
                row["market"]["references"][market][str(period_minutes)] = list(
                    minute_bars(one[market], stamp(start), stamp(end), period_minutes)
                )
    return data, windows, archived, minutes


def follows_fill(code):
    parts = tokens(code)
    for i, token in enumerate(parts[:-1]):
        if token.group() == "strategy" and parts[i + 1].group() == "(":
            _, spans = arguments(parts, i + 1)
            return any(
                keyword(parts, s) == ("calc_on_order_fills", ["true"]) for s in spans
            )
    return False


def expand_chart_alias(code):
    """Inline a unique symbol assignment used only as an exact request argument."""
    masked = NO_QUOTED.sub(lambda m: " " * len(m.group()), code)
    changes, count = [], 0
    for m in ALIAS.finditer(code):
        name = m[1]
        if masked[m.start(1) : m.end(1)] != name:
            continue
        occurrences = list(re.finditer(r"\b" + re.escape(name) + r"\b", masked))
        if len(occurrences) < 2 or occurrences[0].start() != m.start(1):
            continue
        before = [masked[: v.start()].rstrip() for v in occurrences[1:]]
        if not all(re.search(r"\bsecurity\s*\($", prefix) for prefix in before):
            continue
        value = (
            "ticker.heikinashi(syminfo.tickerid)"
            if "heikinashi(" in m.group()
            else "syminfo.tickerid"
        )
        changes.append((m.start(), m.end(), ""))
        changes.extend((v.start(), v.end(), value) for v in occurrences[1:])
        count += 1
    return patch(code, changes), count


def confirm_future_looking_requests(code):
    """Construct an explicitly labeled delayed-signal variant."""
    version = VERSION.search(code)
    if not version:
        return code, 0
    parts, edits = tokens(code), []
    for i, token in enumerate(parts[:-1]):
        if token.group() != "security" or parts[i + 1].group() != "(":
            continue
        end, spans = arguments(parts, i + 1)
        fields = request_fields(parts, spans)
        frame = fields.get("timeframe", ("", None))[0]
        expr = fields.get("expression", ("", None))[0]
        if frame == "timeframe.period" or CONFIRMED_OFFSET.fullmatch(expr):
            continue
        setting, span = fields.get("lookahead", ("", None))
        if setting in {"true", "barmerge.lookahead_on"}:
            edits.append((*key_cells(parts, span), "barmerge.lookahead_off"))
        elif not setting and int(version[1]) < 3:
            pos = parts[end].start()
            edits.append((pos, pos, ", lookahead = barmerge.lookahead_off"))
    return patch(code, edits), len(edits)


def constant_capital(code):
    masked = NO_QUOTED.sub(lambda m: " " * len(m.group()), code)
    matches = list(CAPITAL_LINE.finditer(masked))
    writes = re.findall(r"\bstrategy\.initial_capital\s*(?::=|=(?!=|>))", masked)
    if len(matches) != 1 or len(writes) != 1:
        raise MigrationBlocked(
            "Capital override must be one unconditional top-level positive literal"
        )
    m = matches[0]
    prefix = masked[: m.start()]
    if re.search(
        r"\bstrategy\.(?:initial_capital|equity|entry|order|exit|close|close_all)\b",
        prefix,
    ):
        raise MigrationBlocked(
            "Broker state or order is used before the capital override"
        )
    value = float(m[1])
    if not math.isfinite(value):
        raise MigrationBlocked("Capital override is not finite")
    return patch(code, [(m.start(), m.end(), "")]), value


def snapshot_clock(code):
    masked = NO_QUOTED.sub("", code)
    if re.search(
        r"\btimenow[ \t]*(?::=|=(?!=))|\w+\([^)\n]*\btimenow\b[^)\n]*\)\s*=>", masked
    ):
        raise MigrationBlocked("Clock identifier is locally bound")
    positions = [t for t in tokens(code) if t.group() == "timenow"]
    if not positions:
        raise MigrationBlocked("No active built-in clock to anchor")
    return patch(code, [(t.start(), t.end(), str(SNAPSHOT_MS)) for t in positions])


def prepare(
    archive,
    backlog,
    five,
    minute,
    work,
    isolated=False,
    causal_only=False,
    capital_only=False,
    clock_only=False,
):
    inputs = read(backlog)
    records, entries = [], []
    with ZipFile(archive) as z:
        for raw_id, item in inputs.items():
            source = item["source"]
            if "/fmzquant/strategies/blob/" not in source:
                continue
            ident = int(raw_id)
            ref, path = unquote(source.split("/blob/", 1)[1]).split("/", 1)
            assert ref == FMZ_REF
            raw = z.read(f"strategies-{ref}/{path}")
            document = raw.decode("utf-8")
            reason = item["reason"]
            if causal_only and not (
                "lookahead" in reason.lower() or "future-looking default" in reason
            ):
                continue
            if capital_only and "wallet" not in reason:
                continue
            if clock_only and not re.search(r"\btimenow\b", document):
                continue
            target = (
                reason.startswith(SCOPE)
                or "Unavailable market-data dependency:" in reason
            )
            if not (
                causal_only or capital_only or clock_only or target
            ) and not re.search(r"\bcalc_on_order_fills\s*=\s*true", document):
                continue
            if not re.search(r"@version\s*=", document):
                continue
            codes = script_blocks(document, isolated)
            try:
                if len(codes) != 1:
                    raise MigrationBlocked("Requires one executable Pine strategy")
                block, declaration = (
                    (codes[0], {}) if isinstance(codes[0], str) else codes[0]
                )
                block, aliased = expand_chart_alias(block)
                capital = None
                if capital_only:
                    block, capital = constant_capital(block)
                if clock_only:
                    block = snapshot_clock(block)
                delayed = 0
                if causal_only:
                    block, delayed = confirm_future_looking_requests(block)
                    if not delayed:
                        raise MigrationBlocked(
                            "No literal historical lookahead setting with a verified equivalent timing rewrite"
                        )
                fill = follows_fill(block)
                if not (fill or capital_only or clock_only) and not SERIES_HINT.search(
                    block
                ):
                    raise MigrationBlocked(
                        "No supported minute feed or fill-recalculation dependency in source"
                    )
                code, version, repairs = prepare_source(
                    block,
                    with_heikin=True,
                    isolated_literals=isolated,
                    verified_fill_recalc=fill,
                    chart_ticker_alias=True,
                )
                repairs.update(declaration)
                if aliased:
                    repairs["immutable chart ticker alias"] = aliased
                if fill:
                    repairs["native OHLC recalculation after fills"] = 1
                if delayed:
                    repairs["delay unsafe request until candle confirmation"] = delayed
                if capital is not None:
                    repairs[f"archived constant capital {capital:g} USDT"] = 1
                if clock_only:
                    repairs["execution clock anchored at 4 Nov 2026 00:00 IST"] = 1
            except ValueError as exc:
                records.append([ident, "Pending · FMZ intrabar or feed", str(exc)])
                continue
            period = re.search(r"(?m)^period:\s*(\S+)", document)
            entries.append(
                {
                    "id": ident,
                    "name": item["name"],
                    "source": source,
                    "hash": hashlib.sha256(raw).hexdigest(),
                    "archived": period[1] if period else "",
                    "code": code,
                    "version": version,
                    "repairs": repairs,
                    "allowFillRecalculation": fill,
                    "confirmedVariant": bool(delayed),
                    "snapshotVariant": clock_only,
                    "adapted_sha256": hashlib.sha256(code.encode()).hexdigest(),
                    **({"initialCapital": capital} if capital is not None else {}),
                }
            )
    work.mkdir(parents=True, exist_ok=True)
    data, windows, archived, minute_evidence = market_data(five, minute)
    write(work / "candles.json", data)
    write(work / "candidates.json", entries)
    write(
        work / "screening.json",
        {
            "coverage": records,
            "bar_archives": archived,
            "minute_archives": minute_evidence,
            "windows": windows,
            "source_revision": FMZ_REF,
            "requires_os_isolation": isolated,
        },
    )
    print(
        "Admitted",
        len(entries),
        "including fill recalculation",
        sum(x["allowFillRecalculation"] for x in entries),
    )
    print("Unresolved at preflight", Counter(x[2] for x in records).most_common(12))


def finalize(work, output):
    screened = read(work / "screening.json")
    if screened["requires_os_isolation"]:
        probe = read(work / "isolation-probe.json")
        assert probe == {"privateDenied": True, "networkDenied": True}
        screened["isolation_probe"] = probe
    receipts = [
        json.loads(x)
        for x in (work / "out.jsonl").read_text(encoding="utf-8-sig").splitlines()
    ]
    items = {x["id"]: x for x in read(work / "candidates.json")}
    assert len(receipts) == len(items) and {x["id"] for x in receipts} == items.keys()
    rows = []
    for receipt in receipts:
        ident = receipt["id"]
        item = items[ident]
        if reason := receipt.get("reason"):
            screened["coverage"].append(
                [ident, "Pending · FMZ intrabar or feed", "Binance 15m: " + reason]
            )
            continue
        samples = receipt["results"]
        assert (
            len(samples) == 6
            and len({(x["period"], x["market"]) for x in samples}) == 6
        )
        fill = item["allowFillRecalculation"]
        delayed = item.get("confirmedVariant", False)
        capital = item.get("initialCapital")
        fixed_clock = item.get("snapshotVariant", False)
        group = (
            "FMZ · Capital override"
            if capital is not None
            else "FMZ · Clock snapshot"
            if fixed_clock
            else "FMZ · Confirmed variant"
            if delayed
            else "FMZ · Intrabar OHLC"
            if fill
            else "FMZ · Minute data"
        )
        for row in samples:
            assert row["source_sha256"] == item["hash"] and row["id"] == ident
            row.update(
                group=group,
                quote_currency="USDT",
                pine_source_version=item["version"],
                repairs=item["repairs"],
                migration_sha256=item["adapted_sha256"],
            )
        rows.extend(samples)
        status = "Tested · " + group
        if not any(x["trades"] for x in samples):
            status += ", no closes"
        detail = (
            f"Interpreted single literal workspace capital as {capital:g} USDT initial equity."
            if capital is not None
            else "Clock snapshot variant fixes evaluation time at the shared data cutoff, 4 Nov 2026 00:00 IST."
            if fixed_clock
            else "Confirmed variant delays future-looking requests to their historical close."
            if delayed
            else "PineTS historical OHLC path and source fill recalc. Full-bar inputs can expose intrabar lookahead."
            if fill
            else "Binance USD-M, 15m chart and available confirmed 1m/3m reference data."
        )
        if (delayed or fixed_clock or capital is not None) and fill:
            detail += " The fill emulator still uses the historical OHLC model."
        screened["coverage"].append([ident, status, detail])
    screened["coverage"].sort()
    screened.update(results=sorted(rows, key=lambda x: x["id"]), engine="PineTS 0.13.1")
    write(output, screened)
    print(Counter(x[1] for x in screened["coverage"]), len(rows), "result rows")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    stages = p.add_subparsers(dest="stage", required=True)
    for action, fields in (
        ("prepare", ("archive", "backlog", "five", "minute", "work")),
        ("finalize", ("work", "output")),
    ):
        plan = stages.add_parser(action)
        for field in fields:
            plan.add_argument(field, type=Path)
        if action == "prepare":
            plan.add_argument("--isolated", action="store_true")
            plan.add_argument("--causal-only", action="store_true")
            plan.add_argument("--capital-only", action="store_true")
            plan.add_argument("--clock-only", action="store_true")
    args = vars(p.parse_args())
    action = args.pop("stage")
    (prepare if action == "prepare" else finalize)(**args)
