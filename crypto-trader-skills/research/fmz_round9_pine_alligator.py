"""Replay native daily Alligator with Pine v5 eager history and validate fills."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from hashlib import sha512
from itertools import chain
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

IDENT = 86
DAY = 86_400_000
CAPITAL = 10_000
LOT_STEP = 0.001
TICKS = {"BTCUSDT": 0.1, "ETHUSDT": 0.01}
SLIPPAGE_TICKS = 5
SMMA_LENGTHS = (13, 8, 5)
WINDOWS = (
    ("Alligator native daily", "2023-05-11", "2024-05-16"),
    ("Alligator following daily", "2024-05-16", "2025-05-22"),
)
GROUP = "FMZ Pine · Native daily · Verified Alligator v5 history"
WITNESSES = '\nplot(jaw_o, "Audited jaw")\nplot(teeth_o, "Audited teeth")\nplot(lips_o, "Audited lips")\n'


def eager_variant(code):
    assert re.findall(r"(?m)^\w+ = smma\(([^\n]+)", code) == [
        "hl2, 13)[8]",
        "hl2, 8)[5]",
        "hl2, 5)[3]",
        "hl2, 13)",
        "hl2, 8)",
        "hl2, 5)",
    ]
    seed = "    smma := na(smma[1]) ? ta.sma(src, length) : (smma[1] * (length - 1) + src) / length"
    assert code.count(seed) == 1
    code = code.replace(
        seed,
        "    smaSeed = ta.sma(src, length)\n"
        + seed.replace("ta.sma(src, length)", "smaSeed"),
    )
    conditional = "longCondition = is_LowAboveAlligator(jaw, teeth, lips) and is_AlligatorHungry(jaw_o, teeth_o, lips_o)"
    assert code.count(conditional) == 1
    code = code.replace(
        conditional,
        "alligatorHungry = is_AlligatorHungry(jaw_o, teeth_o, lips_o)\nlongCondition = is_LowAboveAlligator(jaw, teeth, lips) and alligatorHungry",
    )
    assert code.count("timenow") == 2
    code, payloads = re.subn(
        r'(?m)^(\s*strategy\.(?:entry|close)\(id = "entry1"[^\n]*?), alert_message = .*?\)[ \t]*$',
        r"\1)",
        code,
    )
    assert payloads == 2 and "timenow" not in code
    return (code.rstrip() + "\n" + WITNESSES).encode("utf-8")


def inspect_source(archive, ledger):
    assert sha256(archive) == FMZ_SHA256
    (row,) = [item for item in read(ledger)["disposition"] if item["id"] == IDENT]
    assert row["status"].startswith("Pending")
    _, originals = archival_items(archive, {IDENT: row})
    code, digest, interval = originals[IDENT]
    assert interval == "1d"
    with ZipFile(archive) as source:
        _, _, document, observed_digest = next(documents(source, {IDENT: row}))
    assert observed_digest == digest
    fields = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):\s*([^\r\n]+)", document
        )
    )
    assert fields == {
        "start": "2023-05-11 00:00:00",
        "end": "2024-05-16 00:00:00",
        "period": "1d",
        "basePeriod": "1h",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    original, _ = strip_fmz_wrapper(code)
    return (
        row,
        digest,
        fields,
        original.encode("utf-8"),
        eager_variant(original.replace("\r\n", "\n")),
    )


def provider_data(public):
    manifest, feeds = [], {}
    months = [
        f"{year}-{month:02}"
        for year in range(2023, 2026)
        for month in range(1, 13)
        if "2023-05" <= f"{year}-{month:02}" <= "2025-05"
    ]
    sizes = set()
    for symbol in TICKS:
        archives = verified_archives(public, symbol, "1d", months, manifest)
        candles = list(chain.from_iterable(raw_ohlcv(file, DAY) for file in archives))
        for label, start, end in WINDOWS:
            first, last = date_ms(start), date_ms(end)
            bars = [list(candle) for candle in candles if first <= candle[0] < last]
            assert [bar[0] for bar in bars] == list(range(first, last, DAY))
            sizes.add(len(bars))
            feeds.setdefault(label, {})[symbol] = bars
    assert sizes == {371}
    return manifest, feeds


def stage(archive, ledger, public, runtime, work):
    _, _, _, original, variant = inspect_source(archive, ledger)
    _, candles = provider_data(public)
    work.mkdir(parents=True, exist_ok=True)
    copy_runtime(runtime, work)
    copy2(Path(__file__).with_suffix(".mjs"), work / "replay-alligator.mjs")
    (work / "source-86.pine").write_bytes(original)
    (work / "variant-86.pine").write_bytes(variant)
    write(work / "alligator-feeds.json", candles)


def average(values, length):
    state = fsum(values[:length]) / length
    result = [None] * (length - 1) + [state]
    for value in values[length:]:
        state = (state * (length - 1) + value) / length
        result.append(state)
    return result


def verify_case(case, bars):
    midpoint = [(bar[2] + bar[3]) / 2 for bar in bars]
    jaw, teeth, lips = lines = [average(midpoint, length) for length in SMMA_LENGTHS]
    for actual, expected in zip(case["series"], lines, strict=True):
        for value, reference in zip(actual, expected, strict=True):
            assert (
                value is None
                if reference is None
                else isclose(value, reference, rel_tol=1e-13)
            )
    open_at, positions = None, []
    for index in range(20, len(bars) - 1):
        lagged_bands = jaw[index - 8], teeth[index - 5], lips[index - 3]
        hungry = (
            lips[index] > jaw[index - 5]
            and lips[index] > teeth[index - 2]
            and teeth[index] > jaw[index - 3]
        )
        if open_at is None and bars[index][3] > max(lagged_bands) and hungry:
            open_at = index + 1
        if open_at is not None and bars[index][4] < lagged_bands[0]:
            positions.append((open_at, index + 1))
            open_at = None
    assert case["unsettled"] == int(open_at is not None)
    assert len(positions) == len(case["closed"])
    times = [bar[0] for bar in bars]
    equity = CAPITAL
    slippage = TICKS[case["market"]] * SLIPPAGE_TICKS
    settlements = []
    for trade, (entry, exit_bar) in zip(case["closed"], positions, strict=True):
        assert (trade["entryBar"], trade["exitBar"], trade["dir"]) == (
            entry,
            exit_bar,
            1,
        )
        assert isclose(trade["entryPrice"], bars[entry][1] + slippage, rel_tol=1e-12)
        assert isclose(trade["exitPrice"], bars[exit_bar][1] - slippage, rel_tol=1e-12)
        expected_size = floor(equity / trade["entryPrice"] / LOT_STEP) * LOT_STEP
        assert isclose(trade["qty"], expected_size, rel_tol=1e-10)
        flow = verify_trade(trade, times)
        equity += flow[1] - flow[2]
        settlements.append(flow)
    return settlements


def finalize(archive, ledger, public, work, output):
    row, digest, fields, original, variant = inspect_source(archive, ledger)
    manifest, feeds = provider_data(public)
    assert feeds == read(work / "alligator-feeds.json")
    assert original == (work / "source-86.pine").read_bytes()
    assert variant == (work / "variant-86.pine").read_bytes()
    assert (
        Path(__file__).with_suffix(".mjs").read_bytes()
        == (work / "replay-alligator.mjs").read_bytes()
    )
    assert (work / "replay-alligator.exit").read_text().strip() == "0"
    isolation = read(work / "isolation-probe.json")
    assert isolation == {"privateDenied": True, "networkDenied": True}
    package = work / f"piner-{PINER_VERSION}.tgz"
    assert b64encode(sha512(package.read_bytes()).digest()).decode("ascii") == PINER_PIN
    with open_tar(package, "r:gz") as distribution:
        bundle = distribution.extractfile("package/dist/index.js").read()
    assert bundle == (work / "package/dist/index.js").read_bytes()
    receipt = read(work / "alligator-receipt.json")
    assert receipt["source_sha256"] == sha256(work / "source-86.pine")
    assert receipt["variant_sha256"] == sha256(work / "variant-86.pine")
    assert (
        receipt["settings"]["initialCapital"] == CAPITAL
        and receipt["settings"]["qtyValue"] == 100
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
            "interval": "1d",
            "archive_interval": "1d",
            "group": GROUP,
            "exit": "Archived next-open market close with slippage",
            "market_data": "Binance USD-M historical futures candles",
            "repairs": {
                "Explicit v5 eager function history and equivalent finite-price SMA seed": 2,
                "Historical alert text excluded": 2,
            },
        }
        for market, candles in markets.items():
            case = cases[(period, market)]
            flow = verify_case(case, candles)
            unsettled = case["unsettled"]
            results.append(
                {**common, "market": market, **summarize(flow, unsettled, CAPITAL)}
            )
            pool.extend(flow)
            unresolved += unsettled
            count += len(flow)
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
            "piner_version": PINER_VERSION,
            "piner_tarball_sha512": PINER_PIN,
            "isolation_probe": isolation,
            "artifacts": {
                name: sha256(work / name)
                for name in (
                    "replay-alligator.mjs",
                    "alligator-feeds.json",
                    "alligator-receipt.json",
                )
            },
            "cost_model": {
                "fee_per_side": FEE,
                "execution_buffer_per_side": EXECUTION,
                "source_slippage_ticks_per_market_fill": SLIPPAGE_TICKS,
            },
            "references": [
                "https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-6/#lazy-evaluation-of-conditions"
            ],
            "method": "Both Piner backends matched. Independent chart arithmetic verified every jaw/teeth/lips value, entry, exit, equity-dependent quantity, price including archived slippage, and fee. Gross is before commission and includes the archive's five-tick price offset.",
            "coverage": [
                [
                    IDENT,
                    f"Tested · {GROUP}",
                    "Native daily OHLCV and eager Pine v5 history verified against independent arithmetic.",
                ]
            ],
            "results": results,
        },
    )
    print(
        f"Verified native Alligator source {IDENT}, {len(results)} rows and {count} closed trades."
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
