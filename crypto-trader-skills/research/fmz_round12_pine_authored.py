"""Validate archived Pine entries recovered from indicator-labelled FMZ sources."""

from __future__ import annotations

import argparse
import csv
import io
import re
from base64 import b64encode
from bisect import bisect_right
from datetime import UTC, datetime
from hashlib import sha512
from itertools import chain, pairwise
from math import floor, fsum, isclose
from pathlib import Path
from shutil import copy2, copytree
from tarfile import open as open_tar
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round6_pine import archival_items
from research.fmz_round7_magnifier import (
    FMZ_SHA256,
    aggregate,
    date_ms,
    sha256,
    verified_archives,
)
from research.fmz_round7_pine import (
    EXECUTION,
    FEE,
    PINER_PIN,
    PINER_VERSION,
    strip_fmz_wrapper,
    summarize,
    verify_trade,
)

CAPITAL, CASH = 10_000, 1_000
LOT_STEP = 0.001
MINUTE = 60_000
MARKETS = ("BTCUSDT", "ETHUSDT")
REFERENCE_FRAMES = (15, 30, 60, 120, 240)
SPECS = {
    183: ("12h", "15m", "2022-04-15", "2022-05-14 23:59:00"),
    240: ("2h", "15m", "2022-02-06", "2022-05-06 00:00:00"),
    634: ("1h", "15m", "2022-04-15", "2022-05-14 23:59:00"),
    721: ("15m", "5m", "2022-05-08", "2022-05-14 23:59:00"),
    1105: ("10m", "1m", "2022-04-22", "2022-05-21 23:59:00"),
}
TESTS = {
    183: (720, "15m", "FMZ Pine · Native 12h · Authored CCI reversal"),
    721: (15, "15m", "FMZ Pine · Native 15m · Authored RSI reversal"),
    1105: (10, "5m", "FMZ Pine · Native 10m · Authored candlestick and RSI reversal"),
}
PENDING = {
    240: (
        "Saved invalid Pine timeframe",
        (
            "The order signal actively depends on request.security with the saved resolution '18000'. "
            "That is a quoted default on input.int and exceeds Pine's valid 1–1440 minute range. "
            "The archived Bitfinex BTC/USD 2h chart does not establish a valid replacement resolution."
        ),
        (
            "res = input.int(title='Resolution', defval='18000')",
            "src = request.security(syminfo.tickerid, res, inp[0])[1]",
        ),
    ),
    634: (
        "Saved future-leaking higher timeframe and unpinned clock",
        (
            "The 1h chart defaults to a 3h reference with lookahead_on and delayOffset=0. "
            "Early historical 1h bars receive the completed 3h close before it existed. "
            "The active order gate also depends on a runtime clock that the archive does not record. "
            "The source exposes optional delayOffset and ebar inputs, but the archive saves the original defaults."
        ),
        (
            "useRes = input(defval=true",
            "intRes = input(defval=3",
            "delayOffset = input.int(defval=0",
            "lookahead=barmerge.lookahead_on",
            "closeSeries = variant(basisType, close[delayOffset]",
            "(timenow - time)",
            "ebar = input.int(defval=10000",
            "if ((ebar==0 or tdays<=ebar)",
        ),
    ),
}


def mtf_variant(code, stem, value, length, lower, upper):
    sig = rf"(?m)^{stem}Src\s*= input\s*\(.*defval={value},"
    assert re.search(sig, code)
    for field, expected in (
        ("Length", length),
        ("Oversold", lower),
        ("Overbought", upper),
    ):
        assert re.search(
            rf"(?m)^{stem}{field}\s*= input\.int\(.*defval={expected},", code
        )
    code, declarations = re.subn(r'(?m)^indicator\(("[^"]+")\)$', r"strategy(\1)", code)
    assert declarations == 1
    helper = (
        "Fsec(Sym, Tf, Exp) =>\n"
        "    request.security(Sym, Tf, Exp[barstate.isrealtime ? 1 : 0], "
        "barmerge.gaps_off, barmerge.lookahead_off) [barstate.isrealtime ? 0 : 1]"
    )
    assert code.count(helper) == 1
    code = code.replace(helper, "")
    for index, minutes in enumerate(REFERENCE_FRAMES, 1):
        tf = f"{stem}Tf{index}"
        assert re.search(rf'(?m)^{tf}\s*= input.timeframe\(.*defval="{minutes}"', code)
        assert re.search(rf"(?m)^{tf}_E\s*= input.bool\(.*defval=true", code)
        original = f"Fsec(syminfo.tickerid, {tf}, ta.{stem}({stem}Src, {stem}Length))"
        replacement = (
            f"request.security(syminfo.tickerid, {tf}, ta.{stem}({value}, {stem}Length), "
            "barmerge.gaps_off, barmerge.lookahead_off)[1]"
        )
        assert code.count(original) == 1
        code = code.replace(original, replacement)
    code = re.sub(r"(?m)^(?:plot|hline|bgcolor|alertcondition)\s*\([^\n]+\n", "", code)
    witnesses = [f'plot({stem}{i}, "Reference {i}")' for i in range(1, 6)]
    witnesses.append(f'plot({stem}Ob ? 1 : {stem}Os ? -1 : 0, "Direction proof")')
    return code + "\n" + "\n".join(witnesses) + "\n"


def local_rsi_variant(code):
    names = (
        "rsi_source",
        "rsi_upper",
        "rsi_buffer",
        "rsi_additional_upper",
        "r7",
        "c1o1",
        "c1o",
        "oc",
        "c1c",
    )
    assignments = []
    for name in names:
        (assignment,) = re.findall(rf"(?m)^{name}\s*=[^\n]+$", code)
        assignments.append(assignment)
    assert all(
        value in line
        for value, line in zip(
            ("defval=open", "defval=75", "defval=5"), assignments[:3], strict=True
        )
    )
    assert assignments[3:] == [
        "rsi_additional_upper = rsi_upper + rsi_buffer",
        "r7=ta.rsi(rsi_source,7)",
        "c1o1 = close[1]>=open[1] ",
        "c1o = close[1]>=open ",
        "oc = open>=close ",
        "c1c = close[1]>=close ",
    ]
    entries = (
        "if c1o1 and c1o and oc and c1c and r7>=rsi_additional_upper\n"
        '    strategy.entry("Enter Long", strategy.long)\n'
        "else if c1o1 and c1o and oc and c1c and r7>=rsi_upper\n"
        '    strategy.entry("Enter Short", strategy.short)'
    )
    assert code.count(entries) == 1
    header = re.match(
        r'(?m)^indicator\(("ogcheckers_1hr_scalp_ema_sma_rsi"),"[^"]+",overlay=true,timeframe="",timeframe_gaps=true\)$',
        next(line for line in code.splitlines() if line.startswith("indicator(")),
    )
    assert header
    proof = (
        "plot(c1o1 and c1o and oc and c1c ? "
        '(r7 >= rsi_additional_upper ? 1 : r7 >= rsi_upper ? -1 : 0) : 0, "Direction proof")'
    )
    return "\n".join(
        (
            "//@version=5",
            f"strategy({header[1]}, overlay=true)",
            *assignments,
            entries,
            'plot(r7, "RSI proof")',
            proof,
            "",
        )
    )


def archive_cases(archive, ledger):
    assert sha256(archive) == FMZ_SHA256
    pending = {
        row["id"]: row for row in read(ledger)["disposition"] if row["id"] in SPECS
    }
    assert pending.keys() == SPECS.keys()
    assert all(row["status"].startswith("Pending") for row in pending.values())
    _, code = archival_items(archive, pending)
    variants = {}
    with ZipFile(archive) as source:
        for ident, row, document, observed in documents(source, pending):
            text, digest, interval = code[ident]
            frame, base, start, end = SPECS[ident]
            assert interval == frame and digest == observed
            fields = dict(
                re.findall(
                    r"(?m)^(start|end|period|basePeriod|exchanges):\s*([^\r\n]+)",
                    document,
                )
            )
            venue = (
                '[{"eid":"Bitfinex","currency":"BTC_USD"}]'
                if ident == 240
                else '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]'
            )
            assert fields == {
                "start": f"{start} 00:00:00",
                "end": end,
                "period": frame,
                "basePeriod": base,
                "exchanges": venue,
            }
            original, _ = strip_fmz_wrapper(text)
            normalized = original.replace("\r\n", "\n")
            active = re.sub(r"(?m)//[^\n]*", "", normalized)
            assert re.findall(r"\bstrategy\.(\w+)", active) == [
                "entry",
                "long",
                "entry",
                "short",
            ]
            match ident:
                case 183:
                    variant = mtf_variant(normalized, "cci", "hlc3", 20, -100, 100)
                case 721:
                    variant = mtf_variant(normalized, "rsi", "close", 14, 35, 65)
                case 1105:
                    variant = local_rsi_variant(normalized)
                case _:
                    assert all(fragment in active for fragment in PENDING[ident][2])
                    variant = ""
            variants[ident] = row, digest, fields, original.encode(), variant.encode()
    return variants


def provider_bars(path, step):
    with ZipFile(path) as archive:
        (entry,) = archive.namelist()
        with archive.open(entry) as stream:
            for row in csv.reader(io.TextIOWrapper(stream, encoding="ascii")):
                if not row[0].isdigit():
                    continue
                time = int(row[0])
                o, h, low, c, volume = map(float, row[1:6])
                assert (
                    int(row[6]) == time + step - 1
                    and 0 < low <= min(o, c) <= max(o, c) <= h
                )
                assert volume >= 0
                if volume == 0:
                    assert (
                        o == h == low == c and float(row[7]) == 0 and int(row[8]) == 0
                    )
                yield time, o, h, low, c, volume


def aligned(source, start, stop, frame, resolution):
    width = frame * MINUTE
    first = (start + width - 1) // width * width
    end = stop // width * width
    rows = [row for row in source if first <= row[0] < end]
    assert [row[0] for row in rows] == list(range(first, end, resolution * MINUTE))
    return [list(row) for row in aggregate(rows, frame // resolution)]


def provider_cases(public):
    manifest, inputs, intervals = [], {}, {}
    for ident, (frame, interval, _) in TESTS.items():
        _, _, start_day, cutoff = SPECS[ident]
        start = date_ms(start_day)
        end = date_ms(cutoff) // (frame * MINUTE) * (frame * MINUTE)
        windows = [
            ("FMZ native complete bars", start, end),
            ("Next equal window", end, 2 * end - start),
        ]
        if ident == 721:
            windows.append(
                ("June 2022 expansion", date_ms("2022-06-01"), date_ms("2022-07-01"))
            )
        resolution = int(interval.removesuffix("m"))
        for market in MARKETS:
            files = verified_archives(
                public, market, interval, ("2022-04", "2022-05", "2022-06"), manifest
            )
            source = list(
                chain.from_iterable(
                    provider_bars(file, resolution * MINUTE) for file in files
                )
            )
            for label, begin, stop in windows:
                chart = aligned(source, begin, stop, frame, resolution)
                assert chart[0][0] == begin and chart[-1][0] + frame * MINUTE == stop
                references = (
                    {}
                    if ident == 1105
                    else {
                        str(ref): aligned(source, begin, stop, ref, resolution)
                        for ref in REFERENCE_FRAMES
                    }
                )
                inputs.setdefault(str(ident), {}).setdefault(label, {})[market] = {
                    "chart": chart,
                    "references": references,
                    "frame": str(frame),
                }
            intervals[ident] = {
                label: [
                    datetime.fromtimestamp(time / 1000, UTC).isoformat()
                    for time in (begin, stop)
                ]
                for label, begin, stop in windows
            }
    unique = {entry["url"]: entry for entry in manifest}
    return list(unique.values()), inputs, intervals


def stage(archive, ledger, public, runtime, work):
    sources = archive_cases(archive, ledger)
    _, feeds, _ = provider_cases(public)
    work.mkdir(parents=True, exist_ok=True)
    for file in ("node.exe", f"piner-{PINER_VERSION}.tgz", "probe.cjs", "sandbox.ps1"):
        copy2(runtime / file, work / file)
    copytree(runtime / "package", work / "package", dirs_exist_ok=True)
    copy2(Path(__file__).with_suffix(".mjs"), work / "run.mjs")
    for ident in TESTS:
        _, _, _, original, variant = sources[ident]
        (work / f"source-{ident}.pine").write_bytes(original)
        (work / f"variant-{ident}.pine").write_bytes(variant)
    write(work / "feeds.json", feeds)


def cci(values, size):
    result = [None] * (size - 1)
    for stop in range(size, len(values) + 1):
        recent = values[stop - size : stop]
        center = fsum(recent) / size
        deviation = fsum(abs(value - center) for value in recent) / size
        result.append(
            (values[stop - 1] - center) / (0.015 * deviation) if deviation else None
        )
    return result


def rsi(values, size):
    def current(gain, loss):
        return 100 - 100 / (1 + gain / loss) if loss else 100

    changes = [after - before for before, after in pairwise(values)]
    gain = fsum(max(value, 0) for value in changes[:size]) / size
    loss = fsum(max(-value, 0) for value in changes[:size]) / size
    result = [None] * size + [current(gain, loss)]
    for change in changes[size:]:
        gain = (gain * (size - 1) + max(change, 0)) / size
        loss = (loss * (size - 1) + max(-change, 0)) / size
        result.append(current(gain, loss))
    return result


def local_rsi_reference(chart):
    values = rsi([row[1] for row in chart], 7)
    directions = [0]
    for prior, row, value in zip(chart[:-1], chart[1:], values[1:], strict=True):
        conditions = (
            prior[4] >= prior[1]
            and prior[4] >= row[1]
            and row[1] >= row[4]
            and prior[4] >= row[4]
        )
        if value is None or not conditions:
            directions.append(0)
        else:
            directions.append(1 if value >= 80 else -1 if value >= 75 else 0)
    return [values, directions]


def reference(ident, payload):
    chart = payload["chart"]
    if ident == 1105:
        return local_rsi_reference(chart)
    lower, upper = (-100, 100) if ident == 183 else (35, 65)
    observed = []
    for timeframe, source in payload["references"].items():
        closes = [row[0] + int(timeframe) * MINUTE for row in source]
        if ident == 183:
            values = cci([fsum(row[2:5]) / 3 for row in source], 20)
        else:
            values = rsi([row[4] for row in source], 14)
        # The prior chart close equals this chart open under contiguous timestamps.
        indices = [bisect_right(closes, row[0]) - 1 for row in chart]
        observed.append([values[index] if index >= 0 else None for index in indices])
    directions = []
    for values in zip(*observed, strict=True):
        if any(value is None for value in values):
            directions.append(0)
        else:
            directions.append(
                1 if min(values) >= upper else -1 if max(values) <= lower else 0
            )
    return [*observed, directions]


def verify_case(ident, case, payload):
    symbol = f"BINANCE:{case['market']}.P"
    assert case["requested"] == [
        {"symbol": symbol, "timeframe": timeframe, "lowerTf": False}
        for timeframe in payload["references"]
    ]
    expected = reference(ident, payload)
    for witness, actual in zip(expected, case["witnesses"], strict=True):
        for x, y in zip(witness, actual, strict=True):
            assert (
                x is None
                and y is None
                or x is not None
                and y is not None
                and isclose(x, y, rel_tol=1e-10, abs_tol=1e-8)
            )
    take = []
    side = 0
    for index, direction in enumerate(expected[-1][:-1]):
        if direction and direction != side:
            take.append((index + 1, direction))
            side = direction
    assert len(case["closed"]) == max(0, len(take) - 1)
    assert case["unsettled"] == int(bool(take))
    chart = payload["chart"]
    times = [row[0] for row in chart]
    assert all(chart[index][5] > 0 for index, _ in take)
    events = []
    for trade, ((entry, direction), (exit_bar, _)) in zip(
        case["closed"], pairwise(take), strict=True
    ):
        assert trade["entryId"] == ("Enter Long" if direction == 1 else "Enter Short")
        assert (trade["entryBar"], trade["dir"], trade["exitBar"]) == (
            entry,
            direction,
            exit_bar,
        )
        assert (trade["entryPrice"], trade["exitPrice"]) == (
            chart[entry][1],
            chart[exit_bar][1],
        )
        assert isclose(
            trade["qty"],
            floor(CASH / chart[entry][1] / LOT_STEP) * LOT_STEP,
            rel_tol=1e-10,
        )
        events.append(verify_trade(trade, times))
    return events


def verify_runtime(work):
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
    return isolation


def finalize(archive, ledger, public, work, output):
    sources = archive_cases(archive, ledger)
    published, feeds, windows = provider_cases(public)
    assert read(work / "feeds.json") == feeds
    isolation = verify_runtime(work)
    receipts = read(work / "receipt.json")
    assert (
        len(receipts) == len(TESTS)
        and {entry["id"] for entry in receipts} == TESTS.keys()
    )
    coverage, rows, audits = [], [], {}
    for ident, (row, digest, settings, original, variant) in sources.items():
        audits[ident] = {
            "published_source_settings": settings,
            "source_document_sha256": digest,
            "source": row["source"],
        }
        if ident in PENDING:
            name, reason, witnesses = PENDING[ident]
            coverage.append([ident, f"Pending · {name}", reason])
            audits[ident]["archived_active_evidence"] = list(witnesses)
            continue
        receipt = next(item for item in receipts if item["id"] == ident)
        source_path, variant_path = (
            work / f"source-{ident}.pine",
            work / f"variant-{ident}.pine",
        )
        assert (
            source_path.read_bytes() == original
            and variant_path.read_bytes() == variant
        )
        assert receipt["sourceHash"] == sha256(source_path) and receipt[
            "variantHash"
        ] == sha256(variant_path)
        cases = {(case["period"], case["market"]): case for case in receipt["cases"]}
        assert len(cases) == len(receipt["cases"]) == len(MARKETS) * len(windows[ident])
        common = {
            "id": ident,
            "name": row["name"],
            "source": row["source"],
            "source_sha256": digest,
            "executed_source_sha256": receipt["variantHash"],
            "interval": settings["period"],
            "archive_interval": settings["period"],
            "quote_currency": "USDT",
            "group": TESTS[ident][2],
            "market_data": "Binance USD-M historical futures candles",
            "exit": "Archived next-open market reversal",
        }
        closes = 0
        for label, markets in feeds[str(ident)].items():
            pool, remaining = [], 0
            for market, payload in markets.items():
                case = cases[(label, market)]
                events = verify_case(ident, case, payload)
                unsettled = case["unsettled"]
                rows.append(
                    {
                        **common,
                        "period": label,
                        "market": market,
                        **summarize(events, unsettled, CAPITAL),
                    }
                )
                pool.extend(events)
                remaining += unsettled
                closes += len(events)
            rows.append(
                {
                    **common,
                    "period": label,
                    "market": "BTCUSDT + ETHUSDT",
                    **summarize(pool, remaining, 2 * CAPITAL),
                }
            )
        assert closes > 0
        audits[ident].update({"closed": closes, "windows_utc": windows[ident]})
        coverage.append(
            [
                ident,
                f"Tested · {TESTS[ident][2]}",
                "Authored reversal orders and historical series verified by both Piner backends and an independent signal and fill ledger.",
            ]
        )
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(ledger),
            "archive_sha256": FMZ_SHA256,
            "isolation_probe": isolation,
            "published_binance_candles": published,
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
                "https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/",
                "https://www.tradingview.com/pine-script-docs/concepts/timeframes/",
                "https://www.tradingview.com/pine-script-docs/concepts/time/",
                "https://github.com/binance/binance-public-data",
            ],
            "method": [
                "The three archived indicators contain authored strategy.entry blocks. Standalone strategy declarations retain the closed-bar order rules and the original chart intervals.",
                "CCI and RSI references use saved 15, 30, 60, 120 and 240 minute settings with lookahead off. The historical outer [1] delays each merged observation by one chart bar. Independent CCI and Wilder RSI witnesses verify each merge and each direction.",
                "The 10m branch uses the archived candle predicates and RSI of open, with 80 and 75 thresholds as authored. Daily display inputs have no dependency into either order branch. The 10m chart is built from exchange-published 5m candles. Market orders use the next 10m open.",
                "Only complete candles inside each UTC window are used. Each window resets indicator warm-up and position state. The 15m RSI adds the full, separate June 2022 month because its native and equal windows yield no closed trades.",
                "Flat zero-volume exchange bars stay in the indicator series and are validated against their zero quote volume and trade count. No order in the verified cashflow test fills on a zero-volume bar.",
                "BTC matches the archived venue and contract. ETH is a comparable same-venue perpetual; pooled drawdown normalizes to independent 10000 USDT capital per market.",
            ],
            "source_audits": audits,
            "coverage": coverage,
            "results": rows,
        },
    )
    print(
        f"Verified {len(TESTS)} tested IDs, {len(rows)} rows and {sum(audits[ident]['closed'] for ident in TESTS)} closed trades."
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
