"""Verify the archived six-frame gate simplifies to causal-sensitive daily extrema."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from shutil import copy2
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, aggregate, date_ms, sha256
from research.fmz_round19_pine_broker import equal
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH
from research.fmz_round28_pine_callback import cache_bars

IDENT = 4111
DAY = 86_400_000
M15 = 900_000
H4 = 16 * M15
FRAMES = (1, 2, 4, 8, 16, 96)
PRODUCER = "fmz_round44_pine_drexel_probe.py"


def record(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (row,) = (r for r in read(baseline)["disposition"] if r["id"] == IDENT)
    assert row["status"].startswith("Pending")
    with ZipFile(archive) as book:
        ((_, _, doc, checksum),) = documents(book, {IDENT: row})
    (raw,) = re.findall(r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", doc)
    facts = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)", raw
        )
    )
    assert facts == {
        "start": "2023-11-11 00:00:00",
        "end": "2023-12-11 00:00:00",
        "period": "4h",
        "basePeriod": "15m",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    assert len(re.findall(r"=rsx\(open,Length\(\d+\)\)", raw)) == 10
    for s in (
        "//@version=2",
        "Length2=9",
        "c3a = nz(c3a[1])",
        "Length(mod)=>(mod*c3a)+Length2",
        "trend1 = (((a-b1)+(c-d)+(e-f)+(g-h)+(i-j))/10)",
        "XPrice = high, xprice = low",
        "trend1==0?XPrice",
        "trend1==0?xprice",
        "bh1=request.security(syminfo.tickerid,'D',trend2)",
        "bh2=request.security(syminfo.tickerid,'D',trend3)",
        "Trend11=((bc-bc1)+(bd-bd1)+(be-be1)+(bf-bf1)+(bg-bg1)+(bh1))",
        "Trend33 = max(min(min(min(bc2,bd2),min(be2,bf2)),bg2),bh2)",
        "x1 = trend3==Trend33",
        "y1 = trend2==Trend11",
        'strategy.entry("Long",true,when=x1)',
        'strategy.entry("Short",false,when=y1)',
    ):
        assert s in raw, s
    return (
        raw.encode(),
        facts,
        checksum,
        re.search(r"https://www\.fmz\.com/strategy/\d+", doc)[0],
    )


def feeds(cache):
    a, b = map(date_ms, ("2023-11-11", "2023-12-11"))
    end = 2 * b - a
    cases, manifest = {}, []
    for market in ("BTCUSDT", "ETHUSDT"):
        rows = [
            r
            for r in cache_bars(
                cache, market, "15m", ("2023-11", "2023-12", "2024-01"), M15, manifest
            )
            if a <= r[0] < end
        ]
        assert [r[0] for r in rows] == list(range(a, end, M15))
        for period, lo, hi in (("native", a, b), ("next", b, end)):
            used = [r for r in rows if lo <= r[0] < hi]
            contexts = {
                str(15 * k): [list(r) for r in aggregate(used, k)] for k in FRAMES
            }
            cases.setdefault(period, {})[market] = {
                "chart": contexts["240"],
                "contexts": contexts,
            }
    return cases, manifest


def verify_prefix(cases, runs):
    assert len(runs) == 24
    index = {(r["period"], r["market"], r["frame"]): r for r in runs}
    assert len(index) == len(runs)
    points = 0
    for period, markets in cases.items():
        for market, sample in markets.items():
            for key, rows in sample["contexts"].items():
                run = index[(period, market, key)]
                assert not run["diagnostics"] and not run["strategy"]["diagnostics"]
                plots = run["plots"]
                for candle, (length_term, difference, high1, high2, low) in zip(
                    rows[:48],
                    zip(
                        *(
                            plots[k]
                            for k in (
                                "c3a",
                                "Derived trend",
                                "High branch 1",
                                "High branch 2",
                                "Low branch",
                            )
                        ),
                        strict=True,
                    ),
                    strict=True,
                ):
                    assert length_term == difference == 0
                    assert (
                        equal(high1, candle[2])
                        and equal(high2, candle[2])
                        and equal(low, candle[3])
                    )
                    points += 1
    return points


def check(sample, run, previous):
    assert {d["code"] for d in run["diagnostics"]} == {"W_LEGACY_SECURITY_LOOKAHEAD"}
    assert not run["strategy"]["diagnostics"]
    days = {r[0]: r for r in sample["contexts"]["1440"]}
    plot = run["plots"]
    witnesses = []
    current_high, current_low = None, None
    for i, c in enumerate(sample["chart"]):
        t, _, hi, lo, _, _ = c
        day = t // DAY * DAY
        stamp = day - DAY if previous else day
        ref = days.get(stamp)
        high = ref[2] if ref else None
        low = ref[3] if ref else None
        available = stamp + DAY
        assert equal(plot["Daily high"][i], high) and equal(plot["Daily low"][i], low)
        low_predicate = lo == max(lo, low) if low is not None else False
        high_predicate = hi == high if high is not None else False
        if t == day:
            current_high, current_low = hi, lo
        else:
            current_high, current_low = max(current_high, hi), min(current_low, lo)
        assert low_predicate == plot["Long"][i] and high_predicate == plot["Short"][i]
        assert equal(
            plot["Trend long low"][i], max(lo, low) if low is not None else None
        )
        assert equal(plot["Trend short high"][i], high)
        witnesses.append(
            {
                "chart_start": t,
                "available_at": t + H4,
                "reference_finalized_at": available,
                "low_gate": low_predicate,
                "high_gate": high_predicate,
                "active_day_high": current_high,
                "active_day_low": current_low,
                "referenced_high": high,
                "referenced_low": low,
                "partial_high_gate": hi == current_high,
            }
        )
    if previous:
        assert all(r["reference_finalized_at"] <= r["available_at"] for r in witnesses)
    return witnesses


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "finalize"))
    for key in ("archive", "baseline", "work", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    parser.add_argument("--cache", type=Path, nargs="+", required=True)
    a = parser.parse_args()
    raw, facts, checksum, source_link = record(a.archive, a.baseline)
    samples, manifest = feeds(a.cache)
    probe = Path(__file__).with_name(PRODUCER)
    staged = a.work / "r44_drexel_probe.py"
    source = a.work / "r44-drexel-source.pine"
    tape = a.work / "r44-drexel-feeds.json"
    if a.mode == "stage":
        source.write_bytes(raw)
        write(tape, samples)
        copy2(probe, staged)
        return
    assert source.read_bytes() == raw and read(tape) == samples
    assert probe.read_bytes() == staged.read_bytes()
    assert (
        sha256(a.work / "priced-runtime/pine_compat/pine_compat.pyd")
        == NATIVE_BINARY_HASH
    )
    isolation = read(a.work / "round3-isolation-python.json")
    assert all(
        isolation[k][0] == "PermissionError" for k in ("file_error", "network_error")
    )
    literal = a.work / "r44-drexel-literal-error.txt"
    typed = a.work / "r44-drexel-typed-error.txt"
    assert (
        "E_LEGACY_REFERENCE_TYPE" in literal.read_text()
        and "`c3a`" in literal.read_text()
    )
    assert (
        "E_UNSUPPORTED_FEATURE" in typed.read_text()
        and "mutable captures" in typed.read_text()
    )
    receipts = {
        name: a.work / f"r44-drexel-{name}.json"
        for name in ("prefix", "projected", "available")
    }
    observed_points = verify_prefix(samples, read(receipts["prefix"]))
    other = {}
    for mode in ("projected", "available"):
        runs = read(receipts[mode])
        other[mode] = {(r["period"], r["market"]): r for r in runs}
        assert len(runs) == len(other[mode]) == 4
    findings = []
    for period, assets in samples.items():
        for market, sample in assets.items():
            key = (period, market)
            legacy = other["projected"][key]
            shifted = other["available"][key]
            current, prior = check(sample, legacy, False), check(sample, shifted, True)
            changed = [
                (x, y)
                for x, y in zip(current, prior, strict=True)
                if (x["low_gate"], x["high_gate"]) != (y["low_gate"], y["high_gate"])
            ]
            causal_witnesses = [
                x
                for x in current
                if x["high_gate"] != x["partial_high_gate"]
                and x["reference_finalized_at"] > x["available_at"]
            ]
            assert causal_witnesses
            findings.append(
                {
                    "period": period,
                    "market": market,
                    "mixed_gate_differences": len(changed),
                    "legacy_closes": len(legacy["strategy"]["trades"]),
                    "previous_confirmed_closes": len(shifted["strategy"]["trades"]),
                    "previous_confirmed_first_change": changed[0],
                    "causal_current_day_differences": len(causal_witnesses),
                    "causal_current_day_first_witness": causal_witnesses[0],
                }
            )
    assert [x["mixed_gate_differences"] for x in findings] == [60, 60, 63, 64]
    assert sum(x["legacy_closes"] for x in findings) == 218
    assert not any(x["previous_confirmed_closes"] for x in findings)
    write(
        a.output,
        {
            "baseline_coverage_sha256": sha256(a.baseline),
            "archive_sha256": FMZ_SHA256,
            "document_sha256": checksum,
            "archived_settings": facts,
            "pine_compat_binary_sha256": NATIVE_BINARY_HASH,
            "isolation_probe": isolation,
            "provider_archives": manifest,
            "artifacts": {
                p.name: sha256(p)
                for p in (probe, source, tape, literal, typed, *receipts.values())
            },
            "native_prefix_witness_counts": {"scopes": 24, "bars": observed_points},
            "diagnostic_outcomes": findings,
            "method": [
                "The pinned source has an untyped self-recursive c3a and modern request spellings in v2. Type annotations restore its startup recurrence. The native compiler rejects complex security-context captures, so six-frame prefix probes validate each branch separately before substituting mathematically equivalent direct high/low requests.",
                "c3a starts at zero via nz and stays zero. Each of ten RSX calls receives the same source and length 9. Pairwise differences are exactly zero. The branch selecting the chart high twice and chart low once follows on all typed prefix clips, including startup. In the active 4h gates, lower-frame highs cancel and lower-frame lows are at least as large as the full 4h low. The surviving formulas depend on the daily high and low.",
                "Legacy future-aware controls read finalized daily extrema throughout the day. Comparing only prior finalized days changes 247 gate decisions across the four scopes and changes the engine close count from 218 to zero. Independently calculated partial daily high also changes short gates within the same UTC day, proving an unavailable-future-data dependency without imposing a prior-day policy.",
            ],
            "references": [
                source_link,
                "https://www.tradingview.com/pine-script-docs/v5/concepts/other-timeframes-and-data/",
                "https://github.com/binance/binance-public-data",
            ],
            "coverage": [
                [
                    IDENT,
                    "Pending · FMZ future-leaking daily high/low gates",
                    "The deterministic zero recursion collapses all timeframe paths to high/low lookups. Finalized daily extrema drive orders before they are known. Current partial-day witnesses change short signals, while previous confirmed days change 247 gates and reduce diagnostic closes from 218 to zero. Exact causal source behavior has no authored binding.",
                ]
            ],
            "results": [],
        },
    )
    print(
        f"Verified 24 prefix contexts, {observed_points} prefix bars and 247 changed trading gates. #4111 remains pending."
    )


if __name__ == "__main__":
    main()
