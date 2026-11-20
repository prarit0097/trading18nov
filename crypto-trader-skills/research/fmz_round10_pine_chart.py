"""Replay chart-trading logic independently of unused Pine sessions and panels."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from collections import deque
from hashlib import sha512
from itertools import chain, pairwise
from math import floor, fsum, isclose, log
from pathlib import Path
from shutil import copy2
from statistics import pstdev
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
from research.fmz_round10_pine_legacy import replace_once

MARKETS = ("BTCUSDT", "ETHUSDT")
LOT_STEP = 0.001
CAPITAL = {1375: 10_000, 1768: 1_000}
DATES = {
    1375: ("2024-01-01", "2024-01-24", "2024-02-16", "1h", "Next equal 1h"),
    1768: ("2023-01-01", "2023-10-26", "2025-03-09", "1d", "Next 500 daily"),
}
REPAIRS = {
    1375: "Dormant session section separated and v4 scalar operators retained",
    1768: "Display table separated and documented prior-window rising semantics restored",
}


def bollinger_variant(source):
    source, removed = re.subn(r"(?ms)^// session\s*\n.+?(?=^//   vfi)", "", source)
    assert removed == 1
    assert not re.search(
        r"\b(?:isinsession|preNew|preSession|preHigh|preLow|trade_session|is_session|is_newbar)\b",
        source,
    )
    changes = (
        ("//@version=4", "//@version=5"),
        ("ma(x,y) => 0 ? sma(x,y) : x", ""),
        ("vfi = ma(sum( vcp , length )/vave, 3)", "vfi = math.sum(vcp, length) / vave"),
        ("vc = iff(volume < vmax, volume, vmax)", "vc = volume < vmax ? volume : vmax"),
        (
            "vcp = iff( mf > cutoff, vc, iff ( mf < -cutoff, -vc, 0 ) )",
            "vcp = mf > cutoff ? vc : mf < -cutoff ? -vc : 0",
        ),
    )
    for old, new in changes:
        source = replace_once(source, old, new)
    source = re.sub(r"(?<![\w.])log\(", "math.log(", source)
    source = re.sub(
        r"(?<![\w.])(sma|ema|stdev|crossover|crossunder)\(", r"ta.\1(", source
    )
    source, entries = re.subn(
        r"(?m)^if (.+)\n    strategy.entry",
        r"longGate = \1\nif longGate\n    strategy.entry",
        source,
    )
    source, exits = re.subn(
        r"(?m)^if (.+)\n    strategy.close",
        r"closeGate = \1\nif closeGate\n    strategy.close",
        source,
    )
    assert entries == exits == 1
    return (
        source
        + '\nplot(vfi,"VFI proof")\nplot(vfima,"VFIMA proof")\nplot(diff,"EMA gap proof")\nplot(upper,"Upper proof")\nplot(longGate ? 1 : 0,"Long proof")\nplot(closeGate ? 1 : 0,"Exit proof")\n'
    )


def monthly_variant(source):
    head, body = source.split("// MONTHLY TABLE //", 1)
    assert set(re.findall(r"\bstrategy\.(\w+)", body)) == {"equity"}
    assert head.count("strategy.entry(") == head.count("strategy.close(") == 1
    changes = (
        ("//@version=4", "//@version=5"),
        ("input(400)", "input.int(400)"),
        ("vwma(", "ta.vwma("),
        (
            "uptrend= rising(wma, 5)",
            "priorMaximum = ta.highest(wma[1], 5)\nuptrend = not na(wma[5]) and wma > priorMaximum",
        ),
        ("downtrend= falling(wma,5)", ""),
    )
    for old, new in changes:
        head = replace_once(head, old, new)
    assert "downtrend" not in head
    return head + '\nplot(wma,"VWMA proof")\nplot(uptrend ? 1 : 0,"Rising proof")\n'


def source_cases(archive, ledger):
    assert sha256(archive) == FMZ_SHA256
    rows = {row["id"]: row for row in read(ledger)["disposition"] if row["id"] in DATES}
    assert rows.keys() == DATES.keys() and all(
        row["status"].startswith("Pending") for row in rows.values()
    )
    _, originals = archival_items(archive, rows)
    variants = {1375: bollinger_variant, 1768: monthly_variant}
    output = {}
    with ZipFile(archive) as source:
        for ident, row, document, observed in documents(source, rows):
            script, digest, interval = originals[ident]
            start, stop, _, expected_interval, _ = DATES[ident]
            assert observed == digest and interval == expected_interval
            settings = dict(
                re.findall(
                    r"(?m)^(start|end|period|basePeriod|exchanges):\s*([^\r\n]+)",
                    document,
                )
            )
            assert settings == {
                "start": f"{start} 00:00:00",
                "end": f"{stop} 00:00:00",
                "period": interval,
                "basePeriod": "15m" if ident == 1375 else "1h",
                "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
            }
            original, _ = strip_fmz_wrapper(script)
            variant = variants[ident](original.replace("\r\n", "\n"))
            output[ident] = (
                row,
                settings,
                digest,
                original.encode("utf-8"),
                variant.encode("utf-8"),
            )
    return output


def provider_data(hourly, daily):
    manifest, feeds = [], {}
    for ident, (first, split, last, interval, followup) in DATES.items():
        monthly = [
            f"{y}-{m:02}"
            for y in range(2023, 2026)
            for m in range(1, 13)
            if first[:7] <= f"{y}-{m:02}" <= last[:7]
        ]
        path, step = (hourly, 3_600_000) if ident == 1375 else (daily, 86_400_000)
        for symbol in MARKETS:
            archive_files = verified_archives(path, symbol, interval, monthly, manifest)
            records = list(
                chain.from_iterable(raw_ohlcv(file, step) for file in archive_files)
            )
            for label, start, end in (
                (f"FMZ native {interval}", first, split),
                (followup, split, last),
            ):
                lower, upper = date_ms(start), date_ms(end)
                bars = [list(row) for row in records if lower <= row[0] < upper]
                assert [bar[0] for bar in bars] == list(range(lower, upper, step))
                feeds.setdefault(str(ident), {}).setdefault(label, {})[symbol] = bars
    return manifest, feeds


def stage(archive, ledger, hourly, daily, runtime, work):
    inputs = source_cases(archive, ledger)
    _, feeds = provider_data(hourly, daily)
    work.mkdir(parents=True, exist_ok=True)
    copy_runtime(runtime, work)
    copy2(Path(__file__).with_suffix(".mjs"), work / "run.mjs")
    for ident, (_, _, _, source, variant) in inputs.items():
        (work / f"source-{ident}.pine").write_bytes(source)
        (work / f"variant-{ident}.pine").write_bytes(variant)
    write(work / "feeds.json", feeds)


def ema(value, previous, length):
    weight = 2 / (length + 1)
    return value if previous is None else previous * (1 - weight) + value * weight


def bollinger_reference(bars):
    closes = [row[4] for row in bars]
    volumes = [row[5] for row in bars]
    typical = [sum(row[2:5]) / 3 for row in bars]
    logarithms = list(map(log, typical))
    changes = [None] + [
        current - previous for previous, current in pairwise(logarithms)
    ]
    volumes_used = deque(maxlen=130)
    fast = slow = gap_average = flow_average = None
    previous_upper = previous_lower = None
    flow_trace, average_trace, gap_trace, upper_trace, entry, exit_gate = (
        [],
        [],
        [],
        [],
        [],
        [],
    )
    for index, price in enumerate(closes):
        fast, slow = ema(price, fast, 20), ema(price, slow, 50)
        gap = (fast - slow) * 100 / fast
        gap_average = ema(gap, gap_average, 20)
        previous_volume = (
            fsum(volumes[index - 130 : index]) / 130 if index >= 130 else None
        )
        cutoff = (
            0.2 * pstdev(changes[index - 29 : index + 1]) * price
            if index >= 30
            else None
        )
        volume = (
            min(volumes[index], previous_volume * 2.5)
            if previous_volume is not None
            else None
        )
        change = typical[index] - typical[index - 1] if index else 0
        money_flow = 0
        if cutoff is not None and abs(change) > cutoff:
            money_flow = None if volume is None else volume if change > 0 else -volume
        if money_flow is not None:
            volumes_used.append(money_flow)
        vfi = (
            fsum(volumes_used) / previous_volume
            if previous_volume is not None and len(volumes_used) == 130
            else None
        )
        if vfi is not None:
            flow_average = ema(vfi, flow_average, 5)
        upper = lower = None
        if index >= 19:
            recent = closes[index - 19 : index + 1]
            middle, width = fsum(recent) / 20, 1.5 * pstdev(recent)
            upper, lower = middle + width, middle - width
        cross_up = (
            previous_upper is not None
            and price > upper
            and closes[index - 1] <= previous_upper
        )
        cross_down = (
            previous_lower is not None
            and price < lower
            and closes[index - 1] >= previous_lower
        )
        flows = [value for value in (vfi, flow_average) if value is not None]
        permitted = (any(value > 0 for value in flows) or gap_average > 0.05) and any(
            value < 14 for value in flows
        )
        entry.append(
            int(
                cross_up
                and gap > gap_average
                and gap > 0
                or upper is not None
                and price > upper
                and permitted
            )
        )
        exit_gate.append(
            int(
                cross_down
                or any(value > 19 for value in flows)
                or gap < gap_average + 0.01
            )
        )
        flow_trace.append(vfi)
        average_trace.append(flow_average)
        gap_trace.append(gap)
        upper_trace.append(upper)
        previous_upper, previous_lower = upper, lower
    return (
        [flow_trace, average_trace, gap_trace, upper_trace, entry, exit_gate],
        entry,
        exit_gate,
    )


def monthly_reference(bars):
    vwma = [None] * min(399, len(bars))
    for index in range(399, len(bars)):
        window = bars[index - 399 : index + 1]
        vwma.append(
            fsum((row[2] + row[3]) / 2 * row[5] for row in window)
            / fsum(row[5] for row in window)
        )
    up = [
        int(index >= 404 and value > max(vwma[index - 5 : index]))
        for index, value in enumerate(vwma)
    ]
    return [vwma, up], up, [1 - signal for signal in up]


def check_case(ident, case, bars):
    reference = bollinger_reference if ident == 1375 else monthly_reference
    series, entry, exit_gate = reference(bars)
    for expected, actual in zip(series, case["witnesses"], strict=True):
        for x, y in zip(expected, actual, strict=True):
            assert (
                x is None
                and y is None
                or x is not None
                and y is not None
                and isclose(x, y, rel_tol=1e-10, abs_tol=1e-9)
            )
    holding, settled = None, []
    for index in range(len(bars) - 1):
        if holding is None:
            if entry[index]:
                holding = index + 1
        elif exit_gate[index]:
            settled.append((holding, index + 1))
            holding = None
    assert case["unsettled"] == int(holding is not None) and len(case["closed"]) == len(
        settled
    )
    times = [bar[0] for bar in bars]
    equity, events = CAPITAL[ident], []
    for trade, (i, j) in zip(case["closed"], settled, strict=True):
        assert (i, j, 1) == (trade["entryBar"], trade["exitBar"], trade["dir"])
        assert trade["entryPrice"] == bars[i][1] and trade["exitPrice"] == bars[j][1]
        cash = 1_000 if ident == 1375 else equity
        assert isclose(
            trade["qty"],
            floor(cash / trade["entryPrice"] / LOT_STEP) * LOT_STEP,
            rel_tol=1e-10,
        )
        flow = verify_trade(trade, times)
        equity += flow[1] - flow[2]
        events.append(flow)
    return events


def finalize(archive, ledger, hourly, daily, work, output):
    inputs = source_cases(archive, ledger)
    manifest, feeds = provider_data(hourly, daily)
    assert read(work / "feeds.json") == feeds
    assert (
        Path(__file__).with_suffix(".mjs").read_bytes()
        == (work / "run.mjs").read_bytes()
    )
    assert (work / "run.exit").read_text().strip() == "0"
    isolation = read(work / "isolation-probe.json")
    assert isolation == {"privateDenied": True, "networkDenied": True}
    package = work / f"piner-{PINER_VERSION}.tgz"
    assert b64encode(sha512(package.read_bytes()).digest()).decode("ascii") == PINER_PIN
    with open_tar(package, "r:gz") as distribution:
        assert (
            distribution.extractfile("package/dist/index.js").read()
            == (work / "package/dist/index.js").read_bytes()
        )
    receipts = read(work / "receipt.json")
    reported = {row["id"]: row for row in receipts}
    assert len(reported) == len(receipts) == 2 and reported.keys() == inputs.keys()
    coverage, summaries, audits = [], [], {}
    for ident, (row, settings, digest, original, adapted) in inputs.items():
        source, variant = work / f"source-{ident}.pine", work / f"variant-{ident}.pine"
        assert source.read_bytes() == original and variant.read_bytes() == adapted
        receipt = reported[ident]
        assert receipt["diagnostics"] == []
        assert receipt["sourceHash"] == sha256(source) and receipt[
            "variantHash"
        ] == sha256(variant)
        cases = {(case["period"], case["market"]): case for case in receipt["cases"]}
        assert len(cases) == len(receipt["cases"]) == 4
        group = "FMZ Pine · Native verified chart decisions"
        common = {
            "id": ident,
            "name": row["name"],
            "source": row["source"],
            "source_sha256": digest,
            "executed_source_sha256": receipt["variantHash"],
            "interval": DATES[ident][3],
            "archive_interval": DATES[ident][3],
            "quote_currency": "USDT",
            "group": group,
            "exit": "Source next-open market close",
            "market_data": "Binance USD-M historical futures candles",
            "repairs": {REPAIRS[ident]: 1},
        }
        closes = 0
        for period, markets in feeds[str(ident)].items():
            pooled, pending = [], 0
            for market, bars in markets.items():
                case = cases[(period, market)]
                cashflow = check_case(ident, case, bars)
                ongoing = case["unsettled"]
                summaries.append(
                    {
                        **common,
                        "period": period,
                        "market": market,
                        **summarize(cashflow, ongoing, CAPITAL[ident]),
                    }
                )
                pooled.extend(cashflow)
                closes += len(cashflow)
                pending += ongoing
            summaries.append(
                {
                    **common,
                    "period": period,
                    "market": "BTCUSDT + ETHUSDT",
                    **summarize(pooled, pending, 2 * CAPITAL[ident]),
                }
            )
        audits[ident] = {
            "original_document_sha256": digest,
            "original_archive_settings": settings,
            "closed": closes,
        }
        coverage.append(
            [
                ident,
                f"Tested · {group}",
                "Native reference series and each market settlement reconciled by independent code.",
            ]
        )
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(ledger),
            "archive_sha256": FMZ_SHA256,
            "isolation_probe": isolation,
            "published_binance_candles": manifest,
            "piner_version": PINER_VERSION,
            "piner_tarball_sha512": PINER_PIN,
            "artifacts": {
                name: sha256(work / name)
                for name in ("feeds.json", "run.mjs", "receipt.json")
            },
            "cost_model": {
                "fee_per_side": FEE,
                "execution_buffer_per_side": EXECUTION,
                "lot_step": LOT_STEP,
            },
            "references": ["https://www.fmz.com/bbs-topic/9293"],
            "method": "Original BTCUSDT windows and native Binance intervals plus comparative ETHUSDT and later periods. For #1768 the comparison explicitly waits for the full 400-day VWMA and five preceding finite values. Its original 298-day cold-start window has no signal. Both Piner backends and independent indicator, fill, quantity and fee verifiers agree.",
            "source_audits": audits,
            "coverage": coverage,
            "results": summaries,
        },
    )
    print(
        f"Verified {len(inputs)} chart strategies and {len(summaries)} rows, {sum(row['closed'] for row in audits.values())} closed trades."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, handler, args in (
        ("stage", stage, ("archive", "ledger", "hourly", "daily", "runtime", "work")),
        (
            "finalize",
            finalize,
            ("archive", "ledger", "hourly", "daily", "work", "output"),
        ),
    ):
        subcommand = commands.add_parser(name)
        for param in args:
            subcommand.add_argument(param, type=Path)
        subcommand.set_defaults(handler=handler)
    settings = vars(parser.parse_args())
    settings.pop("command")
    settings.pop("handler")(**settings)


if __name__ == "__main__":
    main()
