"""Retry previous Pine timeouts on same and coarser verified market data."""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pine_compatibility import plain_pine, shell
from research.delta_pine_liquid_replay import MARKETS, WINDOWS, archived_candles
from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.delta_strategy_replay import stamp
from research.fmz_intrabar_replay import expand_chart_alias, minute_archive, minute_bars
from research.fmz_marketdata_replay import market_windows, prepare_source, script_blocks

PRIOR_BATCHES = (
    "remaining/feed-retry",
    "remaining/variant-retry",
    "compatibility-retry/refined",
    "compatibility-retry/isolated",
    "compatibility-retry/production",
    "full/market-isolated",
    "full/market-native",
    "full/market-final",
    "full/market-ha",
    "compatibility-final/15",
)


def prepare(prior, base, scratch, frame, implicit=False):
    target = (
        "Pine source has no active strategy declaration"
        if implicit
        else "PineTS per-source time or memory budget exceeded"
    )
    pending = {
        row["id"]: row for row in read(base)["disposition"] if target in row["reason"]
    }
    candidates = {}
    coverage = []
    for batch in () if implicit else PRIOR_BATCHES:
        if frame == 60 and batch == "full/market-ha":
            continue
        for item in read(prior / batch / "candidates.json"):
            ident = item["id"]
            if ident in pending and ident not in candidates:
                if frame == 60 and any(
                    item.get(setting)
                    for setting in (
                        "confirmedVariant",
                        "initialCapital",
                        "snapshotVariant",
                    )
                ):
                    continue
                candidates[ident] = {
                    **item,
                    "timeoutMs": 60_000,
                    "prior_batch": batch,
                    "replay_sha256": hashlib.sha256(item["code"].encode()).hexdigest(),
                }
    with ZipFile(prior / "fmz.zip") as archive:
        if implicit:
            for ident, row in pending.items():
                ref, name = unquote(row["source"].split("/blob/", 1)[1]).split("/", 1)
                assert ref == FMZ_REF
                content = archive.read(f"strategies-{ref}/{name}")
                document = content.decode("utf-8")
                try:
                    [block] = script_blocks(document, False)
                    with_header, settings = shell(plain_pine(block))
                    assert settings == {"FMZ implicit strategy declaration": 1}
                    with_header, aliases = expand_chart_alias(with_header)
                    code, version, repairs = prepare_source(
                        with_header,
                        with_heikin=True,
                        isolated_literals=True,
                        chart_ticker_alias=True,
                    )
                    repairs.update(settings)
                    if aliases:
                        repairs["immutable chart ticker alias"] = aliases
                except (AssertionError, ValueError) as exc:
                    detail = (
                        str(exc)
                        or "Archive did not yield one verified implicit strategy"
                    )
                    coverage.append([ident, "FMZ implicit strategy pending", detail])
                    continue
                archived = re.search(r"(?m)^period:\s*(\S+)", document)
                candidates[ident] = {
                    "id": ident,
                    "name": row["name"],
                    "source": row["source"],
                    "hash": hashlib.sha256(content).hexdigest(),
                    "archived": archived[1] if archived else "",
                    "code": code,
                    "version": version,
                    "repairs": repairs,
                    "timeoutMs": 55_000,
                    "replay_sha256": hashlib.sha256(code.encode()).hexdigest(),
                }
        for ident, item in candidates.items():
            source = pending[ident]["source"]
            ref, name = unquote(source.split("/blob/", 1)[1]).split("/", 1)
            assert ref == FMZ_REF == item["source"].split("/blob/", 1)[1].split("/")[0]
            content = archive.read(f"strategies-{ref}/{name}")
            assert hashlib.sha256(content).hexdigest() == item["hash"]
            checksum = item.get("adapted_sha256") or item.get("migration_sha256")
            if checksum:
                assert checksum == item["replay_sha256"], ident
    five, archives = archived_candles(prior / "liquid-reviewed")
    one, minutes = minute_archive(prior / "nonpine/binance")
    data, windows = market_windows(five, minutes=frame, with_heikin=True)
    for period, (start, end) in WINDOWS.items():
        for market in MARKETS:
            refs = data["Binance · " + period]["market"]["references"][market]
            for minute in (1, 3):
                refs[str(minute)] = list(
                    minute_bars(one[market], stamp(start), stamp(end), minute)
                )
    write(scratch / "candidates.json", list(candidates.values()))
    write(scratch / "candles.json", data)
    write(
        scratch / "timeout-settings.json",
        {
            "archives": archives + minutes,
            "windows": windows,
            "chart_minutes": frame,
            "unavailable_past_inputs": sorted(pending.keys() - candidates.keys()),
            "implicit_declaration": implicit,
            "coverage": coverage,
        },
    )
    print(
        f"Prepared {len(candidates)} pinned inputs of {len(pending)} cases at {frame}m"
    )


def finalize(scratch, out):
    context = read(scratch / "timeout-settings.json")
    probe = read(scratch / "isolation-probe.json")
    assert probe == {"networkDenied": True, "privateDenied": True}
    context["isolation_probe"] = probe
    frame = context["chart_minutes"]
    candidates = {item["id"]: item for item in read(scratch / "candidates.json")}
    lines = (scratch / "out.jsonl").read_text(encoding="utf-8-sig").splitlines()
    receipts = [json.loads(line) for line in lines]
    assert len(receipts) == len(candidates) == len({r["id"] for r in receipts})
    assert {r["id"] for r in receipts} == candidates.keys()
    coverage, results = context.pop("coverage", []), []
    implicit = context.get("implicit_declaration", False)
    for record in receipts:
        ident = record["id"]
        item = candidates[ident]
        if reason := record.get("reason"):
            label = (
                "FMZ implicit strategy pending"
                if implicit
                else "Pine runtime retry pending"
            )
            coverage.append([ident, label, f"{frame}m: {reason}"])
            continue
        rows = record["results"]
        assert len(rows) == 6
        group = (
            "FMZ · 60m timeframe variant"
            if frame == 60
            else "FMZ · Binance runtime retry"
        )
        expected = (
            "The same approved Pine source with a 60-minute chart. Chart-timeframe-dependent signals can change."
            if frame == 60
            else "15-minute source replay on Binance perpetual candles with a one-minute candidate budget."
        )
        if implicit:
            group = "FMZ · Implicit declaration variant"
            expected = (
                "Archived FMZ order calls on a 15m chart with a minimal strategy declaration "
                "and the common study's broker settings. Commented TradingView settings remain inactive."
            )
        if item.get("allowFillRecalculation"):
            expected += (
                " The historical OHLC order-fill path can expose completed-bar values."
            )
        if item.get("confirmedVariant"):
            group += " · confirmed variant"
            expected += " Delays the prior future-looking requests to confirmation."
        if capital := item.get("initialCapital"):
            group += " · capital variant"
            expected += f" Uses the source's literal {capital:g} USDT wallet size."
        if item.get("snapshotVariant"):
            group += " · clock snapshot"
            expected += " Fixes clock time at the archive cutoff."
        for row in rows:
            assert (
                row["id"] == ident
                and row["source_sha256"] == item["hash"]
                and row["interval"] == f"{frame}m"
            )
            row.update(
                group=group,
                quote_currency="USDT",
                market_data="Binance USD-M BTCUSDT and ETHUSDT perpetuals",
                funding_model="Historical funding is outside this Pine replay",
                pine_source_version=item.get("version", item.get("old_version")),
                repairs=item.get("repairs"),
                migration_sha256=item["replay_sha256"],
            )
        results.extend(rows)
        suffix = "" if any(row["trades"] for row in rows) else ", no closes"
        coverage.append([ident, "Tested · " + group + suffix, expected])
    write(
        out,
        dict(
            **context,
            engine="PineTS 0.13.1",
            coverage=sorted(coverage),
            results=sorted(results, key=lambda x: x["id"]),
        ),
    )
    print(Counter(row[1] for row in coverage), len(results), "result rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="step", required=True)
    prep = sub.add_parser("prepare")
    for name in ("prior", "base", "scratch"):
        prep.add_argument(name, type=Path)
    prep.add_argument("frame", choices=(15, 60), type=int)
    prep.add_argument("--implicit", action="store_true")
    finish = sub.add_parser("finalize")
    for name in ("scratch", "out"):
        finish.add_argument(name, type=Path)
    args = vars(parser.parse_args())
    step = args.pop("step")
    (prepare if step == "prepare" else finalize)(**args)
