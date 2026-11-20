"""Stage and validate the archived Round 10 market-order magnifier study."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from itertools import chain, pairwise
from pathlib import Path

from research.fmz_round7_magnifier import (
    aggregate,
    date_ms,
    iso_day,
    ledger_metrics,
    raw_ohlcv,
    read,
    sha256,
    verified_archives,
    write,
)

EVIDENCE_BASE = "84af82e18dff9d2e4b8e60c4b8df5e73ceb6e150"
ENGINE_COMMIT = "c0ecc3bde5eece9c4f2a63c6785aec9c5e571acc"
LOCK_SHA = "3b55229fb85cafd2218cc4545d1d35b4a5278396f775e6a29fa6b9c8cbaf33ba"
PATCH_SHA = "6d044b62947bb038f824092d164ec847b5b81036ff85e2978b18934a5b7ee591"
BASELINE_RUNTIME_SHA = (
    "973d03e34fefa09c324cbfa3f82bfb374d7ced058f4a826d4a04fb0de0ef0b65"
)
TESTED = {4721: (10_000, "EL"), 5520: (1_000, "entry")}
SYMBOLS = ("BTCUSDT", "ETHUSDT")
MONTHS = ("2026-08", "2026-09", "2026-10")
WINDOWS = (("2026-08-01", "2026-09-01"), ("2026-09-01", "2026-11-01"))
SIZING_FAILURES = {
    "gap_qty",
    "gap_value",
    "fee_lot",
    "fee_profit",
    "reversal_old_lot",
    "reversal_new_net",
}


def round7_reference():
    return read(Path(__file__).with_name("fmz-round7-magnifier.json"))


def archive_records():
    return {
        row["id"]: row
        for row in round7_reference()["archive_records"]
        if row["id"] in TESTED
    }


def stage(work, public):
    work.mkdir(parents=True, exist_ok=True)
    reference = {row["name"]: row["sha256"] for row in round7_reference()["inputs"]}
    manifest = []
    for symbol in SYMBOLS:
        archives = verified_archives(public, symbol, "1m", MONTHS, manifest)
        assert all(sha256(path) == reference[path.name] for path in archives)
        all_bars = list(
            chain.from_iterable(raw_ohlcv(file, 60_000) for file in archives)
        )
        assert all(b[0] - a[0] == 60_000 for a, b in pairwise(all_bars))
        for chart, lower in ((45, 5), (60, 10)):
            for first, last in WINDOWS:
                start, end = date_ms(first), date_ms(last)
                bars = [row for row in all_bars if start <= row[0] < end]
                assert bars[0][0] == start and len(bars) * 60_000 == end - start
                payload = {
                    "symbol": symbol,
                    "chartTimeframe": str(chart),
                    "targetTimeframe": str(lower),
                    "chartMs": chart * 60_000,
                    "ltfMs": lower * 60_000,
                    "from": start,
                    "to": end,
                    "chart": aggregate(bars, chart),
                    "intrabar": aggregate(bars, lower),
                }
                path = work / f"feed-{symbol}-{chart}-{lower}-{first}.json"
                path.write_bytes(
                    json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
                )
    write(work / "market-input-manifest.json", manifest)
    write(
        work / "market-archive-sources.json",
        {ident: row["script_sha256"] for ident, row in archive_records().items()},
    )


def validate_fixtures(work):
    baseline = read(work / "market-fixtures-baseline.json")
    patched = read(work / "market-fixtures-patched.json")
    assert set(baseline["checks"]) == set(patched["checks"])
    assert {
        name for name, passed in baseline["checks"].items() if not passed
    } == SIZING_FAILURES
    assert len(patched["checks"]) == 12 and all(patched["checks"].values())
    return baseline, patched


def finalize(work, output):
    patch = Path(__file__).with_name("fmz-round10-magnifier-market.patch")
    assert sha256(patch) == PATCH_SHA
    before, after = validate_fixtures(work)
    archive = archive_records()
    baseline_binary = work / "baseline-runtime/pine_compat/pine_compat.pyd"
    patched_binary = work / "patched-runtime/pine_compat/pine_compat.pyd"
    assert sha256(baseline_binary) == BASELINE_RUNTIME_SHA
    replay = work / "market-replay.json"
    runs = read(replay)
    assert len(runs) == 8
    groups = defaultdict(list)
    for run in runs:
        assert run["verified_exact_pct_fills"] and run["magnifier_fallbacks"] == 0
        public = work / run["feed"]
        assert sha256(public) == run["feed_sha256"]
        feed = read(public)
        assert run["chart_count"] == len(feed["chart"]) and run["lower_count"] == len(
            feed["intrabar"]
        )
        sid = run["id"]
        source = work / f"source-{sid}.pine"
        assert sha256(source) == run["source_sha256"] == archive[sid]["script_sha256"]
        run.update(
            market=feed["symbol"],
            start=feed["from"],
            end=feed["to"],
            interval=feed["chartTimeframe"],
            lower=feed["targetTimeframe"],
        )
        groups[sid, run["start"], run["end"]].append(run)
    results = []
    for (sid, start, end), cases in sorted(groups.items()):
        cases.sort(key=lambda c: c["market"])
        assert [c["market"] for c in cases] == list(SYMBOLS)
        capital, entry_id = TESTED[sid]
        chart, lower = cases[0]["interval"], cases[0]["lower"]
        common = {
            "id": sid,
            "group": f"FMZ · Pine Compat next-open sizing · {chart}m→{lower}m",
            "exit": "Archived Pine exits",
            "period": f"Binance USD-M · {iso_day(start)} to {iso_day(end)} UTC exclusive",
            "archive_interval": f"{chart}m",
            "interval": f"{chart}m",
            "currency": "USDT",
        }
        pooled = []
        pending = 0
        for case in cases:
            closed = []
            for trade in case["trades"]:
                assert (
                    trade["id"] == entry_id
                    and start <= trade["entryTime"] <= trade["exitTime"] < end
                )
                commission = (
                    trade["qty"]
                    * (trade["entryPrice"] + trade["exitPrice"])
                    * case["fee_percent"]
                    / 100
                )
                closed.append({**trade, "dir": 1, "commission": commission})
            unsettled = int(case["end_position"] != 0)
            results.append(
                {
                    **common,
                    "market": case["market"],
                    **ledger_metrics(closed, capital, unsettled),
                }
            )
            pooled.extend(closed)
            pending += unsettled
        results.append(
            {
                **common,
                "market": "BTCUSDT + ETHUSDT",
                **ledger_metrics(pooled, 2 * capital, pending),
            }
        )
    assert len(results) == 12 and len(groups) == 4
    write(
        output,
        {
            "schema": "Round 10 Pine Compat archived market-order magnifier checkpoint",
            "baseline_commit": EVIDENCE_BASE,
            "engine_source_commit": ENGINE_COMMIT,
            "engine_source_license": "MIT",
            "engine_patch_sha256": PATCH_SHA,
            "baseline_wheel_binary_sha256": sha256(baseline_binary),
            "windows_native_extension_sha256": sha256(patched_binary),
            "cargo_lock_sha256": LOCK_SHA,
            "rust_toolchain": "1.95.0-x86_64-pc-windows-gnu",
            "raw_ledger_sha256": sha256(replay),
            "baseline_fixtures": before,
            "patched_fixtures": after,
            "archives": list(archive.values()),
            "inputs": read(work / "market-input-manifest.json"),
            "coverage": [
                [
                    sid,
                    "Tested · Pine Compat historical Bar Magnifier",
                    "Archived Pine on verified Binance USD-M candles. Market percent sizing evaluated at each actual fill including fees and lot rounding.",
                ]
                for sid in TESTED
            ],
            "runs": runs,
            "results": results,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    children = parser.add_subparsers(dest="phase", required=True)
    staging = children.add_parser("stage")
    staging.add_argument("work", type=Path)
    staging.add_argument("public", type=Path)
    closing = children.add_parser("finalize")
    closing.add_argument("work", type=Path)
    closing.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.phase == "stage":
        stage(args.work, args.public)
    else:
        finalize(args.work, args.output)
