"""Source-audited FMZ Pine replays on native historical Binance futures candles."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from hashlib import sha512
from itertools import chain, pairwise
from math import floor, fsum, isclose
from pathlib import Path
from shutil import copy2
from tarfile import open as open_tar
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round6_pine import archival_items
from research.fmz_round7_magnifier import (
    FMZ_SHA256,
    date_ms,
    raw_ohlcv,
    sha256,
    verified_archives,
)
from research.fmz_round7_pine import (
    EXECUTION,
    FEE,
    PINER_PIN,
    PINER_VERSION,
    copy_runtime,
    strip_fmz_wrapper,
    summarize,
    verify_trade,
)

IDENT = 1044
MARKETS = ("BTCUSDT", "ETHUSDT")
TIMEFRAME_MS = 3_600_000
LOT_STEP = 0.001
CAPITAL = 10_000.0
CASH = 1_000.0
WINDOWS = (
    ("FMZ native window", "2024-05-21", "2024-06-20"),
    ("Next equal window", "2024-06-20", "2024-07-20"),
)
MONTHS = ("2024-05", "2024-06", "2024-07")
SOURCE_REQUEST = (
    "request.security(ticker.heikinashi(syminfo.tickerid), timeframe.period, src)"
)
GROUP = "FMZ Pine · Native 1h Binance · Verified Heikin-Ashi reference"


def inspect_archive(archive, ledger):
    assert sha256(archive) == FMZ_SHA256
    (row,) = [item for item in read(ledger)["disposition"] if item["id"] == IDENT]
    assert row["status"].startswith("Pending")
    audit, originals = archival_items(archive, {IDENT: row})
    code, doc_checksum, interval = originals[IDENT]
    with ZipFile(archive) as source:
        _, _, document, observed_checksum = next(documents(source, {IDENT: row}))
    assert observed_checksum == doc_checksum
    original_fields = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):\s*([^\r\n]+)", document
        )
    )
    assert original_fields == {
        "start": "2024-05-21 00:00:00",
        "end": "2024-06-20 00:00:00",
        "period": "1h",
        "basePeriod": "15m",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    assert interval == "1h"
    archived, _ = strip_fmz_wrapper(code)
    assert archived.count(SOURCE_REQUEST) == 1
    assert re.findall(r"(?m)^src\s*:?=[^\r\n]+", archived) == ["src = close"]
    return (
        row,
        original_fields,
        doc_checksum,
        archived.encode("utf-8"),
        audit[str(IDENT)],
    )


def chart_feeds(public):
    manifest, windows = [], {}
    for market in MARKETS:
        archives = verified_archives(public, market, "1h", MONTHS, manifest)
        source = list(
            chain.from_iterable(raw_ohlcv(path, TIMEFRAME_MS) for path in archives)
        )
        assert all(
            right[0] == left[0] + TIMEFRAME_MS for left, right in pairwise(source)
        )
        for label, start, end in WINDOWS:
            first, last = date_ms(start), date_ms(end)
            selected = [bar for bar in source if first <= bar[0] < last]
            start_times = [bar[0] for bar in selected]
            assert start_times == list(range(first, last, TIMEFRAME_MS))
            windows.setdefault(label, {})[market] = selected
    return manifest, windows


def stage(archive, ledger, public, prior_runtime, output):
    row, fields, checksum, code, evidence = inspect_archive(archive, ledger)
    manifest, windows = chart_feeds(public)
    output.mkdir(parents=True, exist_ok=True)
    copy_runtime(prior_runtime, output)
    copy2(Path(__file__).with_suffix(".mjs"), output / "replay-ha.mjs")
    (output / "source-1044.pine").write_bytes(code)
    write(output / "feeds.json", windows)
    write(
        output / "preflight.json",
        {
            "id": IDENT,
            "source": row["source"],
            "original_document_sha256": checksum,
            "archive_sha256": FMZ_SHA256,
            "original_archive_settings": fields,
            "original_pine_evidence": evidence,
            "baseline_coverage_sha256": sha256(ledger),
            "published_binance_candles": manifest,
            "chart_sha256": sha256(output / "feeds.json"),
        },
    )


def check_order_timing(case, candles):
    signals, values = case["signal"], case["ha"]
    assert len(signals) == len(values) == len(candles)
    assert set(signals) <= {-1, 0, 1}
    assert all(
        isclose(value, fsum(bar[1:5]) / 4, rel_tol=1e-13)
        for value, bar in zip(values, candles, strict=True)
    )
    transitions = []
    direction = 0
    for index, signal in enumerate(signals):
        if signal and signal != direction:
            transitions.append((index, signal))
            direction = signal
    assert case["unsettled"] == int(bool(transitions))
    assert len(case["closed"]) == max(0, len(transitions) - 1)
    times = [bar[0] for bar in candles]
    events = []
    for trade, ((entry_bar, entry_dir), (exit_bar, _)) in zip(
        case["closed"], pairwise(transitions), strict=True
    ):
        assert [trade[key] for key in ("entryBar", "dir", "exitBar")] == [
            entry_bar,
            entry_dir,
            exit_bar,
        ]
        assert trade["entryPrice"] == candles[entry_bar][4]
        assert trade["exitPrice"] == candles[exit_bar][4]
        expected_qty = floor(CASH / trade["entryPrice"] / LOT_STEP) * LOT_STEP
        assert isclose(trade["qty"], expected_qty, rel_tol=1e-9)
        epoch, *cashflow = verify_trade(trade, times)
        events.append((epoch + TIMEFRAME_MS, *cashflow))
    return events, len(transitions)


def finalize(archive, ledger, public, work, output):
    row, _, checksum, archived, _ = inspect_archive(archive, ledger)
    manifest, windows = chart_feeds(public)
    preflight = read(work / "preflight.json")
    assert preflight["baseline_coverage_sha256"] == sha256(ledger)
    assert preflight["original_document_sha256"] == checksum
    assert preflight["published_binance_candles"] == manifest
    assert preflight["chart_sha256"] == sha256(work / "feeds.json")
    assert (work / "source-1044.pine").read_bytes() == archived
    assert (work / "replay-ha.exit").read_text().strip() == "0"
    assert (
        Path(__file__).with_suffix(".mjs").read_bytes()
        == (work / "replay-ha.mjs").read_bytes()
    )
    isolation = read(work / "isolation-probe.json")
    assert isolation == {"privateDenied": True, "networkDenied": True}
    package = work / f"piner-{PINER_VERSION}.tgz"
    assert b64encode(sha512(package.read_bytes()).digest()).decode("ascii") == PINER_PIN
    with open_tar(package, "r:gz") as distribution:
        pin = distribution.extractfile("package/dist/index.js").read()
    assert (work / "package/dist/index.js").read_bytes() == pin
    receipt = read(work / "ha-receipt.json")
    assert receipt["source_sha256"] == sha256(work / "source-1044.pine")
    assert receipt["mode"] == "equivalent request and plot witness agree"
    assert receipt["settings"]["initialCapital"] == CAPITAL
    cases = {(item["period"], item["market"]): item for item in receipt["cases"]}
    assert len(cases) == len(receipt["cases"]) == 4
    results, findings = [], []
    fills = 0
    for period, markets in windows.items():
        pool, remaining = [], 0
        common = {
            "id": IDENT,
            "name": row["name"],
            "source": row["source"],
            "source_sha256": checksum,
            "executed_source_sha256": receipt["executed_source_sha256"],
            "period": period,
            "quote_currency": "USDT",
            "archive_interval": "1h",
            "interval": "60m",
            "group": GROUP,
            "exit": "Archived Pine market reversal",
            "market_data": "Binance USD-M historical futures candles",
            "repairs": {
                "Same-timeframe Heikin-Ashi request reads its own context's immutable close alias": 1
            },
        }
        for market, candles in markets.items():
            case = cases[(period, market)]
            assert case["requested"] == [
                {
                    "symbol": f"BINANCE:{market}.P_HA",
                    "timeframe": "60",
                    "lowerTf": False,
                }
            ]
            events, transitions = check_order_timing(case, candles)
            unsettled = case["unsettled"]
            results.append(
                {**common, "market": market, **summarize(events, unsettled, CAPITAL)}
            )
            findings.append(
                {
                    "period": period,
                    "market": market,
                    "verified_reference_bars": len(candles),
                    "transitions": transitions,
                    "closes": len(events),
                }
            )
            pool.extend(events)
            remaining += unsettled
            fills += len(events)
        results.append(
            {
                **common,
                "market": "BTCUSDT + ETHUSDT",
                **summarize(pool, remaining, 2 * CAPITAL),
            }
        )
    write(
        output,
        {
            **preflight,
            "isolation_probe": isolation,
            "piner_version": PINER_VERSION,
            "piner_tarball_sha512": PINER_PIN,
            "artifacts": {
                name: sha256(work / name)
                for name in ("replay-ha.mjs", "ha-receipt.json", "feeds.json")
            },
            "cost_model": {
                "fee_per_side": FEE,
                "execution_buffer_per_side": EXECUTION,
                "lot_step": LOT_STEP,
            },
            "execution": "Same-bar close market fills on regular OHLC. Heikin-Ashi close is used for signals only. Source archive was BTCUSDT; ETHUSDT runs the same strategy and dates as comparative research.",
            "evidence": {
                "closed": fills,
                "per_market": findings,
                "independent_checks": "Every reference close, position reversal, regular-price fill, base-lot quantity, fee and P&L independently reconciled.",
            },
            "coverage": [
                [
                    IDENT,
                    f"Tested · {GROUP}",
                    "Original archive dates and timeframe verified against Binance files. Equivalent same-symbol alias and both Piner backends reconciled.",
                ]
            ],
            "results": results,
        },
    )
    print(
        f"Verified source {IDENT} with {len(results)} result rows and {fills} closed trades."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, handler, args in (
        ("stage", stage, ("archive", "ledger", "public", "prior_runtime", "output")),
        ("finalize", finalize, ("archive", "ledger", "public", "work", "output")),
    ):
        command = commands.add_parser(name)
        for arg in args:
            command.add_argument(arg, type=Path)
        command.set_defaults(handler=handler)
    settings = vars(parser.parse_args())
    settings.pop("command")
    settings.pop("handler")(**settings)


if __name__ == "__main__":
    main()
