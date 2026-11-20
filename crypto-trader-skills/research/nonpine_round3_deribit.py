"""Extend the existing atomic combo-print replay into earlier, disjoint windows."""

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from research.delta_pinets_catalogue import read, write
from research.nonpine_round2_deribit import STRUCTURES, UNIT, epoch, replay

WINDOWS = {
    "Historical June–July": ("2026-06-01", "2026-08-01"),
    "Historical August–September": ("2026-08-01", "2026-09-23"),
}
OLDER_WINDOWS = {
    "Historical January–February": ("2026-01-01", "2026-03-01"),
    "Historical March–May": ("2026-03-01", "2026-06-01"),
}
YEAR_2025_WINDOWS = {
    "Historical July–September 2025": ("2025-07-01", "2025-10-01"),
    "Historical October–December 2025": ("2025-10-01", "2026-01-01"),
}
KIND = ("option_combo", "future_combo")
API = "https://history.deribit.com/api/v2/public/get_last_trades_by_currency_and_time"
DAY = 86_400_000


def fetch(directory, currency, kind, start, end):
    query = urlencode(
        {
            "currency": currency,
            "kind": kind,
            "start_timestamp": start,
            "end_timestamp": end - 1,
            "count": 1000,
            "sorting": "asc",
        }
    )
    url = f"{API}?{query}"
    path = directory / f"{currency}-{kind}-{start}-{end}.json"
    if not path.exists():
        with urlopen(url, timeout=35) as response:
            payload = json.load(response)["result"]
        encoded = json.dumps(payload, separators=(",", ":")).encode()
        tmp = path.with_suffix(".partial")
        tmp.write_bytes(encoded)
        tmp.replace(path)
    encoded = path.read_bytes()
    payload = json.loads(encoded)
    trades = payload["trades"]
    if payload["has_more"] or len(trades) >= 1000:
        if end - start < 1000:
            raise ValueError("Further subdivision would not verify a complete page")
        middle = (start + end) // 2
        return fetch(directory, currency, kind, start, middle) + fetch(
            directory, currency, kind, middle, end
        )
    if any(not start <= row["timestamp"] < end for row in trades):
        raise ValueError(f"Archive returned an out-of-window record: {path.name}")
    return [
        {
            "file": path.name,
            "url": url,
            "trades": len(trades),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }
    ]


def archive(directory, windows=WINDOWS):
    directory.mkdir(parents=True, exist_ok=True)
    first, end = (
        epoch(next(iter(windows.values()))[0]),
        epoch(list(windows.values())[-1][1]),
    )
    jobs = [
        (directory, currency, kind, start, min(start + DAY, end))
        for currency in UNIT
        for kind in KIND
        for start in range(first, end, DAY)
    ]
    receipt = []
    with ThreadPoolExecutor(6) as pool:
        futures = [pool.submit(fetch, *job) for job in jobs]
        for count, task in enumerate(futures, 1):
            receipt.extend(task.result())
            if count % 100 == 0:
                print(f"Fetched {count} of {len(jobs)} archive intervals", flush=True)
    write(directory / "manifest.json", receipt)


def finalize(directory, baseline, report, windows=WINDOWS, prior_reports=()):
    inputs = replay(directory, windows)
    target = {
        r["id"]
        for r in read(baseline)["disposition"]
        if 6054 <= r["id"] < 6054 + len(STRUCTURES)
        and not r["status"].startswith("Tested")
    }
    for prior_report in prior_reports:
        target -= {row["id"] for row in read(prior_report)["results"]}
    first = next(iter(windows.values()))[0]
    end = list(windows.values())[-1][1]
    results, coverage, evidence = [], [], {}
    for case in inputs["cases"]:
        ident = case["id"]
        if ident not in target:
            continue
        evidence[ident] = case["evidence"]
        if rows := case.get("results"):
            for row in rows:
                row["group"] = "Deribit combo trade-print model · earlier archive"
            results.extend(rows)
            coverage.append(
                [
                    ident,
                    "Tested · Deribit earlier observed prints",
                    f"Same atomic combo buy/sell and 15-minute wait model, from {first} until {end} IST.",
                ]
            )
            evidence[ident]["trade_ids"] = case["trade_ids"]
        else:
            coverage.append(
                [
                    ident,
                    "Deribit earlier archive · no matched round trip",
                    f"{case['reason']} from {first} until {end} IST.",
                ]
            )
    assert {row[0] for row in coverage} == target
    write(
        report,
        {
            "windows": windows,
            "inputs": inputs["inputs"],
            "coverage": coverage,
            "results": results,
            "evidence": evidence,
        },
    )
    print(f"Deribit earlier archive: {len(results) // 6} measured of {len(target)}")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("directory", type=Path)
    cli.add_argument("baseline", type=Path)
    cli.add_argument("report", type=Path)
    cli.add_argument(
        "--older-after", type=Path, action="append", default=[], metavar="PRIOR_REPORT"
    )
    cli.add_argument("--year-2025", action="store_true")
    args = cli.parse_args()
    windows = (
        YEAR_2025_WINDOWS
        if args.year_2025
        else OLDER_WINDOWS
        if args.older_after
        else WINDOWS
    )
    archive(args.directory, windows)
    finalize(args.directory, args.baseline, args.report, windows, args.older_after)
