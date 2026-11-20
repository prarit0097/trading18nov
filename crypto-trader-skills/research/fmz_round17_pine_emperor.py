"""Verify FMZ MA Emperor defaults and the authored long-only risk mode."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from hashlib import sha512
from itertools import chain
from math import floor, isclose
from pathlib import Path
from shutil import copy2, copytree
from tarfile import open as open_tar
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round6_pine import archival_items
from research.fmz_round7_magnifier import FMZ_SHA256, date_ms, sha256, verified_archives
from research.fmz_round7_pine import (
    EXECUTION,
    FEE,
    PINER_PIN,
    PINER_VERSION,
    strip_fmz_wrapper,
    summarize,
    verify_trade,
)
from research.fmz_round11_pine_playzone import exponential
from research.fmz_round12_pine_authored import aligned, provider_bars

MARKETS = ("BTCUSDT", "ETHUSDT")
CAPITAL = 10_000
CASH = 1_000
LOT_STEP = 0.001
MINUTE = 60_000


def emperor_variant(code, ident):
    assert all(
        text in code
        for text in (
            "ssrc = close",
            "ha = false",
            'len2=input(13, title = "MA 2")',
            'len3=input(21, title = "MA 3")',
            "ma2 =  variant(type, ssrc, len2)",
            "ma3 =  variant(type, ssrc, len3)",
            "longCond = crossover(ma2, ma3)",
            "shortCond = crossunder(ma2, ma3)",
        )
    )
    variant = "LowPass" if ident == 494 else "EMA"
    assert f'type = input(defval = "{variant}"' in code
    header = 'strategy("MA Emperor insiliconot", overlay=true)'
    shared = ["//@version=5", header]
    if ident == 494:
        body = re.search(
            r"(?ms)^variant_lowPass\(src, len\)=>\n(?:    [^\n]+\n){5}", code
        )[0].rstrip()
        assert 'type=="LowPass" ? variant_lowPass(src, len)' in code
        shared.extend(
            (
                body,
                "ma2 = variant_lowPass(close, 13)",
                "ma3 = variant_lowPass(close, 21)",
            )
        )
        orders = 'if longCond\n    strategy.entry("Enter Long", strategy.long)\nelse if shortCond\n    strategy.entry("Enter Short", strategy.short)'
        assert orders in code
        names = ["longCond", "shortCond"]
    else:
        assert (
            'strat_dir_input = input(title="Strategy Direction", defval="long"' in code
        )
        assert "strategy.risk.allow_entry_in(strat_dir_value)" in code
        assert 'orderQty = input(1, "Order quantity", type = float)' in code
        shared.extend(
            (
                "strategy.risk.allow_entry_in(strategy.direction.long)",
                "ma2 = ta.ema(close, 13)",
                "ma3 = ta.ema(close, 21)",
            )
        )
        if ident == 5010:
            assert (
                "testPeriod() =>\n    time >= testPeriodStart and time <= testPeriodStop ? true : false"
                in code
            )
            specs = [
                "testStartYear = input(2020,",
                "testStartMonth = input(1,",
                "testStartDay = input(1,",
                "testStopYear = input(2030,",
                "testStopMonth = input(12,",
                "testStopDay = input(30,",
            ]
            assert all(line in code for line in specs)
            shared.append(
                "inWindow = time >= timestamp(2020,1,1,0,0) and time <= timestamp(2030,12,30,0,0)"
            )
        else:
            assert "testPeriod() => true" in code
            shared.append("inWindow = true")
        assert (
            'strategy.entry("buy", strategy.long, qty = orderQty, when = open > ma2[1])'
            in code
        )
        assert (
            'strategy.entry("sell", strategy.short, qty = orderQty, when = open < ma2[1])'
            in code
        )
        orders = 'buyOrder = longCond and inWindow and open > ma2[1]\nsellOrder = shortCond and inWindow and open < ma2[1]\nif buyOrder\n    strategy.entry("buy", strategy.long, qty=1)\nif sellOrder\n    strategy.entry("sell", strategy.short, qty=1)'
        names = ["buyOrder", "sellOrder"]
    shared.extend(
        (
            "fast = math.round(ma2, 9)",
            "slow = math.round(ma3, 9)",
            "longCond = fast > slow and fast[1] < slow[1]",
            "shortCond = fast < slow and fast[1] > slow[1]",
            orders,
            'plot(ma2,"Fast")',
            'plot(ma3,"Slow")',
            f'plot({names[0]}?1:0,"Buy")',
            f'plot({names[1]}?1:0,"Sell")',
            "",
        )
    )
    return "\n".join(shared)


def lowpass(series, n):
    alpha = 2 / (1 + n)
    values = []
    for i, p in enumerate(series):
        source_previous = series[i - 1] if i else 0
        source_older = series[i - 2] if i > 1 else 0
        filter_previous = values[i - 1] if i else 0
        filter_older = values[i - 2] if i > 1 else 0
        values.append(
            (alpha - 0.25 * alpha**2) * p
            + 0.5 * alpha**2 * source_previous
            - (alpha - 0.75 * alpha**2) * source_older
            + 2 * (1 - alpha) * filter_previous
            - (1 - alpha) ** 2 * filter_older
        )
    return values


def expected(ident, bars):
    method = lowpass if ident == 494 else exponential
    close = [r[4] for r in bars]
    fast, slow = (method(close, size) for size in (13, 21))
    buy, sell = [0], [0]
    for i, row in enumerate(bars[1:], 1):
        pem, psm, em, sm = [
            round(v, 9) for v in (fast[i - 1], slow[i - 1], fast[i], slow[i])
        ]
        buy.append(
            int(em > sm and pem < psm and (ident == 494 or round(row[1], 9) > pem))
        )
        sell.append(
            int(em < sm and pem > psm and (ident == 494 or round(row[1], 9) < pem))
        )
    return fast, slow, buy, sell


def verify(ident, case, payload):
    bars = payload["chart"]
    desired = expected(ident, bars)
    assert not case["requested"]
    for wanted, measured in zip(desired, case["witnesses"], strict=True):
        for x, y in zip(wanted, measured, strict=True):
            assert isclose(x, y, rel_tol=1e-10, abs_tol=1e-9), (x, y)
    closed = []
    side = 0
    entry = None
    for i, (buy, sell) in enumerate(
        zip(desired[-2][:-1], desired[-1][:-1], strict=True), 1
    ):
        order = buy - sell
        if not order or order == side:
            continue
        if ident == 494:
            if side:
                closed.append((entry, side, i))
            side, entry = order, i
        elif order == 1:
            side, entry = 1, i
        elif side:
            closed.append((entry, side, i))
            side, entry = 0, None
    assert len(case["closed"]) == len(closed) and case["unsettled"] == int(bool(side))
    events = []
    times = [r[0] for r in bars]
    for trade, (i, side, j) in zip(case["closed"], closed, strict=True):
        assert (trade["entryBar"], trade["dir"], trade["exitBar"]) == (i, side, j)
        assert (trade["entryPrice"], trade["exitPrice"]) == (bars[i][1], bars[j][1])
        assert bars[i][5] > 0 and bars[j][5] > 0
        qty = floor(CASH / bars[i][1] / LOT_STEP) * LOT_STEP if ident == 494 else 1
        assert isclose(trade["qty"], qty, rel_tol=1e-10)
        events.append(verify_trade(trade, times))
    return events


SPECS = {
    494: (
        "1h",
        "15m",
        60,
        "2022-04-06",
        "2022-05-05 23:59:00",
        "5m",
        ("2022-04", "2022-05", "2022-06"),
        "FMZ Pine · Native 1h · Authored LowPass reversals",
    ),
    5010: (
        "1d",
        "1h",
        1440,
        "2022-12-05",
        "2023-12-11 00:00:00",
        "1d",
        tuple(
            f"{year}-{month:02}"
            for year in range(2022, 2025)
            for month in range(1, 13)
            if "2022-12" <= f"{year}-{month:02}" <= "2024-12"
        ),
        "FMZ Pine · Native daily · Authored one-unit long-only EMA",
    ),
    5047: (
        "10m",
        "1m",
        10,
        "2023-09-07",
        "2023-09-08 09:00:00",
        "5m",
        ("2023-09",),
        "FMZ Pine · Native 10m · Authored one-unit long-only EMA",
    ),
}


def archive_sources(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    rows = {
        row["id"]: row for row in read(baseline)["disposition"] if row["id"] in SPECS
    }
    assert rows.keys() == SPECS.keys()
    assert all(
        "pending" in row["status"].lower() and row["selected_report"] is None
        for row in rows.values()
    )
    _, originals = archival_items(archive, rows)
    cases = {}
    with ZipFile(archive) as source:
        for ident, row, document, observed in documents(source, rows):
            text, digest, interval = originals[ident]
            frame, base, _, first, last, *_ = SPECS[ident]
            fields = dict(
                re.findall(
                    r"(?m)^(start|end|period|basePeriod|exchanges):\s*([^\r\n]+)",
                    document,
                )
            )
            assert digest == observed and interval == frame
            assert fields == {
                "start": f"{first} 00:00:00",
                "end": last,
                "period": frame,
                "basePeriod": base,
                "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
            }
            original, _ = strip_fmz_wrapper(text)
            normalized = original.replace("\r\n", "\n")
            active = re.sub(r"(?m)//[^\n]*", "", normalized)
            assert re.findall(r"\bstrategy\.(entry|close|exit|order)\(", active) == [
                "entry",
                "entry",
            ]
            cases[ident] = (
                row,
                digest,
                fields,
                original.encode(),
                emperor_variant(normalized, ident).encode(),
            )
    return cases


def periods(ident):
    _, _, frame, start, stop, *_ = SPECS[ident]
    begin = date_ms(start)
    end = date_ms(stop) // (frame * MINUTE) * (frame * MINUTE)
    windows = [
        ("FMZ native window", begin, end),
        ("Next equal window", end, 2 * end - begin),
    ]
    if ident == 5047:
        windows.append(
            ("September 2023 expansion", date_ms("2023-09-11"), date_ms("2023-09-18"))
        )
    return windows


def provider_cases(public):
    manifest, feeds = [], {}
    for ident, (_, _, frame, _, _, interval, months, _) in SPECS.items():
        resolution = 1440 if interval == "1d" else 5
        for market in MARKETS:
            files = verified_archives(public, market, interval, months, manifest)
            source = list(
                chain.from_iterable(
                    provider_bars(file, resolution * MINUTE) for file in files
                )
            )
            for label, begin, end in periods(ident):
                chart = aligned(source, begin, end, frame, resolution)
                assert chart[0][0] == begin and chart[-1][0] + frame * MINUTE == end
                feeds.setdefault(str(ident), {}).setdefault(label, {})[market] = {
                    "chart": chart,
                    "frame": "D" if frame == 1440 else str(frame),
                }
    return manifest, feeds


def stage(archive, baseline, public, runtime, work):
    cases = archive_sources(archive, baseline)
    _, feeds = provider_cases(public)
    work.mkdir(parents=True, exist_ok=True)
    if runtime.resolve() != work.resolve():
        for name in (
            "node.exe",
            f"piner-{PINER_VERSION}.tgz",
            "probe.cjs",
            "sandbox.ps1",
        ):
            copy2(runtime / name, work / name)
        copytree(runtime / "package", work / "package", dirs_exist_ok=True)
    copy2(Path(__file__).with_suffix(".mjs"), work / "emperor-run.mjs")
    for ident, (_, _, _, original, variant) in cases.items():
        (work / f"source-{ident}.pine").write_bytes(original)
        (work / f"variant-{ident}.pine").write_bytes(variant)
    write(work / "emperor-feeds.json", feeds)


def verified_runtime(work):
    assert (work / "emperor-run.exit").read_text().strip() == "0"
    assert (work / "emperor-run.mjs").read_bytes() == Path(__file__).with_suffix(
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
    return isolation


def finalize(archive, baseline, public, work, output):
    expected = archive_sources(archive, baseline)
    manifest, feeds = provider_cases(public)
    assert read(work / "emperor-feeds.json") == feeds
    isolation = verified_runtime(work)
    entries = read(work / "emperor-receipt.json")
    receipts = {entry["id"]: entry for entry in entries}
    assert (
        len(entries) == len(receipts) == len(expected)
        and receipts.keys() == expected.keys()
    )
    coverage, rows, details = [], [], {}
    for ident, (row, digest, metadata, original, variant) in expected.items():
        source = work / f"source-{ident}.pine"
        executed = work / f"variant-{ident}.pine"
        assert source.read_bytes() == original and executed.read_bytes() == variant
        receipt = receipts[ident]
        assert receipt["sourceHash"] == sha256(source) and receipt[
            "variantHash"
        ] == sha256(executed)
        cases = {(c["period"], c["market"]): c for c in receipt["cases"]}
        assert len(cases) == len(receipt["cases"]) == len(periods(ident)) * len(MARKETS)
        group = SPECS[ident][-1]
        common = {
            "id": ident,
            "name": row["name"],
            "source": row["source"],
            "source_sha256": digest,
            "executed_source_sha256": receipt["variantHash"],
            "interval": metadata["period"],
            "archive_interval": metadata["period"],
            "quote_currency": "USDT",
            "group": group,
            "market_data": "Binance USD-M checked historical candles",
            "exit": "Authored regular chart reversal"
            if ident == 494
            else "Authored opposite entry reduces the open long",
        }
        closed = 0
        for label, markets in feeds[str(ident)].items():
            cashflows, open_count = [], 0
            for market, payload in markets.items():
                case = cases[(label, market)]
                events = verify(ident, case, payload)
                remaining = case["unsettled"]
                rows.append(
                    {
                        **common,
                        "period": label,
                        "market": market,
                        **summarize(events, remaining, CAPITAL),
                    }
                )
                cashflows.extend(events)
                open_count += remaining
                closed += len(events)
            rows.append(
                {
                    **common,
                    "period": label,
                    "market": "BTCUSDT + ETHUSDT",
                    **summarize(cashflows, open_count, 2 * CAPITAL),
                }
            )
        assert closed > 0
        coverage.append(
            [
                ident,
                f"Tested · {group}",
                "Archived selected filter and authored order path verified from independent signals, risk direction, prices, size and fees.",
            ]
        )
        details[ident] = {
            "archive_settings": metadata,
            "source_document_sha256": digest,
            "windows_utc_ms": {
                label: [begin, end] for label, begin, end in periods(ident)
            },
            "closed": closed,
        }
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(baseline),
            "archive_sha256": FMZ_SHA256,
            "isolation_probe": isolation,
            "published_binance_candles": manifest,
            "piner_version": PINER_VERSION,
            "piner_tarball_sha512": PINER_PIN,
            "artifacts": {
                name: sha256(work / name)
                for name in (
                    "emperor-feeds.json",
                    "emperor-run.mjs",
                    "emperor-receipt.json",
                )
            },
            "cost_model": {
                "fee_per_side": FEE,
                "execution_buffer_per_side": EXECUTION,
                "lot_step": LOT_STEP,
                "lowpass_default_notional": CASH,
                "ema_order_size": 1,
            },
            "references": [
                "https://www.fmz.com/doc/9293",
                "https://www.tradingview.com/pine-script-docs/concepts/strategies/",
                "https://github.com/binance/binance-public-data",
            ],
            "method": [
                "The archived non-Heikin-Ashi close source and 13/21 lengths are preserved. Default selection disables the mixed-indentation filter branches. The LowPass source recurrence and both EMA cross paths run in the active source-equivalent program.",
                "For the two EMA scripts, the archived long-only restriction rejects flat short entries and turns an opposite entry against a long into a market close. Their fixed quantity of one base unit, open-price filters and distinct date predicates were preserved.",
                "Bitcoin matches the saved Binance USD-M instrument and ETH is a comparison. The main and equal windows use the complete bars preceding source cutoffs. The short 10m archive also has a separate preselected September week replay.",
                "The 1h and 10m charts use contiguous 5m exchange candles. Both backends and independent calculations agree on every signal, next-open order and cashflow. Closed cashflows include shared fees and an execution buffer. Margin and liquidation were outside this comparison.",
            ],
            "source_audits": details,
            "coverage": coverage,
            "results": rows,
        },
    )
    print(
        f"Verified {len(details)} strategies, {len(rows)} rows and {sum(r['closed'] for r in details.values())} closed trades."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, handler, arguments in (
        ("stage", stage, ("archive", "baseline", "public", "runtime", "work")),
        ("finalize", finalize, ("archive", "baseline", "public", "work", "output")),
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
