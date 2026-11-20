"""Verify the six active indicators in a Pine archive without a saved chart interval."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from hashlib import sha512
from itertools import chain, pairwise
from math import fsum, isclose, log
from pathlib import Path
from shutil import copy2, copytree
from statistics import pstdev
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
    summarize,
    verify_trade,
)
from research.fmz_round11_pine_playzone import exponential, simple
from research.fmz_round12_pine_authored import aligned, provider_bars
from research.fmz_round18_pine_qqe import executable_lines

IDENT = 3742
CAPITAL = 10_000
DAY = 86_400_000
MARKETS = ("BTCUSDT", "ETHUSDT")
GROUP = "FMZ Pine · Daily research comparison · Verified six-indicator order logic"


def factors_variant(code):
    for text in (
        'strategy("Strategy for The Bitcoin Buy/Sell Indicator", overlay=true, calc_on_every_tick=true)',
        "startSAR = 0.02",
        "incrementSAR = 0.02",
        "maximumSAR = 0.2",
        "psar = sar(startSAR, incrementSAR, maximumSAR)",
        "maj_qual=6",
        "maj_len=30",
        "major=lele(maj_qual,maj_len)",
        'input(20, minval=9, title="Tenkan',
        'input(60, minval=26, title="Kijun',
        'input(120, minval=52, title="Chikou',
        'input(30, minval=26, title="Displacement',
        "donchian(len) => avg(lowest(len), highest(len))",
        "lengthAMA=20",
        "fastsc=0.6022",
        "slowsc=0.0645",
        "filterp = 10",
        "cm2(x) => sma(x,2)",
        "ma1=cm2(C)",
        "ma10=cm2(ma9)",
        "lengthVFI = 130",
        "coefVFI = 0.2",
        "vcoefVFI = 2.5",
        "smoothVFI=true",
        "longCondition = leledecMajorBullish or bullishPSAR or strongBullishSignal or amaLongConditionEntry or rahulMohindarOscilllatorLongEntry or bullishVFI",
        "closeLongCondition = leledecMajorBearish or bearishPSAR or strongBearishSignal or amaShortConditionEntry or rahulMohindarOscilllatorShortEntry or bearishVFI",
        'if (longCondition )\n    strategy.entry("Long", strategy.long, leverage, comment="Enter Long")\nelse\n    strategy.close("Long", when=closeLongCondition)',
        "leverage=input(1)",
    ):
        assert text in code, text
    return """//@version=5
strategy("Strategy for The Bitcoin Buy/Sell Indicator", overlay=true, calc_on_every_tick=true)
psar=ta.sar(0.02,0.02,0.2)
bullishPSAR = psar < high and psar[1] > low
bearishPSAR = psar > low and psar[1] < high
priorHigh = ta.highest(high,30)
priorLow = ta.lowest(low,30)
var int bindex = 0
var int sindex = 0
bindex := nz(bindex[1])+(close>close[4]?1:0)
sindex := nz(sindex[1])+(close<close[4]?1:0)
leleDec = 0
if bindex>6 and close<open and high>=priorHigh
    bindex := 0
    leleDec := -1
if sindex>6 and close>open and low<=priorLow
    sindex := 0
    leleDec := 1
donchian(n) => (ta.lowest(low,n)+ta.highest(high,n))/2
tenkan=donchian(20)
kijun=donchian(60)
senkouA=(tenkan+kijun)/2
senkouB=donchian(120)
A=senkouA[30]
B=senkouB[30]
T=math.round(tenkan,9)
K=math.round(kijun,9)
crossUp=T>K and T[1]<K[1]
crossDown=T<K and T[1]>K[1]
strongBullishSignal=crossUp and tenkan>A and tenkan>B and low>tenkan and A>B
strongBearishSignal=crossDown and tenkan<A and tenkan<B and high<tenkan and A<B
noise=math.sum(math.abs(close-close[1]),20)
smooth=math.pow(math.abs(close-close[20])/noise*0.6022+0.0645,2)
var float ama=na
var float amalow=na
var float amahigh=na
ama:=nz(ama[1],close)+smooth*(close-nz(ama[1],close))
filter=0.1*ta.stdev(ama-nz(ama),20)
amalow:=ama<nz(ama[1])?ama:nz(amalow[1])
amahigh:=ama>nz(ama[1])?ama:nz(amahigh[1])
bw=ama-amalow>filter?1:amahigh-ama>filter?-1:0
amaLongConditionEntry=bw==1 and bw[1]!=1
amaShortConditionEntry=bw==-1 and bw[1]!=-1
m1=ta.sma(close,2)
m2=ta.sma(m1,2)
m3=ta.sma(m2,2)
m4=ta.sma(m3,2)
m5=ta.sma(m4,2)
m6=ta.sma(m5,2)
m7=ta.sma(m6,2)
m8=ta.sma(m7,2)
m9=ta.sma(m8,2)
m10=ta.sma(m9,2)
swing=100*(close-(m1+m2+m3+m4+m5+m6+m7+m8+m9+m10)/10)/(ta.highest(close,10)-ta.lowest(close,10))
impulse=ta.ema(swing,30)
rmo=ta.ema(swing,81)
ribbon=rmo>0?1:rmo<0?-1:0
barSignal=impulse>0?1:rmo<0?-1:rmo>0?1:0
rmoUp=ribbon==1 and ribbon[1]==-1 and barSignal==1
rmoDown=ribbon==-1 and ribbon[1]==1 and barSignal==-1
typical=hlc3
inter=math.log(typical)-math.log(typical[1])
cutoff=0.2*ta.stdev(inter,30)*close
vave=ta.sma(volume,130)[1]
vc=volume<vave*2.5?volume:vave*2.5
mf=typical-typical[1]
vcp=mf>cutoff?vc:mf<-cutoff?-vc:0
vfi=ta.sma(math.sum(vcp,130)/vave,3)
bullishVFI=vfi>0 and vfi[1]<=0
bearishVFI=vfi<0 and vfi[1]>=0
longCondition=leleDec==1 or bullishPSAR or strongBullishSignal or amaLongConditionEntry or rmoUp or bullishVFI
closeLongCondition=leleDec==-1 or bearishPSAR or strongBearishSignal or amaShortConditionEntry or rmoDown or bearishVFI
if longCondition
    strategy.entry("Long",strategy.long,qty=1,comment="Enter Long")
else
    strategy.close("Long",when=closeLongCondition)
plot(psar,"SAR")
plot(leleDec,"Leledec")
plot(tenkan,"Tenkan")
plot(kijun,"Kijun")
plot(A,"A")
plot(B,"B")
plot(ama,"AMA")
plot(bw,"AMA trend")
plot(impulse,"Impulse")
plot(rmo,"RMO")
plot(vfi,"VFI")
plot(longCondition?1:0,"Buy")
plot(closeLongCondition?1:0,"Sell")
"""


def sar_reference(bars):
    output = [None]
    value = extreme = accel = below = None
    for i in range(1, len(bars)):
        hi, lo, close = bars[i][2:5]
        first = i == 1
        if first:
            below = close > bars[i - 1][4]
            extreme = hi if below else lo
            value = bars[i - 1][3 if below else 2]
            accel = 0.02
        value += accel * (extreme - value)
        if below and value > lo:
            below = False
            first = True
            value = max(hi, extreme)
            extreme = lo
            accel = 0.02
        elif not below and value < hi:
            below = True
            first = True
            value = min(lo, extreme)
            extreme = hi
            accel = 0.02
        if not first and ((below and hi > extreme) or (not below and lo < extreme)):
            extreme = hi if below else lo
            accel = min(accel + 0.02, 0.2)
        recent = bars[max(0, i - 2) : i]
        barrier = min if below else max
        value = barrier(value, *(row[3 if below else 2] for row in recent))
        output.append(value)
    return output


def rolling(values, length, fn):
    seen = []
    out = []
    for value in values:
        if value is not None:
            seen.append(value)
        out.append(fn(seen[-length:]) if len(seen) >= length else None)
    return out


def ama_path(prices):
    difference = [None, *[abs(x - y) for x, y in pairwise(prices)]]
    noise = rolling(difference, 20, fsum)
    values = []
    modes = []
    low = high = 0
    count = 0
    for i, price in enumerate(prices):
        prev = values[-1] if values else None
        cur = None
        if i >= 20 and noise[i]:
            m = (abs(price - prices[i - 20]) / noise[i] * 0.6022 + 0.0645) ** 2
            seed = price if prev is None else prev
            cur = seed + m * (price - seed)
            count += 1
            prior = 0 if prev is None else prev
            if cur < prior:
                low = cur
            if cur > prior:
                high = cur
        modes.append(
            0
            if cur is None or count < 20
            else 1
            if cur > low
            else -1
            if high > cur
            else 0
        )
        values.append(cur)
    return values, modes


def rmo_path(prices):
    levels = []
    prior = prices
    for _ in range(10):
        prior = simple(prior, 2)
        levels.append(prior)
    swing = []
    for i, pr in enumerate(prices):
        window = prices[i - 9 : i + 1] if i >= 9 else []
        denominator = max(window) - min(window) if window else 0
        details = [series[i] for series in levels]
        swing.append(
            100 * (pr - fsum(details) / 10) / denominator
            if denominator and all(d is not None for d in details)
            else None
        )
    return exponential(swing, 30), exponential(swing, 81)


def vfi_path(bars):
    typical = [fsum(bar[2:5]) / 3 for bar in bars]
    diff = [None, *[log(y) - log(x) for x, y in pairwise(typical)]]
    deviation = rolling(diff, 30, pstdev)
    volume = [bar[5] for bar in bars]
    vave = [None, *simple(volume, 130)[:-1]]
    flow = []
    for i, bar in enumerate(bars):
        change = typical[i] - typical[i - 1] if i else None
        threshold = 0.2 * deviation[i] * bar[4] if deviation[i] is not None else None
        capped = min(volume[i], vave[i] * 2.5) if vave[i] is not None else None
        if threshold is None or abs(change) <= threshold:
            flow.append(0)
        else:
            flow.append(
                None if capped is None else capped if change > threshold else -capped
            )
    total = rolling(flow, 130, fsum)
    return simple(
        [
            num / den if num is not None and den else None
            for num, den in zip(total, vave, strict=True)
        ],
        3,
    )


def prices_expected(bars):
    prices = [row[4] for row in bars]
    sar = sar_reference(bars)

    def midpoint(n):
        out = [None] * (n - 1)
        for i in range(n, len(bars) + 1):
            window = bars[i - n : i]
            out.append((max(r[2] for r in window) + min(r[3] for r in window)) / 2)
        return out

    tenkan, kijun, sankoub = (midpoint(n) for n in (20, 60, 120))
    cloud_a = [None] * 30 + [
        (x + y) / 2 if x is not None and y is not None else None
        for x, y in zip(tenkan[:-30], kijun[:-30], strict=True)
    ]
    cloud_b = [None] * 30 + sankoub[:-30]
    ama, modes = ama_path(prices)
    impulse, rmo = rmo_path(prices)
    vfi = vfi_path(bars)
    major = []
    buy = []
    sell = []
    count_high = count_low = 0
    for i, bar in enumerate(bars):
        o, h, lo, close = bar[1:5]
        if i >= 4:
            count_high += int(close > prices[i - 4])
            count_low += int(close < prices[i - 4])
        code = 0
        if i >= 29:
            window = bars[i - 29 : i + 1]
            if count_high > 6 and close < o and h >= max(r[2] for r in window):
                count_high = 0
                code = -1
            if count_low > 6 and close > o and lo <= min(r[3] for r in window):
                count_low = 0
                code = 1
        major.append(code)
        psar_up = i >= 2 and sar[i] < h and sar[i - 1] > lo
        psar_down = i >= 2 and sar[i] > lo and sar[i - 1] < h
        ichi_up = ichi_down = False
        if cloud_a[i] is not None and cloud_b[i] is not None:
            x, y, a, b = [
                round(a, 9) for a in (tenkan[i], kijun[i], tenkan[i - 1], kijun[i - 1])
            ]
            ichi_up = (
                x > y
                and a < b
                and tenkan[i] > max(cloud_a[i], cloud_b[i])
                and lo > tenkan[i]
                and cloud_a[i] > cloud_b[i]
            )
            ichi_down = (
                x < y
                and a > b
                and tenkan[i] < min(cloud_a[i], cloud_b[i])
                and h < tenkan[i]
                and cloud_a[i] < cloud_b[i]
            )
        ama_up = i > 0 and modes[i] == 1 and modes[i - 1] != 1
        ama_down = i > 0 and modes[i] == -1 and modes[i - 1] != -1
        rmo_up = (
            i > 0
            and rmo[i] is not None
            and rmo[i - 1] is not None
            and rmo[i] > 0 > rmo[i - 1]
        )
        rmo_down = (
            i > 0
            and rmo[i] is not None
            and rmo[i - 1] is not None
            and rmo[i] < 0 < rmo[i - 1]
            and impulse[i] <= 0
        )
        vfi_up = (
            i > 0
            and vfi[i] is not None
            and vfi[i - 1] is not None
            and vfi[i] > 0 >= vfi[i - 1]
        )
        vfi_down = (
            i > 0
            and vfi[i] is not None
            and vfi[i - 1] is not None
            and vfi[i] < 0 <= vfi[i - 1]
        )
        buy.append(int(code == 1 or psar_up or ichi_up or ama_up or rmo_up or vfi_up))
        sell.append(
            int(
                code == -1 or psar_down or ichi_down or ama_down or rmo_down or vfi_down
            )
        )
    return (
        sar,
        major,
        tenkan,
        kijun,
        cloud_a,
        cloud_b,
        ama,
        modes,
        impulse,
        rmo,
        vfi,
        buy,
        sell,
    )


def verify(case, payload):
    chart = payload["chart"]
    expected = prices_expected(chart)
    assert not case["requested"]
    for w, (actual, desired) in enumerate(
        zip(case["witnesses"], expected, strict=True)
    ):
        for i, (x, y) in enumerate(zip(actual, desired, strict=True)):
            assert (
                x is None
                and y is None
                or x is not None
                and y is not None
                and isclose(x, y, rel_tol=1e-10, abs_tol=1e-7)
            ), (w, i, x, y)
    entry = None
    legs = []
    for i, (buy, sell) in enumerate(
        zip(expected[-2][:-1], expected[-1][:-1], strict=True), 1
    ):
        if buy:
            if entry is None:
                entry = i
        elif sell and entry is not None:
            legs.append((entry, i))
            entry = None
    assert len(case["closed"]) == len(legs) and case["unsettled"] == int(
        entry is not None
    )
    times = [r[0] for r in chart]
    events = []
    for trade, (entry, exit) in zip(case["closed"], legs, strict=True):
        assert (trade["entryBar"], trade["exitBar"], trade["dir"], trade["qty"]) == (
            entry,
            exit,
            1,
            1,
        )
        assert (
            trade["entryPrice"] == chart[entry][1]
            and trade["exitPrice"] == chart[exit][1]
        )
        assert chart[entry][5] > 0 and chart[exit][5] > 0
        events.append(verify_trade(trade, times))
    return events


WINDOWS = (
    ("Research daily 2023", "2023-01-01", "2024-01-01"),
    ("Research daily 2024", "2024-01-01", "2025-01-01"),
)


def archived_source(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (row,) = [r for r in read(baseline)["disposition"] if r["id"] == IDENT]
    assert row["status"].startswith("Pending")
    with ZipFile(archive) as source:
        ((_, _, document, digest),) = documents(source, {IDENT: row})
    (block,) = re.findall(
        r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", document
    )
    assert not re.search(r"(?m)^(start|end|period|basePeriod|exchanges):", block)
    original = block.replace("\r\n", "\n")
    active = executable_lines(original)
    assert not any("/*" in line for line in active)
    old = executable_lines(re.sub(r"/\*.*?\*/", "", block, flags=re.DOTALL))
    restored = active - old
    assert sum(restored.values()) == 40
    assert re.findall(r"\bstrategy\.(entry|exit|close|order)\(", "\n".join(active)) == [
        "entry",
        "close",
    ]
    return row, digest, original.encode(), factors_variant(original).encode()


def provider_cases(public):
    manifest, feeds = [], {}
    months = tuple(
        f"{year}-{month:02}" for year in (2023, 2024) for month in range(1, 13)
    )
    for market in MARKETS:
        files = verified_archives(public, market, "1d", months, manifest)
        source = list(chain.from_iterable(provider_bars(f, DAY) for f in files))
        for label, first, last in WINDOWS:
            begin, end = date_ms(first), date_ms(last)
            chart = aligned(source, begin, end, 1440, 1440)
            assert chart[0][0] == begin and chart[-1][0] + DAY == end
            feeds.setdefault(label, {})[market] = {"chart": chart, "frame": "D"}
    return manifest, {str(IDENT): feeds}


def stage(archive, baseline, public, runtime, work):
    _, _, original, normalized = archived_source(archive, baseline)
    _, feeds = provider_cases(public)
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
    copy2(Path(__file__).with_suffix(".mjs"), work / "factors-run.mjs")
    (work / f"source-{IDENT}.pine").write_bytes(original)
    (work / f"variant-{IDENT}.pine").write_bytes(normalized)
    write(work / "factors-feeds.json", feeds)


def check_runtime(work):
    assert (work / "factors-run.exit").read_text().strip() == "0"
    assert (work / "factors-run.mjs").read_bytes() == Path(__file__).with_suffix(
        ".mjs"
    ).read_bytes()
    isolation = read(work / "isolation-probe.json")
    assert isolation == {"privateDenied": True, "networkDenied": True}
    package = work / f"piner-{PINER_VERSION}.tgz"
    assert b64encode(sha512(package.read_bytes()).digest()).decode("ascii") == PINER_PIN
    with open_tar(package, "r:gz") as dist:
        assert (
            dist.extractfile("package/dist/index.js").read()
            == (work / "package/dist/index.js").read_bytes()
        )
    return isolation


def finalize(archive, baseline, public, work, output):
    item, digest, original, normalized = archived_source(archive, baseline)
    manifest, feeds = provider_cases(public)
    assert read(work / "factors-feeds.json") == feeds
    isolation = check_runtime(work)
    (receipt,) = read(work / "factors-receipt.json")
    assert receipt["id"] == IDENT and len(receipt["cases"]) == 4
    raw, executed = work / f"source-{IDENT}.pine", work / f"variant-{IDENT}.pine"
    assert raw.read_bytes() == original and executed.read_bytes() == normalized
    assert receipt["sourceHash"] == sha256(raw) and receipt["variantHash"] == sha256(
        executed
    )
    cases = {(case["period"], case["market"]): case for case in receipt["cases"]}
    assert len(cases) == 4
    common = {
        "id": IDENT,
        "name": item["name"],
        "source": item["source"],
        "source_sha256": digest,
        "executed_source_sha256": receipt["variantHash"],
        "interval": "1d",
        "archive_interval": "unspecified",
        "quote_currency": "USDT",
        "group": GROUP,
        "market_data": "Binance USD-M native historical daily research candles",
        "exit": "Original long-only market close at next open",
    }
    rows, closed = [], 0
    for label, markets in feeds[str(IDENT)].items():
        pool, open_count = [], 0
        for market, payload in markets.items():
            case = cases[(label, market)]
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
                "market": "BTCUSDT + ETHUSDT",
                **summarize(pool, open_count, 2 * CAPITAL),
            }
        )
    assert closed > 0
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
                    "factors-feeds.json",
                    "factors-run.mjs",
                    "factors-receipt.json",
                )
            },
            "cost_model": {
                "fee_per_side": FEE,
                "execution_buffer_per_side": EXECUTION,
                "base_quantity_per_trade": 1,
            },
            "references": [
                "https://www.fmz.com/lang/en/strategy/430013",
                "https://www.fmz.com/doc/9293",
                "https://www.tradingview.com/pine-script-docs/concepts/strategies/",
                "https://github.com/binance/binance-public-data",
            ],
            "method": [
                "A comment-aware reading of the pinned document restores 40 executable lines. The defaults and order dependencies are preserved for the Parabolic SAR, Leledec, Ichimoku, Kaufman AMA, Rahul Mohindar Oscillator and Volume Flow Indicator.",
                "The source buys if any of the six long gates fires. Its close is a separate fallback branch, so a simultaneous bullish signal takes precedence. The archived leverage input passes a literal quantity of one into strategy.entry. The saved calc_on_every_tick setting applies to realtime ticks.",
                "The archive and available public description give no saved backtest venue, timeframe, or date range. This report uses preselected 2023 and 2024 calendar-year research windows and daily Binance BTCUSDT and ETHUSDT archives. The dates and venue are explicit comparison assumptions.",
                "Independent calculations reproduce the documented Parabolic SAR initialization, six indicator paths, active branch order, quantity, next-open fills and modeled costs. The auxiliary display filters have no order dependency.",
                "Results use 10,000 USDT comparison capital per market and a consistent fee and execution buffer. A one-BTC strategy order can exceed that capital in notional. These tests use a historical broker without margin or liquidation modeling.",
            ],
            "source_audits": {
                IDENT: {
                    "archive_settings": None,
                    "source_document_sha256": digest,
                    "restored_executable_lines": 40,
                    "closed": closed,
                    "research_windows_utc": {
                        label: [begin, end] for label, begin, end in WINDOWS
                    },
                }
            },
            "coverage": [
                [
                    IDENT,
                    f"Tested · {GROUP}",
                    "Preserved original six-indicator and market-order behavior, independently verified on documented daily research windows because the source does not save a chart interval.",
                ]
            ],
            "results": rows,
        },
    )
    print(
        f"Verified {len(rows)} rows and {closed} closed trades in named daily research windows."
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
