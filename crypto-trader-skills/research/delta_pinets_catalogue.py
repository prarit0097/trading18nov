"""Prepare and reconcile the remaining FMZ catalogue for the offline PineTS engine."""

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from itertools import groupby
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_strategy_replay import (
    BAR,
    COINS,
    EXECUTION,
    FEE,
    LATER,
    NOTIONAL,
    REFERENCES,
    ROOT,
    load,
    stamp,
    summarize,
)

FMZ_REF = "7853bb2bf262c4567ac238d3552d97f0e50cb801"
INTERVAL = 15 * 60
PRIOR = (
    "delta-fmz-replay.json",
    "delta-fmz-priced-replay.json",
    "delta-fmz-staged-replay.json",
)
EXTERNAL = re.compile(
    r"\b(?:request\s*\.|security\s*\(|security_lower_tf\s*\(|import\b|"
    r"lookahead_on\b|chart\s*\.\s*(?:left|right)_visible_bar_time)"
)
UNSAFE_HOST = re.compile(
    r"\b(?:process|require|module|globalThis|global|Buffer|XMLHttpRequest|WebSocket|"
    r"fetch|constructor|__proto__|prototype|eval|Function|Deno|Bun)\b"
)


def read(path):
    return json.loads(path.read_bytes())


def write(path, data):
    path.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def aggregate(data, first, end, interval=INTERVAL):
    candles = []
    for t in range(first, end, interval):
        parts = [data.get(k) for k in range(t, t + interval, BAR)]
        if not all(parts):
            continue
        traded = [x for x in parts if x["volume"] > 0]
        bars = traded or parts
        candles.append(
            {
                "open": bars[0]["open"],
                "close": bars[-1]["close"],
                "high": max(x["high"] for x in bars),
                "low": min(x["low"] for x in bars),
                "volume": sum(x["volume"] for x in bars),
                "openTime": t * 1000,
                "closeTime": (t + interval) * 1000,
            }
        )
    groups = groupby(
        enumerate(candles), key=lambda x: x[1]["openTime"] - x[0] * interval * 1000
    )
    return [[c for _, c in group] for _, group in groups]


def source_block(document):
    blocks = re.findall(r"(?ms)^\x60{3}[^\n]*\n(.*?)^\x60{3}", document)
    return [
        b
        for b in blocks
        if re.search(r"\bstrategy\s*\(", b)
        and re.search(r"\bstrategy\.(?:entry|order)\s*\(", b)
    ]


def eligibility(
    block,
    *,
    verified_requests=False,
    isolated_literals=False,
    verified_fill_recalc=False,
):
    version = re.search(r"(?m)^\s*//\s*@version\s*=\s*(\d+)", block)
    if not version or version[1] not in ("5", "6"):
        return "Pine 2–4 or unversioned source needs a compatible runtime"
    code = re.sub(r"/\*.*?\*/", "", block, flags=re.DOTALL)
    if isolated_literals:
        # This option is reserved for an independently verified no-network
        # process sandbox. Preserve source strings and screen executable tokens.
        executable = re.sub(
            r"""//[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'""", " ", code
        )
        if '"' in executable or "'" in executable:
            return "Source outside the isolated Pine runner's supported syntax"
    else:
        executable = re.sub(r"(?m)//.*$", "", code)
    if UNSAFE_HOST.search(executable) or re.search(r"[{};\\\x60]", executable):
        return "Source outside the isolated Pine runner's supported syntax"
    stripped = re.sub(r"""("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')""", "", executable)
    if (EXTERNAL.search(stripped) and not verified_requests) or re.search(
        r"\binput\.symbol\b", stripped
    ):
        return "External data, visible chart range or imported library required"
    intrabar = ["calc_on_every_tick", "use_bar_magnifier", "calc_on_every_history_tick"]
    if not verified_fill_recalc:
        intrabar.append("calc_on_order_fills")
    if re.search(r"\b(?:" + "|".join(intrabar) + r")\s*=\s*(?!\s*false\b)", stripped):
        return "Source requires tick or intrabar recalculation"
    if len(code) > 85000:
        return "Source exceeds offline evaluator size limit"
    return None


def datasets(reference, later, archive_reports, interval, *, align_epoch=False):
    manifest = read(REFERENCES)
    windows, meta = {}, {}
    for label, start, end, path in [
        (
            "Reference",
            manifest["from_ist"][:10],
            manifest["to_ist_exclusive"][:10],
            reference,
        ),
        ("Later", *LATER, later),
    ]:
        candles, hashes = load(path)
        assert all(x["candle_sha256"][label] == hashes for x in archive_reports)
        first, stop = stamp(start), stamp(end)
        if align_epoch:
            first = ((first + interval - 1) // interval) * interval
            stop = (stop // interval) * interval
        windows[label] = {
            s: aggregate(candles[s], first, stop, interval) for s in COINS
        }
        meta[label] = {
            "start_ist": start,
            "end_ist_exclusive": end,
            "base_candle_sha256": hashes,
            "bars": {s: sum(len(g) for g in windows[label][s]) for s in COINS},
            "segments": {s: len(windows[label][s]) for s in COINS},
            "untraded_bars": {
                s: sum(c["volume"] <= 0 for g in windows[label][s] for c in g)
                for s in COINS
            },
        }
    return windows, meta


def prepare(archive, reference, later, output):
    report = [read(ROOT / name) for name in PRIOR]
    seen = {i: s for group in report for i, s, _ in group["coverage"]}
    pending = {i for i, s in seen.items() if not s.startswith("Tested")}
    windows, meta = datasets(reference, later, report, INTERVAL)
    entries, coverage = [], []
    with (
        ZipFile(archive) as z,
        (ROOT / "public-strategy-catalogue.csv").open(encoding="utf-8-sig") as f,
    ):
        for i, row in enumerate(csv.DictReader(f), 1):
            if row["source"] != "FMZ" or i not in pending:
                continue
            name = unquote(row["source_url"].split("/" + FMZ_REF + "/", 1)[1])
            raw = z.read("strategies-" + FMZ_REF + "/" + name)
            blocks = source_block(raw.decode("utf-8"))
            if len(blocks) != 1:
                coverage.append(
                    [
                        i,
                        "FMZ native replay pending",
                        "No single supported Pine strategy in the pinned document",
                    ]
                )
                continue
            block = blocks[0]
            problem = eligibility(block)
            if problem:
                coverage.append([i, "FMZ native replay pending", problem])
                continue
            version = re.sub(
                r"(?m)^\s*//\s*@version\s*=\s*([56])", r"//@version=\1", block
            )
            archived = re.search(r"(?m)^period:\s*(\S+)", block)
            entries.append(
                {
                    "id": i,
                    "name": row["name"],
                    "source": row["source_url"],
                    "hash": hashlib.sha256(raw).hexdigest(),
                    "archived": archived[1] if archived else "",
                    "code": re.sub(r"/\*.*?\*/", "", version, flags=re.DOTALL).strip(),
                }
            )
    output.mkdir(parents=True, exist_ok=True)
    write(output / "candidates.json", entries)
    write(output / "candles.json", windows)
    write(output / "screening.json", {"coverage": coverage, "windows": meta})
    print(
        f"{len(entries)} executable candidates, {len(coverage)} blocked during screening"
    )
    print(meta)


def finish(work, result):
    base = read(work / "screening.json")
    candidates = read(work / "candidates.json")
    candidates = {r["id"]: r for r in candidates}
    received = {}
    with (work / "out.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            value = json.loads(line)
            assert value["id"] not in received
            received[value["id"]] = value
    assert set(received) == set(candidates)
    coverage = base["coverage"]
    rows = []
    for idx, out in sorted(received.items()):
        if "reason" in out:
            coverage.append([idx, "FMZ native replay pending", out["reason"]])
            continue
        executable = re.sub(r"(?m)//.*$", "", candidates[idx]["code"])
        if re.search(
            r"\b(?:timenow|barstate\s*\.\s*isrealtime)\b|\[\s*-\d", executable
        ):
            coverage.append(
                [
                    idx,
                    "FMZ native replay pending",
                    "Wall-clock, realtime or future-index dependency",
                ]
            )
            continue
        trial = out["results"]
        assert len(trial) == 6
        assert all(
            x["source"] == candidates[idx]["source"] and x["id"] == idx for x in trial
        )
        rows.extend(trial)
        status = (
            "Tested · FMZ PineTS"
            if any(x["trades"] for x in trial)
            else "Tested · FMZ PineTS, no closes"
        )
        coverage.append(
            [idx, status, "15m PineTS broker replay with source order rules"]
        )
    write(
        result,
        {
            "results": rows,
            "coverage": sorted(coverage),
            "windows": base["windows"],
            "engine": "PineTS 0.13.1",
            "interval": "15m",
            "source_revision": FMZ_REF,
        },
    )
    print(Counter(r[1] for r in coverage))
    print("Reason counts", Counter(r[2] for r in coverage).most_common(22))


def prepare_retry(reference, later, base, output):
    records = [
        json.loads(line)
        for line in (base / "out.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    blocked = {
        r["id"] for r in records if r.get("reason") == "Broker used an untraded candle"
    }
    candidates = [
        item for item in read(base / "candidates.json") if item["id"] in blocked
    ]
    windows, meta = datasets(
        reference, later, [read(ROOT / name) for name in PRIOR], 30 * 60
    )
    output.mkdir(parents=True, exist_ok=True)
    write(output / "candidates.json", candidates)
    write(output / "candles.json", windows)
    write(output / "screening.json", {"coverage": [], "windows": meta})
    print("30m retry candidates", len(candidates), meta)


def merge_retry(base, retry):
    original = read(base)
    new = read(retry)
    overview = {r[0]: r for r in original["coverage"]}
    for i, status, reason in new["coverage"]:
        assert overview[i][2] == "Broker used an untraded candle"
        if status.startswith("Tested"):
            overview[i] = [i, status, "30m PineTS retry with no untraded-candle fills"]
        else:
            overview[i] = [i, status, "15m: untraded fill. 30m: " + reason]
    original["coverage"] = sorted(overview.values())
    original["results"].extend(new["results"])
    original["retry_windows"] = new["windows"]
    write(base, original)


def finish_legacy(work, result):
    candidates = {row["id"]: row for row in read(work / "legacy-candidates.json")}
    records = [
        json.loads(line)
        for line in (work / "legacy-out.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == len(candidates) == len({r["id"] for r in records})
    results, coverage = [], []
    for record in records:
        idx = record["id"]
        row = candidates[idx]
        if "reason" in record:
            reason = record["reason"]
            status = (
                "Excluded"
                if reason.startswith("Demonstration")
                else "Legacy adapter pending"
            )
            coverage.append([idx, status, reason])
            continue
        samples, unresolved = {}, {}
        for group in record["results"]:
            sample = []
            for time, entry, exit_price in group["trades"]:
                assert min(entry, exit_price) > 0
                units = NOTIONAL / entry
                gross = units * (exit_price - entry)
                turnover = units * (entry + exit_price)
                sample.append(
                    (
                        time,
                        gross,
                        gross - turnover * FEE,
                        gross - turnover * (FEE + EXECUTION),
                    )
                )
            key = group["period"], group["symbol"]
            samples[key], unresolved[key] = sample, group["unsettled"]
        strategy_results = []
        for period in ("Reference", "Later"):
            merged = period, "BTC + ETH"
            samples[merged] = samples[(period, "BTCUSD")] + samples[(period, "ETHUSD")]
            unresolved[merged] = (
                unresolved[(period, "BTCUSD")] + unresolved[(period, "ETHUSD")]
            )
            for market in (*COINS, "BTC + ETH"):
                key = period, market
                section = (
                    "Gekko advice replay"
                    if row["source"] == "gekko"
                    else "Zenbot signal replay"
                )
                report = summarize(
                    (section, row["name"], market, "Source spot exit"),
                    period,
                    samples[key],
                    unresolved[key],
                )
                report.update(
                    id=idx,
                    source=row["source_url"],
                    source_sha256=record["hash"],
                    interval="15m",
                    archive_interval="",
                )
                strategy_results.append(report)
        results.extend(strategy_results)
        status = (
            "Tested · legacy source"
            if any(x["trades"] for x in strategy_results)
            else "Tested · legacy, no closes"
        )
        coverage.append(
            [idx, status, "15m source advice replay, buy to open and sell to close"]
        )
    write(
        result,
        {
            "results": results,
            "coverage": coverage,
            "windows": read(work / "screening.json")["windows"],
            "interval": "15m",
            "sources": {
                "gekko": "ff5698f1ae6329bab5729f145c35a74161e82bac",
                "zenbot": "52872fb4b5f9d10e2f891d95daec05da0b721ceb",
            },
        },
    )
    print(Counter(x[1] for x in coverage))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    inputs = sub.add_parser("prepare")
    for k in ("archive", "reference", "later", "work"):
        inputs.add_argument(k, type=Path)
    for action in ("finish", "finish-legacy"):
        outputs = sub.add_parser(action)
        for k in ("work", "output"):
            outputs.add_argument(k, type=Path)
    retry = sub.add_parser("prepare-retry")
    for k in ("reference", "later", "base", "work"):
        retry.add_argument(k, type=Path)
    merged = sub.add_parser("merge-retry")
    merged.add_argument("base", type=Path)
    merged.add_argument("retry", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.archive, args.reference, args.later, args.work)
    elif args.command == "finish":
        finish(args.work, args.output)
    elif args.command == "finish-legacy":
        finish_legacy(args.work, args.output)
    elif args.command == "prepare-retry":
        prepare_retry(args.reference, args.later, args.base, args.work)
    else:
        merge_retry(args.base, args.retry)
