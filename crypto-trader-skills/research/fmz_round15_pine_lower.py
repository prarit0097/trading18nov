"""Replay archived Pine daily orders from confirmed Binance and Bitfinex intrabars."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from bisect import bisect_right
from collections import defaultdict
from hashlib import sha512
from itertools import chain, pairwise
from math import floor, fsum, isclose, isfinite
from pathlib import Path
from shutil import copy2, copytree
from tarfile import open as open_tar
from urllib.parse import urlencode
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

BINANCE = 965
BITFINEX = 5474
CAPITAL = 10000
DAY = 86_400_000
HALF_HOUR = 1_800_000
MARKETS = ("BTCUSDT", "ETHUSDT")
GROUPS = {
    BINANCE: "FMZ Pine · Native daily · Confirmed 30m DEMA",
    BITFINEX: "FMZ Pine · Native daily · Confirmed Bitfinex hourly EMA",
}


def lower_variant(code):
    assert all(f"ema{n}=ta.ema(close, {n})" in code for n in (5, 2))
    observations = []
    for label, n in (("Fast", 5), ("Slow", 2)):
        series = rf'(?m)^dema{label}\s*=\s*request\.security\(syminfo.tickerid,\s*"30",\s*2 \* ema{n} - ta\.ema\(ema{n}, {n}\)\s*\)\s*$'
        assert re.search(series, code)
        observations.append(
            f'dema{label} = request.security(syminfo.tickerid, "30", 2 * ta.ema(close, {n}) - ta.ema(ta.ema(close, {n}), {n}), gaps=barmerge.gaps_off, lookahead=barmerge.lookahead_off)'
        )
    assert (
        "ta.crossover(demaSlow, demaFast)" in code
        and "ta.crossunder(demaSlow, demaFast)" in code
    )
    body = re.search(
        r'(?m)^strategy.entry\("BUY", strategy.long, 1, when = buy\)\nstrategy.entry\("SELL", strategy.short, 1, when = sell \)',
        code,
    )[0]
    return "\n".join(
        (
            "//@version=5",
            'strategy(title = "SuperTrend", shorttitle = "BTC")',
            *observations,
            "slow=math.round(demaSlow,9)",
            "fast=math.round(demaFast,9)",
            "buy = slow > fast and slow[1] < fast[1]",
            "sell = slow < fast and slow[1] > fast[1]",
            body,
            'plot(demaFast,"FAST")',
            'plot(demaSlow,"SLOW")',
            'plot(buy?1:sell?-1:0,"Direction")',
            "",
        )
    )


def expected_lower(payload):
    source = [bar[4] for bar in payload["reference"]]
    chart = payload["chart"]
    for i, bar in enumerate(chart):
        assert (
            payload["reference"][(i + 1) * 48 - 1][0] + 1_800_000 == bar[0] + 86_400_000
        )

    def dema(n):
        first = exponential(source, n)
        second = exponential(first, n)
        return [(2 * a - b) for a, b in zip(first, second, strict=True)][47::48]

    fast, slow = dema(5), dema(2)
    decision = [0]
    for (a, b), (c, d) in pairwise(zip(slow, fast, strict=True)):
        a, b, c, d = [round(value, 9) for value in (a, b, c, d)]
        decision.append(1 if c > d and a < b else -1 if c < d and a > b else 0)
    return fast, slow, decision


def verify_lower(case, payload):
    assert case["requested"] == [
        {"symbol": f"BINANCE:{case['market']}.P", "timeframe": "30", "lowerTf": False}
    ]
    expected = expected_lower(payload)
    for w, series in enumerate(zip(expected, case["witnesses"], strict=True)):
        for i, (x, y) in enumerate(zip(*series, strict=True)):
            assert (
                x is not None
                and y is not None
                and isclose(x, y, rel_tol=1e-11, abs_tol=1e-8)
            ), (w, i, x, y)
    entries = []
    pos = 0
    for idx, side in enumerate(expected[-1][:-1], 1):
        if side and side != pos:
            entries.append((idx, side))
            pos = side
    assert len(case["closed"]) == max(0, len(entries) - 1)
    assert case["unsettled"] == int(bool(entries))
    chart = payload["chart"]
    assert all(chart[i][5] > 0 for i, _ in entries)
    times = [row[0] for row in chart]
    events = []
    for trade, ((i, side), (j, _)) in zip(
        case["closed"], pairwise(entries), strict=True
    ):
        assert (trade["entryBar"], trade["dir"], trade["exitBar"]) == (i, side, j)
        assert (trade["entryPrice"], trade["exitPrice"], trade["qty"]) == (
            chart[i][1],
            chart[j][1],
            1,
        )
        events.append(verify_trade(trade, times))
    return events


def bitfinex_variant(code):
    assert 'strategy("multiple timeframe trading")' in code
    assert "expr = ta.ema(close, 5)" in code
    assert "hVal = request.security(syminfo.tickerid, '60', expr)" in code
    orders = (
        "if hVal > expr\n"
        '    strategy.entry("long", strategy.long)\n'
        "else\n"
        '    strategy.entry("short", strategy.short)'
    )
    assert orders in code
    return (
        "//@version=5\n"
        'strategy("multiple timeframe trading")\n'
        "expr = ta.ema(close, 5)\n"
        'hVal = request.security(syminfo.tickerid, "60", ta.ema(close, 5), '
        "gaps=barmerge.gaps_off, lookahead=barmerge.lookahead_off)\n"
        f"{orders}\n"
        'plot(expr,"Daily")\n'
        'plot(hVal,"Hourly")\n'
        'plot(hVal>expr?1:-1,"Direction")\n'
    )


def reorder(row):
    time, opened, close, high, low, vol = row
    return [time, opened, high, low, close, vol]


def bitfinex_expected(payload):
    bars = payload["chart"]
    refs = payload["reference"]
    local = exponential([bar[4] for bar in bars], 5)
    source = exponential([bar[4] for bar in refs], 5)
    closes = [bar[0] + 3_600_000 for bar in refs]
    selected = [bisect_right(closes, bar[0] + 86_400_000) - 1 for bar in bars]
    assert all(i >= 0 for i in selected)
    hour = [source[i] for i in selected]
    direction = [
        1 if round(a, 9) > round(b, 9) else -1 for a, b in zip(hour, local, strict=True)
    ]
    return local, hour, direction


def verify_bitfinex(case, payload):
    assert case["requested"] == [
        {"symbol": f"BITFINEX:{case['market']}", "timeframe": "60", "lowerTf": False}
    ]
    expected = bitfinex_expected(payload)
    for wanted, actual in zip(expected, case["witnesses"], strict=True):
        for x, y in zip(wanted, actual, strict=True):
            assert isclose(x, y, rel_tol=1e-11, abs_tol=1e-8)
    entries = []
    open_side = 0
    for index, side in enumerate(expected[-1][:-1], 1):
        if open_side != side:
            entries.append((index, side))
            open_side = side
    assert len(case["closed"]) == len(entries) - 1
    assert case["unsettled"] == 1
    bars = payload["chart"]
    times = [row[0] for row in bars]
    assert all(bars[i][5] > 0 for i, _ in entries)
    events = []
    for trade, ((i, side), (j, _)) in zip(
        case["closed"], pairwise(entries), strict=True
    ):
        assert (trade["entryBar"], trade["dir"], trade["exitBar"]) == (i, side, j)
        assert (trade["entryPrice"], trade["exitPrice"]) == (bars[i][1], bars[j][1])
        assert isclose(
            trade["qty"], floor(1000 / bars[i][1] / 0.001) * 0.001, rel_tol=1e-10
        )
        events.append(verify_trade(trade, times))
    return events


START = "2023-01-01"
END = "2023-09-18"
WINDOWS = (
    ("FMZ native window", date_ms(START), date_ms(END)),
    ("Next equal window", date_ms(END), 2 * date_ms(END) - date_ms(START)),
)
MONTHS = tuple(
    f"{year}-{month:02}"
    for year in (2023, 2024)
    for month in range(1, 13)
    if f"{year}-{month:02}" <= "2024-06"
)


BITFINEX_START = "2021-05-04"
BITFINEX_END = "2022-05-03"
BITFINEX_CUTOFF = "2023-05-03"
BITFINEX_WINDOWS = (
    ("FMZ native window", date_ms(BITFINEX_START), date_ms(BITFINEX_END)),
    (
        "Next equal window",
        date_ms(BITFINEX_END),
        2 * date_ms(BITFINEX_END) - date_ms(BITFINEX_START),
    ),
)
ETH_VOLUME_DIFFERENCES = {1625011200000, 1665532800000}


def archived_sources(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    rows = {
        row["id"]: row for row in read(baseline)["disposition"] if row["id"] in GROUPS
    }
    assert rows.keys() == GROUPS.keys()
    assert all(
        "pending" in row["status"].lower() and row["selected_report"] is None
        for row in rows.values()
    )
    _, originals = archival_items(archive, rows)
    sources = {}
    with ZipFile(archive) as source:
        for ident, row, document, observed in documents(source, rows):
            text, digest, period = originals[ident]
            assert observed == digest and period == "1d"
            fields = dict(
                re.findall(
                    r"(?m)^(start|end|period|basePeriod|exchanges):\s*([^\r\n]+)",
                    document,
                )
            )
            start, end, exchange = (
                (
                    f"{START} 00:00:00",
                    f"{END} 00:00:00",
                    '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
                )
                if ident == BINANCE
                else (
                    f"{BITFINEX_START} 00:00:00",
                    "2022-05-03 23:59:00",
                    '[{"eid":"Bitfinex","currency":"BTC_USD"}]',
                )
            )
            assert fields == {
                "start": start,
                "end": end,
                "period": "1d",
                "basePeriod": "1h",
                "exchanges": exchange,
            }
            original, _ = strip_fmz_wrapper(text)
            normalized = original.replace("\r\n", "\n")
            active = re.sub(r"(?m)//[^\n]*", "", normalized)
            assert re.findall(r"\bstrategy\.(entry|close|exit|order)\(", active) == [
                "entry",
                "entry",
            ]
            convert = lower_variant if ident == BINANCE else bitfinex_variant
            sources[ident] = (
                row,
                digest,
                fields,
                original.encode(),
                convert(normalized).encode(),
            )
    return sources


def binance_cases(public):
    feeds, manifest = {}, []
    for market in MARKETS:
        streams = {}
        for interval, width in (("30m", HALF_HOUR), ("1d", DAY)):
            files = verified_archives(public, market, interval, MONTHS, manifest)
            streams[interval] = list(
                chain.from_iterable(provider_bars(file, width) for file in files)
            )
        for label, start, stop in WINDOWS:
            daily = aligned(streams["1d"], start, stop, 1440, 1440)
            intraday = aligned(streams["30m"], start, stop, 30, 30)
            assert [r[:5] for r in daily] == [
                r[:5] for r in aligned(intraday, start, stop, 1440, 30)
            ]
            assert daily[0][0] == start and daily[-1][0] + DAY == stop
            feeds.setdefault(str(BINANCE), {}).setdefault(label, {})[market] = {
                "chart": daily,
                "reference": intraday,
                "frame": "D",
            }
    return manifest, feeds


def bitfinex_url(interval, market, start, stop):
    query = urlencode({"start": start, "end": stop - 1, "sort": 1, "limit": 10000})
    return f"https://api-pub.bitfinex.com/v2/candles/trade:{interval}:t{market}/hist?{query}"


def bitfinex_stream(public, market, interval, width, partition, first, last, manifest):
    candles = []
    for index, start in enumerate(range(first, last, partition * DAY)):
        stop = min(last, start + partition * DAY)
        raw = public / f"t{market}-{interval}-{index:02}.json"
        data = [reorder(row) for row in read(raw)]
        assert all(start <= row[0] < stop for row in data)
        candles.extend(data)
        manifest.append(
            {"url": bitfinex_url(interval, market, start, stop), "sha256": sha256(raw)}
        )
    assert all(a[0] < b[0] for a, b in pairwise(candles))
    for timestamp, opened, high, low, close, volume in candles:
        assert (
            timestamp % width == 0
            and 0 < low <= min(opened, close) <= max(opened, close) <= high
        )
        assert isfinite(volume) and volume > 0
    return candles


def bitfinex_reconcile(public, market, daily, hourly, manifest):
    grouped = defaultdict(list)
    for row in hourly:
        grouped[row[0] // DAY * DAY].append(row)
    differences = {}
    for timestamp, opened, high, low, close, volume in daily:
        batch = grouped[timestamp]
        assert (opened, high, low, close) == (
            batch[0][1],
            max(row[2] for row in batch),
            min(row[3] for row in batch),
            batch[-1][4],
        )
        observed_volume = fsum(row[-1] for row in batch)
        if not isclose(observed_volume, volume, rel_tol=1e-9, abs_tol=1e-7):
            differences[timestamp] = {"daily": volume, "hourly_sum": observed_volume}
    expected = ETH_VOLUME_DIFFERENCES if market == "ETHUSD" else set()
    assert differences.keys() == expected
    first, last = daily[0][0], daily[-1][0] + DAY
    missing = set(range(first, last, 3_600_000)) - {row[0] for row in hourly}
    assert len(missing) == (18 if market == "ETHUSD" else 11)
    for day in sorted(differences):
        for interval in ("15m", "5m"):
            raw = public / f"t{market}-{interval}-{day}.json"
            observations = [reorder(row) for row in read(raw)]
            assert observations and all(
                day <= row[0] < day + DAY
                and row[0] // 3_600_000 * 3_600_000 not in missing
                for row in observations
            )
            manifest.append(
                {
                    "url": bitfinex_url(interval, market, day, day + DAY),
                    "sha256": sha256(raw),
                    "base_volume_sum": fsum(row[-1] for row in observations),
                }
            )
    return {
        "absent_hourly_slots_utc_ms": sorted(missing),
        "daily_volume_differences": differences,
    }


def bitfinex_inputs(public):
    first, last = date_ms(BITFINEX_START), date_ms(BITFINEX_CUTOFF)
    manifest, feeds, diagnostics = [], {}, {}
    for market in ("BTCUSD", "ETHUSD"):
        daily = bitfinex_stream(public, market, "1D", DAY, 730, first, last, manifest)
        hourly = bitfinex_stream(
            public, market, "1h", 3_600_000, 180, first, last, manifest
        )
        assert [row[0] for row in daily] == list(range(first, last, DAY))
        diagnostics[market] = bitfinex_reconcile(
            public, market, daily, hourly, manifest
        )
        for label, start, stop in BITFINEX_WINDOWS:
            chart = [row for row in daily if start <= row[0] < stop]
            refs = [row for row in hourly if start <= row[0] < stop]
            assert chart[0][0] == start and chart[-1][0] + DAY == stop
            feeds.setdefault(str(BITFINEX), {}).setdefault(label, {})[market] = {
                "chart": chart,
                "reference": refs,
                "frame": "D",
            }
    return manifest, feeds, diagnostics


def provider_cases(public):
    binance_files, futures = binance_cases(public)
    bitfinex_responses, spot, reconciliation = bitfinex_inputs(public)
    return binance_files, bitfinex_responses, futures | spot, reconciliation


def stage(archive, baseline, public, runtime, work):
    sources = archived_sources(archive, baseline)
    _, _, feeds, _ = provider_cases(public)
    work.mkdir(parents=True, exist_ok=True)
    if runtime.resolve() != work.resolve():
        for file in (
            "node.exe",
            f"piner-{PINER_VERSION}.tgz",
            "probe.cjs",
            "sandbox.ps1",
        ):
            copy2(runtime / file, work / file)
        copytree(runtime / "package", work / "package", dirs_exist_ok=True)
    copy2(Path(__file__).with_suffix(".mjs"), work / "lower-run.mjs")
    for ident, (_, _, _, original, variant) in sources.items():
        (work / f"source-{ident}.pine").write_bytes(original)
        (work / f"variant-{ident}.pine").write_bytes(variant)
    write(work / "lower-feeds.json", feeds)


def verify_runtime(work):
    assert (work / "lower-run.exit").read_text().strip() == "0"
    assert (work / "lower-run.mjs").read_bytes() == Path(__file__).with_suffix(
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


def case_results(ident, source, feeds, receipt, work):
    row, source_digest, metadata, original, variant = source
    assert receipt["id"] == ident and len(receipt["cases"]) == 4
    source_path, variant_path = (
        work / f"source-{ident}.pine",
        work / f"variant-{ident}.pine",
    )
    assert source_path.read_bytes() == original and variant_path.read_bytes() == variant
    assert receipt["sourceHash"] == sha256(source_path) and receipt[
        "variantHash"
    ] == sha256(variant_path)
    by_case = {(entry["period"], entry["market"]): entry for entry in receipt["cases"]}
    assert len(by_case) == 4
    common = {
        "id": ident,
        "name": row["name"],
        "source": row["source"],
        "source_sha256": source_digest,
        "executed_source_sha256": receipt["variantHash"],
        "interval": metadata["period"],
        "archive_interval": metadata["period"],
        "quote_currency": "USDT" if ident == BINANCE else "USD",
        "group": GROUPS[ident],
        "market_data": (
            "Binance USD-M historical daily and 30m candles"
            if ident == BINANCE
            else "Bitfinex spot historical daily and hourly candles"
        ),
        "exit": "Authored next-daily-open market reversal",
    }
    rows = []
    closed = 0
    verify = verify_lower if ident == BINANCE else verify_bitfinex
    for label, markets in feeds.items():
        pool, open_count = [], 0
        for market, payload in markets.items():
            case = by_case[(label, market)]
            events = verify(case, payload)
            unsettled = case["unsettled"]
            rows.append(
                {
                    **common,
                    "period": label,
                    "market": market,
                    **summarize(events, unsettled, CAPITAL),
                }
            )
            closed += len(events)
            pool.extend(events)
            open_count += unsettled
        rows.append(
            {
                **common,
                "period": label,
                "market": " + ".join(markets),
                **summarize(pool, open_count, 2 * CAPITAL),
            }
        )
    assert closed > 0
    return rows, {
        "archive_settings": metadata,
        "source_document_sha256": source_digest,
        "closed": closed,
    }


def finalize(archive, baseline, public, work, output):
    sources = archived_sources(archive, baseline)
    binance, bitfinex, feeds, checks = provider_cases(public)
    assert read(work / "lower-feeds.json") == feeds
    isolation = verify_runtime(work)
    entries = read(work / "lower-receipt.json")
    receipts = {entry["id"]: entry for entry in entries}
    assert (
        len(entries) == len(receipts) == len(sources)
        and receipts.keys() == sources.keys()
    )
    rows, coverage, audits = [], [], {}
    for ident, source in sources.items():
        case_rows, audit = case_results(
            ident, source, feeds[str(ident)], receipts[ident], work
        )
        rows.extend(case_rows)
        audits[ident] = audit
        coverage.append(
            [
                ident,
                f"Tested · {GROUPS[ident]}",
                "Pinned daily chart and completed intrabars verified with matched source prices, independent indicator arithmetic, and fill and cost calculations.",
            ]
        )
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(baseline),
            "archive_sha256": FMZ_SHA256,
            "isolation_probe": isolation,
            "published_binance_candles": binance,
            "published_bitfinex_responses": bitfinex,
            "bitfinex_input_reconciliation": checks,
            "piner_version": PINER_VERSION,
            "piner_tarball_sha512": PINER_PIN,
            "artifacts": {
                name: sha256(work / name)
                for name in ("lower-feeds.json", "lower-run.mjs", "lower-receipt.json")
            },
            "cost_model": {
                "fee_per_side": FEE,
                "execution_buffer_per_side": EXECUTION,
                "binance_base_units_per_order": 1,
                "bitfinex_notional_per_entry_usd": 1000,
            },
            "references": [
                "https://www.fmz.com/doc/9293",
                "https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/",
                "https://github.com/binance/binance-public-data",
                "https://docs.bitfinex.com/reference/rest-public-candles",
            ],
            "method": [
                "The native daily Pine logic selects the final completed 30m intrabar using lookahead off. DEMA 5 and 2 are evaluated inside the same market's 30m series.",
                "Complete native Binance 30m OHLC reconstructs the independent daily candles and supplies the original lower reference interval below the FMZ base period. Both backends and independent computations agree on the one-unit reversals and cashflows.",
                "The Bitfinex daily source compares EMA5 of native daily close against EMA5 on the last completed published native hour. All daily OHLC independently reconcile with hourly candles. BTC and ETH have 11 and 18 absent hourly slots respectively, which are preserved without filling or repeating observations.",
                "Two Bitfinex ETH daily volume totals differ from the hourly sums. Published 5m and 15m checks supply no candles in those absent hour slots. Archived EMA signals consume only close prices. Source window boundaries, indicator values, reversals and positive-volume exchange open fills are independently checked.",
                "Bitcoin matches each saved instrument and ETH is the same-venue comparison. Bitfinex USD and Binance USDT amounts are reported separately. The 10,000 quote-unit comparison capital does not model margin, liquidation, financing or borrow availability. Drawdown uses closed trade cashflows.",
            ],
            "source_audits": audits,
            "coverage": coverage,
            "results": rows,
        },
    )
    print(
        f"Verified {len(rows)} rows and {sum(a['closed'] for a in audits.values())} closed trades."
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
