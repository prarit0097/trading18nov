"""Replay the archived enabled daily wave and independently verify all signals."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from datetime import UTC, datetime
from hashlib import sha512
from itertools import chain, pairwise
from math import floor, isclose
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

IDENT = 5582
MARKETS = ("BTCUSDT", "ETHUSDT")
DAY = 86_400_000
LOT_STEP = 0.001
CAPITAL = 1_000
CASH = 1_000
AMPLITUDE = 28
WINDOWS = (
    ("FMZ native daily", date_ms("2022-11-14"), date_ms("2023-11-20")),
    ("Following daily", date_ms("2023-11-20"), date_ms("2024-11-25")),
)
GROUP = "FMZ Pine · Native daily · Archived enabled candle-color wave"


def source_variant(original):
    for stem, expected in (
        ("bar_change", "true"),
        ("volume", "false"),
        ("coin_flip", "false"),
    ):
        assert re.search(
            rf"^\b{stem}_trade = input\.bool\(defval={expected},",
            original,
            re.MULTILINE,
        )
    assert re.search(
        r'^bar_change_sine_wave_res = input\.timeframe\(defval="D",',
        original,
        re.MULTILINE,
    )
    assert re.search(
        r"^bar_color_time_adj = request\.security\(syminfo\.tickerid, bar_change_sine_wave_res, bar_color\)$",
        original,
        re.MULTILINE,
    )
    assert re.findall(
        r'\bstrategy\.(?:entry|order|close|exit)\(id="([^"]+)"', original
    ) == [
        "short",
        "long",
        "short-volume",
        "long-volume",
        "short-coinflip",
        "long-coinflip",
    ]
    patterns = (
        r"^//@version=5$",
        r"^strategy\([^\n]+$",
        r"^var bar_change_wave_direction = [^\n]+$",
        r"^bar_change_sine_wave_number = [^\n]+$",
        r"^bar_change_trade = [^\n]+$",
        r"^bar_color = [^\n]+$",
        r"^var bar_change_wave_count = 0$",
        r"^if\(bar_color_time_adj\[1\] != bar_color_time_adj\)\n    bar_change_wave_count :=[^\n]+$",
        r"^if\(math\.abs\(bar_change_wave_count\)[^\n]+\n    bar_change_wave_direction :=[^\n]+$",
        r'^if\(bar_change_wave_count==[^\n]+\n    strategy\.entry\(id="short"[^\n]+$',
        r'^if\(bar_change_wave_count==[^\n]+\n    strategy\.entry\(id="long"[^\n]+$',
        r'^plot\(bar_change_wave_count,title="Bar Change"[^\n]+$',
    )
    blocks = []
    for pattern in patterns:
        (match,) = re.findall(pattern, original, re.MULTILINE)
        blocks.append(match)
    blocks.insert(6, "bar_color_time_adj = bar_color")
    return ("\n".join(blocks) + "\n").encode("utf-8")


def inspect_source(archive, ledger):
    assert sha256(archive) == FMZ_SHA256
    (row,) = [cell for cell in read(ledger)["disposition"] if cell["id"] == IDENT]
    assert row["status"].startswith("Pending")
    _, originals = archival_items(archive, {IDENT: row})
    code, digest, interval = originals[IDENT]
    assert interval == "1d"
    with ZipFile(archive) as source:
        _, _, document, document_digest = next(documents(source, {IDENT: row}))
    assert digest == document_digest
    fields = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):\s*([^\r\n]+)", document
        )
    )
    assert fields == {
        "start": "2022-11-14 00:00:00",
        "end": "2023-11-20 00:00:00",
        "period": "1d",
        "basePeriod": "1h",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    original, _ = strip_fmz_wrapper(code)
    return (
        row,
        fields,
        digest,
        original.encode("utf-8"),
        source_variant(original.replace("\r\n", "\n")),
    )


def provider_data(public):
    boundaries = [
        datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m")
        for ms in (WINDOWS[0][1], WINDOWS[-1][2] - DAY)
    ]
    months = [
        f"{year}-{month:02}"
        for year in (2022, 2023, 2024)
        for month in range(1, 13)
        if boundaries[0] <= f"{year}-{month:02}" <= boundaries[1]
    ]
    candles, manifest = {}, []
    assert WINDOWS[0][2] - WINDOWS[0][1] == WINDOWS[1][2] - WINDOWS[1][1]
    for market in MARKETS:
        archives = verified_archives(public, market, "1d", months, manifest)
        bars = list(chain.from_iterable(raw_ohlcv(file, DAY) for file in archives))
        for label, start, end in WINDOWS:
            window = [bar for bar in bars if start <= bar[0] < end]
            assert [bar[0] for bar in window] == list(range(start, end, DAY))
            candles.setdefault(label, {})[market] = window
    return manifest, candles


def stage(archive, ledger, public, runtime, work):
    _, _, _, original, variant = inspect_source(archive, ledger)
    _, candles = provider_data(public)
    work.mkdir(parents=True, exist_ok=True)
    copy_runtime(runtime, work)
    copy2(Path(__file__).with_suffix(".mjs"), work / "replay-wave.mjs")
    (work / "source-5582.pine").write_bytes(original)
    (work / "variant-5582.pine").write_bytes(variant)
    write(work / "wave-feeds.json", candles)


def verify_case(case, candles):
    colors = [bar[4] > bar[1] for bar in candles]
    count, direction, walk = 0, 1, [0]
    for previous, current in pairwise(colors):
        if previous != current:
            count += direction
            if abs(count) == AMPLITUDE:
                direction = -direction
        walk.append(count)
    assert case["wave"] == walk
    positions, direction = [], 0
    for i, value in enumerate(walk[:-1]):
        signal = -value // AMPLITUDE if abs(value) == AMPLITUDE else 0
        if signal and signal != direction:
            positions.append((i + 1, signal))
            direction = signal
    assert len(case["closed"]) == max(0, len(positions) - 1)
    assert case["unsettled"] == int(bool(positions))
    times = [bar[0] for bar in candles]
    cashflows = []
    for trade, ((entry, side), (exit_bar, _)) in zip(
        case["closed"], pairwise(positions), strict=True
    ):
        assert (entry, side, exit_bar) == (
            trade["entryBar"],
            trade["dir"],
            trade["exitBar"],
        )
        assert (
            trade["entryPrice"] == candles[entry][1]
            and trade["exitPrice"] == candles[exit_bar][1]
        )
        assert isclose(
            trade["qty"], floor(CASH / trade["entryPrice"] / LOT_STEP) * LOT_STEP
        )
        cashflows.append(verify_trade(trade, times))
    return cashflows


def finalize(archive, ledger, public, work, output):
    row, fields, digest, original, variant = inspect_source(archive, ledger)
    manifest, candles = provider_data(public)
    assert read(work / "wave-feeds.json") == {
        p: {m: [list(bar) for bar in rows] for m, rows in markets.items()}
        for p, markets in candles.items()
    }
    assert (work / "source-5582.pine").read_bytes() == original
    assert (work / "variant-5582.pine").read_bytes() == variant
    assert (
        Path(__file__).with_suffix(".mjs").read_bytes()
        == (work / "replay-wave.mjs").read_bytes()
    )
    isolation = read(work / "isolation-probe.json")
    assert isolation == {"privateDenied": True, "networkDenied": True}
    assert (work / "replay-wave.exit").read_text().strip() == "0"
    package = work / f"piner-{PINER_VERSION}.tgz"
    assert b64encode(sha512(package.read_bytes()).digest()).decode("ascii") == PINER_PIN
    with open_tar(package, "r:gz") as distribution:
        bundle = distribution.extractfile("package/dist/index.js").read()
    assert (work / "package/dist/index.js").read_bytes() == bundle
    receipt = read(work / "wave-receipt.json")
    assert receipt["source_sha256"] == sha256(work / "source-5582.pine")
    assert receipt["variant_sha256"] == sha256(work / "variant-5582.pine")
    assert receipt["settings"]["initialCapital"] == CAPITAL
    cases = {(case["period"], case["market"]): case for case in receipt["cases"]}
    assert len(cases) == len(receipt["cases"]) == 4
    results, total_closes = [], 0
    for period, markets in candles.items():
        pool, unresolved = [], 0
        common = {
            "id": IDENT,
            "name": row["name"],
            "source": row["source"],
            "source_sha256": digest,
            "executed_source_sha256": receipt["variant_sha256"],
            "period": period,
            "quote_currency": "USDT",
            "interval": "1d",
            "archive_interval": "1d",
            "group": GROUP,
            "exit": "Archived wave reversal",
            "market_data": "Binance USD-M historical futures candles",
            "repairs": {
                "Same-symbol daily request uses the identical native chart series": 1,
                "Disabled independent volume and random branches excluded from the saved-default trading replay": 2,
            },
        }
        for market, rows in markets.items():
            case = cases[(period, market)]
            events = verify_case(case, rows)
            remaining = case["unsettled"]
            results.append(
                {**common, "market": market, **summarize(events, remaining, CAPITAL)}
            )
            pool.extend(events)
            unresolved += remaining
            total_closes += len(events)
        results.append(
            {
                **common,
                "market": "BTCUSDT + ETHUSDT",
                **summarize(pool, unresolved, 2 * CAPITAL),
            }
        )
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(ledger),
            "archive_sha256": FMZ_SHA256,
            "original_archive_settings": fields,
            "original_document_sha256": digest,
            "published_binance_candles": manifest,
            "isolation_probe": isolation,
            "piner_version": PINER_VERSION,
            "piner_tarball_sha512": PINER_PIN,
            "artifacts": {
                name: sha256(work / name)
                for name in ("replay-wave.mjs", "wave-feeds.json", "wave-receipt.json")
            },
            "cost_model": {
                "fee_per_side": FEE,
                "execution_buffer_per_side": EXECUTION,
                "lot_step": LOT_STEP,
            },
            "method": "Native saved daily chart and dates plus an equal following window, with BTCUSDT original and ETHUSDT comparative. Both Piner backends matched. An independent implementation reconciled each threshold transition, next-open execution, quantity, commission and net P&L.",
            "coverage": [
                [
                    IDENT,
                    f"Tested · {GROUP}",
                    "Verified archived active strategy with no random exposure at the saved settings.",
                ]
            ],
            "results": results,
        },
    )
    print(
        f"Verified native wave source {IDENT}, {len(results)} rows, {total_closes} closed trades."
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
