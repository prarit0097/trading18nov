"""Verify confirmed monthly trend and a legacy USD Heikin-Ashi channel source."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from bisect import bisect_right
from datetime import UTC, date, datetime
from hashlib import sha512
from itertools import groupby
from math import floor, fsum
from pathlib import Path
from shutil import copy2
from tarfile import open as open_tar
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_marketdata_replay import heikin_bars
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
from research.fmz_round12_pine_authored import provider_bars
from research.fmz_round15_pine_lower import bitfinex_inputs
from research.fmz_round18_pine_qqe import executable_lines
from research.fmz_round19_pine_broker import equal
from research.fmz_round20_pine_daily import months

DAY = 86_400_000
LOT_STEP = 0.001
CAPITAL = {409: 500, 4755: 10_000}
START, END = "2022-11-16", "2023-11-22"
REFERENCE_FIRST = "2020-01-01"
REFERENCE_LAST = "2024-12-01"
GROUPS = {
    409: "FMZ Pine · Bitfinex USD daily Heikin-Ashi research comparison",
    4755: "FMZ Pine · Native daily · Prior-month close and EMA",
}

PINE_409 = """//@version=5
strategy("Hi-Lo Channel Strategy",overlay=true,default_qty_type=strategy.percent_of_equity,initial_capital=500,default_qty_value=100,currency=currency.USD)
haClose=(open+high+low+close)/4
var float haOpen=na
haOpen := na(haOpen[1])?(open+close)/2:(haOpen[1]+haClose[1])/2
haHigh=math.max(high,haOpen,haClose)
haLow=math.min(low,haOpen,haClose)
upper=ta.sma(haHigh,5)
lower=ta.sma(haLow,5)
enter=haClose>upper
leave=haClose<lower
if enter
    strategy.entry("Buy",strategy.long)
if leave
    strategy.close("Buy")
plot(haClose,"HA close")
plot(haOpen,"HA open")
plot(haHigh,"HA high")
plot(haLow,"HA low")
plot(upper,"Upper")
plot(lower,"Lower")
plot(enter?1:0,"Enter")
plot(leave?1:0,"Leave")
plot(strategy.position_size,"Size")
plot(strategy.equity,"Equity")
"""

PINE_4755 = """//@version=5
strategy("Monthly MA Close ",shorttitle="MMAC",overlay=true,default_qty_type=strategy.percent_of_equity,default_qty_value=100)
previousClose=request.security(syminfo.tickerid,"M",close[1],lookahead=barmerge.lookahead_on)
previousAverage=request.security(syminfo.tickerid,"M",ta.ema(close,8)[1],lookahead=barmerge.lookahead_on)
enter=previousClose>previousAverage
leave=previousClose<previousAverage
if enter
    strategy.entry("long",strategy.long)
if leave
    strategy.close("long")
plot(previousClose,"Previous month close")
plot(previousAverage,"Previous month EMA")
plot(enter?1:0,"Enter")
plot(leave?1:0,"Leave")
plot(strategy.position_size,"Size")
plot(strategy.equity,"Equity")
"""


def monthly_signals(chart, reference, start_ix=0):
    closes = [x[4] for x in reference]
    months = [x[0] for x in reference]
    av = [None] * start_ix
    state = closes[start_ix]
    for close in closes[start_ix:]:
        state = (7 * state + 2 * close) / 9
        av.append(state)
    for bar in chart:
        i = bisect_right(months, bar[0]) - 2
        assert i >= start_ix
        prior = closes[i]
        buy, sell = prior > av[i], prior < av[i]
        yield prior, av[i], buy, sell


def trader(chart, conditions, capital):
    balance = capital
    pos = None
    pending = 0
    ledger = []
    witnesses = []
    for i, (row, condition) in enumerate(zip(chart, conditions, strict=True)):
        _, op, _, _, cl, _ = row
        if pending == 1 and pos is None:
            qty = floor(balance / op / LOT_STEP) * LOT_STEP
            if qty > 0:
                pos = (i, op, qty)
                balance -= op * qty * FEE
        if pending == -1 and pos:
            j, p, qty = pos
            balance += qty * (op - p) - qty * op * FEE
            ledger.append((1, j, p, i, op, qty))
            pos = None
        qty = pos[2] if pos else 0
        equity = balance + qty * (cl - pos[1]) if pos else balance
        witnesses.append((*condition, qty, equity))
        pending = 1 if condition[-2] else -1 if condition[-1] else 0
    return ledger, witnesses, pos


def ha_signals(chart):
    columns = ("open", "high", "low", "close")
    derived = heikin_bars([dict(zip(columns, c[1:5], strict=True)) for c in chart])
    for i, b in enumerate(derived):
        upper = fsum(k["high"] for k in derived[i - 4 : i + 1]) / 5 if i >= 4 else None
        lower = fsum(k["low"] for k in derived[i - 4 : i + 1]) / 5 if i >= 4 else None
        yield (
            b["close"],
            b["open"],
            b["high"],
            b["low"],
            upper,
            lower,
            upper is not None and b["close"] > upper,
            lower is not None and b["close"] < lower,
        )


def pinned_sources(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    pending = {
        r["id"]: r
        for r in read(baseline)["disposition"]
        if r["status"].startswith("Pending")
    }
    proofs = {
        409: (
            'initial_capital=500, default_qty_value=100, currency="USD"',
            'lenh = input(5, "High-Based MA")',
            'lenl = input (5, "Low-Based MA")',
            'ha = input(true, "Use Heikin Ashi OHCL values (on real chart)?")',
            "ha_h = security(heikinashi(syminfo.tickerid), timeframe.period, high)",
            "ha_l = security(heikinashi(syminfo.tickerid), timeframe.period, low)",
            "ha_c = security(heikinashi(syminfo.tickerid), timeframe.period, close)",
            "mah := sma(ha_h, lenh)",
            "mal := sma(ha_l, lenl)",
            "longCondition := ha_c > mah",
            "shortCondition := ha_c < mal",
            'strategy.entry("Buy", 100)',
            'strategy.close("Buy")',
        ),
        4755: (
            "default_qty_type =  strategy.percent_of_equity, default_qty_value = 100",
            "f_secureSecurity(_symbol, _res, _src) => security(_symbol, _res, _src[1], lookahead = barmerge.lookahead_on)",
            'exponential = input(true, title="Exponential MA")',
            'ticker = input(false, title="Other ticker MA")',
            'res_ma = input(title="Time MA (W, D, [min])", type=input.string, defval="M")',
            'len_ma = input(8, minval=1, title="Period MA")',
            "ma_long = exponential?f_secureSecurity(syminfo.tickerid, res_ma, ema(close,len_ma))",
            "cl1 = f_secureSecurity(syminfo.tickerid, 'M', close)",
            "bullish_cross = ticker?cl2>ma_cus : cl1>ma_long",
            "bearish_cross = ticker?cl2<ma_cus : cl1<ma_long",
            'strategy.entry("long", strategy.long, when = window() and bullish_cross)',
            'strategy.close("long", when = window() and bearish_cross)',
        ),
    }
    sources = {}
    with ZipFile(archive) as pinned:
        for ident, row, doc, digest in documents(
            pinned, {i: pending[i] for i in CAPITAL}
        ):
            (block,) = re.findall(
                r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", doc
            )
            fields = dict(
                re.findall(
                    r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)",
                    block,
                )
            )
            assert "//@version=4" in block
            assert fields == (
                {}
                if ident == 409
                else {
                    "start": f"{START} 00:00:00",
                    "end": f"{END} 00:00:00",
                    "period": "1d",
                    "basePeriod": "1h",
                    "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
                }
            )
            active = "\n".join(executable_lines(block))
            for line in proofs[ident]:
                assert line in active, (ident, line)
            variant = PINE_409 if ident == 409 else PINE_4755
            sources[ident] = row, digest, fields, block.encode(), variant.encode()
    return sources


def exchange_paths(public, bitfinex):
    manifest, feeds, diagnostics = bitfinex_inputs(bitfinex)
    spot = {
        f"USD research year {k}": {
            market: {"chart": [list(row) for row in data["chart"]], "frame": "D"}
            for market, data in panel.items()
        }
        for k, panel in enumerate(feeds["5474"].values(), 1)
    }
    monthly, binance = {}, []
    begin, end = map(date_ms, (START, END))
    all_months = tuple(
        months(date.fromisoformat(REFERENCE_FIRST), date.fromisoformat(REFERENCE_LAST))
    )
    for market in ("BTCUSDT", "ETHUSDT"):
        stream = []
        for month in all_months:
            name = f"{market}-1d-{month}.zip"
            folder = next(folder for folder in public if (folder / name).is_file())
            (file,) = verified_archives(folder, market, "1d", (month,), binance)
            stream.extend(provider_bars(file, DAY))
        assert [r[0] for r in stream] == list(
            range(date_ms(REFERENCE_FIRST), date_ms(REFERENCE_LAST), DAY)
        )
        reference = []

        def month_key(bar):
            return datetime.fromtimestamp(bar[0] / 1000, UTC).date().replace(day=1)

        for month, group in groupby(stream, key=month_key):
            batch = list(group)
            assert batch[0][0] == date_ms(month.isoformat())
            reference.append(
                [
                    batch[0][0],
                    batch[0][1],
                    max(r[2] for r in batch),
                    min(r[3] for r in batch),
                    batch[-1][4],
                    fsum(r[5] for r in batch),
                ]
            )
        for label, left, right in (
            ("FMZ native window", begin, end),
            ("Next equal window", end, 2 * end - begin),
        ):
            chart = [r for r in stream if left <= r[0] < right]
            assert [r[0] for r in chart] == list(range(left, right, DAY))
            monthly.setdefault(label, {})[market] = {
                "chart": [list(r) for r in chart],
                "frame": "D",
                "reference": reference,
            }
    return binance, manifest, diagnostics, {"409": spot, "4755": monthly}


def stage(archive, baseline, work, bitfinex, public):
    sources = pinned_sources(archive, baseline)
    _, _, _, feeds = exchange_paths(public, bitfinex)
    for ident, (_, _, _, raw, variant) in sources.items():
        (work / f"monthly-trend-source-{ident}.pine").write_bytes(raw)
        (work / f"monthly-trend-variant-{ident}.pine").write_bytes(variant)
    copy2(Path(__file__).with_suffix(".mjs"), work / "monthly-trend-run.mjs")
    write(work / "monthly-trend-feeds.json", feeds)


def runtime(work):
    assert (work / "monthly-trend-run.exit").read_text().strip() == "0"
    assert (work / "monthly-trend-run.mjs").read_bytes() == Path(__file__).with_suffix(
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


def validate_direction(receipt):
    proof = read(receipt)
    assert (
        proof["runtime_sha256"]
        == "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
    )
    assert set(proof["direction_witnesses"]) == {
        "100",
        "1",
        "0",
        "true",
        "false",
        "strategy.long",
        "strategy.short",
    }
    for literal, size in proof["direction_witnesses"].items():
        goal = -1 if literal in {"0", "false", "strategy.short"} else 1
        assert size == [0, goal, goal, goal]
    return proof


def reconcile(ident, case, data):
    chart = data["chart"]
    if ident == 409:
        signals = list(ha_signals(chart))
        assert not case["requested"]
    else:
        reference = data["reference"]
        signals = list(monthly_signals(chart, reference))
        alternate = list(monthly_signals(chart, reference, 12))
        assert [r[-2:] for r in signals] == [r[-2:] for r in alternate]
        assert case["requested"] == [
            {
                "symbol": f"BINANCE:{case['market']}.P",
                "timeframe": "M",
                "lowerTf": False,
            }
        ]
    ledger, expected, remaining = trader(chart, signals, CAPITAL[ident])
    assert case["unsettled"] == int(remaining is not None)
    seen = case["witnesses"]
    for i, (a, b) in enumerate(zip(expected, zip(*seen, strict=True), strict=True)):
        assert all(equal(x, y) for x, y in zip(a, b, strict=True)), (ident, i, a, b)
    time = [r[0] for r in chart]
    events = []
    for source, observed in zip(ledger, case["closed"], strict=True):
        side, i, entry, j, out, qty = source
        assert (side, i, entry, j, out) == (
            observed["dir"],
            observed["entryBar"],
            observed["entryPrice"],
            observed["exitBar"],
            observed["exitPrice"],
        )
        assert observed["entryId"] == ("Buy" if ident == 409 else "long")
        assert equal(qty, observed["qty"])
        assert chart[i][5] > 0 and chart[j][5] > 0
        events.append(verify_trade(observed, time))
    return events, {
        "closed": len(events),
        "open_at_cutoff": case["unsettled"],
        "chart_bars": len(chart),
        "witnesses_checked": len(chart) * len(seen),
        "entry_signal_bars": sum(bool(s[-2]) for s in signals),
        "exit_signal_bars": sum(bool(s[-1]) for s in signals),
    }


METHOD = {
    409: [
        "The source supplies no saved venue, dates or chart interval. The comparison uses two disjoint UTC daily windows of official Bitfinex BTC/USD and ETH/USD history with the authored USD balance and position sizing. Daily OHLC values reconcile against hourly observations. Signal state resets at the start of each window.",
        "The default Heikin-Ashi flag is on. The independent Heikin-Ashi open/high/low/close reconstruction and both Pine backends reconcile the active five-bar channel and each signal. Trades use the underlying Bitfinex market candles and fill at the next real open.",
        "In v4 the second strategy.entry argument is the Boolean long direction. The pinned Pine Compat v4 fixture maps 100, true and strategy.long to the same long direction. The v5 adapter therefore uses the named direction and preserves the authored 100%-equity default quantity and $500 capital.",
    ],
    4755: [
        "The default other-ticker option is off. The active order decision compares the previous completed calendar month's close with its EMA(8), both from the chart symbol. The previous-month offset makes that value available on the first new monthly bar.",
        "The monthly EMA begins with the complete January 2020 Binance record. A second January 2021 seed leaves every observed order gate unchanged. Both Pine backends and the independent calendar and equity calculations match all 1,484 daily observations.",
        "BTC preserves the archived chart dates and Binance Futures instrument. ETH and the equal forward window supply reference comparisons. Both assets use the authored 100%-equity rule and a 10,000 USDT accounting base because the archive leaves starting equity implicit.",
    ],
}


def report(archive, baseline, work, bitfinex, direction, output, public):
    sources = pinned_sources(archive, baseline)
    binance, spot, spot_ohlc, feeds = exchange_paths(public, bitfinex)
    assert read(work / "monthly-trend-feeds.json") == feeds
    fixture = validate_direction(direction)
    isolation = runtime(work)
    receipts = {r["id"]: r for r in read(work / "monthly-trend-receipt.json")}
    rows, stats, coverage, audits = [], [], [], {}
    for ident, (original, digest, fields, raw, variant) in sources.items():
        receipt = receipts[ident]
        assert "error" not in receipt
        assert receipt["model"]["initialCapital"] == CAPITAL[ident]
        assert equal(receipt["model"]["commissionValue"] / 100, FEE)
        assert (receipt["model"]["qtyType"], receipt["model"]["qtyValue"]) == (
            "percent_of_equity",
            100,
        )
        archived = work / f"monthly-trend-source-{ident}.pine"
        altered = work / f"monthly-trend-variant-{ident}.pine"
        assert archived.read_bytes() == raw and receipt["sourceHash"] == sha256(
            archived
        )
        assert altered.read_bytes() == variant and receipt["variantHash"] == sha256(
            altered
        )
        cases = {(c["period"], c["market"]): c for c in receipt["cases"]}
        assert len(cases) == len(receipt["cases"]) == 4
        data = {
            "id": ident,
            "name": original["name"],
            "source": original["source"],
            "source_sha256": digest,
            "executed_source_sha256": receipt["variantHash"],
            "interval": "1d",
            "archive_interval": "1d",
            "quote_currency": "USD" if ident == 409 else "USDT",
            "market_data": "Official Bitfinex spot daily USD"
            if ident == 409
            else "Official Binance USD-M historical daily and monthly OHLCV",
            "group": GROUPS[ident],
            "exit": "HA close below five-bar channel low"
            if ident == 409
            else "Prior monthly close below its EMA(8)",
        }
        closed_count = 0
        for period, markets in feeds[str(ident)].items():
            open_total, pooled = 0, []
            for market, payload in markets.items():
                case = cases[(period, market)]
                ledger, check = reconcile(ident, case, payload)
                pooled.extend(ledger)
                opened = case["unsettled"]
                open_total += opened
                stats.append({"id": ident, "period": period, "market": market, **check})
                closed_count += len(ledger)
                rows.append(
                    {
                        **data,
                        "period": period,
                        "market": market,
                        **summarize(ledger, opened, CAPITAL[ident]),
                    }
                )
            combined = "BTCUSD + ETHUSD" if ident == 409 else "BTCUSDT + ETHUSDT"
            rows.append(
                {
                    **data,
                    "period": period,
                    "market": combined,
                    **summarize(pooled, open_total, CAPITAL[ident] * 2),
                }
            )
        audits[ident] = {
            "archive_settings": fields,
            "source_document_sha256": digest,
            "closed": closed_count,
        }
        coverage.append(
            [
                ident,
                f"Tested · {GROUPS[ident]}",
                "Source defaults, official historical data, signal and execution state, fee-adjusted amounts, and terminal open positions reconciled.",
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
            "legacy_v4_direction_fixture": fixture,
            "legacy_v4_direction_fixture_sha256": sha256(direction),
            "published_binance_candles": binance,
            "public_bitfinex_candles": spot,
            "bitfinex_ohlc_quality": spot_ohlc,
            "artifacts": {
                name: sha256(work / name)
                for name in (
                    "monthly-trend-feeds.json",
                    "monthly-trend-run.mjs",
                    "monthly-trend-receipt.json",
                )
            },
            "cost_model": {
                "comparison_fee_per_side": FEE,
                "execution_buffer_per_side": EXECUTION,
                "position_size_step": LOT_STEP,
            },
            "references": [
                "https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/",
                "https://www.tradingview.com/pine-script-docs/v5/language/type-system/",
                "https://www.tradingview.com/pine-script-docs/concepts/non-standard-charts-data/",
                "https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/",
                "https://docs.bitfinex.com/reference/rest-public-candles",
                "https://github.com/binance/binance-public-data",
            ],
            "method": METHOD,
            "reporting_model": [
                "Venue-denominated P&L uses realized closes and the comparison fee in each row. Net deducts the project 0.03% execution buffer per fill. Unclosed positions are reported separately. USD and USDT results retain their respective quotes.",
            ],
            "source_audits": audits,
            "per_case_order_counts": stats,
            "coverage": coverage,
            "results": rows,
        },
    )
    print(
        f"Verified {len(coverage)} archived strategies, {len(rows)} workbook rows, and {sum(s['closed'] for s in stats)} closed positions."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, handler in (("stage", stage), ("finalize", report)):
        cmd = commands.add_parser(name)
        fields = ["archive", "baseline", "work", "bitfinex"]
        if name == "finalize":
            fields.extend(("direction", "output"))
        for field in fields:
            cmd.add_argument(field, type=Path)
        cmd.add_argument("public", type=Path, nargs="+")
        cmd.set_defaults(handler=handler)
    options = vars(parser.parse_args())
    options.pop("command")
    options.pop("handler")(**options)


if __name__ == "__main__":
    main()
