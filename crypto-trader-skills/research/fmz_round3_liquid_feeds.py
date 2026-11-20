"""Re-run the Delta untraded-fill cohort on verified Binance USD-M candles."""

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pine_compatibility import recheck
from research.delta_pine_liquid_replay import (
    MARKETS,
    POOLED,
    archived_candles,
    checksum,
    prepare_candles,
)
from research.delta_pinets_catalogue import FMZ_REF, read, source_block, write
from research.delta_strategy_replay import ROOT
from research.fmz_pine_remaining import make_worker

LEDGER = ROOT / "remaining-backtest-round2-coverage.json"
REASON = "15m: untraded fill. 30m: Broker used an untraded candle"
GROUP = "FMZ Pine · Binance liquid feed"


def prepare(archive, cache, work, minutes):
    work.mkdir(parents=True, exist_ok=True)
    ledger = read(LEDGER)
    targets = [row for row in ledger["disposition"] if row["reason"] == REASON]
    entries, blocked = [], []
    with ZipFile(archive) as fmz:
        for row in targets:
            ref, path = unquote(row["source"].split("/blob/", 1)[1]).split("/", 1)
            assert ref == FMZ_REF and not row["status"].startswith("Tested")
            raw = fmz.read(f"strategies-{ref}/{path}")
            digest = checksum(raw)
            assert digest == row["pinned_document_sha256"]
            blocks = source_block(raw.decode())
            if len(blocks) != 1:
                blocked.append(
                    [
                        row["id"],
                        "Pending · FMZ liquid feed",
                        "Source block is not unique",
                    ]
                )
                continue
            try:
                code, version, transforms, repairs = recheck(blocks[0])
            except ValueError as exc:
                blocked.append([row["id"], "Pending · FMZ liquid feed", str(exc)])
                continue
            period = re.search(r"(?m)^period:\s*(\S+)", blocks[0])
            entries.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "source": row["source"],
                    "hash": digest,
                    "archived": period[1] if period else "",
                    "old_version": version,
                    "code": code,
                    "transforms": transforms,
                    "repairs": repairs,
                    "migration_sha256": checksum(code.encode()),
                }
            )
    archive_data, files = archived_candles(cache)
    candles, windows = prepare_candles(archive_data, minutes)
    candles = {"Binance · " + period: bars for period, bars in candles.items()}
    windows = {"Binance · " + period: meta for period, meta in windows.items()}
    assert all(not any(meta["untraded_bars"].values()) for meta in windows.values())
    assert len(entries) + len(blocked) == len(targets)
    write(work / "candidates.json", entries)
    write(work / "candles.json", candles)
    write(
        work / "preflight.json",
        {
            "coverage": blocked,
            "minutes": minutes,
            "windows": windows,
            "source_revision": FMZ_REF,
            "bar_archives": files,
            "base_disposition_sha256": checksum(LEDGER.read_bytes()),
            "candles_sha256": checksum((work / "candles.json").read_bytes()),
            "worker_sha256": make_worker(work, 45_000),
        },
    )
    print(f"{len(entries)} candidates and {len(blocked)} source blocks, {minutes}m")


def reconcile(samples, windows, item, minutes):
    assert len(samples) == 6
    assert {(row["period"], row["market"]) for row in samples} == {
        (period, market) for period in windows for market in (*MARKETS, POOLED)
    }
    for row in samples:
        assert (row["id"], row["source_sha256"], row["interval"]) == (
            item["id"],
            item["hash"],
            f"{minutes}m",
        )
        for key in ("trades", "unsettled", "gross_dd", "fee_dd", "net_dd"):
            assert math.isfinite(row[key]) and row[key] >= 0
        assert math.isclose(row["fees"], row["gross"] - row["after_fees"], abs_tol=1e-6)
        assert math.isclose(
            row["execution"], row["after_fees"] - row["net"], abs_tol=1e-6
        )
    for period in windows:
        market_rows = {row["market"]: row for row in samples if row["period"] == period}
        for key in (
            "trades",
            "unsettled",
            "gross_wins",
            "fee_wins",
            "net_wins",
            "gross",
            "after_fees",
            "net",
        ):
            assert math.isclose(
                market_rows[POOLED][key],
                sum(market_rows[m][key] for m in MARKETS),
                abs_tol=1e-6,
            )


def finalize(work, output):
    report = read(work / "preflight.json")
    isolation = read(work / "isolation-probe.json")
    assert isolation == {"privateDenied": True, "networkDenied": True}
    assert report["candles_sha256"] == checksum((work / "candles.json").read_bytes())
    assert report["worker_sha256"] == checksum((work / "worker.mjs").read_bytes())
    assert report["base_disposition_sha256"] == checksum(LEDGER.read_bytes())
    items = {row["id"]: row for row in read(work / "candidates.json")}
    receipts = [
        json.loads(line)
        for line in (work / "out.jsonl").read_text(encoding="utf-8-sig").splitlines()
    ]
    assert (
        len(receipts) == len(items) and {row["id"] for row in receipts} == items.keys()
    )
    minutes = report["minutes"]
    results = []
    for receipt in sorted(receipts, key=lambda row: row["id"]):
        ident = receipt["id"]
        item = items[ident]
        assert checksum(item["code"].encode()) == item["migration_sha256"]
        if reason := receipt.get("reason"):
            report["coverage"].append([ident, "Pending · FMZ liquid feed", reason])
            continue
        rows = receipt["results"]
        reconcile(rows, report["windows"], item, minutes)
        for row in rows:
            row.update(
                group=GROUP,
                quote_currency="USDT",
                market_data="Binance USD-M perpetuals",
                pine_source_version=item["old_version"],
                transforms=item["transforms"],
                repairs=item["repairs"],
                migration_sha256=item["migration_sha256"],
            )
        results.extend(rows)
        status = f"Tested · {GROUP}" + (
            "" if any(row["trades"] for row in rows) else ", no closes"
        )
        report["coverage"].append(
            [
                ident,
                status,
                f"Binance USD-M BTCUSDT and ETHUSDT {minutes}m. Prior Delta replay encountered untraded fill candles.",
            ]
        )
    report.update(
        coverage=sorted(report["coverage"]),
        engine="PineTS 0.13.1",
        results=results,
        isolation_probe=isolation,
        requires_os_isolation=True,
        engine_sha256=checksum((work.parent / "engine.mjs").read_bytes()),
    )
    write(output, report)
    print(Counter(row[1] for row in report["coverage"]))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    stages = cli.add_subparsers(dest="stage", required=True)
    staging = stages.add_parser("prepare")
    for field in ("archive", "cache", "work"):
        staging.add_argument(field, type=Path)
    staging.add_argument("--minutes", type=int, choices=(15, 30), default=15)
    final = stages.add_parser("finalize")
    final.add_argument("work", type=Path)
    final.add_argument("output", type=Path)
    params = vars(cli.parse_args())
    stage = params.pop("stage")
    (prepare if stage == "prepare" else finalize)(**params)
