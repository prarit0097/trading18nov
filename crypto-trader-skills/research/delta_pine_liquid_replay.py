"""Re-run pending FMZ Pine strategies on archived Binance USD-M trade candles."""

import argparse
import csv
import hashlib
import io
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import unquote
from urllib.request import urlopen
from zipfile import ZipFile

from research.delta_pine_followup import followup, records_from
from research.delta_pine_repair import NO_QUOTED, repair
from research.delta_pinets_catalogue import FMZ_REF, aggregate, eligibility, read, source_block, write
from research.delta_pinets_migration import MigrationBlocked, migrate
from research.delta_strategy_replay import BAR, LATER, ROOT, stamp

BINANCE = "https://data.binance.vision/data/futures/um"
MARKETS = ("BTCUSDT", "ETHUSDT")
POOLED = "BTCUSDT + ETHUSDT"
GROUP = "FMZ Pine · Binance USD-M"
MARKET = {
    "prefix": "BINANCE", "currency": "USDT",
    "symbols": {"BTCUSDT": {"tick": .1, "step": .001}, "ETHUSDT": {"tick": .01, "step": .001}},
}
WINDOWS = {"Reference": ("2026-09-23", "2026-10-21"), "Later": LATER}
REPORTS = (
    "delta-pinets-catalogue.json",
    "delta-pinets-migration.json",
    "delta-pine-repair.json",
    "delta-pine-followup.json",
)
BUDGET_EXCEEDED = "PineTS per-source time or memory budget exceeded"
INVALID_CLOCK = re.compile(
    r"\b(?:timenow|isrealtime|islastconfirmedhistory)\b|\[\s*-\d|"
    r"\b(?:heikinashi|renko|kagi|linebreak|pointfigure)\s*\("
)


def checksum(raw):
    return hashlib.sha256(raw).hexdigest()


def download(url, location):
    if not location.exists():
        with urlopen(url, timeout=30) as response:
            location.write_bytes(response.read())
    return location.read_bytes()


def archived_candles(work):
    data, files = {}, []
    for symbol in MARKETS:
        data[symbol] = rows = {}
        for date in ("2026-09", "2026-10", "2026-11-01", "2026-11-02", "2026-11-03"):
            folder = "monthly" if len(date) == 7 else "daily"
            name = f"{symbol}-5m-{date}"
            url = f"{BINANCE}/{folder}/klines/{symbol}/5m/{name}.zip"
            raw = download(url, work / f"{name}.zip")
            published = download(url + ".CHECKSUM", work / f"{name}.zip.CHECKSUM")
            digest = checksum(raw)
            assert published.decode().split() == [digest, f"{name}.zip"], url
            files.append({"market": symbol, "url": url, "sha256": digest})
            with ZipFile(io.BytesIO(raw)) as archive, archive.open(f"{name}.csv") as stream:
                for row in csv.DictReader(io.TextIOWrapper(stream, encoding="ascii")):
                    time = int(row["open_time"])
                    assert time % (BAR * 1000) == 0 and time // 1000 not in rows, (symbol, time)
                    assert int(row["close_time"]) == time + BAR * 1000 - 1, (symbol, time)
                    candle = {key: float(row[key]) for key in ("open", "high", "low", "close", "volume")}
                    assert all(map(math.isfinite, candle.values())), (symbol, time)
                    assert 0 < candle["low"] <= min(candle["open"], candle["close"]), (symbol, time)
                    assert max(candle["open"], candle["close"]) <= candle["high"], (symbol, time)
                    assert candle["volume"] >= 0 and (candle["volume"] > 0) == (int(row["count"]) > 0), (symbol, time)
                    rows[time // 1000] = candle
    return data, files


def prepare_candles(data, minutes):
    interval = minutes * 60
    windows, metadata = {}, {}
    for label, (start_ist, end_ist) in WINDOWS.items():
        first = ((stamp(start_ist) + interval - 1) // interval) * interval
        stop = stamp(end_ist) // interval * interval
        markets = {symbol: aggregate(rows, first, stop, interval) for symbol, rows in data.items()}
        windows[label] = {**markets, "market": MARKET}
        counts = {s: sum(map(len, groups)) for s, groups in markets.items()}
        assert all(n == (stop - first) // interval for n in counts.values()), (label, minutes, counts)
        metadata[label] = {
            "start_ist": start_ist,
            "end_ist_exclusive": end_ist,
            "first_bar_open_ms": first * 1000,
            "last_bar_close_ms": stop * 1000,
            "bars": counts,
            "segments": {s: len(groups) for s, groups in markets.items()},
            "untraded_bars": {
                s: sum(candle["volume"] == 0 for group in groups for candle in group)
                for s, groups in markets.items()
            },
        }
    return windows, metadata


def target_strategies():
    reports = [read(ROOT / name) for name in REPORTS]
    completed = {row["id"] for report in reports for row in report["results"]}
    targets = {}
    for name, report in zip(REPORTS, reports, strict=True):
        for i, _, reason in report["coverage"]:
            interval = re.search(r"(\d+)m: Broker used an untraded candle$", reason)
            if i not in completed and interval and (i not in targets or reason == interval[0]):
                targets[i] = (name, int(interval[1]), reason)
    return targets


def compatible_code(block, report):
    repairs = {}
    if report == REPORTS[0]:
        if problem := eligibility(block):
            raise MigrationBlocked(problem)
        header = re.compile(r"(?m)^\s*//\s*@version\s*=\s*([56])")
        version = int(header.search(block)[1])
        normalized = header.sub(r"//@version=\1", block)
        code, transforms = re.sub(r"/\*.*?\*/", "", normalized, flags=re.DOTALL).strip(), {}
    elif report == REPORTS[1]:
        try:
            code, version, transforms = migrate(
                block, allow_read_only_legacy=True, resolve_shadowed=True
            )
        except MigrationBlocked:
            code, version, transforms = migrate(block)
    elif report == REPORTS[2]:
        code, version, transforms, repairs = repair(block)
    else:
        code, version, transforms, repairs = followup(block)
    executable = re.sub(r"(?m)//.*$", "", NO_QUOTED.sub("", code))
    if INVALID_CLOCK.search(executable):
        raise MigrationBlocked("Wall-clock, realtime, future-index or synthetic-chart dependency")
    if re.search(r"\brandom\s*\(", executable):
        raise MigrationBlocked("Source uses randomness without a verified deterministic replay")
    return code, version, transforms, repairs


def prepare(archive, work):
    work.mkdir(parents=True, exist_ok=True)
    targets = target_strategies()
    coverage, jobs = [], defaultdict(list)
    for label, (start, stop) in WINDOWS.items():
        assert stamp(start) < stamp(stop), label
    with ZipFile(archive) as fmz, (ROOT / "public-strategy-catalogue.csv").open(encoding="utf-8-sig") as stream:
        for i, row in enumerate(csv.DictReader(stream), 1):
            if i not in targets:
                continue
            report, minutes, reason = targets[i]
            path = unquote(row["source_url"].split(f"/{FMZ_REF}/", 1)[1])
            document = fmz.read(f"strategies-{FMZ_REF}/{path}")
            blocks = source_block(document.decode("utf-8"))
            try:
                if len(blocks) != 1:
                    raise MigrationBlocked("No single supported Pine strategy in the pinned document")
                code, version, transforms, repairs = compatible_code(blocks[0], report)
            except (MigrationBlocked, ValueError) as exc:
                coverage.append([i, "FMZ Pine liquid replay pending", str(exc)])
                continue
            archived = re.search(r"(?m)^period:\s*(\S+)", blocks[0])
            jobs[minutes].append({
                "id": i, "name": row["name"], "source": row["source_url"],
                "hash": checksum(document), "archived": archived[1] if archived else "",
                "code": code, "old_version": version, "migration_sha256": checksum(code.encode()),
                "transforms": transforms, "repairs": repairs, "prior_report": report, "prior_reason": reason,
            })
    assert len(coverage) + sum(map(len, jobs.values())) == len(targets)
    base, archives = archived_candles(work)
    windows_by_minutes = {}
    for minutes in sorted({5, 15, 30, *jobs}):
        folder = work / str(minutes)
        folder.mkdir(exist_ok=True)
        candles, metadata = prepare_candles(base, minutes)
        write(folder / "candles.json", candles)
        windows_by_minutes[str(minutes)] = metadata
        if minutes in jobs:
            write(folder / "candidates.json", jobs[minutes])
    worker = (ROOT / "delta_pinets_worker.mjs").read_text(encoding="utf-8").encode()
    (work / "worker.mjs").write_bytes(worker)
    write(work / "batches.json", {
        "coverage": coverage, "bar_archives": archives, "windows_by_minutes": windows_by_minutes,
        "worker_sha256": checksum(worker), "job_minutes": sorted(jobs),
    })
    print("Candidates by interval", {m: len(v) for m, v in sorted(jobs.items())}, "blocked before worker", len(coverage), flush=True)


def finalize(work, destination):
    manifest = read(work / "batches.json")
    assert manifest["worker_sha256"] == checksum((work / "worker.mjs").read_bytes())
    coverage = list(manifest["coverage"])
    rows = []
    for minutes in manifest["job_minutes"]:
        folder = work / str(minutes)
        candidates = {x["id"]: x for x in read(folder / "candidates.json")}
        records = records_from(folder)
        assert candidates.keys() == records.keys(), minutes
        retry_file = folder / "retry-out.jsonl"
        if retry_file.exists():
            retry = [json.loads(line) for line in retry_file.read_text(encoding="utf-8-sig").splitlines()]
            retry_ids = {row["id"] for row in retry}
            assert len(retry_ids) == len(retry) and retry_ids == {
                i for i, row in records.items() if row.get("reason") == BUDGET_EXCEEDED
            }
            records.update((row["id"], row) for row in retry)
        for i, record in sorted(records.items()):
            item = candidates[i]
            if "reason" in record:
                coverage.append([i, "FMZ Pine liquid replay pending", f"{minutes}m Binance USD-M: {record['reason']}"])
                continue
            result = record["results"]
            assert len(result) == 6 and {(x["period"], x["market"]) for x in result} == {
                (period, market) for period in WINDOWS for market in (*MARKETS, POOLED)
            }
            for row in result:
                assert (row["id"], row["source_sha256"], row["interval"]) == (i, item["hash"], f"{minutes}m")
                row.update(
                    group=GROUP, quote_currency="USDT", market_data="Binance USD-M perpetuals",
                    pine_source_version=item["old_version"], migration_sha256=item["migration_sha256"],
                    transforms=item["transforms"], repairs=item["repairs"],
                )
            for period in WINDOWS:
                values = {x["market"]: x for x in result if x["period"] == period}
                for field in ("trades", "unsettled", "gross_wins", "fee_wins", "net_wins"):
                    assert values[POOLED][field] == sum(values[s][field] for s in MARKETS), (i, period, field)
                for field in ("gross", "after_fees", "net"):
                    assert math.isclose(
                        values[POOLED][field], sum(values[s][field] for s in MARKETS), abs_tol=1e-6
                    ), (i, period, field)
            rows.extend(result)
            closes = any(x["trades"] for x in result)
            status = "Tested · Pine Binance USD-M" if closes else "Tested · Pine Binance USD-M, no closes"
            coverage.append([i, status, f"{minutes}m PineTS replay using Binance USD-M BTCUSDT/ETHUSDT. Prior Delta replay: {item['prior_reason']}."])
    assert len(coverage) == len(target_strategies()) and {x[0] for x in coverage} == target_strategies().keys()
    write(destination, {
        "engine": "PineTS 0.13.1", "source_revision": FMZ_REF,
        "market_data": "Binance USD-M BTCUSDT and ETHUSDT perpetual contracts",
        "quote_currency": "USDT", "bar_archives": manifest["bar_archives"], "worker_sha256": manifest["worker_sha256"],
        "windows_by_minutes": {str(m): manifest["windows_by_minutes"][str(m)] for m in manifest["job_minutes"]},
        "candle_files_sha256": {
            str(m): checksum((work / str(m) / "candles.json").read_bytes()) for m in manifest["job_minutes"]
        },
        "coverage": sorted(coverage), "results": sorted(rows, key=lambda row: row["id"]),
    })
    print(Counter(x[1] for x in coverage), "result rows", len(rows))
    print("Unresolved", Counter(x[2] for x in coverage if "pending" in x[1]))


def prepare_retry(work):
    for minutes in read(work / "batches.json")["job_minutes"]:
        folder = work / str(minutes)
        ids = {i for i, row in records_from(folder).items() if row.get("reason") == BUDGET_EXCEEDED}
        if ids:
            candidates = [x for x in read(folder / "candidates.json") if x["id"] in ids]
            assert {x["id"] for x in candidates} == ids
            write(folder / "retry-candidates.json", candidates)
            print(f"{minutes}m serial retries", sorted(ids), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("prepare").add_argument("archive", type=Path)
    sub.add_parser("prepare-retry")
    sub.add_parser("finalize").add_argument("destination", type=Path)
    for action in sub.choices.values():
        action.add_argument("work", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.archive, args.work)
    elif args.action == "prepare-retry":
        prepare_retry(args.work)
    else:
        finalize(args.work, args.destination)
