"""Replay Pine strategies whose prior Binance attempts lacked reference bars."""

import argparse
import csv
import io
import json
import math
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlencode
from zipfile import ZipFile

from research.delta_pine_liquid_replay import (
    BINANCE,
    MARKETS,
    WINDOWS,
    archived_candles,
    checksum,
    download,
    prepare_candles,
)
from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.delta_strategy_replay import ROOT, stamp
from research.fmz_intrabar_replay import (
    confirm_future_looking_requests,
    expand_chart_alias,
    follows_fill,
)
from research.fmz_marketdata_replay import heikin_bars, prepare_source, script_blocks
from research.fmz_pine_remaining import make_worker
from research.fmz_round3_liquid_feeds import LEDGER, reconcile

DAY = 86_400
MINUTE_START = int(datetime(2026, 6, 1, tzinfo=UTC).timestamp())
DAILY_START = int(datetime(2020, 1, 1, tzinfo=UTC).timestamp())
DAILY_STOP = int(datetime(2026, 11, 4, tzinfo=UTC).timestamp())
GROUP = "FMZ Pine · Binance extended timeframes"
FRAMES = {
    657: ("D", "W", "M"),
    878: ("D", "W", "M"),
    1189: ("D", "W", "M"),
    1438: ("5D",),
    1592: ("600", "1440", "D"),
    1857: ("M",),
    1895: ("375",),
    2343: ("D", "W", "540", "720"),
    3074: ("12M",),
    3075: ("D", "M"),
    3395: ("M",),
    3407: ("34",),
    3493: ("M", "W"),
    3759: ("25", "75", "125"),
    4029: ("2", "5"),
    4060: ("D", "W", "M"),
    4062: ("D", "5D", "15D", "45D"),
    4212: ("W", "M"),
    4889: ("18",),
    4976: ("370",),
    5343: ("98",),
    5369: ("M",),
    5441: ("D", "W", "M"),
}


def valid_values(values, trades):
    opened, high, low, closed, volume = map(float, values)
    assert all(map(math.isfinite, (opened, high, low, closed, volume)))
    assert 0 < low <= min(opened, closed) <= max(opened, closed) <= high
    assert volume >= 0 and (volume > 0) == (int(trades) > 0)
    return opened, high, low, closed, volume


def complete_feed(market, cache, previous_cache):
    minutes, days, evidence = {}, {}, []
    known = read(ROOT / "nonpine_replay.json")["market_data"]
    for date in (
        "2026-06",
        "2026-07",
        "2026-08",
        "2026-09",
        "2026-10",
        "2026-11-01",
        "2026-11-02",
        "2026-11-03",
    ):
        folder = "monthly" if len(date) == 7 else "daily"
        name = f"{market}-1m-{date}.zip"
        url = f"{BINANCE}/{folder}/klines/{market}/1m/{name}"
        earlier = f"klines-futures-{name}"
        if earlier in known and (path := previous_cache / earlier).is_file():
            raw = path.read_bytes()
            assert known[earlier]["url"] == url
            assert checksum(raw) == known[earlier]["sha256_or_error"]
        else:
            raw = download(url, cache / name)
            assert download(
                url + ".CHECKSUM", cache / (name + ".CHECKSUM")
            ).decode().split() == [checksum(raw), name]
        evidence.append(
            {
                "market": market,
                "url": url,
                "sha256": checksum(raw),
                "kind": "archive checksum",
            }
        )
        with (
            ZipFile(io.BytesIO(raw)) as z,
            z.open(name.removesuffix(".zip") + ".csv") as stream,
        ):
            for line in csv.DictReader(io.TextIOWrapper(stream, encoding="ascii")):
                at = int(line["open_time"])
                assert at % 60_000 == 0 and at // 1000 not in minutes
                assert int(line["close_time"]) == at + 59_999
                minutes[at // 1000] = valid_values(
                    [line[key] for key in ("open", "high", "low", "close", "volume")],
                    line["count"],
                )
    assert sorted(minutes) == list(range(MINUTE_START, DAILY_STOP, 60))
    for first in range(DAILY_START, DAILY_STOP, 1_000 * DAY):
        stop = min(DAILY_STOP, first + 1_000 * DAY)
        name = f"{market}-1d-{datetime.fromtimestamp(first, UTC):%Y-%m-%d}.json"
        query = urlencode(
            {
                "symbol": market,
                "interval": "1d",
                "limit": 1000,
                "startTime": first * 1000,
                "endTime": stop * 1000 - 1,
            }
        )
        url = f"https://fapi.binance.com/fapi/v1/klines?{query}"
        raw = download(url, cache / name)
        evidence.append(
            {
                "market": market,
                "url": url,
                "sha256": checksum(raw),
                "kind": "public REST response",
            }
        )
        batch = json.loads(raw)
        assert [line[0] for line in batch] == list(
            range(first * 1000, stop * 1000, DAY * 1000)
        )
        for line in batch:
            assert line[6] == line[0] + DAY * 1000 - 1
            days[line[0] // 1000] = valid_values(line[1:6], line[8])
    for at in range(MINUTE_START, DAILY_STOP, DAY):
        merged = rollup((minutes[t] for t in range(at, at + DAY, 60)), at, at + DAY)
        actual = tuple(
            merged[key] for key in ("open", "high", "low", "close", "volume")
        )
        assert actual[:4] == days[at][:4] and math.isclose(
            actual[4], days[at][4], abs_tol=1e-6
        ), (market, at)
    return minutes, days, evidence


def rollup(values, first, stop):
    rows = list(values)
    traded = [row for row in rows if row[4] > 0] or rows
    return {
        "open": traded[0][0],
        "high": max(row[1] for row in traded),
        "low": min(row[2] for row in traded),
        "close": traded[-1][3],
        "volume": math.fsum(row[4] for row in traded),
        "openTime": first * 1000,
        "closeTime": stop * 1000,
    }


def periods(frame, start, stop):
    if frame.isdecimal():
        length = int(frame) * 60
        for day in range(start, stop, DAY):
            for at in range(day, min(day + DAY, stop), length):
                yield at, min(day + DAY, at + length)
        return
    count = int(frame[:-1] or 1)
    if frame.endswith("W"):
        assert count == 1
        first = start + ((7 - datetime.fromtimestamp(start, UTC).weekday()) % 7) * DAY
        for at in range(first, stop, 7 * DAY):
            yield at, at + 7 * DAY
        return
    for year in range(2020, 2027):
        jan = int(datetime(year, 1, 1, tzinfo=UTC).timestamp())
        next_year = int(datetime(year + 1, 1, 1, tzinfo=UTC).timestamp())
        if frame.endswith("D"):
            for at in range(jan, min(next_year, stop), count * DAY):
                if at >= start:
                    yield at, min(at + count * DAY, next_year)
        else:
            assert frame.endswith("M") and 12 % count == 0
            for month in range(1, 13, count):
                at = int(datetime(year, month, 1, tzinfo=UTC).timestamp())
                if start <= at < stop:
                    after = (
                        int(datetime(year, month + count, 1, tzinfo=UTC).timestamp())
                        if month + count <= 12
                        else next_year
                    )
                    yield at, after


def reference_bars(frame, minutes, days, start, stop):
    first = MINUTE_START if frame.isdecimal() else DAILY_START
    result = []
    for at, natural_end in periods(frame, first, stop):
        if frame.isdecimal():
            if natural_end < start - 30 * DAY:
                continue
            values = [minutes[t] for t in range(at, min(stop, natural_end), 60)]
        else:
            end = min(stop, natural_end)
            full_days_end = end // DAY * DAY
            values = [days[t] for t in range(at, full_days_end, DAY)]
            if full_days_end < end:
                partial = rollup(
                    (minutes[t] for t in range(full_days_end, end, 60)),
                    full_days_end,
                    end,
                )
                values.append(
                    tuple(
                        partial[k] for k in ("open", "high", "low", "close", "volume")
                    )
                )
        # A partially covered terminal bar retains its natural close. The Pine
        # historical matcher needs its span to return the preceding closed bar.
        result.append(rollup(values, at, natural_end))
    assert result and result[-1]["openTime"] < stop * 1000 <= result[-1]["closeTime"]
    return result


def worker_for(work, timeout=55_000):
    make_worker(work, timeout)
    path = work / "worker.mjs"
    code = path.read_text(encoding="utf-8")
    old = """            const secondary = feeds?.[symbol]?.[key]?.filter(
              row => row.openTime >= firstTime && row.closeTime <= lastTime
            );"""
    new = """            const secondary = feeds?.[symbol]?.[key]?.filter(row => row.openTime < lastTime);"""
    assert code.count(old) == 1
    path.write_bytes(code.replace(old, new).encode())
    return checksum(path.read_bytes())


def prepare(archive, five_cache, previous_cache, cache, work):
    cache.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    entries, coverage = [], []
    targets = {
        row["id"]: row
        for row in read(LEDGER)["disposition"]
        if "Unavailable market-data dependency:" in row["reason"]
        and not row["status"].startswith("Tested")
    }
    assert targets.keys() == FRAMES.keys()
    with ZipFile(archive) as z:
        for ident, item in targets.items():
            source = item["source"]
            ref, path = unquote(source.split("/blob/", 1)[1]).split("/", 1)
            assert ref == FMZ_REF
            raw = z.read(f"strategies-{ref}/{path}")
            doc = raw.decode()
            blocks = script_blocks(doc, allow_fmz_shell=True)
            try:
                if len(blocks) != 1:
                    raise ValueError("No unique standalone Pine block")
                block, declaration = (
                    (blocks[0], {}) if isinstance(blocks[0], str) else blocks[0]
                )
                block, aliased = expand_chart_alias(block)
                if item["selected_report"] == "fmz-confirmed-variant-replay.json":
                    block, delayed = confirm_future_looking_requests(block)
                    assert delayed > 0
                else:
                    delayed = 0
                fill = follows_fill(block)
                code, version, notes = prepare_source(
                    block,
                    with_heikin=True,
                    isolated_literals=True,
                    verified_fill_recalc=fill,
                    chart_ticker_alias=True,
                )
            except ValueError as exc:
                coverage.append([ident, "Pending · FMZ extended timeframes", str(exc)])
                continue
            notes.update(declaration)
            if aliased:
                notes["immutable chart ticker alias"] = aliased
            if delayed:
                notes["delay unsafe request until candle confirmation"] = delayed
            if fill:
                notes["native OHLC recalculation after fills"] = 1
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
                    "confirmed_variant": bool(delayed),
                }
            )
    five, bar_evidence = archived_candles(five_cache)
    data, windows = prepare_candles(five, 15)
    frames = sorted({label for series in FRAMES.values() for label in series})
    for market in MARKETS:
        minutes, days, evidence = complete_feed(market, cache, previous_cache)
        bar_evidence.extend(evidence)
        for period, (begin, end) in WINDOWS.items():
            start, stop = stamp(begin), stamp(end)
            row = data[period]
            feeds = row.setdefault("references", {})
            heikin = row.setdefault("heikinAshi", {})
            feeds[market] = {
                frame: reference_bars(frame, minutes, days, start, stop)
                for frame in frames
            }
            heikin[market] = {
                frame: heikin_bars(feeds[market][frame]) for frame in FRAMES[1189]
            }
    for row in data.values():
        row["market"] = {
            **row["market"],
            "references": row.pop("references"),
            "heikinAshi": row.pop("heikinAshi"),
        }
    data = {"Binance · " + period: row for period, row in data.items()}
    windows = {"Binance · " + period: row for period, row in windows.items()}
    write(work / "candles.json", data)
    write(work / "candidates.json", entries)
    write(
        work / "preflight.json",
        {
            "coverage": coverage,
            "windows": windows,
            "bar_archives": bar_evidence,
            "base_disposition_sha256": checksum(LEDGER.read_bytes()),
            "source_revision": FMZ_REF,
            "minutes": 15,
            "reference_frames": frames,
            "reference_frames_by_id": FRAMES,
            "candles_sha256": checksum((work / "candles.json").read_bytes()),
            "worker_sha256": worker_for(work),
            "alignment": {
                "minute_bars": "UTC day grid with last bucket shortened at UTC day end",
                "daily_groups": "UTC year grid",
                "weekly_bars": "Monday UTC",
                "monthly_bars": "UTC calendar",
                "terminal_bar": "as-of-window candle retained at its natural close and used to align prior confirmed bars",
            },
        },
    )
    print(f"{len(entries)} executable sources, {len(coverage)} pending preflight")


def read_receipts(work):
    rows = [
        json.loads(line)
        for line in (work / "out.jsonl").read_text(encoding="utf-8-sig").splitlines()
    ]
    assert len(rows) == len({row["id"] for row in rows})
    return {row["id"]: row for row in rows}


def prepare_retry(work, retry):
    receipts = read_receipts(work)
    retry_ids = {
        i
        for i, row in receipts.items()
        if row.get("reason") == "PineTS per-source time or memory budget exceeded"
    }
    assert retry_ids
    retry.mkdir(parents=True, exist_ok=True)
    candidates = [
        row for row in read(work / "candidates.json") if row["id"] in retry_ids
    ]
    assert len(candidates) == len(retry_ids)
    data = read(work / "candles.json")
    needed = {frame for ident in retry_ids for frame in FRAMES[ident]}
    for window in data.values():
        for key in ("references", "heikinAshi"):
            for symbol, frames in window["market"][key].items():
                window["market"][key][symbol] = {
                    f: bars for f, bars in frames.items() if f in needed
                }
    write(retry / "candidates.json", candidates)
    write(retry / "candles.json", data)
    write(
        retry / "preflight.json",
        {
            "candidate_ids": sorted(retry_ids),
            "frames": sorted(needed),
            "timeout_ms": 115_000,
            "candles_sha256": checksum((retry / "candles.json").read_bytes()),
            "worker_sha256": worker_for(retry, timeout=115_000),
        },
    )


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
        extra = read(retry / "preflight.json")
        assert read(retry / "isolation-probe.json") == isolation
        for field, file in (
            ("candles_sha256", "candles.json"),
            ("worker_sha256", "worker.mjs"),
        ):
            assert extra[field] == checksum((retry / file).read_bytes())
        recovered = read_receipts(retry)
        eligible = {
            i
            for i, row in receipts.items()
            if row.get("reason") == "PineTS per-source time or memory budget exceeded"
        }
        assert recovered.keys() == eligible == set(extra["candidate_ids"])
        assert all(items[row["id"]] == row for row in read(retry / "candidates.json"))
        receipts.update(recovered)
        report["retry"] = extra
    results = []
    for receipt in sorted(receipts.values(), key=lambda row: row["id"]):
        ident = receipt["id"]
        item = items[ident]
        assert item["migration_sha256"] == checksum(item["code"].encode())
        if reason := receipt.get("reason"):
            report["coverage"].append(
                [ident, "Pending · FMZ extended timeframes", reason]
            )
            continue
        samples = receipt["results"]
        reconcile(samples, report["windows"], item, 15)
        group = GROUP + (
            ", confirmed timing variant" if item["confirmed_variant"] else ""
        )
        for row in samples:
            row.update(
                group=group,
                quote_currency="USDT",
                market_data="Binance USD-M perpetuals",
                pine_source_version=item["old_version"],
                repairs=item["repairs"],
                migration_sha256=item["migration_sha256"],
            )
        results.extend(samples)
        status = f"Tested · {group}" + (
            "" if any(row["trades"] for row in samples) else ", no closes"
        )
        note = "Binance USD-M 15m chart with public extended references: " + ", ".join(
            FRAMES[ident]
        )
        if item["confirmed_variant"]:
            note += ". Future-looking request timing delayed until confirmation."
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
    assert len(report["coverage"]) == len(FRAMES)
    write(output, report)
    print(Counter(x[1] for x in report["coverage"]))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    stages = cli.add_subparsers(dest="stage", required=True)
    staging = stages.add_parser("prepare")
    for field in ("archive", "five_cache", "previous_cache", "cache", "work"):
        staging.add_argument(field, type=Path)
    recheck = stages.add_parser("prepare-retry")
    recheck.add_argument("work", type=Path)
    recheck.add_argument("retry", type=Path)
    final = stages.add_parser("finalize")
    final.add_argument("work", type=Path)
    final.add_argument("output", type=Path)
    final.add_argument("fixture", type=Path)
    final.add_argument("--retry", type=Path)
    params = vars(cli.parse_args())
    stage = params.pop("stage")
    {"prepare": prepare, "prepare-retry": prepare_retry, "finalize": finalize}[stage](
        **params
    )
