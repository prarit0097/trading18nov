"""Verify the source daily RSI signals, alternate timeframe smoothing and equity sizing."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from datetime import date, timedelta
from hashlib import sha512
from itertools import pairwise
from math import floor, isclose
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
from research.fmz_round19_pine_broker import average_wilder, relative_strength
from research.fmz_round20_pine_daily import months

DAY = 86_400_000
HOUR = 3_600_000
MARKETS = ("BTCUSDT", "ETHUSDT")
SPECS = {
    1728: ("2022-12-27", "2024-01-02", "1h", HOUR, 10_000),
    2855: ("2023-02-22", "2024-02-28", "1d", DAY, 1_000),
}
CYCLE = ("2020–2021 market cycle", "2020-01-01", "2022-01-01")
GROUP = {
    1728: "FMZ Pine · Daily RSI with native 3h ADX input",
    2855: "FMZ Pine · Daily VWAP RSI with half-equity sizing",
}
BASE_LOT_STEP = 0.001

PINE_1728 = """//@version=5
strategy("RSI scalping",overlay=true)
h=request.security(syminfo.tickerid,"180",high,lookahead=barmerge.lookahead_off)
l=request.security(syminfo.tickerid,"180",low,lookahead=barmerge.lookahead_off)
c=request.security(syminfo.tickerid,"180",close,lookahead=barmerge.lookahead_off)
nativeTR=request.security(syminfo.tickerid,"180",ta.tr,lookahead=barmerge.lookahead_off)
wilder(src,n) =>
    var float value=na
    var float total=0.0
    var int samples=0
    if not na(src)
        if samples<n
            total+=src
            samples+=1
            if samples==n
                value:=total/n
        else
            value:=(value*(n-1)+src)/n
    value
moveUp=ta.change(h)
moveDown=-ta.change(l)
plusDM=na(moveUp)?na:moveUp>moveDown and moveUp>0?moveUp:0
minusDM=na(moveDown)?na:moveDown>moveUp and moveDown>0?moveDown:0
atr=ta.rma(nativeTR,14)
plus=fixnan(100*wilder(plusDM,14)/atr)
minus=fixnan(100*wilder(minusDM,14)/atr)
sumDM=plus+minus
sig=100*wilder(math.abs(plus-minus)/(sumDM==0?1:sumDM),14)
smma=ta.rma(c,20)
rsi=ta.rsi(close,7)
adxRise=sig>sig[1] and sig[1]>sig[2] and sig[2]>sig[3] and sig>15
smaDrop=smma<smma[1] and smma[1]<smma[2] and smma[2]<smma[3]
smaRise=smma>smma[1] and smma[1]>smma[2] and smma[2]>smma[3]
goLong=ta.crossover(rsi,68) and adxRise and smaRise
goShort=ta.crossunder(rsi,28) and adxRise and smaDrop
if goLong
    strategy.entry("Long entry",strategy.long)
if goShort
    strategy.entry("Short Entry",strategy.short)
plot(h,"Reference high")
plot(l,"Reference low")
plot(c,"Reference close")
plot(nativeTR,"Reference true range")
plot(sig,"ADX")
plot(smma,"SMMA")
plot(rsi,"RSI")
plot(goLong?1:0,"Long")
plot(goShort?1:0,"Short")
plot(strategy.position_size,"Position")
"""

PINE_2855 = """//@version=5
strategy("Soran Strategy 2 - LONG SIGNALS",pyramiding=1,initial_capital=1000,default_qty_type=strategy.percent_of_equity,default_qty_value=50,overlay=false)
rawVwap=ta.vwap(close)
rsi=ta.rsi(rawVwap,20)
entry=ta.crossover(rsi,30)
targetCross=ta.crossover(rsi,85)
exitCross=ta.crossunder(rsi,85)
exit=targetCross[28] or exitCross
if entry
    strategy.entry("Long",strategy.long)
if exit
    strategy.close("Long")
plot(rawVwap,"VWAP")
plot(rsi,"RSI")
plot(entry?1:0,"Entry")
plot(exit?1:0,"Exit")
plot(strategy.position_size,"Position")
plot(strategy.equity,"Equity")

"""


def crossed(ind, i, threshold, side):
    return (
        i > 0
        and ind[i] is not None
        and ind[i - 1] is not None
        and side * (ind[i] - threshold) > 0
        and side * (ind[i - 1] - threshold) <= 0
    )


def signals_adx(chart, lower):
    ctx = []
    for i in range(len(chart)):
        j = 8 * (i + 2) - 1
        t, _, h, l, c, _ = lower[j]
        assert t - chart[i][0] == 21 * 3_600_000
        assert c == chart[i][4]
        prev = lower[j - 1][4]
        ctx.append((h, l, c, max(h - l, abs(h - prev), abs(l - prev))))
    movements = [(None, None)]
    for last, row in pairwise(ctx):
        u = row[0] - last[0]
        d = last[1] - row[1]
        movements.append((u if u > d and u > 0 else 0, d if d > u and d > 0 else 0))
    a, b = (list(average_wilder(col, 14)) for col in zip(*movements, strict=True))
    atr = list(average_wilder([r[3] for r in ctx], 14))
    dx = []
    for p, m, v in zip(a, b, atr, strict=True):
        pi = 100 * p / v if p is not None else None
        mi = 100 * m / v if m is not None else None
        dx.append(None if pi is None else abs(pi - mi) / (pi + mi if pi + mi else 1))
    adx = [None if v is None else 100 * v for v in average_wilder(dx, 14)]
    smo = list(average_wilder([r[2] for r in ctx], 20))
    rsi = relative_strength([r[4] for r in chart], 7)
    for i, row in enumerate(ctx):
        rising = (
            i >= 4
            and adx[i - 3] is not None
            and adx[i] > 15
            and adx[i] > adx[i - 1] > adx[i - 2] > adx[i - 3]
        )
        falling_ema = (
            i >= 4
            and smo[i - 3] is not None
            and smo[i] < smo[i - 1] < smo[i - 2] < smo[i - 3]
        )
        rising_ema = (
            i >= 4
            and smo[i - 3] is not None
            and smo[i] > smo[i - 1] > smo[i - 2] > smo[i - 3]
        )
        yield (
            *row,
            adx[i],
            smo[i],
            rsi[i],
            rising and rising_ema and crossed(rsi, i, 68, 1),
            rising and falling_ema and crossed(rsi, i, 28, -1),
        )


def signals_vwap(chart):
    vwap = [r[4] * r[5] / r[5] for r in chart]
    series = relative_strength(vwap, 20)
    for i, (v, rsi) in enumerate(zip(vwap, series, strict=True)):
        yield (
            v,
            rsi,
            crossed(series, i, 30, 1),
            crossed(series, i, 85, -1) or crossed(series, i - 28, 85, 1),
        )


def broker(ident, chart, signals):
    equity = SPECS[ident][4]
    cash = equity
    size = 0
    entry = None
    pending = 0
    trades = []
    poses = []
    for i, (bar, signal) in enumerate(zip(chart, signals, strict=True)):
        if pending:
            if size and (pending == -1 if ident == 2855 else size != pending):
                entry_idx, entered = entry
                qty = abs(size)
                px = bar[1]
                cash += size * (px - entered) - FEE * px * qty
                trades.append((1 if size > 0 else -1, qty, entry_idx, entered, i, px))
                entry = None
                size = 0
            if size == 0 and (ident != 2855 or pending == 1):
                qty = (
                    floor((cash * 0.5 / bar[1]) / BASE_LOT_STEP) * BASE_LOT_STEP
                    if ident == 2855
                    else 1
                )
                if qty > 0:
                    size = qty * pending
                    entry = i, bar[1]
                    cash -= FEE * qty * bar[1]
        equity = cash + size * (bar[4] - entry[1]) if entry else cash
        poses.append((size, equity) if ident == 2855 else (size,))
        long, short = signal[-2:]
        if ident == 2855:
            pending = -1 if short and size else 1 if long and not size else 0
        else:
            assert not (long and short)
            pending = 1 if long else -1 if short else 0
    return trades, poses, entry


def equal(a, b):
    return (
        a is None
        and b is None
        or a is not None
        and b is not None
        and isclose(a, b, abs_tol=1e-8, rel_tol=1e-9)
    )


def source_variant(ident, raw):
    active = "\n".join(executable_lines(raw))
    if ident == 1728:
        witnesses = (
            'input(defval=true,title= "Custom Resolution / TF ? "',
            'input(title="Custom Resolution / TF", defval="180")',
            'input(14, title="ADX Smoothing")',
            'input(14, title="DI Length")',
            "h = request.security(syminfo.tickerid, res, high)",
            "l = request.security(syminfo.tickerid, res, low)",
            "c = request.security(syminfo.tickerid, res, close)",
            "truer = request.security(syminfo.tickerid, res, tr)",
            "truerange = rma(truer, len)",
            "sig = adx(dilen, adxlen)",
            "smma := na(smma[1]) ? sma(c, len) : (smma[1] * (len - 1) + c) / len",
            'input(20, minval=1, title="SMA HTF Length")',
            "RSI = rsi(close, 7)",
            'input( 28, title= "RSI oversold" )',
            'input( 68, title= "RSI overbought" )',
            "ADXrising = (sig > sig[1]) and (sig[1] > sig[2]) and (sig[2]  > sig[3]) and (sig > 15)",
            'strategy.entry("Long entry", strategy.long)',
            'strategy.entry("Short Entry", strategy.short)',
        )
        result = PINE_1728
    else:
        witnesses = (
            "pyramiding=1, initial_capital=1000, default_qty_type=strategy.percent_of_equity, default_qty_value=50",
            'reso = input(title="Resolution", type=input.resolution, defval="")',
            'length = input(20, title="RSI Length", type=input.integer)',
            'ovrsld = input(30, "RSI Oversold level", type=input.float)',
            'ovrbgt = input(85, "RSI Overbought level", type=input.float)',
            'lateleave = input(28, "Number of candles", type=input.integer)',
            'stratbull = input(title="Enter longs ?", type = input.bool, defval=true)',
            'laguerre = input(title="Use Laguerre on RSI ?", type=input.bool, defval=false)',
            "rsiV = security(syminfo.tickerid, reso, rsi(vwap(close), length))",
            "rsiVWAP = laguerre ? laguerre_cal(rsiV,gamma) : rsiV",
            'strategy.entry("Long", true, when = timebull and crossover(rsiVWAP, ovrsld), comment="")',
            'strategy.close("Long", when = timebull and crossover(rsiVWAP, ovrbgt)[lateleave] or crossunder(rsiVWAP, ovrbgt), comment="")',
        )
        assert active.count("stratstart") == 1
        result = PINE_2855
    for line in witnesses:
        assert line in active, (ident, line)
    return result


def pinned(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    pending = {
        r["id"]: r
        for r in read(baseline)["disposition"]
        if r["status"].startswith("Pending")
    }
    output = {}
    with ZipFile(archive) as fmz:
        for ident, row, doc, digest in documents(
            fmz, {key: pending[key] for key in SPECS}
        ):
            (block,) = re.findall(
                r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", doc
            )
            start, end, _, _, _ = SPECS[ident]
            settings = dict(
                re.findall(
                    r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)",
                    block,
                )
            )
            assert settings == {
                "start": f"{start} 00:00:00",
                "end": f"{end} 00:00:00",
                "period": "1d",
                "basePeriod": "1h",
                "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
            }
            assert f"//@version={3 if ident == 1728 else 4}" in block
            output[ident] = (
                row,
                digest,
                settings,
                block.encode(),
                source_variant(ident, block).encode(),
            )
    return output


def provider_data(public):
    manifest, feeds = {}, {}
    for ident, (from_day, to_day, interval, step, _) in SPECS.items():
        start, end = map(date.fromisoformat, (from_day, to_day))
        forward = end + (end - start)
        windows = [
            ("FMZ native window", from_day, to_day),
            ("Next equal window", to_day, forward.isoformat()),
        ]
        extra = int(ident == 1728)
        needed = list(months(start - timedelta(days=extra), forward))
        if ident == 2855:
            windows.append(CYCLE)
            needed = (
                list(months(date.fromisoformat(CYCLE[1]), date.fromisoformat(CYCLE[2])))
                + needed
            )
        archives = manifest[ident] = []
        cases = feeds[str(ident)] = {}
        for market in MARKETS:
            bars = []
            for month in needed:
                name = f"{market}-{interval}-{month}.zip"
                folder = next(folder for folder in public if (folder / name).is_file())
                (path,) = verified_archives(
                    folder, market, interval, (month,), archives
                )
                bars.extend(provider_bars(path, step))
            for label, a, b in windows:
                left, right = date_ms(a), date_ms(b)
                lower = [r for r in bars if left - extra * DAY <= r[0] < right]
                assert [r[0] for r in lower] == list(
                    range(left - extra * DAY, right, step)
                )
                chart = aggregate([r for r in lower if r[0] >= left], DAY // step)
                data = {"chart": [list(r) for r in chart], "frame": "D"}
                if extra:
                    data["lower"] = [list(r) for r in aggregate(lower, 3)]
                cases.setdefault(label, {})[market] = data
    return manifest, feeds


def stage(archive, baseline, work, public):
    source = pinned(archive, baseline)
    _, feeds = provider_data(public)
    for ident, (_, _, _, original, variant) in source.items():
        (work / f"daily-rsi-source-{ident}.pine").write_bytes(original)
        (work / f"daily-rsi-variant-{ident}.pine").write_bytes(variant)
    copy2(Path(__file__).with_suffix(".mjs"), work / "daily-rsi-run.mjs")
    write(work / "daily-rsi-feeds.json", feeds)


def runtime(work):
    assert (work / "daily-rsi-run.exit").read_text().strip() == "0"
    assert (work / "daily-rsi-run.mjs").read_bytes() == Path(__file__).with_suffix(
        ".mjs"
    ).read_bytes()
    isolation = read(work / "isolation-probe.json")
    assert isolation == {"privateDenied": True, "networkDenied": True}
    package = work / f"piner-{PINER_VERSION}.tgz"
    assert b64encode(sha512(package.read_bytes()).digest()).decode("ascii") == PINER_PIN
    with open_tar(package, "r:gz") as tar:
        assert (
            tar.extractfile("package/dist/index.js").read()
            == (work / "package/dist/index.js").read_bytes()
        )
    return isolation


def reconcile(ident, case, data):
    chart = data["chart"]
    market = case["market"]
    if ident == 1728:
        assert case["requested"] == [
            {"symbol": f"BINANCE:{market}.P", "timeframe": "180", "lowerTf": False}
        ]
        signals = list(signals_adx(chart, data["lower"]))
    else:
        assert not case["requested"]
        signals = list(signals_vwap(chart))
    fills, witnesses, remaining = broker(ident, chart, signals)
    assert case["unsettled"] == int(remaining is not None)
    actual = case["witnesses"]
    for i, (signal, pos, seen) in enumerate(
        zip(signals, witnesses, zip(*actual, strict=True), strict=True)
    ):
        assert all(equal(a, b) for a, b in zip((*signal, *pos), seen, strict=True)), (
            ident,
            market,
            i,
            signal,
            pos,
            seen,
        )
    ledger = []
    times = [r[0] for r in chart]
    for independent, raw in zip(fills, case["closed"], strict=True):
        side, qty, entry_bar, entry, exit_bar, exit_price = independent
        order = "Long" if ident == 2855 else "Long entry" if side > 0 else "Short Entry"
        assert (side, entry_bar, entry, exit_bar, exit_price, order) == (
            raw["dir"],
            raw["entryBar"],
            raw["entryPrice"],
            raw["exitBar"],
            raw["exitPrice"],
            raw["entryId"],
        )
        assert equal(qty, raw["qty"])
        assert chart[entry_bar][5] > 0 and chart[exit_bar][5] > 0
        ledger.append(verify_trade(raw, times))
    return ledger, {
        "closed": len(ledger),
        "open_at_cutoff": case["unsettled"],
        "chart_bars": len(chart),
        "signal_a": sum(int(r[-2]) for r in signals),
        "signal_b": sum(int(r[-1]) for r in signals),
        "witnesses_checked": len(actual) * len(chart),
    }


METHOD = {
    1728: [
        "The saved 1d strategy requests its own market's 3h prices and true range with legacy v3 lookahead_off. The default context uses the last completed 3h bar for each daily evaluation. Active directional movement, ADX and SMMA then operate on that merged daily sequence, while RSI uses the daily instrument close.",
        "Piner's raw Wilder smoother remained undefined after a leading unavailable movement sample. The compatibility code explicitly accumulates the initial SMA seed from 14 valid observations, then applies the FMZ documented Wilder recurrence. The independent calculation matches every selected price, ADX, SMMA, RSI, signal, position and fill on both Pine backends.",
        "Next-open long/short one-way reversals use one base unit and a 10,000 USDT comparison accounting basis because the source leaves sizing and balance implicit. Fees use the comparison 0.059% per fill.",
    ],
    2855: [
        "The archived empty request resolution means the chart timeframe. On this native 1d session VWAP with close as input, the one available source observation supplies each day's VWAP. The active Laguerre mean remains off and the daily RSI(20) starts after its authored warmup.",
        "The entry uses the authored crossover of 30. The exit combines the authored immediate cross under 85 and the earlier 85 upward crossover indexed 28 chart bars back. The sole archived direction is long. The independent broker uses the authored 1,000 USDT balance, 50% of current cash at the next open, and the Piner simulation step of 0.001 base units. Comparison fee is 0.059% per side.",
        "Both the archive and its equal forward window have zero realized closes, with terminal open positions preserved. The additional separately labeled 2020–2021 calendar regime displays two independently reconciled terminal closes under the same rules and costs.",
    ],
}


def report(archive, baseline, work, output, public):
    sources = pinned(archive, baseline)
    manifest, feeds = provider_data(public)
    assert feeds == read(work / "daily-rsi-feeds.json")
    isolation = runtime(work)
    receipts = {r["id"]: r for r in read(work / "daily-rsi-receipt.json")}
    results, coverage, counts, audits = [], [], [], {}
    for ident, (source, digest, settings, raw, variant) in sources.items():
        receipt = receipts[ident]
        assert "error" not in receipt
        capital = SPECS[ident][4]
        assert receipt["model"]["initialCapital"] == capital
        assert equal(receipt["model"]["commissionValue"] / 100, FEE)
        if ident == 2855:
            assert (receipt["model"]["qtyType"], receipt["model"]["qtyValue"]) == (
                "percent_of_equity",
                50,
            )
        original = work / f"daily-rsi-source-{ident}.pine"
        executed = work / f"daily-rsi-variant-{ident}.pine"
        assert original.read_bytes() == raw and receipt["sourceHash"] == sha256(
            original
        )
        assert executed.read_bytes() == variant and receipt["variantHash"] == sha256(
            executed
        )
        observed = {(c["period"], c["market"]): c for c in receipt["cases"]}
        assert len(observed) == len(receipt["cases"]) == (6 if ident == 2855 else 4)
        common = {
            "id": ident,
            "name": source["name"],
            "source": source["source"],
            "source_sha256": digest,
            "executed_source_sha256": receipt["variantHash"],
            "interval": "1d",
            "archive_interval": SPECS[ident][2],
            "quote_currency": "USDT",
            "group": GROUP[ident],
            "market_data": "Official Binance USD-M OHLCV",
            "exit": "Reverse on opposite RSI + ADX + trend signal"
            if ident == 1728
            else "RSI crossdown or 28-bar rotated upper-cross exit",
        }
        closed = 0
        for label, markets in feeds[str(ident)].items():
            combined, opened = [], 0
            for market, data in markets.items():
                case = observed[(label, market)]
                events, proof = reconcile(ident, case, data)
                counts.append({"id": ident, "period": label, "market": market, **proof})
                combined.extend(events)
                opened += case["unsettled"]
                closed += len(events)
                results.append(
                    {
                        **common,
                        "period": label,
                        "market": market,
                        **summarize(events, case["unsettled"], capital),
                    }
                )
            results.append(
                {
                    **common,
                    "period": label,
                    "market": "BTCUSDT + ETHUSDT",
                    **summarize(combined, opened, 2 * capital),
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
                "Preserved exact archived defaults and reconciled provider references, all order gates, opened positions and closed fee-adjusted cashflows.",
            ]
        )
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(baseline),
            "archive_sha256": FMZ_SHA256,
            "piner_version": PINER_VERSION,
            "piner_tarball_sha512": PINER_PIN,
            "isolation_probe": isolation,
            "published_binance_candles": manifest,
            "artifacts": {
                name: sha256(work / name)
                for name in (
                    "daily-rsi-feeds.json",
                    "daily-rsi-run.mjs",
                    "daily-rsi-receipt.json",
                )
            },
            "cost_model": {
                "comparison_fee_per_side": FEE,
                "execution_buffer_per_side": EXECUTION,
            },
            "references": [
                "https://www.fmz.com/doc/9293",
                "https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/#lower-timeframe-data",
                "https://www.tradingview.com/support/solutions/43000502018-volume-weighted-average-price-vwap/",
                "https://github.com/binance/binance-public-data",
            ],
            "method": METHOD,
            "reporting_model": [
                "BTC preserves the archived Binance Futures market and timing. ETH uses same-venue historical comparison data. Each period resets strategy state, with a preceding day of lower data to obtain the first 3h true range where applicable.",
                "After-fee P&L is realized. The net comparison deducts a 0.03% per-fill execution buffer. Terminal open positions and zero-close windows preserve their status and undefined win rates.",
            ],
            "source_audits": audits,
            "per_case_order_counts": counts,
            "coverage": coverage,
            "results": results,
        },
    )
    print(
        f"Verified {len(coverage)} strategies, {len(results)} result rows and {sum(r['closed'] for r in counts)} closes."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    command = parser.add_subparsers(dest="command", required=True)
    for name, handler in (("stage", stage), ("finalize", report)):
        op = command.add_parser(name)
        for field in ("archive", "baseline", "work"):
            op.add_argument(field, type=Path)
        if name == "finalize":
            op.add_argument("output", type=Path)
        op.add_argument("public", type=Path, nargs="+")
        op.set_defaults(handler=handler)
    options = vars(parser.parse_args())
    options.pop("command")
    options.pop("handler")(**options)


if __name__ == "__main__":
    main()
