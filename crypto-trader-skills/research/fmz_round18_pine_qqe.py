"""Verify QQE Pine defaults restored from complete pinned FMZ code fences."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from collections import Counter
from hashlib import sha512
from itertools import chain, pairwise
from math import floor, isclose
from pathlib import Path
from shutil import copy2, copytree
from tarfile import open as open_tar
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
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
from research.fmz_round12_pine_authored import aligned, provider_bars, rsi

CAPITAL, CASH = 10000, 1000
LOT_STEP = 0.001
DAY = 86_400_000
MARKETS = ("BTCUSDT", "ETHUSDT")
GROUP = "FMZ Pine · Native daily · Restored QQE defaults and order gates"
SPECS = {2794: ("2022-12-22", "2023-12-28"), 2796: ("2023-01-15", "2024-01-21")}


def qqe_variant(source):
    for var, value in (
        ("anchor", "4"),
        ("RSILen", "14"),
        ("SF", "8"),
        ("QQEfactor", "5.0"),
        ("threshhold", "10"),
        ("type2", '"EMA"'),
        ("len2", "21"),
        ("RSIsrc", "close"),
        ("tradeSignal", '"XC"'),
        ("closeSignal", '"XQ"'),
        ("filter", "false"),
        ("dfilter", "true"),
        ("ufirst", "false"),
        ("testStartYear", "2018"),
        ("testStartMonth", "6"),
        ("testStartDay", "12"),
    ):
        assert re.search(
            rf"(?m)^{var}\s*=\s*input\((?:defval=)?{re.escape(value)},", source
        ), var
    assert (
        re.search(r"(?m)^testStopYear = 9999\b", source)
        and re.search(r"(?m)^testStopMonth = 12\b", source)
        and re.search(r"(?m)^testStopDay = 31\b", source)
    )
    declarations = re.findall(r"(?m)^strategy\([^\n]*\)$", source)
    (decl,) = declarations
    assert "overlay=true" in decl and "commission" not in decl
    for code in (
        "Wilders_Period = RSILen * 2 - 1",
        "Rsi = rsi(RSIsrc,RSILen)",
        "RSIndex = ema(Rsi, SF)",
        "AtrRsi = abs(RSIndex[1] - RSIndex)",
        "MaAtrRsi = ema(AtrRsi, Wilders_Period)",
        "DeltaFastAtrRsi = ema(MaAtrRsi,Wilders_Period) * QQEfactor",
        "trend:=cross(RSIndex, shortband[1])? 1 : cross(longband[1], RSIndex) ? -1 : nz(trend[1],1)",
        "direction = rising(ma_medium,3) ? 1 : falling(ma_medium,3) ? -1 : 0",
        "altDirection = rising(ma_medium_alt,3) ? 1 : falling(ma_medium_alt,3) ? -1 : 0",
        "(not dfilter or (direction>0 and altDirection>0 and srcclose>ma_medium))",
        "(not dfilter or (direction<0 and altDirection<0 and srcclose<ma_medium))",
        "(QQEclong[1]==1 and QQEflong[1] ? buy_+1 : 0)",
        "(QQEcshort[1]==1 and QQEfshort[1] ? sell_+1 : 0)",
        "((QQExshort==1 or QQEzshort or QQEcshort) ? closeLong+1 : 0)",
        "((QQExlong==1  or QQEzlong or QQEclong==1) ? closeShort+1 : 0)",
        '    strategy.entry("Long", 1, when=isLong)',
        '    strategy.close("Long", when=isCloseLong )',
        '    strategy.entry("Short", 0,  when=isShort)',
        '    strategy.close("Short", when=isCloseShort )',
    ):
        assert code in source, code
    return f"""//@version=5
{decl}
referenceRsi = ta.rsi(close,14)
RSIndex = ta.ema(referenceRsi,8)
AtrRsi = math.abs(RSIndex[1]-RSIndex)
MaAtrRsi = ta.ema(AtrRsi,27)
DeltaFastAtrRsi = ta.ema(MaAtrRsi,27)*5
newshortband = RSIndex + DeltaFastAtrRsi
newlongband = RSIndex - DeltaFastAtrRsi
var float longband = na
var float shortband = na
var int trend = 1
longband := RSIndex[1] > longband[1] and RSIndex > longband[1] ? math.max(longband[1],newlongband) : newlongband
shortband := RSIndex[1] < shortband[1] and RSIndex < shortband[1] ? math.min(shortband[1],newshortband) : newshortband
rs = math.round(RSIndex,9)
prevShort = math.round(shortband[1],9)
prevLong = math.round(longband[1],9)
crossShort = (rs>prevShort and rs[1]<prevShort[1]) or (rs<prevShort and rs[1]>prevShort[1])
crossLong = (rs>prevLong and rs[1]<prevLong[1]) or (rs<prevLong and rs[1]>prevLong[1])
trend := crossShort ? 1 : crossLong ? -1 : nz(trend[1],1)
FastAtrRsiTL = trend==1 ? longband : shortband
medium = ta.ema(close,21)
alt = ta.ema(close,84)
medRise=medium>math.max(medium[1],medium[2],medium[3])
altRise=alt>math.max(alt[1],alt[2],alt[3])
medFall=medium<math.min(medium[1],medium[2],medium[3])
altFall=alt<math.min(alt[1],alt[2],alt[3])
QQEflong = medRise and altRise and close>medium
QQEfshort = medFall and altFall and close<medium
var int QQExlong = 0
var int QQExshort = 0
var int QQEzlong = 0
var int QQEzshort = 0
var int QQEclong = 0
var int QQEcshort = 0
QQExlong := FastAtrRsiTL<RSIndex ? nz(QQExlong[1])+1 : 0
QQExshort := FastAtrRsiTL>RSIndex ? nz(QQExshort[1])+1 : 0
QQEzlong := RSIndex>=50 ? nz(QQEzlong[1])+1 : 0
QQEzshort := RSIndex<50 ? nz(QQEzshort[1])+1 : 0
QQEclong := RSIndex>60 ? nz(QQEclong[1])+1 : 0
QQEcshort := RSIndex<40 ? nz(QQEcshort[1])+1 : 0
var int buy = 0
var int sell = 0
var int closeLong = 0
var int closeShort = 0
buy := QQEclong[1]==1 and QQEflong[1] ? nz(buy[1])+1 : 0
sell := QQEcshort[1]==1 and QQEfshort[1] ? nz(sell[1])+1 : 0
closeLong := QQExshort==1 or QQEzshort!=0 or QQEcshort!=0 ? nz(closeLong[1])+1 : 0
closeShort := QQExlong==1 or QQEzlong!=0 or QQEclong==1 ? nz(closeShort[1])+1 : 0
var int tradestate = 0
previousState = nz(tradestate[1])
tradestate := previousState==0 ? (buy==1 ? 1 : sell==1 ? 2 : 0) : (previousState==1 and closeLong==1) or (previousState==2 and closeShort==1) ? 0 : previousState
changed = tradestate!=previousState
inWindow = time>=timestamp(2018,6,12,0,0) and time<=timestamp(9999,12,31,0,0)
if inWindow
    strategy.entry("Long", strategy.long, when=changed and tradestate==1)
    strategy.close("Long", when=changed and tradestate==0 and previousState==1)
    strategy.entry("Short", strategy.short, when=changed and tradestate==2)
    strategy.close("Short", when=changed and tradestate==0 and previousState==2)
plot(referenceRsi,"RSI")
plot(RSIndex,"Index")
plot(DeltaFastAtrRsi,"Q ATR")
plot(longband,"Long band")
plot(shortband,"Short band")
plot(trend,"Trend")
plot(medium,"Medium")
plot(alt,"Alt")
plot(QQEflong?1:0,"Long filter")
plot(QQEfshort?1:0,"Short filter")
plot(buy,"Buy")
plot(sell,"Sell")
plot(closeLong,"Close long")
plot(closeShort,"Close short")
plot(tradestate,"State")
"""


def sign_cross(level_now, target_now, level_previous, target_previous):
    if any(
        value is None
        for value in (level_now, target_now, level_previous, target_previous)
    ):
        return False
    current, target, previous, prior = [
        round(value, 9)
        for value in (level_now, target_now, level_previous, target_previous)
    ]
    return (current > target and previous < prior) or (
        current < target and previous > prior
    )


def qqe_expected(bars):
    prices = [bar[4] for bar in bars]
    vrsi = rsi(prices, 14)
    smooth = exponential(vrsi, 8)
    atr = [
        None,
        *[
            abs(x - y) if x is not None and y is not None else None
            for x, y in pairwise(smooth)
        ],
    ]
    deviation = [
        5 * a if a is not None else None for a in exponential(exponential(atr, 27), 27)
    ]
    medium, alt = (exponential(prices, n) for n in (21, 84))
    lows = []
    highs = []
    regimes = []
    trend = 1
    flongs = []
    fshorts = []
    buys = []
    sells = []
    closing_l = []
    closing_s = []
    states = []
    qq_long = qq_short = zero_l = zero_s = ch_l = ch_s = b = s = c_l = c_s = state = 0
    for i, price in enumerate(prices):
        fixed = smooth[i]
        width = deviation[i]
        prev_fix = smooth[i - 1] if i else None
        lo = lows[-1] if lows else None
        hi = highs[-1] if highs else None
        low = fixed - width if width is not None else None
        high = fixed + width if width is not None else None
        if low is not None and lo is not None and prev_fix > lo and fixed > lo:
            low = max(lo, low)
        if high is not None and hi is not None and prev_fix < hi and fixed < hi:
            high = min(hi, high)
        if i >= 2:
            if sign_cross(fixed, hi, prev_fix, highs[-2]):
                trend = 1
            elif sign_cross(fixed, lo, prev_fix, lows[-2]):
                trend = -1
        stop_line = low if trend == 1 else high
        b = b + 1 if ch_l == 1 and flongs[-1] else 0
        s = s + 1 if ch_s == 1 and fshorts[-1] else 0
        qq_long = qq_long + 1 if stop_line is not None and stop_line < fixed else 0
        qq_short = qq_short + 1 if stop_line is not None and stop_line > fixed else 0
        zero_l = zero_l + 1 if fixed is not None and fixed >= 50 else 0
        zero_s = zero_s + 1 if fixed is not None and fixed < 50 else 0
        ch_l = ch_l + 1 if fixed is not None and fixed > 60 else 0
        ch_s = ch_s + 1 if fixed is not None and fixed < 40 else 0
        c_l = c_l + 1 if qq_short == 1 or zero_s or ch_s else 0
        c_s = c_s + 1 if qq_long == 1 or zero_l or ch_l == 1 else 0
        if state == 0:
            state = 1 if b == 1 else 2 if s == 1 else 0
        elif (state == 1 and c_l == 1) or (state == 2 and c_s == 1):
            state = 0
        filtered_up = (
            i >= 3
            and medium[i] > max(medium[i - 3 : i])
            and alt[i] > max(alt[i - 3 : i])
            and price > medium[i]
        )
        filtered_down = (
            i >= 3
            and medium[i] < min(medium[i - 3 : i])
            and alt[i] < min(alt[i - 3 : i])
            and price < medium[i]
        )
        lows.append(low)
        highs.append(high)
        regimes.append(trend)
        flongs.append(int(filtered_up))
        fshorts.append(int(filtered_down))
        buys.append(b)
        sells.append(s)
        closing_l.append(c_l)
        closing_s.append(c_s)
        states.append(state)
    return (
        vrsi,
        smooth,
        deviation,
        lows,
        highs,
        regimes,
        medium,
        alt,
        flongs,
        fshorts,
        buys,
        sells,
        closing_l,
        closing_s,
        states,
    )


def verify(case, sample):
    chart = sample["chart"]
    expected = qqe_expected(chart)
    assert not case["requested"]
    for w, (e, a) in enumerate(zip(expected, case["witnesses"], strict=True)):
        for i, (x, y) in enumerate(zip(e, a, strict=True)):
            assert (x is None and y is None) or (
                x is not None
                and y is not None
                and isclose(x, y, rel_tol=1e-10, abs_tol=1e-8)
            ), (w, i, x, y)
    state = 0
    entry = None
    closed = []
    for index, next_state in enumerate(expected[-1][:-1], 1):
        if next_state == state:
            continue
        if state:
            assert next_state == 0
            closed.append((entry, 1 if state == 1 else -1, index))
            entry = None
        else:
            entry = index
        state = next_state
    assert len(case["closed"]) == len(closed) and case["unsettled"] == int(bool(state))
    times = [row[0] for row in chart]
    result = []
    for trade, (i, side, j) in zip(case["closed"], closed, strict=True):
        assert (trade["entryBar"], trade["dir"], trade["exitBar"]) == (i, side, j)
        assert (trade["entryPrice"], trade["exitPrice"]) == (chart[i][1], chart[j][1])
        assert chart[i][5] > 0 and chart[j][5] > 0
        assert isclose(
            trade["qty"], floor(CASH / chart[i][1] / LOT_STEP) * LOT_STEP, rel_tol=1e-10
        )
        result.append(verify_trade(trade, times))
    return result


def executable_lines(code):
    uncommented = re.sub(r"(?m)//[^\n]*", "", code)
    return Counter(line.strip() for line in uncommented.splitlines() if line.strip())


def archive_cases(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    rows = {
        row["id"]: row for row in read(baseline)["disposition"] if row["id"] in SPECS
    }
    assert rows.keys() == SPECS.keys()
    assert all(
        "pending" in row["status"].lower() and row["selected_report"] is None
        for row in rows.values()
    )
    cases = {}
    with ZipFile(archive) as source:
        for ident, row, document, digest in documents(source, rows):
            (fenced,) = re.findall(
                r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", document
            )
            start, end = SPECS[ident]
            settings = dict(
                re.findall(
                    r"(?m)^(start|end|period|basePeriod|exchanges):\s*([^\r\n]+)",
                    fenced,
                )
            )
            assert settings == {
                "start": f"{start} 00:00:00",
                "end": f"{end} 00:00:00",
                "period": "1d",
                "basePeriod": "1h",
                "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
            }
            source_text, wrapper = strip_fmz_wrapper(fenced.replace("\r\n", "\n"))
            assert wrapper and not any(
                "/*" in line for line in executable_lines(source_text)
            )
            original_active = executable_lines(source_text)
            old = executable_lines(re.sub(r"/\*.*?\*/", "", fenced, flags=re.DOTALL))
            restored = original_active - old
            assert sum(restored.values()) == 28
            assert any(re.match(r"RSILen\s*=\s*input\(14,", line) for line in restored)
            assert any(line.startswith("strategy(") for line in restored)
            calls = re.findall(
                r"\bstrategy\.(entry|close|order|exit)\(", "\n".join(original_active)
            )
            assert calls == ["entry", "close", "entry", "close"]
            cases[ident] = (
                row,
                digest,
                settings,
                source_text.encode(),
                qqe_variant(source_text).encode(),
                sum(restored.values()),
            )
    return cases


def provider_cases(public):
    manifest, feeds = [], {}
    for ident, (first, last) in SPECS.items():
        begin, end = date_ms(first), date_ms(last)
        months = tuple(
            f"{year}-{month:02}"
            for year in range(2022, 2026)
            for month in range(1, 13)
            if first[:7] <= f"{year}-{month:02}" <= "2025-01"
        )
        for market in MARKETS:
            files = verified_archives(public, market, "1d", months, manifest)
            source = list(
                chain.from_iterable(provider_bars(file, DAY) for file in files)
            )
            for label, start, stop in (
                ("FMZ native window", begin, end),
                ("Next equal window", end, 2 * end - begin),
            ):
                chart = aligned(source, start, stop, 1440, 1440)
                assert chart[0][0] == start and chart[-1][0] + DAY == stop
                feeds.setdefault(str(ident), {}).setdefault(label, {})[market] = {
                    "chart": chart,
                    "frame": "D",
                }
    unique = {row["url"]: row for row in manifest}
    return list(unique.values()), feeds


def stage(archive, baseline, public, runtime, work):
    cases = archive_cases(archive, baseline)
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
    copy2(Path(__file__).with_suffix(".mjs"), work / "qqe-run.mjs")
    for ident, (_, _, _, original, variant, _) in cases.items():
        (work / f"source-{ident}.pine").write_bytes(original)
        (work / f"variant-{ident}.pine").write_bytes(variant)
    write(work / "qqe-feeds.json", feeds)


def check_runtime(work):
    assert (work / "qqe-run.exit").read_text().strip() == "0"
    assert (work / "qqe-run.mjs").read_bytes() == Path(__file__).with_suffix(
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
    expected = archive_cases(archive, baseline)
    manifest, feeds = provider_cases(public)
    assert read(work / "qqe-feeds.json") == feeds
    isolation = check_runtime(work)
    entries = read(work / "qqe-receipt.json")
    receipts = {entry["id"]: entry for entry in entries}
    assert (
        len(entries) == len(receipts) == len(expected)
        and receipts.keys() == expected.keys()
    )
    rows, coverage, audits = [], [], {}
    for ident, (row, digest, settings, original, variant, restored) in expected.items():
        raw, rewritten = work / f"source-{ident}.pine", work / f"variant-{ident}.pine"
        assert raw.read_bytes() == original and rewritten.read_bytes() == variant
        receipt = receipts[ident]
        assert receipt["sourceHash"] == sha256(raw) and receipt[
            "variantHash"
        ] == sha256(rewritten)
        by_case = {
            (trial["period"], trial["market"]): trial for trial in receipt["cases"]
        }
        assert len(by_case) == len(receipt["cases"]) == 4
        common = {
            "id": ident,
            "name": row["name"],
            "source": row["source"],
            "source_sha256": digest,
            "executed_source_sha256": receipt["variantHash"],
            "interval": "1d",
            "archive_interval": "1d",
            "quote_currency": "USDT",
            "group": GROUP,
            "market_data": "Binance USD-M native historical daily futures candles",
            "exit": "Archived threshold and QQE trend-state market closes",
        }
        closed = 0
        for label, markets in feeds[str(ident)].items():
            combined, open_count = [], 0
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
                combined.extend(events)
                open_count += unsettled
            rows.append(
                {
                    **common,
                    "period": label,
                    "market": "BTCUSDT + ETHUSDT",
                    **summarize(combined, open_count, 2 * CAPITAL),
                }
            )
        assert closed > 0
        audits[ident] = {
            "archive_settings": settings,
            "source_document_sha256": digest,
            "active_lines_restored_by_literal_fence_extraction": restored,
            "closed": closed,
        }
        coverage.append(
            [
                ident,
                f"Tested · {GROUP}",
                "Original RSI lengths, QQE state and trend filters recovered from the same archived source and verified independently for each daily market window.",
            ]
        )
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
                for name in ("qqe-feeds.json", "qqe-run.mjs", "qqe-receipt.json")
            },
            "cost_model": {
                "fee_per_side": FEE,
                "execution_buffer_per_side": EXECUTION,
                "lot_step": LOT_STEP,
            },
            "references": [
                "https://www.fmz.com/doc/9293",
                "https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/",
                "https://github.com/binance/binance-public-data",
            ],
            "method": [
                "A legacy block-comment regex misinterpreted line-comment stars and removed 28 active lines from each source. Direct extraction from the pinned Pine fences restores their complete declarations and input defaults, including the unambiguous fixed length 14 for Wilder RSI.",
                "The saved strategy uses RSI smoothing 8, two 27-period deviation EMAs with factor 5, the 60 and 40 channel, and the two EMA trend gates at 21 and 84. The documented FMZ rising and falling definitions compare the current value against each of the previous three bars. This is implemented explicitly because the alternate runtime otherwise requires monotonic prior bars.",
                "The authored channel entries are delayed by one signal chart bar and the order executes at the next daily open. Legacy numeric Boolean values retain their nonzero meaning in the close gates. Independent RSI, EMA, recursive bands, candidate counters, trade state, quantities and costs matched both execution backends.",
                "Separate archive windows are preserved even though the two documents use the same default decision rules. BTC matches each original Binance instrument, ETH is a same-venue comparison, and the equal chronological samples reset warm-up and position state.",
            ],
            "source_audits": audits,
            "coverage": coverage,
            "results": rows,
        },
    )
    print(
        f"Verified {len(audits)} strategies, {len(rows)} rows and {sum(a['closed'] for a in audits.values())} closed trades."
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
