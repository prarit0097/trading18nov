"""Verify the native daily BB source's hourly inputs and the daily VWAP gate."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from datetime import date, timedelta
from hashlib import sha512
from math import fsum, isclose
from pathlib import Path
from shutil import copy2
from statistics import pstdev
from tarfile import open as open_tar
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
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
    summarize,
    verify_trade,
)
from research.fmz_round12_pine_authored import provider_bars
from research.fmz_round18_pine_qqe import executable_lines

DAY = 86_400_000
HOUR = 3_600_000
CAPITAL = 10_000
MARKETS = ("BTCUSDT", "ETHUSDT")
SPECS = {
    165: ("2022-10-18", "2023-10-24", "1h", HOUR),
    5599: ("2022-11-14", "2023-11-20", "1d", DAY),
}
GROUP = {
    165: "FMZ Pine · Native 1d bands and first-hour trend input",
    5599: "FMZ Pine · Native 1d session VWAP · Verified no entries",
}

PINE_165 = """//@version=5
strategy(title="yuthavithi BB Scalper 2 strategy",overlay=true)
basis=ta.sma(close,20)
sd=ta.stdev(close,20)
hi=basis+4*sd
lo=basis-4*sd
hiHalf=basis+2*sd
loHalf=basis-2*sd
hiTwice=basis+8*sd
loTwice=basis-8*sd
width=(hi-lo)/basis
hr=request.security(syminfo.tickerid,"60",close,lookahead=barmerge.lookahead_on)
hrAvg=request.security(syminfo.tickerid,"60",ta.sma(close,20),lookahead=barmerge.lookahead_on)
up=hr>hrAvg
down=hr<hrAvg
upperCross=ta.cross(close,hiHalf)
lowerCross=ta.cross(close,loHalf)
basisCross=ta.cross(close,basis)
short=(upperCross or basisCross) and close[1]>close and down
long=(lowerCross or basisCross) and close[1]<close and up
closeBuy=high[1]>hi[1] and close<hi and close<open and up
closeSell=(low[1]<lo[1] and close>lo or low[2]<lo[2] and close[1]>lo[1]) and close>open and down
cutBuy=width>.005 ? low<lo and low[1]>lo[1] and up : low<loTwice and low[1]>loTwice[1] and up
cutSell=width>.005 ? high>hi and high[1]<hi[1] and down : high>hiTwice and high[1]<hiTwice[1] and down
if long
    strategy.entry("Buy",strategy.long,comment="Buy")
if short
    strategy.entry("Sell",strategy.short,comment="Sell")
if closeBuy or cutBuy
    strategy.close("Buy")
if closeSell or cutSell
    strategy.close("Sell")
plot(hr,"Reference")
plot(hrAvg,"Reference SMA")
plot(basis,"Basis")
plot(sd,"Deviation")
plot(long?1:0,"Long")
plot(short?1:0,"Short")
plot(closeBuy or cutBuy?1:0,"Close Buy")
plot(closeSell or cutSell?1:0,"Close Sell")
plot(strategy.position_size,"Position")

"""

PINE_5599 = """//@version=5
strategy(title="VWAP and BB strategy [$$]",overlay=true,pyramiding=2,default_qty_value=1,default_qty_type=strategy.fixed,initial_capital=10000,currency=currency.USD)
fast=ta.ema(close,50)
slow=ta.ema(close,200)
rawVwap=ta.vwap(close)
basis=ta.sma(close,7)
upper=basis+2*ta.stdev(close,7)
lower=basis-2*ta.stdev(close,7)
recentDip=ta.lowest(close[1],10)<lower
above=math.round(close,9)>math.round(rawVwap,9)
enter=fast>slow and close>open and above and close<upper and recentDip and strategy.position_size<1
add=strategy.position_size>=1 and close<strategy.position_avg_price and above
out=ta.crossover(close,upper)
if enter
    strategy.entry("long",strategy.long,comment="VB LE")
if add
    strategy.entry("long",strategy.long,comment="Add")
if out
    strategy.close("long",comment="TP Exit")
plot(rawVwap,"VWAP")
plot(above?1:0,"Above")
plot(enter?1:0,"Long")
plot(add?1:0,"Add")
plot(out?1:0,"Close")
plot(strategy.position_size,"Position")
"""


def eq(a, b):
    return (
        a is None
        and b is None
        or a is not None
        and b is not None
        and isclose(a, b, abs_tol=1e-7, rel_tol=1e-10)
    )


def independently_165(chart, lower):
    closes = [r[4] for r in chart]
    prices = [r[4] for r in lower]
    daily = [None if i < 19 else closes[i - 19 : i + 1] for i in range(len(chart))]
    means = [None if chunk is None else fsum(chunk) / 20 for chunk in daily]
    sd = [None if chunk is None else pstdev(chunk) for chunk in daily]

    def level(i, k):
        return None if i < 19 else means[i] + sd[i] * k

    def cross(i, k):
        return i >= 20 and (
            closes[i] > level(i, k)
            and closes[i - 1] <= level(i - 1, k)
            or closes[i] < level(i, k)
            and closes[i - 1] >= level(i - 1, k)
        )

    for i, (_, op, high, low, close, vol) in enumerate(chart):
        j = 24 * (i + 1)
        assert lower[j][0] == chart[i][0]
        first = prices[j]
        mean = fsum(prices[j - 19 : j + 1]) / 20
        trendup, trenddown = first > mean, first < mean
        enter_l = (
            i >= 20
            and (cross(i, -2) or cross(i, 0))
            and closes[i - 1] < close
            and trendup
        )
        enter_s = (
            i >= 20
            and (cross(i, 2) or cross(i, 0))
            and closes[i - 1] > close
            and trenddown
        )
        close_l, close_s = False, False
        if i >= 20:
            close_l = (
                chart[i - 1][2] > level(i - 1, 4)
                and close < level(i, 4)
                and close < op
                and trendup
            )
            close_s = (
                (
                    chart[i - 1][3] < level(i - 1, -4)
                    and close > level(i, -4)
                    or i >= 21
                    and chart[i - 2][3] < level(i - 2, -4)
                    and closes[i - 1] > level(i - 1, -4)
                )
                and close > op
                and trenddown
            )
            k = 4 if 8 * sd[i] / means[i] > 0.005 else 8
            close_l |= (
                low < level(i, -k) and chart[i - 1][3] > level(i - 1, -k) and trendup
            )
            close_s |= (
                high > level(i, k) and chart[i - 1][2] < level(i - 1, k) and trenddown
            )
        yield first, mean, means[i], sd[i], enter_l, enter_s, close_l, close_s


def daily_market(chart, signals):
    pos = 0
    entry = None
    pending = ()
    transactions = []
    for i, (bar, signal) in enumerate(zip(chart, signals, strict=True)):
        for action, side in pending:
            if action == "enter" and side != pos:
                if pos:
                    transactions.append((pos, entry, i, bar[1]))
                pos, entry = side, (i, bar[1])
            if action == "close" and side == pos:
                transactions.append((pos, entry, i, bar[1]))
                pos, entry = 0, None
        a, b, c, d = signal[-4:]
        pending = tuple(
            (action, side)
            for flag, (action, side) in zip(
                (a, b, c, d),
                (("enter", 1), ("enter", -1), ("close", 1), ("close", -1)),
                strict=True,
            )
            if flag
        )
        yield pos, transactions, entry


def active_source(ident, source):
    active = "\n".join(executable_lines(source))
    if ident == 165:
        evidence = (
            'strategy(title="yuthavithi BB Scalper 2 strategy", overlay=true)',
            'len = input(20, minval=1, title="Length")',
            'multiplier = input(4, minval=1, title="multiplier")',
            'trendTimeFrame = input(60, minval=1, title="Trend Time Frame")',
            'useTrendFilter = input(true, type=bool, title = "Use Trend Filter")',
            "closeLongTerm = request.security(syminfo.tickerid, tostring(trendTimeFrame), close)",
            "smaLongTerm = request.security(syminfo.tickerid, tostring(trendTimeFrame), sma(close,20))",
            "cutLossBuy = iff(bbWidth > 0.005,",
            "cutLossSell = iff(bbWidth > 0.005,",
            'strategy.entry("Buy", strategy.long, comment="Buy")',
            'strategy.entry("Sell", strategy.short, comment="Sell")',
            'strategy.close("Buy", closeBuy or cutLossBuy)',
            'strategy.close("Sell", closeSell or cutLossSell)',
        )
        variant = PINE_165
    else:
        evidence = (
            "pyramiding=2, default_qty_value=1, default_qty_type=strategy.fixed",
            "initial_capital=10000, currency=currency.USD)",
            "vwapVal=vwap(close)",
            'shortEMA = input(50, title="fast EMA", minval=1)',
            'longEMA = input(200, title="slow EMA", minval=1)',
            'smaLength = input(7, title="BB SMA Length", minval=1)',
            'defval="BB")',
            "close>open and close>vwapVal and close<upperBand",
            'strategy.entry(id="long", comment="VB LE"',
            'strategy.entry(id="long", comment="Add"',
            "close<strategy.position_avg_price and close>vwapVal",
            'strategy.close(id="long", comment="TP Exit",   when=crossover(close,upperBand) )',
        )
        assert active.count("close>vwapVal") == 2
        assert 'comment="SL Exit"' not in active
        variant = PINE_5599
    for line in evidence:
        assert line in active, (ident, line)
    return variant


def source_cases(archive, prior):
    assert sha256(archive) == FMZ_SHA256
    pending = {
        r["id"]: r
        for r in read(prior)["disposition"]
        if r["status"].startswith("Pending")
    }
    result = {}
    with ZipFile(archive) as pinned:
        for ident, row, text, digest in documents(
            pinned, {i: pending[i] for i in SPECS}
        ):
            first, last, _, _ = SPECS[ident]
            (code,) = re.findall(
                r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", text
            )
            settings = dict(
                re.findall(
                    r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)",
                    code,
                )
            )
            assert settings == {
                "start": f"{first} 00:00:00",
                "end": f"{last} 00:00:00",
                "period": "1d",
                "basePeriod": "1h",
                "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
            }
            assert f"//@version={2 if ident == 165 else 4}" in code
            result[ident] = (
                row,
                digest,
                settings,
                code.encode(),
                active_source(ident, code).encode(),
            )
    return result


def months(begin, end):
    current = begin.replace(day=1)
    while current < end:
        yield current.isoformat()[:7]
        current = (current + timedelta(days=32)).replace(day=1)


def provider_cases(public):
    manifests, feeds = {}, {}
    for ident, (begin, cutoff, interval, step) in SPECS.items():
        first, end = map(date.fromisoformat, (begin, cutoff))
        extra = int(ident == 165)
        forward = end + (end - first)
        months_needed = tuple(months(first - timedelta(days=extra), forward))
        manifest = manifests[ident] = []
        result = feeds[str(ident)] = {}
        for market in MARKETS:
            stream = []
            for month in months_needed:
                name = f"{market}-{interval}-{month}.zip"
                directory = next(
                    folder for folder in public if (folder / name).is_file()
                )
                (archive,) = verified_archives(
                    directory, market, interval, (month,), manifest
                )
                stream.extend(provider_bars(archive, step))
            for label, start, stop in (
                ("FMZ native window", first, end),
                ("Next equal window", end, forward),
            ):
                lo, hi = date_ms(start.isoformat()), date_ms(stop.isoformat())
                lower = [row for row in stream if lo - extra * DAY <= row[0] < hi]
                assert [row[0] for row in lower] == list(
                    range(lo - extra * DAY, hi, step)
                )
                chart = aggregate([row for row in lower if row[0] >= lo], DAY // step)
                case = result.setdefault(label, {})
                case[market] = {"chart": [list(row) for row in chart], "frame": "D"}
                if extra:
                    case[market]["lower"] = [list(row) for row in lower]
    return manifests, feeds


def stage(archive, prior, work, public):
    sources = source_cases(archive, prior)
    _, feeds = provider_cases(public)
    for ident, (_, _, _, archive_code, pine) in sources.items():
        (work / f"daily-source-{ident}.pine").write_bytes(archive_code)
        (work / f"daily-variant-{ident}.pine").write_bytes(pine)
    copy2(Path(__file__).with_suffix(".mjs"), work / "daily-refs-run.mjs")
    write(work / "daily-refs-feeds.json", feeds)


def attest(work):
    assert (work / "daily-refs-run.exit").read_text().strip() == "0"
    assert (work / "daily-refs-run.mjs").read_bytes() == Path(__file__).with_suffix(
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


def reconcile_band(case, chart, lower):
    assert case["requested"] == [
        {"symbol": f"BINANCE:{case['market']}.P", "timeframe": "60", "lowerTf": False}
    ]
    times = [row[0] for row in chart]
    witnesses = list(independently_165(chart, lower))
    states = list(daily_market(chart, witnesses))
    for i, ((pos, _, _), values, actual) in enumerate(
        zip(states, witnesses, zip(*case["witnesses"], strict=True), strict=True)
    ):
        for j, (want, seen) in enumerate(zip((*values, pos), actual, strict=True)):
            assert eq(want, seen), (i, j, want, seen)
    _, fills, unsettled = states[-1]
    assert case["unsettled"] == int(unsettled is not None)
    events = []
    for (side, (entry_bar, entry), exit_bar, exit_price), raw in zip(
        fills, case["closed"], strict=True
    ):
        assert raw["entryId"] == ("Buy" if side > 0 else "Sell")
        assert (side, entry_bar, entry, exit_bar, exit_price, 1) == (
            raw["dir"],
            raw["entryBar"],
            raw["entryPrice"],
            raw["exitBar"],
            raw["exitPrice"],
            raw["qty"],
        )
        assert chart[entry_bar][5] > 0 and chart[exit_bar][5] > 0
        events.append(verify_trade(raw, times))
    return events, {
        "chart_bars": len(chart),
        "witnesses_checked": 9 * len(chart),
        "hourly_bars_including_warmup": len(lower),
    }


def reconcile_vwap(case, chart):
    assert not case["requested"] and not case["unsettled"] and not case["closed"]
    vol = [row[5] for row in chart]
    assert all(v > 0 for v in vol)
    closes = [row[4] for row in chart]
    expected = [c * v / v for c, v in zip(closes, vol, strict=True)]
    upper = [None] * len(chart)
    for i in range(6, len(chart)):
        column = closes[i - 6 : i + 1]
        upper[i] = fsum(column) / 7 + 2 * pstdev(column)
    close_marks = 0
    for i, (c, v, actual) in enumerate(
        zip(closes, expected, zip(*case["witnesses"], strict=True), strict=True)
    ):
        witnessed, above, entered, added, exit_gate, pos = actual
        assert eq(v, witnessed) and round(c, 9) == round(v, 9)
        assert (above, entered, added, pos) == (0, 0, 0, 0)
        cross = (
            i >= 7
            and round(c, 9) > round(upper[i], 9)
            and round(closes[i - 1], 9) <= round(upper[i - 1], 9)
        )
        assert exit_gate == int(cross)
        close_marks += int(cross)
    return [], {
        "chart_bars": len(chart),
        "witnesses_checked": 6 * len(chart),
        "flat_close_calls": close_marks,
    }


METHOD = {
    165: [
        "The saved chart is Binance Futures BTC_USDT 1d. The active trend filter requests its own market at 60 minutes and calculates SMA(20) in hourly context. Pine v2 defaults to legacy lookahead_on, which selects the first hourly bar on completed historical dates. Its close and SMA are already known 23 hours before the next daily order fill. The comparator does not claim realtime parity because realtime lower-timeframe request selection differs.",
        "Both Pine backends and an independent implementation agree on every first-hour close and hourly SMA, 20-day basis and population deviation, authored 4×/2×/8× band rules, strict direction gates, four eligible order instructions, and next-open one-way positions and fills. The old eager calculations are evaluated before their conditions.",
        "The archive does not pin a broker lot size or fee. The comparison uses one unit of base asset, 10,000 USDT accounting base and 0.059% commission per fill. No original wallet state is assumed.",
    ],
    5599: [
        "The source uses vwap(close) on the explicit native 1d cryptocurrency chart, so session VWAP resets every single bar. It equals the only daily close observation to Pine's nine fractional comparison digits. Both the entry and add predicates require close strictly above this value.",
        "Both Pine backends and the independent single-weight arithmetic match all 1,484 verified observations. The conditional Bollinger take-profit close is allowed to occur while flat and generates no order. The unused legacy dates, session helper and commented stop are outside the active order path.",
        "Source capital and quantity are retained. The archived broker denomination is USD, while the provider quote is USDT. No fill, fee, currency conversion, equity change or drawdown occurs in any window.",
    ],
}


def report(archive, prior, work, public, output):
    sources = source_cases(archive, prior)
    manifests, feeds = provider_cases(public)
    assert feeds == read(work / "daily-refs-feeds.json")
    isolation = attest(work)
    cases_by_id = {row["id"]: row for row in read(work / "daily-refs-receipt.json")}
    results, coverage, counts, audits = [], [], [], {}
    for ident, (original, digest, settings, archived, adapted) in sources.items():
        receipt = cases_by_id[ident]
        assert "error" not in receipt
        path = work / f"daily-source-{ident}.pine"
        variant = work / f"daily-variant-{ident}.pine"
        assert path.read_bytes() == archived and receipt["sourceHash"] == sha256(path)
        assert variant.read_bytes() == adapted and receipt["variantHash"] == sha256(
            variant
        )
        assert receipt["model"]["initialCapital"] == CAPITAL
        assert eq(receipt["model"]["commissionValue"] / 100, FEE)
        cases = {(r["period"], r["market"]): r for r in receipt["cases"]}
        assert len(cases) == len(receipt["cases"]) == 4
        common = {
            "id": ident,
            "name": original["name"],
            "source": original["source"],
            "source_sha256": digest,
            "executed_source_sha256": receipt["variantHash"],
            "interval": "1d",
            "archive_interval": SPECS[ident][2],
            "quote_currency": "USDT",
            "market_data": f"Official Binance USD-M {SPECS[ident][2]} archives",
            "group": GROUP[ident],
            "exit": "Authored band closes and reversals"
            if ident == 165
            else "Bollinger crossover while flat",
        }
        closed = 0
        for label, markets in feeds[str(ident)].items():
            combined, opened = [], 0
            for market, data in markets.items():
                case = cases[(label, market)]
                if ident == 165:
                    events, proof = reconcile_band(case, data["chart"], data["lower"])
                else:
                    events, proof = reconcile_vwap(case, data["chart"])
                settled = case["unsettled"]
                counts.append(
                    {
                        "id": ident,
                        "period": label,
                        "market": market,
                        "closed": len(events),
                        "open_at_cutoff": settled,
                        **proof,
                    }
                )
                results.append(
                    {
                        **common,
                        "period": label,
                        "market": market,
                        **summarize(events, settled, CAPITAL),
                    }
                )
                combined.extend(events)
                opened += settled
                closed += len(events)
            results.append(
                {
                    **common,
                    "period": label,
                    "market": "BTCUSDT + ETHUSDT",
                    **summarize(combined, opened, 2 * CAPITAL),
                }
            )
        audits[ident] = {
            "archive_settings": settings,
            "source_document_sha256": digest,
            "closed": closed,
        }
        coverage.append(
            [
                ident,
                f"Tested · {GROUP[ident]}",
                "Verified historical hourly trend merges and native daily fills."
                if ident == 165
                else "Verified that the saved daily close/VWAP gate prevents entry and add orders. Win rate is undefined.",
            ]
        )
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(prior),
            "archive_sha256": FMZ_SHA256,
            "piner_version": PINER_VERSION,
            "piner_tarball_sha512": PINER_PIN,
            "isolation_probe": isolation,
            "published_binance_candles": manifests,
            "artifacts": {
                name: sha256(work / name)
                for name in (
                    "daily-refs-feeds.json",
                    "daily-refs-run.mjs",
                    "daily-refs-receipt.json",
                )
            },
            "cost_model": {
                "comparison_fee_per_side": FEE,
                "execution_buffer_per_side": EXECUTION,
            },
            "references": [
                "https://www.fmz.com/doc/9293",
                "https://www.tradingview.com/pine-script-docs/v3/essential/context-switching-the-security-function/",
                "https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/#lower-timeframe-data",
                "https://www.tradingview.com/support/solutions/43000502018-volume-weighted-average-price-vwap/",
                "https://www.tradingview.com/pine-script-docs/language/type-system/#float",
                "https://github.com/binance/binance-public-data",
            ],
            "method": METHOD,
            "reporting_model": [
                "BTC uses the saved exchange and historical window. ETH uses a same-venue comparison. Following calendar windows are equal length. Each chart resets strategy state at its boundary; the first-hour SMA has a full preceding day of source data.",
                "Realized P&L is measured before and after fees and after the prespecified 0.03% per-fill execution buffer. An unsettled position remains open at the cutoff. Zero fills produce no eligible wins and no win-rate denominator.",
            ],
            "source_audits": audits,
            "per_case_order_counts": counts,
            "coverage": coverage,
            "results": results,
        },
    )
    print(
        f"Verified {len(coverage)} strategies and {sum(r['closed'] for r in counts)} closed positions."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, handler in (("stage", stage), ("finalize", report)):
        command = commands.add_parser(name)
        for arg in ("archive", "prior", "work"):
            command.add_argument(arg, type=Path)
        if name == "finalize":
            command.add_argument("output", type=Path)
        command.add_argument("public", type=Path, nargs="+")
        command.set_defaults(handler=handler)
    options = vars(parser.parse_args())
    options.pop("command")
    options.pop("handler")(**options)


if __name__ == "__main__":
    main()
