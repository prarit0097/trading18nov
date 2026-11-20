"""Verify native Pine strategies with a same-symbol historical reference."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from datetime import UTC, datetime
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
    aggregate,
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
from research.fmz_round11_pine_playzone import exponential

HOUR = 3_600_000
CAPITAL, CASH = 10_000, 1_000
LOT_STEP = 0.001
MARKETS = ("BTCUSDT", "ETHUSDT")
SPECS = {
    410: ("4h", "15m", "2021-05-08", "2022-05-07 23:59:00", "2022-05-07T20:00:00"),
    4732: ("1d", "1h", "2022-09-14", "2023-09-20 00:00:00", "2023-09-20"),
}
GROUPS = {
    410: "FMZ Pine · Native 4h · Authored Heikin-Ashi entry variant",
    4732: "FMZ Pine · Native daily · Verified legacy hourly reference",
}


def heikin_variant(code):
    changes = (
        (
            'indicator("Heikin-Ashi Trend Alert", overlay=true)',
            'strategy("Heikin-Ashi Trend Alert", overlay=true)',
        ),
        ("timeframe.period, ema_open)", "timeframe.period, ta.ema(open, ema_input))"),
        ("timeframe.period, ema_close)", "timeframe.period, ta.ema(close, ema_input))"),
    )
    for old, new in changes:
        code = replace_once(code, old, new)
    assert re.findall(r'\bstrategy\.entry\("([^"]+)"', code) == [
        "Enter Long",
        "Enter Short",
    ]
    return (
        code
        + '\nplot(heikinashi_open_smooth, "HA open proof")\nplot(heikinashi_close_smooth, "HA close proof")\nplot(trend ? 1 : 0, "Trend proof")\n'
    )


def smi_variant(code):
    changes = (
        ("//@version=2", "//@version=5"),
        ("input(18, minval=1)", "input.int(18, minval=1)"),
        (
            'input(false, title="Trade reverse")',
            'input.bool(false, title="Trade reverse")',
        ),
        (
            'security(syminfo.tickerid, "60", close[1])',
            'request.security(syminfo.tickerid, "60", close[1], lookahead=barmerge.lookahead_on)',
        ),
        (
            'security(syminfo.tickerid, "60", open[1])',
            'request.security(syminfo.tickerid, "60", open[1], lookahead=barmerge.lookahead_on)',
        ),
        ("nRes = nz(nRes[1], 1)", "var float nRes = na\nnRes := nz(nRes[1], 1)"),
        ("xSmaRes = sma(nRes, Length)", "xSmaRes = ta.sma(nRes, Length)"),
    )
    for old, new in changes:
        code = replace_once(code, old, new)
    code, branches = re.subn(
        r"(?m)^pos = iff\(xSmaRes > nRes, 1,\s*iff\(xSmaRes < nRes, -1, nz\(pos\[1\], 0\)\)\)\s*$",
        "var int pos = na\npos := xSmaRes > nRes ? 1 : xSmaRes < nRes ? -1 : nz(pos[1], 0)",
        code,
    )
    assert branches == 1
    code, directions = re.subn(
        r"(?m)^possig = iff\(reverse and pos == 1, -1,\s*iff\(reverse and pos == -1, 1, pos\)\)\s*$",
        "possig = reverse and pos == 1 ? -1 : reverse and pos == -1 ? 1 : pos\n",
        code,
    )
    assert directions == 1
    code, display = re.subn(r"(?m)^(?:barcolor|plot)\([^\n]+\n", "", code)
    assert display == 3
    return (
        code
        + '\nplot(nRes, "Index proof")\nplot(xSmaRes, "SMA proof")\nplot(possig, "Signal proof")\nplot(xcloseH1,"Previous close proof")\nplot(xopenH1,"Previous open proof")\n'
    )


def archive_cases(archive, ledger):
    assert sha256(archive) == FMZ_SHA256
    rows = {row["id"]: row for row in read(ledger)["disposition"] if row["id"] in SPECS}
    assert rows.keys() == SPECS.keys() and all(
        row["status"].startswith("Pending") for row in rows.values()
    )
    _, originals = archival_items(archive, rows)
    result = {}
    with ZipFile(archive) as source:
        for ident, row, document, observed in documents(source, rows):
            text, digest, interval = originals[ident]
            frame, base, start, end, _ = SPECS[ident]
            assert interval == frame and digest == observed
            values = dict(
                re.findall(
                    r"(?m)^(start|end|period|basePeriod|exchanges):\s*([^\r\n]+)",
                    document,
                )
            )
            assert values == {
                "start": f"{start} 00:00:00",
                "end": end,
                "period": frame,
                "basePeriod": base,
                "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
            }
            original, _ = strip_fmz_wrapper(text)
            transform = heikin_variant if ident == 410 else smi_variant
            result[ident] = (
                row,
                digest,
                values,
                original.encode("utf-8"),
                transform(original.replace("\r\n", "\n")).encode("utf-8"),
            )
    return result


def provider_cases(public):
    manifest, feeds = [], {}
    for ident, (_, _, first, _, last) in SPECS.items():
        begin, end = date_ms(first), date_ms(last)
        following_end = 2 * end - begin
        resolution, step = ("4h", 4 * HOUR) if ident == 410 else ("1h", HOUR)
        bounds = [
            datetime.fromtimestamp(epoch / 1000, tz=UTC).strftime("%Y-%m")
            for epoch in (begin - step, following_end - step)
        ]
        months = [
            f"{year}-{m:02}"
            for year in range(2021, 2025)
            for m in range(1, 13)
            if bounds[0] <= f"{year}-{m:02}" <= bounds[1]
        ]
        for symbol in MARKETS:
            files = verified_archives(public, symbol, resolution, months, manifest)
            candles = list(chain.from_iterable(raw_ohlcv(file, step) for file in files))
            for period, start, stop in (
                ("FMZ native window", begin, end),
                ("Next equal window", end, following_end),
            ):
                selected = [row for row in candles if start <= row[0] < stop]
                assert [row[0] for row in selected] == list(range(start, stop, step))
                chart = selected if ident == 410 else aggregate(selected, 24)
                case = {"chart": [list(row) for row in chart]}
                if ident == 4732:
                    (prior,) = [row for row in candles if row[0] == start - step]
                    case["reference"] = [list(row) for row in (prior, *selected)]
                feeds.setdefault(str(ident), {}).setdefault(period, {})[symbol] = case
    return manifest, feeds


def stage(archive, ledger, public, runtime, work):
    settings = archive_cases(archive, ledger)
    _, feeds = provider_cases(public)
    work.mkdir(parents=True, exist_ok=True)
    copy_runtime(runtime, work)
    copy2(Path(__file__).with_suffix(".mjs"), work / "run.mjs")
    for ident, (_, _, _, original, variant) in settings.items():
        (work / f"source-{ident}.pine").write_bytes(original)
        (work / f"variant-{ident}.pine").write_bytes(variant)
    write(work / "feeds.json", feeds)


def heikin_reference(payload):
    opens, closes = [], []
    for bar in payload["chart"]:
        opens.append((opens[-1] + closes[-1]) / 2 if opens else (bar[1] + bar[4]) / 2)
        closes.append(fsum(bar[1:5]) / 4)
    smoothed_open, smoothed_close = (
        exponential(exponential(values, 77), 21) for values in (opens, closes)
    )
    trend = [int(c >= o) for o, c in zip(smoothed_open, smoothed_close, strict=True)]
    return [smoothed_open, smoothed_close, trend], [
        1 if direction else -1 for direction in trend
    ]


def smi_reference(payload):
    chart, reference = payload["chart"], payload["reference"]
    assert len(reference) == 1 + 24 * len(chart)
    index_level, moving_average, directions, hour_close, hour_open = [], [], [], [], []
    direction = 0
    for index, bar in enumerate(chart):
        prior_hour = reference[index * 24]
        assert prior_hour[0] + HOUR == bar[0]
        close, open_price = prior_hour[4], prior_hour[1]
        state = (
            (index_level[-1] if index_level else 1)
            - (bar[1] - bar[4])
            + open_price
            - close
        )
        index_level.append(state)
        average = fsum(index_level[-18:]) / 18 if len(index_level) >= 18 else None
        if average is not None and average != state:
            direction = 1 if average > state else -1
        moving_average.append(average)
        directions.append(direction)
        hour_close.append(close)
        hour_open.append(open_price)
    return [index_level, moving_average, directions, hour_close, hour_open], directions


def verify_case(ident, case, payload):
    symbol = f"BINANCE:{case['market']}.P"
    request = (
        {"symbol": symbol + "_HA", "timeframe": "240", "lowerTf": False}
        if ident == 410
        else {"symbol": symbol, "timeframe": "60", "lowerTf": False}
    )
    assert case["requested"] == [request]
    reference = heikin_reference if ident == 410 else smi_reference
    witnesses, direction = reference(payload)
    for expected, actual in zip(witnesses, case["witnesses"], strict=True):
        for x, y in zip(expected, actual, strict=True):
            assert (
                x is None
                and y is None
                or x is not None
                and y is not None
                and isclose(x, y, rel_tol=1e-11, abs_tol=1e-8)
            )
    reversals = []
    open_side = 0
    for index, side in enumerate(direction[:-1]):
        if side and side != open_side:
            reversals.append((index + 1, side))
            open_side = side
    assert len(case["closed"]) == max(0, len(reversals) - 1)
    assert case["unsettled"] == int(bool(reversals))
    chart, events = payload["chart"], []
    times = [row[0] for row in chart]
    for trade, ((entry, side), (exit_bar, _)) in zip(
        case["closed"], pairwise(reversals), strict=True
    ):
        assert (entry, side, exit_bar) == (
            trade["entryBar"],
            trade["dir"],
            trade["exitBar"],
        )
        assert (
            trade["entryPrice"] == chart[entry][1]
            and trade["exitPrice"] == chart[exit_bar][1]
        )
        assert isclose(
            trade["qty"],
            floor(CASH / trade["entryPrice"] / LOT_STEP) * LOT_STEP,
            rel_tol=1e-10,
        )
        events.append(verify_trade(trade, times))
    return events


def finalize(archive, ledger, public, work, output):
    sources = archive_cases(archive, ledger)
    manifest, feeds = provider_cases(public)
    assert read(work / "feeds.json") == feeds
    assert (work / "run.exit").read_text().strip() == "0"
    assert (work / "run.mjs").read_bytes() == Path(__file__).with_suffix(
        ".mjs"
    ).read_bytes()
    isolation = read(work / "isolation-probe.json")
    assert isolation == {"privateDenied": True, "networkDenied": True}
    package = work / f"piner-{PINER_VERSION}.tgz"
    assert b64encode(sha512(package.read_bytes()).digest()).decode("ascii") == PINER_PIN
    with open_tar(package, "r:gz") as distribution:
        assert (
            distribution.extractfile("package/dist/index.js").read()
            == (work / "package/dist/index.js").read_bytes()
        )
    entries = read(work / "receipt.json")
    receipts = {item["id"]: item for item in entries}
    assert (
        len(entries) == len(receipts) == len(sources)
        and receipts.keys() == sources.keys()
    )
    rows, coverage, findings = [], [], {}
    for ident, (item, digest, settings, original, variant) in sources.items():
        source_file, variant_file = (
            work / f"source-{ident}.pine",
            work / f"variant-{ident}.pine",
        )
        assert (
            source_file.read_bytes() == original
            and variant_file.read_bytes() == variant
        )
        receipt = receipts[ident]
        assert receipt["sourceHash"] == sha256(source_file) and receipt[
            "variantHash"
        ] == sha256(variant_file)
        cases = {(case["period"], case["market"]): case for case in receipt["cases"]}
        assert len(cases) == len(receipt["cases"]) == 4
        closes = 0
        common = {
            "id": ident,
            "name": item["name"],
            "source": item["source"],
            "source_sha256": digest,
            "executed_source_sha256": receipt["variantHash"],
            "interval": settings["period"],
            "archive_interval": settings["period"],
            "quote_currency": "USDT",
            "group": GROUPS[ident],
            "market_data": "Binance USD-M historical futures candles",
            "exit": "Archived next-open market reversal",
        }
        for label, markets in feeds[str(ident)].items():
            pool, remaining = [], 0
            for symbol, data in markets.items():
                case = cases[(label, symbol)]
                cashflows = verify_case(ident, case, data)
                unresolved = case["unsettled"]
                rows.append(
                    {
                        **common,
                        "period": label,
                        "market": symbol,
                        **summarize(cashflows, unresolved, CAPITAL),
                    }
                )
                pool.extend(cashflows)
                remaining += unresolved
                closes += len(cashflows)
            rows.append(
                {
                    **common,
                    "period": label,
                    "market": "BTCUSDT + ETHUSDT",
                    **summarize(pool, remaining, 2 * CAPITAL),
                }
            )
        findings[ident] = {
            "source_archive_settings": settings,
            "original_document_sha256": digest,
            "closed": closes,
        }
        coverage.append(
            [
                ident,
                f"Tested · {GROUPS[ident]}",
                "Native context and all order events verified by both execution backends and independent arithmetic.",
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
            "references": [
                "https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-3/",
                "https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/",
            ],
            "method": "#410's authored entries were made standalone and retained their Heikin-Ashi context. Its native window includes only 4h bars closed before the published end. #4732 retains v2's first-intrabar selection, with its [1] sampling the preceding fully closed hour. Native BTC and comparative ETH cases independently reconcile every reference, pivot and resolved trade.",
            "source_audits": findings,
            "coverage": coverage,
            "results": rows,
        },
    )
    print(
        f"Verified {len(sources)} reference strategies, {len(rows)} rows and {sum(row['closed'] for row in findings.values())} closed trades."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, handler, arguments in (
        ("stage", stage, ("archive", "ledger", "public", "runtime", "work")),
        ("finalize", finalize, ("archive", "ledger", "public", "work", "output")),
    ):
        operation = commands.add_parser(name)
        for argument in arguments:
            operation.add_argument(argument, type=Path)
        operation.set_defaults(handler=handler)
    settings = vars(parser.parse_args())
    settings.pop("command")
    settings.pop("handler")(**settings)


if __name__ == "__main__":
    main()
