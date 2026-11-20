"""Replay FMZ's native 1h Double Breakthrough default and verify every reversal."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from hashlib import sha512
from itertools import pairwise
from pathlib import Path
from shutil import copy2
from tarfile import open as open_tar
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round6_pine import archival_items
from research.fmz_round7_magnifier import FMZ_SHA256, sha256
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
from research.fmz_round8_pine_zigzag import HOUR, MARKETS, POOLED, provider_data

IDENT = 2733
CAPITAL = 1_000_000
FIXED_QTY = 2
GROUP = "FMZ Pine · Native 1h · Verified Double Breakthrough reversals"


def display_variant(code):
    required = (
        r"^InitCapital = 1000000$",
        r"^InitPosition = 2$",
        r"^InitPyramidMax = 1$",
        r"^CalcOnorderFills = false$",
        r"^ProcessOrdersOnClose = true //",
        r"^TradeDateIsAllowed\(\) => true$",
        r"^nb_contracts = input\.int\(2,",
        r'^use_sl\s*= input\.string\("None",',
        r'^use_tp\s*= input\.string\("None",',
        r"\bprocess_orders_on_close=ProcessOrdersOnClose\b",
    )
    assert all(re.search(pattern, code, re.MULTILINE) for pattern in required)
    label = re.compile(
        r"^if show_alerts_debug and barstate\.islastconfirmedhistory\s*\n(?:[ \t]+[^\n]*\n|\n)*",
        re.MULTILINE,
    )
    (match,) = label.finditer(code)
    block = match[0]
    assert "lblTest := label.new(" in block and "strategy." not in block
    variant = code[: match.start()] + code[match.end() :]
    assert "lblTest" not in variant
    assert re.findall(r'^\s*strategy\.entry\(id = "(\w+)"', variant, re.MULTILINE) == [
        "Long",
        "Short",
    ]
    return variant.encode("utf-8")


def inspect_source(archive, ledger):
    assert sha256(archive) == FMZ_SHA256
    (row,) = [item for item in read(ledger)["disposition"] if item["id"] == IDENT]
    assert row["status"].startswith("Pending")
    _, originals = archival_items(archive, {IDENT: row})
    code, digest, interval = originals[IDENT]
    assert interval == "1h"
    with ZipFile(archive) as source:
        _, _, document, observed_digest = next(documents(source, {IDENT: row}))
    assert digest == observed_digest
    fields = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):\s*([^\r\n]+)", document
        )
    )
    assert fields == {
        "start": "2023-12-01 00:00:00",
        "end": "2023-12-31 23:59:59",
        "period": "1h",
        "basePeriod": "15m",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    original, _ = strip_fmz_wrapper(code)
    return (
        row,
        digest,
        fields,
        original.encode("utf-8"),
        display_variant(original.replace("\r\n", "\n")),
    )


def native_hourly(public):
    manifest, archival = provider_data(public)
    return manifest, {
        label.replace("2h", "1h"): {
            symbol: [
                [
                    row[key]
                    for key in ("openTime", "open", "high", "low", "close", "volume")
                ]
                for row in window["market"]["references"][symbol]["60"]
            ]
            for symbol in MARKETS
        }
        for label, window in archival.items()
    }


def stage(archive, ledger, public, runtime, work):
    _, _, _, original, variant = inspect_source(archive, ledger)
    _, feeds = native_hourly(public)
    work.mkdir(parents=True, exist_ok=True)
    copy_runtime(runtime, work)
    copy2(Path(__file__).with_suffix(".mjs"), work / "replay-double.mjs")
    (work / "source-2733.pine").write_bytes(original)
    (work / "variant-2733.pine").write_bytes(variant)
    write(work / "double-feeds.json", feeds)


def check_case(case, candles):
    transitions, direction = [], 0
    for index in range(2, len(candles)):
        a, b, now = candles[index - 2 : index + 1]
        bull = (
            now[4] > now[1] and now[4] > max(a[4], a[1]) and b[3] < a[3] and b[2] < a[2]
        )
        bear = (
            now[4] < now[1] and now[4] < min(a[4], a[1]) and b[3] > a[3] and b[2] > a[2]
        )
        signal = int(bull) - int(bear)
        if signal and signal != direction:
            transitions.append((index, signal))
            direction = signal
    assert case["unsettled"] == int(bool(transitions))
    assert len(case["closed"]) == max(0, len(transitions) - 1)
    times = [row[0] for row in candles]
    settlements = []
    for trade, ((entry, side), (exit_bar, _)) in zip(
        case["closed"], pairwise(transitions), strict=True
    ):
        assert [trade[key] for key in ("entryBar", "dir", "exitBar")] == [
            entry,
            side,
            exit_bar,
        ]
        assert (
            trade["entryPrice"] == candles[entry][4]
            and trade["exitPrice"] == candles[exit_bar][4]
        )
        assert trade["qty"] == FIXED_QTY
        epoch, *flow = verify_trade(trade, times)
        settlements.append((epoch + HOUR, *flow))
    return settlements


def finalize(archive, ledger, public, work, output):
    row, digest, fields, original, variant = inspect_source(archive, ledger)
    manifest, feeds = native_hourly(public)
    assert feeds == read(work / "double-feeds.json")
    assert original == (work / "source-2733.pine").read_bytes()
    assert variant == (work / "variant-2733.pine").read_bytes()
    assert (
        Path(__file__).with_suffix(".mjs").read_bytes()
        == (work / "replay-double.mjs").read_bytes()
    )
    assert (work / "replay-double.exit").read_text().strip() == "0"
    isolation = read(work / "isolation-probe.json")
    assert isolation == {"privateDenied": True, "networkDenied": True}
    package = work / f"piner-{PINER_VERSION}.tgz"
    assert b64encode(sha512(package.read_bytes()).digest()).decode("ascii") == PINER_PIN
    with open_tar(package, "r:gz") as distribution:
        bundle = distribution.extractfile("package/dist/index.js").read()
    assert bundle == (work / "package/dist/index.js").read_bytes()
    receipt = read(work / "double-receipt.json")
    assert receipt["source_sha256"] == sha256(work / "source-2733.pine")
    assert receipt["variant_sha256"] == sha256(work / "variant-2733.pine")
    assert (
        receipt["settings"]["initialCapital"] == CAPITAL
        and receipt["settings"]["qtyValue"] == FIXED_QTY
    )
    cases = {(case["period"], case["market"]): case for case in receipt["cases"]}
    assert len(cases) == len(receipt["cases"]) == 4
    results, count = [], 0
    for period, markets in feeds.items():
        pool, unresolved = [], 0
        common = {
            "id": IDENT,
            "name": row["name"],
            "source": row["source"],
            "source_sha256": digest,
            "executed_source_sha256": receipt["variant_sha256"],
            "period": period,
            "quote_currency": "USDT",
            "interval": "60m",
            "archive_interval": "1h",
            "group": GROUP,
            "exit": "Archived source candle reversal",
            "market_data": "Binance USD-M historical futures candles",
            "repairs": {
                "Alert debug drawing excluded without changing signals or broker calls": 1
            },
        }
        for market, candles in markets.items():
            case = cases[(period, market)]
            flow = check_case(case, candles)
            unsettled = case["unsettled"]
            results.append(
                {**common, "market": market, **summarize(flow, unsettled, CAPITAL)}
            )
            pool.extend(flow)
            unresolved += unsettled
            count += len(flow)
        results.append(
            {**common, "market": POOLED, **summarize(pool, unresolved, 2 * CAPITAL)}
        )
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(ledger),
            "archive_sha256": FMZ_SHA256,
            "original_archive_settings": fields,
            "original_document_sha256": digest,
            "published_binance_candles": manifest,
            "piner_version": PINER_VERSION,
            "piner_tarball_sha512": PINER_PIN,
            "isolation_probe": isolation,
            "artifacts": {
                name: sha256(work / name)
                for name in (
                    "replay-double.mjs",
                    "double-feeds.json",
                    "double-receipt.json",
                )
            },
            "cost_model": {"fee_per_side": FEE, "execution_buffer_per_side": EXECUTION},
            "method": "Saved stop and target modes both disabled. Original BTCUSDT native 1h window, comparative ETHUSDT and equal-length follow-up. Both Piner backends matched, with each signal, same-close trade, size and fee independently reconciled from regular OHLCV.",
            "coverage": [
                [
                    IDENT,
                    f"Tested · {GROUP}",
                    "Archived fixed quantity and same-close timing verified independently against unmodified source entry rules.",
                ]
            ],
            "results": results,
        },
    )
    print(
        f"Verified native Double Breakthrough source {IDENT}, {len(results)} rows and {count} closed trades."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, handler, arguments in (
        ("stage", stage, ("archive", "ledger", "public", "runtime", "work")),
        ("finalize", finalize, ("archive", "ledger", "public", "work", "output")),
    ):
        command = commands.add_parser(name)
        for arg in arguments:
            command.add_argument(arg, type=Path)
        command.set_defaults(handler=handler)
    options = vars(parser.parse_args())
    options.pop("command")
    options.pop("handler")(**options)


if __name__ == "__main__":
    main()
