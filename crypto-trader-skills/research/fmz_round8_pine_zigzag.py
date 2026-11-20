"""Verify the archive's native two-hour ZigZag with its one-hour reference."""

from __future__ import annotations

import argparse
import re
from itertools import chain
from math import isclose
from pathlib import Path
from shutil import copy2
from zipfile import ZipFile

from research.delta_pine_liquid_replay import checksum
from research.delta_pinets_catalogue import read, write
from research.delta_strategy_replay import ROOT
from research.fmz_round3_liquid_feeds import reconcile
from research.fmz_round3_timeframe_feeds import read_receipts
from research.fmz_round4_feeds import artifact_hashes, documents
from research.fmz_round7_magnifier import (
    FMZ_SHA256,
    date_ms,
    raw_ohlcv,
    sha256,
    verified_archives,
)
from research.fmz_round7_pine import stage_zigzag

IDENT = 2953
MARKETS = ("BTCUSDT", "ETHUSDT")
SYMBOLS = {
    "BTCUSDT": {"tick": 0.1, "step": 0.001},
    "ETHUSDT": {"tick": 0.01, "step": 0.001},
}
POOLED = "BTCUSDT + ETHUSDT"
HOUR = 3_600_000
WINDOWS = (
    ("Archived 2h · Dec 2023", "2023-12-01", "2024-01-01"),
    ("Following 2h · Jan 2024", "2024-01-01", "2024-02-01"),
)
GROUP = "FMZ Pine · Native 2h Binance · Verified 1h reference"


def market_context(reference):
    return {
        "prefix": "BINANCE",
        "currency": "USDT",
        "symbols": SYMBOLS,
        "referenceSymbols": [],
        "references": reference,
        "heikinAshi": {},
    }


def candle_row(time, open_price, high, low, close, volume, step):
    return {
        "openTime": time,
        "closeTime": time + step,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def exact_two_hour(upper, lower):
    assert len(lower) == len(upper) * 2
    for index, bar in enumerate(upper):
        left, right = lower[2 * index : 2 * index + 2]
        assert left["openTime"] == bar["openTime"] == right["openTime"] - HOUR
        assert right["closeTime"] == bar["closeTime"]
        assert [bar[key] for key in ("open", "high", "low", "close")] == [
            left["open"],
            max(left["high"], right["high"]),
            min(left["low"], right["low"]),
            right["close"],
        ]
        assert isclose(bar["volume"], left["volume"] + right["volume"], rel_tol=1e-12)


def provider_data(public):
    candles, manifest = {}, []
    for label, begin, finish in WINDOWS:
        start, end = date_ms(begin), date_ms(finish)
        series, refs = {}, {}
        for symbol in MARKETS:
            frames = {}
            for interval, step in (("1h", HOUR), ("2h", 2 * HOUR)):
                archives = verified_archives(
                    public, symbol, interval, (begin[:7],), manifest
                )
                rows = chain.from_iterable(raw_ohlcv(path, step) for path in archives)
                data = [candle_row(*row, step) for row in rows if start <= row[0] < end]
                assert [row["openTime"] for row in data] == list(
                    range(start, end, step)
                )
                frames[interval] = data
            lower, upper = frames["1h"], frames["2h"]
            exact_two_hour(upper, lower)
            series[symbol], refs[symbol] = [upper], {"60": lower}
        candles[label] = {**series, "market": market_context(refs)}
    return manifest, candles


def native_fixture():
    start = date_ms("2024-01-01")
    lower = [
        candle_row(start + i * HOUR, 10 + i, 11 + i, 9 + i, 10.25 + i, 1, HOUR)
        for i in range(16)
    ]
    upper = [
        candle_row(
            left["openTime"],
            left["open"],
            right["high"],
            left["low"],
            right["close"],
            2,
            2 * HOUR,
        )
        for left, right in zip(lower[::2], lower[1::2], strict=True)
    ]
    exact_two_hour(upper, lower)
    fixture_candles = {
        "Fixture A": {
            **{symbol: [upper] for symbol in MARKETS},
            "market": market_context({symbol: {"60": lower} for symbol in MARKETS}),
        }
    }
    source = """//@version=5
strategy("2h with closed 1h context")
sequence() =>
    var int state = na
    state := nz(state[1]) + 1
    state + close
v = request.security(syminfo.tickerid, "60", sequence(), barmerge.gaps_off, barmerge.lookahead_off)
if bar_index == 2 and v == 21.25
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 3 and v == 25.25
    strategy.close("L")
"""
    candidates = [
        {
            "id": 999004,
            "name": "Native merge and local history",
            "source": "fixture",
            "hash": "fixture",
            "archived": "2h",
            "code": source,
            "repairs": {},
            "snapshotVariant": False,
            "confirmedVariant": False,
            "allowFillRecalculation": False,
        }
    ]
    return candidates, fixture_candles


def source_metadata(archive, ledger):
    assert sha256(archive) == FMZ_SHA256
    (row,) = [row for row in read(ledger)["disposition"] if row["id"] == IDENT]
    assert row["status"].startswith("Pending")
    with ZipFile(archive) as source:
        _, _, document, source_digest = next(documents(source, {IDENT: row}))
    fields = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):\s*([^\r\n]+)", document
        )
    )
    assert fields == {
        "start": "2023-12-01 00:00:00",
        "end": "2023-12-31 23:59:59",
        "period": "2h",
        "basePeriod": "15m",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    return row, fields, source_digest


def stage(archive, ledger, public, previous, sandbox, work):
    source_metadata(archive, ledger)
    stage_zigzag(archive, previous, work)
    copy2(sandbox, work / "sandbox-worker.ps1")
    _, candles = provider_data(public)
    write(work / "pine-1/candles.json", candles)
    fixture = work / "native-fixture"
    fixture.mkdir()
    copy2(work / "pine-1/worker.mjs", fixture / "worker.mjs")
    candidates, bars = native_fixture()
    write(fixture / "candidates.json", candidates)
    write(fixture / "candles.json", bars)


def verify_fixture(work):
    fixture = work / "native-fixture"
    candidates, bars = native_fixture()
    assert read(fixture / "candidates.json") == candidates
    assert read(fixture / "candles.json") == bars
    assert (work / "native-fixture-node.exit").read_text().strip() == "0"
    (item,) = candidates
    (receipt,) = read_receipts(fixture).values()
    rows = receipt["results"]
    assert len(rows) == 3 and {row["market"] for row in rows} == {*MARKETS, POOLED}
    for row in rows:
        assert [row[key] for key in ("id", "period", "interval")] == [
            item["id"],
            "Fixture A",
            "120m",
        ]
        lots = 2 if row["market"] == POOLED else 1
        assert row["trades"] == lots and row["unsettled"] == 0
        assert isclose(row["gross"], lots * 4, abs_tol=1e-8)
        assert isclose(row["net"], lots * 3.93948, abs_tol=1e-8)
    return {
        "results": rows,
        "artifacts": artifact_hashes(
            fixture, ("candles.json", "candidates.json", "worker.mjs", "out.jsonl")
        ),
    }


def finalize(archive, ledger, public, work, output):
    row, fields, source_digest = source_metadata(archive, ledger)
    manifest, candles = provider_data(public)
    tried = read(ROOT / "fmz-round7-pine-zigzag.json")
    live = work / "pine-1"
    assert read(live / "candles.json") == candles
    assert sha256(work / "engine.mjs") == tried["engine_sha256"]
    worker_hash = sha256(live / "worker.mjs")
    assert worker_hash == sha256(work / "native-fixture/worker.mjs")
    assert worker_hash == tried["replay_artifacts"]["pine-1"]["worker.mjs"]
    assert (work / "pine-1-node.exit").read_text().strip() == "0"
    isolation = read(work / "isolation-probe.json")
    assert isolation == {"privateDenied": True, "networkDenied": True}
    fixture = verify_fixture(work)
    (item,) = read(live / "candidates.json")
    assert (
        item["id"] == IDENT
        and item["source"] == row["source"]
        and item["hash"] == source_digest
    )
    assert tried["attempts"][str(IDENT)]["migrated_source_sha256"] == checksum(
        item["code"].encode("utf-8")
    )
    (receipt,) = read_receipts(live).values()
    assert receipt["id"] == IDENT
    results = receipt["results"]
    reconcile(results, tuple(candles), item, 120)
    assert all(
        result["trades"] == 0
        and result["unsettled"] == (2 if result["market"] == POOLED else 1)
        for result in results
    )
    for result in results:
        result.update(
            group=GROUP,
            quote_currency="USDT",
            market_data="Binance USD-M historical futures candles",
            repairs=item["repairs"],
        )
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(ledger),
            "archive_sha256": FMZ_SHA256,
            "original_document_sha256": source_digest,
            "original_archive_settings": fields,
            "published_binance_candles": manifest,
            "isolation_probe": isolation,
            "fixture": fixture,
            "artifacts": artifact_hashes(
                live, ("candles.json", "candidates.json", "worker.mjs", "out.jsonl")
            ),
            "pinescript_engine_sha256": tried["engine_sha256"],
            "method": "Original native 2h BTCUSDT archive, comparative ETHUSDT and equal monthly follow-up. Each 2h candle independently reconciled to two official 1h candles. PineTS fixture confirms last closed lower bar and function-local recursion.",
            "coverage": [
                [
                    IDENT,
                    f"Tested · {GROUP}, no closes",
                    "One genuine archived-strategy position remained open in each individual replay, with no close event to settle.",
                ]
            ],
            "results": results,
        },
    )
    print(
        f"Verified native ZigZag source {IDENT}, {len(results)} rows, four open positions and zero closes."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, handler, args in (
        (
            "stage",
            stage,
            ("archive", "ledger", "public", "previous", "sandbox", "work"),
        ),
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
