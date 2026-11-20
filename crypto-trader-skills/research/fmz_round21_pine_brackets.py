"""Verify hourly Pine trend and bracket strategies on Binance historical prices."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from bisect import bisect_right
from collections import Counter
from hashlib import sha512
from itertools import batched, chain
from math import fsum, isclose
from pathlib import Path
from shutil import copy2
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
from research.fmz_round19_pine_broker import relative_strength

HOUR = 3_600_000
WEEK = 168 * HOUR
MONDAY = date_ms("1970-01-05")
CAPITAL = 10_000
MARKETS = ("BTCUSDT", "ETHUSDT")
WINDOWS = {1990: ("2024-01-01", "2024-01-25"), 3172: ("2024-01-01", "2024-01-17")}
TICK = {"BTCUSDT": 0.1, "ETHUSDT": 0.01}
GROUP = {
    1990: "FMZ Pine · Native 1h with confirmed weekly reference",
    3172: "FMZ Pine · Native 1h with ordered trade-tape brackets",
}

PINE_1990 = """//@version=5
strategy("KISS Strategy: SMA + EMA",shorttitle="KISS Strat")
fast=ta.sma(close,13)
slow=ta.sma(close,30)
weekly=request.security(syminfo.tickerid,"W",close,lookahead=barmerge.lookahead_off)
bear=weekly[1]>close
bull=weekly[1]<close
slope=math.abs(math.abs(fast-fast[2])-math.abs(slow-slow[2]))>.01
over=ta.crossover(fast,slow)
under=ta.crossunder(fast,slow)
buy=over and slope and bear[7]
sell=under and slope and bull[7]
if buy
    strategy.entry("HC-Long",strategy.long,comment="HC-Long")
if sell
    strategy.entry("HC-Short",strategy.short,comment="HC-Short")
position=strategy.position_size
avg=strategy.position_avg_price
if position>0
    strategy.exit("Close Long", stop=avg*.88,limit=avg*1.25)
if position<0
    strategy.exit("Close Short", stop=avg*1.12,limit=avg*.75)
plot(weekly,"Weekly")
plot(fast,"Fast")
plot(slow,"Slow")
plot(bear?1:0,"Bear")
plot(bull?1:0,"Bull")
plot(slope?1:0,"Slope")
plot(buy?1:0,"Buy")
plot(sell?1:0,"Sell")
plot(position,"Position")
"""

PINE_3172 = """//@version=5
strategy(title="Moving Average",shorttitle="MA",overlay=true)
upper=ta.sma(high,5)
lower=ta.sma(low,5)
rsi=ta.rsi(close,5)
wantLong=close>upper and close>lower and rsi>80
wantShort=close<upper and close<lower and rsi<10
if wantLong
    strategy.entry("long",strategy.long)
strategy.exit("long_exit","long",profit=150,loss=80)
if wantShort
    strategy.entry("short",strategy.long)
strategy.exit("short_exit","short",profit=150,loss=80)
plot(upper,"Upper")
plot(lower,"Lower")
plot(rsi,"RSI")
plot(wantLong?1:0,"Long gate")
plot(wantShort?1:0,"Short-named gate")
plot(strategy.position_size,"Position")
"""


def signals_weekly(chart, reference):
    c = [bar[4] for bar in chart]
    closes = [bar[0] + WEEK for bar in reference]
    weekly = [reference[bisect_right(closes, bar[0] + HOUR) - 1][4] for bar in chart]
    fast = [None if j < 12 else fsum(c[j - 12 : j + 1]) / 13 for j in range(len(c))]
    slow = [None if j < 29 else fsum(c[j - 29 : j + 1]) / 30 for j in range(len(c))]
    bear = [j > 0 and weekly[j - 1] > c[j] for j in range(len(c))]
    bull = [j > 0 and weekly[j - 1] < c[j] for j in range(len(c))]
    for i in range(len(c)):
        slope = (
            i >= 31
            and abs(abs(fast[i] - fast[i - 2]) - abs(slow[i] - slow[i - 2])) > 0.01
        )
        long = (
            slope and fast[i] > slow[i] and fast[i - 1] <= slow[i - 1] and bear[i - 7]
        )
        short = (
            slope and fast[i] < slow[i] and fast[i - 1] >= slow[i - 1] and bull[i - 7]
        )
        yield weekly[i], fast[i], slow[i], bear[i], bull[i], slope, long, short


def signals_rsi(chart):
    c = [b[4] for b in chart]
    rsi = relative_strength(c, 5)
    for i, bar in enumerate(chart):
        group = chart[i - 4 : i + 1] if i >= 4 else []
        up = fsum(h[2] for h in group) / 5 if group else None
        dn = fsum(h[3] for h in group) / 5 if group else None
        long = rsi[i] is not None and c[i] > up and c[i] > dn and rsi[i] > 80
        short = rsi[i] is not None and c[i] < up and c[i] < dn and rsi[i] < 10
        yield up, dn, rsi[i], long, short


def broker(ident, chart, lower, signals, tick, tape):
    pending = None
    trade = None
    bracket = None
    fills = []
    poses = []
    ambiguities = []
    ratio = HOUR // (lower[1][0] - lower[0][0])
    for i, (bar, intra, line) in enumerate(
        zip(chart, batched(lower, ratio), signals, strict=True)
    ):
        if pending and (not trade or trade[0] != pending[0]):
            if trade:
                fills.append((*trade, i, bar[1], "reversal", bar[0]))
                bracket = None
            trade = (*pending, i, bar[1])
            if ident == 3172:
                bracket = (bar[1] + tick * 150, bar[1] - tick * 80)
        if trade and bracket:
            side, _, _, _ = trade
            q, z = bracket
            for t, o, h, l, _close, _ in intra:
                first_touch_time = t
                hit_p = (h - q if side == 1 else q - l) >= -1e-8
                hit_s = (z - l if side == 1 else h - z) >= -1e-8
                gap_p = side * (o - q) >= -1e-8
                gap_s = side * (z - o) >= -1e-8
                if hit_p and hit_s and not (gap_p or gap_s):
                    target = {
                        "time": t,
                        "index": i,
                        "entry": list(trade),
                        "bracket": list(bracket),
                        "open": o,
                        "high": h,
                        "low": l,
                    }
                    ambiguities.append(target)
                    if tape is not None:
                        evidence = tape[t]
                        assert all(evidence["input"][k] == v for k, v in target.items())
                        assert float(evidence["close"]) == _close
                        name, trade_id, trade_time, price = evidence["cross"]
                        threshold = z if name == "stop" else q
                        touched = (
                            threshold >= float(price)
                            if name == "stop"
                            else threshold <= float(price)
                        )
                        assert touched or equal(threshold, float(price))
                        assert t <= trade_time < t + 60_000
                        assert evidence["first"][0] <= trade_id <= evidence["last"][0]
                        assert evidence["count"] > evidence["trades_before_cross"] >= 1
                        hit_p, hit_s = name == "target", name == "stop"
                        first_touch_time = trade_time
                if hit_p or hit_s:
                    out, tag = (
                        (o, "target gap")
                        if gap_p
                        else (o, "stop gap")
                        if gap_s
                        else (z, "stop")
                        if hit_s
                        else (q, "target")
                    )
                    fills.append((*trade, i, out, tag, first_touch_time))
                    trade = None
                    bracket = None
                    break
        poses.append(trade[0] if trade else 0)
        long, short = line[-2:]
        pending = None
        if ident == 1990:
            if trade:
                side, _, _, px = trade
                bracket = (px * (1 + 0.25 * side), px * (1 - 0.12 * side))
            if long or short:
                pending = (1, "HC-Long") if long else (-1, "HC-Short")
        else:
            if long or short:
                pending = (1, "long" if long else "short")
    return fills, poses, trade, ambiguities


def checked_variant(ident, source):
    active = "\n".join(executable_lines(source))
    if ident == 1990:
        checks = (
            'strategy("KISS Strategy: SMA + EMA", shorttitle="KISS Strat")',
            'SH_SMA_length= input(title="SH SMA Length", defval=13)',
            'LG_SMA_length= input(title="LG SMA Length", defval=30)',
            "wcp = security(syminfo.tickerid, 'W', close)",
            'WiT = input(title="Weeks In Trend", defval=1, maxval=5, minval=1)',
            "if (wcp[n] > price)",
            "if (wcp[m] < price)",
            'SlopeFactor= input(title="Slope Factor", defval=.01',
            'SMA_Y_N=input(defval = "Y"',
            'MACD_Y_N=input(defval = "N"',
            "SMAbuy := SH_LGcrossover and StrongSlope and BearTrend[WiT*7]",
            "SMAsell := SH_LGcrossunder and StrongSlope and BullTrend[WiT*7]",
            "window()  => true",
            'strategy.entry("HC-Long", strategy.long',
            'strategy.entry("HC-Short", strategy.short',
            "stopPer = input(12,",
            "takePer = input(25,",
            'strategy.exit(id="Close Long", when = window(), stop=longStop, limit=longTake)',
            'strategy.exit(id="Close Short", when = window(), stop=shortStop, limit=shortTake)',
        )
        variant = PINE_1990
    else:
        checks = (
            'len = input(5, minval=1, title="Length")',
            'len2 = input(5, minval=1, title="Length")',
            'src = input(high, title="Source")',
            'src2 = input(low, title="Source")',
            "vrsi = rsi(price, length)",
            "length = input( 5 )",
            "overSold = input( 10 )",
            "overBought = input( 80 )",
            "longcond= close > out and close > out2 and vrsi > overBought",
            "shortcont = close < out and close < out2 and vrsi < overSold",
            'tp=input(150,title="tp")',
            'sl=input(80,title="sl")',
            'strategy.entry("long",1,when=longcond)',
            'strategy.entry("short",1,when=shortcont)',
            'strategy.exit("long_exit","long",profit=tp,loss=sl)',
            'strategy.exit("short_exit","short",profit=tp,loss=sl)',
        )
        assert active.count("timeinrange") == 1
        variant = PINE_3172
    for witness in checks:
        assert witness in active, (ident, witness)
    return variant


def pinned_sources(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    rows = {
        r["id"]: r
        for r in read(baseline)["disposition"]
        if r["status"].startswith("Pending")
    }
    active = {}
    with ZipFile(archive) as source:
        for ident, row, document, digest in documents(
            source, {key: rows[key] for key in WINDOWS}
        ):
            (block,) = re.findall(
                r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", document
            )
            start, end = WINDOWS[ident]
            expected_end = f"{end} 00:00:00" if ident == 1990 else "2024-01-16 23:59:59"
            settings = dict(
                re.findall(
                    r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)",
                    block,
                )
            )
            assert settings == {
                "start": f"{start} 00:00:00",
                "end": expected_end,
                "period": "1h",
                "basePeriod": "15m",
                "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
            }
            assert "//@version=4" in block
            active[ident] = (
                row,
                digest,
                settings,
                block.encode(),
                checked_variant(ident, block).encode(),
            )
    return active


def chart_cases(hour, quarter):
    manifest, feeds = [], {}
    for symbol in MARKETS:
        mid = verified_archives(
            quarter, symbol, "15m", ("2024-01", "2024-02"), manifest
        )
        hourly = verified_archives(
            hour, symbol, "1h", ("2023-12", "2024-01", "2024-02"), manifest
        )
        sub = list(chain.from_iterable(provider_bars(f, HOUR // 4) for f in mid))
        native = list(chain.from_iterable(provider_bars(f, HOUR) for f in hourly))
        for ident, (start, stop) in WINDOWS.items():
            begin, end = map(date_ms, (start, stop))
            cases = feeds.setdefault(str(ident), {})
            for label, a, b in (
                ("FMZ native window", begin, end),
                ("Next equal window", end, 2 * end - begin),
            ):
                subbars = [r for r in sub if a <= r[0] < b]
                assert [r[0] for r in subbars] == list(range(a, b, HOUR // 4))
                chart = aggregate(subbars, 4)
                assert [r[:5] for r in chart] == [
                    r[:5] for r in native if a <= r[0] < b
                ]
                case = cases.setdefault(label, {})
                case[symbol] = {
                    "chart": [list(r) for r in chart],
                    "lower": [list(r) for r in subbars],
                    "frame": "60",
                }
                if ident == 1990:
                    lo = MONDAY + (a - MONDAY) // WEEK * WEEK - WEEK
                    hi = MONDAY + (b - MONDAY + WEEK - 1) // WEEK * WEEK
                    weekly = [r for r in native if lo <= r[0] < hi]
                    assert [r[0] for r in weekly] == list(range(lo, hi, HOUR))
                    case[symbol]["reference"] = [
                        list(r) for r in aggregate(weekly, 168)
                    ]
    return manifest, feeds


def minute_cases(cases, minute, quarter):
    manifest = []
    verified = {}
    for market in MARKETS:
        (jan,) = verified_archives(minute, market, "1m", ("2024-01",), manifest)
        name = f"{market}-1m-2024-02-01.zip"
        feb = quarter / name
        digest = sha256(feb)
        assert (quarter / f"{name}.CHECKSUM").read_text().split() == [digest, name]
        manifest.append(
            {
                "name": name,
                "sha256": digest,
                "url": f"https://data.binance.vision/data/futures/um/daily/klines/{market}/1m/{name}",
            }
        )
        candles = list(
            chain.from_iterable(provider_bars(path, 60_000) for path in (jan, feb))
        )
        for period, payload in cases.items():
            chart = payload[market]["chart"]
            source = [r for r in candles if chart[0][0] <= r[0] < chart[-1][0] + HOUR]
            assert [r[0] for r in source] == list(
                range(chart[0][0], chart[-1][0] + HOUR, 60_000)
            )
            assert [r[:5] for r in aggregate(source, 60)] == [
                tuple(r[:5]) for r in chart
            ]
            verified[(period, market)] = source
    return manifest, verified


def stage(archive, baseline, hour, quarter, work):
    sources = pinned_sources(archive, baseline)
    _, cases = chart_cases(hour, quarter)
    for ident, (_, _, _, archived, variant) in sources.items():
        (work / f"weekly-source-{ident}.pine").write_bytes(archived)
        (work / f"weekly-variant-{ident}.pine").write_bytes(variant)
    copy2(Path(__file__).with_suffix(".mjs"), work / "weekly-bracket-run.mjs")
    write(work / "weekly-bracket-feeds.json", cases)


def tick_targets(archive, baseline, hour, quarter, work, minute, output):
    pinned_sources(archive, baseline)
    _, feeds = chart_cases(hour, quarter)
    assert feeds == read(work / "weekly-bracket-feeds.json")
    _, prices = minute_cases(feeds["3172"], minute, quarter)
    targets = []
    for (period, market), tape in prices.items():
        chart = feeds["3172"][period][market]["chart"]
        _, _, _, conflicts = broker(
            3172, chart, tape, list(signals_rsi(chart)), TICK[market], None
        )
        targets.extend(
            {"period": period, "market": market, **item} for item in conflicts
        )
    write(output, targets)


def runtime(work):
    assert (work / "weekly-bracket-run.exit").read_text().strip() == "0"
    assert (work / "weekly-bracket-run.mjs").read_bytes() == Path(__file__).with_suffix(
        ".mjs"
    ).read_bytes()
    isolation = read(work / "isolation-probe.json")
    assert isolation == {"privateDenied": True, "networkDenied": True}
    tarfile = work / f"piner-{PINER_VERSION}.tgz"
    assert b64encode(sha512(tarfile.read_bytes()).digest()).decode("ascii") == PINER_PIN
    with open_tar(tarfile, "r:gz") as tar:
        assert (
            tar.extractfile("package/dist/index.js").read()
            == (work / "package/dist/index.js").read_bytes()
        )
    return isolation


def equal(observed, expected):
    return (
        observed is None
        and expected is None
        or observed is not None
        and expected is not None
        and isclose(observed, expected, rel_tol=1e-9, abs_tol=1e-8)
    )


def verify(ident, case, data, subbars, tick_tape):
    market = case["market"]
    chart = data["chart"]
    if ident == 1990:
        assert case["requested"] == [
            {"symbol": f"BINANCE:{market}.P", "timeframe": "W", "lowerTf": False}
        ]
        signals = list(signals_weekly(chart, data["reference"]))
    else:
        assert not case["requested"]
        signals = list(signals_rsi(chart))
    fills, positions, remaining, conflicts = broker(
        ident, chart, subbars, signals, TICK[market], tick_tape
    )
    assert {item["time"] for item in conflicts} == set(tick_tape)
    assert len(conflicts) == len(tick_tape)
    assert case["unsettled"] == int(remaining is not None)
    for i, (known, pos, observed) in enumerate(
        zip(signals, positions, zip(*case["witnesses"], strict=True), strict=True)
    ):
        assert all(equal(a, b) for a, b in zip((*known, pos), observed, strict=True)), (
            ident,
            market,
            i,
            known,
            observed,
        )
    totals, tags = [], Counter()
    revised = 0
    times = [row[0] for row in chart]
    for independent, observed in zip(fills, case["closed"], strict=True):
        side, entry_id, i, entry, j, price, kind, t = independent
        assert (side, entry_id, i, entry, j, 1) == (
            observed["dir"],
            observed["entryId"],
            observed["entryBar"],
            observed["entryPrice"],
            observed["exitBar"],
            observed["qty"],
        )
        raw_time, _, _, _ = verify_trade(observed, times)
        assert raw_time <= t < raw_time + HOUR and chart[i][5] > 0 and chart[j][5] > 0
        if ident == 1990:
            assert equal(price, observed["exitPrice"])
        else:
            revised += int(not equal(price, observed["exitPrice"]))
        notional = price + entry
        totals.append((t, side * (price - entry), notional * FEE, notional * EXECUTION))
        tags[kind] += 1
    return totals, {
        "closes": len(totals),
        "open_at_cutoff": case["unsettled"],
        "exit_types": dict(tags),
        "chart_bars": len(chart),
        "subbars": len(subbars),
        "tick_resolved_dual_touches": len(conflicts),
        "prices_resolved_differently_than_ohlc_path": revised,
    }


METHOD = {
    1990: [
        "The Pine v4 weekly request is lookahead_off. At each hourly close, the independent series uses only the latest completed Binance UTC Monday-to-Monday week. The legacy wcp[1] and trend[7] preserve one and seven chart-bar offsets, matching the active source.",
        "The saved SMA path remains active. The saved optional MACD path is off. Dual Pine plus an independent broker verifies next-open entries and reversals, the 12% protective stop and 25% target after entry, and cutoff positions with official 15m observations.",
        "The archive leaves size and commission unset. The comparison uses one unit of base asset, 10,000 USDT accounting base and 0.059% per fill.",
    ],
    3172: [
        "Both named entries carry numeric direction 1, therefore both enter long. The two signal gates preserve the exact 5-bar high and low means, Wilder RSI(5), and threshold directions. Authored limits and stops use 150 and 80 exchange ticks, respectively.",
        "The closed-position order sequence matches both Pine engines. Standard chart OHLC fill prices alone do not establish which tight bracket was reached first. Chronological native 1m OHLC resolves ordered touches; when both thresholds fall inside the same minute, checksum-verified raw Binance trade IDs establish which touched first. The archived hourly and 15m timestamps are preserved.",
        "This quote-triggered historical comparison uses the bracket level after a touch and the known minute opening price for moves that already gapped past it. Subsequent queue execution, funding and individual exchange fills are outside the model. The one base unit sizing, 10,000 USDT initial accounting basis and 0.059% comparison fee are disclosed assumptions.",
    ],
}


def report(archive, baseline, hour, quarter, work, minute, tick_evidence, output):
    sources = pinned_sources(archive, baseline)
    manifest, feeds = chart_cases(hour, quarter)
    assert feeds == read(work / "weekly-bracket-feeds.json")
    mins, micro = minute_cases(feeds["3172"], minute, quarter)
    tick = read(tick_evidence)
    keyed = {}
    for day in tick:
        assert day["url"].startswith(
            "https://data.binance.vision/data/futures/um/daily/trades/"
        )
        assert re.fullmatch(r"[0-9a-f]{64}", day["zip_sha256"])
        for cell in day["witnesses"]:
            key = (cell["input"]["period"], cell["input"]["market"])
            moment = cell["input"]["time"]
            assert moment not in keyed.setdefault(key, {})
            assert re.fullmatch(r"[0-9a-f]{64}", cell["raw_minute_sha256"])
            keyed[key][moment] = cell
    isolation = runtime(work)
    observed = {r["id"]: r for r in read(work / "weekly-bracket-receipt.json")}
    rows, coverage, stats, audits = [], [], [], {}
    for ident, (row, digest, settings, archived, variant) in sources.items():
        receipt = observed[ident]
        assert "error" not in receipt
        assert receipt["model"]["initialCapital"] == CAPITAL
        assert equal(receipt["model"]["commissionValue"] / 100, FEE)
        source = work / f"weekly-source-{ident}.pine"
        adapted = work / f"weekly-variant-{ident}.pine"
        assert source.read_bytes() == archived and receipt["sourceHash"] == sha256(
            source
        )
        assert adapted.read_bytes() == variant and receipt["variantHash"] == sha256(
            adapted
        )
        cases = {(r["period"], r["market"]): r for r in receipt["cases"]}
        assert len(cases) == len(receipt["cases"]) == 4
        common = {
            "id": ident,
            "name": row["name"],
            "source": row["source"],
            "source_sha256": digest,
            "executed_source_sha256": receipt["variantHash"],
            "interval": "1h",
            "archive_interval": "15m" if ident == 1990 else "1m",
            "quote_currency": "USDT",
            "group": GROUP[ident],
            "market_data": "Official Binance USD-M 1h/15m provider history"
            if ident == 1990
            else "Official Binance USD-M 1m bars and checksummed exchange trades",
            "exit": "12% stop / 25% limit or opposite entry"
            if ident == 1990
            else "80-tick stop / 150-tick limit",
        }
        closed = 0
        for period, markets in feeds[str(ident)].items():
            combined, opened = [], 0
            for market, data in markets.items():
                key = (period, market)
                case = cases[key]
                sub = data["lower"] if ident == 1990 else micro[key]
                tape = {} if ident == 1990 else keyed.get(key, {})
                events, proof = verify(ident, case, data, sub, tape)
                opened += case["unsettled"]
                closed += len(events)
                stats.append({"id": ident, "period": period, "market": market, **proof})
                combined.extend(events)
                rows.append(
                    {
                        **common,
                        "period": period,
                        "market": market,
                        **summarize(events, case["unsettled"], CAPITAL),
                    }
                )
            rows.append(
                {
                    **common,
                    "period": period,
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
                "Verified confirmed weekly observations, trend gates and next-open historical fills."
                if ident == 1990
                else "Verified authored long direction and stop/target ordering using chronological exchange prints when a native minute crosses both levels.",
            ]
        )
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(baseline),
            "archive_sha256": FMZ_SHA256,
            "isolation_probe": isolation,
            "piner_version": PINER_VERSION,
            "piner_tarball_sha512": PINER_PIN,
            "published_binance_candles": manifest + mins,
            "published_trade_archive_evidence": tick,
            "artifacts": {
                **{
                    key: sha256(work / key)
                    for key in (
                        "weekly-bracket-feeds.json",
                        "weekly-bracket-run.mjs",
                        "weekly-bracket-receipt.json",
                    )
                },
                "raw_minute_crossing_receipt": sha256(tick_evidence),
            },
            "cost_model": {"fee_per_side": FEE, "execution_buffer_per_side": EXECUTION},
            "references": [
                "https://www.tradingview.com/pine-script-docs/v4/essential/strategies/",
                "https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/",
                "https://www.fmz.com/doc/9293",
                "https://github.com/binance/binance-public-data",
            ],
            "method": METHOD,
            "reporting_model": [
                "BTC uses the archived venue and start/end dates. ETH uses its own official Binance Futures prices. Each forward run uses a disjoint chronological window and resets strategy state.",
                "Before- and after-fee P&L and realized drawdowns use chronological verified close prices. Net deducts the project 0.03% execution buffer per fill. Cutoff open positions are reported as open.",
            ],
            "source_audits": audits,
            "per_case_order_counts": stats,
            "coverage": coverage,
            "results": rows,
        },
    )
    print(
        f"Verified {len(coverage)} strategies, {sum(r['closes'] for r in stats)} closed positions and {sum(r['tick_resolved_dual_touches'] for r in stats)} dual touches resolved by trade IDs."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, handler in (
        ("stage", stage),
        ("targets", tick_targets),
        ("finalize", report),
    ):
        cmd = commands.add_parser(name)
        args = ["archive", "baseline", "hour", "quarter", "work"]
        if name == "finalize":
            args.extend(("minute", "tick_evidence", "output"))
        if name == "targets":
            args.extend(("minute", "output"))
        for arg in args:
            cmd.add_argument(arg, type=Path)
        cmd.set_defaults(handler=handler)
    options = vars(parser.parse_args())
    options.pop("command")
    options.pop("handler")(**options)


if __name__ == "__main__":
    main()
