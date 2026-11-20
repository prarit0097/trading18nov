"""Verify FMZ same-symbol Pine references and their native order semantics."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from bisect import bisect_right
from collections import deque
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
from research.fmz_round11_pine_playzone import exponential
from research.fmz_round12_pine_authored import aligned, provider_bars

DAY = 86_400_000
W = 7 * DAY
H4 = 4 * 3_600_000
MONDAY = date_ms("1970-01-05")
CASH, CAPITAL = 1000, 10000
LOT_STEP = 0.001
MARKETS = ("BTCUSDT", "ETHUSDT")


def supertrend_variant(code):
    assert 'orderType = input("Longs+Shorts"' in code and 'TF=input("daily"' in code
    assert "daily = security(_ticker, 'D', _source[1], lookahead=true)" in code
    assert "st_tsl = f_supertrend(Factor, Pd)" in code
    assert "iff(IS_DAILY, st_daily," in code
    f = re.search(r"(?ms)^f_supertrend\(Factor, Pd\) =>.*?^    Tsl\s*$", code)[
        0
    ].rstrip()
    f = re.sub(
        r"(?<![.\w])(atr|max|min)\(",
        lambda m: ("ta." if m[1] == "atr" else "math.") + m[0],
        f,
    )
    out = []
    for name in (
        "orderType",
        "isLong",
        "isShort",
        "fastLength",
        "slowLength",
        "Factor",
        "Pd",
    ):
        (line,) = re.findall(rf"(?m)^{name}\s*=[^\n]+", code)
        if name in ("fastLength", "slowLength", "Pd"):
            line = line.replace("input(", "input.int(")
        elif name == "orderType":
            line = line.replace("input(", "input.string(")
        elif name == "Factor":
            line = line.replace("input(", "input.float(").replace(
                ", type=input.float", ""
            )
        out.append(line)
    out.extend(
        [
            f,
            'st_tsl_TF = request.security(syminfo.tickerid, "D", f_supertrend(Factor, Pd)[1], lookahead=barmerge.lookahead_on)',
        ]
    )
    for var in (
        "sma_fast",
        "sma_slow",
        "long_exit",
        "short_exit",
        "curr",
        "cross_buy",
        "cross_sell",
        "bull",
        "bear",
    ):
        (line,) = re.findall(rf"(?m)^{var}\s*=[^\n]+", code)
        line = re.sub(r"(?<![.\w])(sma|barssince)\(", r"ta.\1(", line)
        line = line.replace(
            "crossunder(sma_fast,sma_slow)",
            "math.round(sma_fast,9)<math.round(sma_slow,9) and math.round(sma_fast[1],9)>math.round(sma_slow[1],9)",
        )
        line = line.replace(
            "crossover(sma_fast,sma_slow)",
            "math.round(sma_fast,9)>math.round(sma_slow,9) and math.round(sma_fast[1],9)<math.round(sma_slow[1],9)",
        )
        line = line.replace("and cross_buy", "and cross_buy != 0").replace(
            "and cross_sell", "and cross_sell != 0"
        )
        out.append(line)
    source_orders = 'if isLong\n    strategy.entry("Long", 1, when=bull)\n    strategy.close("Long", when=long_exit)\n\nif isShort\n    strategy.entry("Short", 0,  when=bear)\n    strategy.close("Short", when=short_exit )'
    assert source_orders in code
    out.append(
        source_orders.replace('"Long", 1,', '"Long", strategy.long,').replace(
            '"Short", 0,', '"Short", strategy.short,'
        )
    )
    for var in ("st_tsl_TF", "sma_fast", "sma_slow", "curr"):
        out.append(f'plot({var},"{var}")')
    out.extend(
        (
            'plot(bull?1:0,"bull")',
            'plot(bear?1:0,"bear")',
            'plot(long_exit?1:0,"long_exit")',
            'plot(short_exit?1:0,"short_exit")',
        )
    )
    return "\n".join(("//@version=5", 'strategy("BEST Supertrend Strategy")', *out, ""))


def ema_variant(code):
    assert (
        'res = input(title="Resolution  - not lower than chart", defval="120")' in code
    )
    assert (
        "closeSeries =  request.security(syminfo.tickerid, res, 2 * ta.ema(close, len) - ta.ema(ta.ema(close, len), len)  )"
        in code
    )
    assert (
        "openSeries  = request.security(syminfo.tickerid,res, 2 * ta.ema(close[1], len) - ta.ema(ta.ema(close[1], len), len)  )"
        in code
    )
    pieces = []
    for var in ("emaSlowPeriod", "emaFastPeriod", "len", "slowema", "fastema"):
        (line,) = re.findall(rf"(?m)^{var}\s*=[^\n]+", code)
        pieces.append(line.replace("input(", "input.int("))
    pieces[3:3] = [
        "closeSeries = 2 * ta.ema(close, len) - ta.ema(ta.ema(close, len), len)",
        "openSeries = 2 * ta.ema(close[1], len) - ta.ema(ta.ema(close[1], len), len)",
    ]
    order = 'strategy.order("BUY", strategy.long, 1, when = ta.crossover(slowema, fastema))\nstrategy.order("SELL", strategy.short, 1, when = ta.crossunder(slowema, fastema))'
    assert order in code
    pieces.extend(
        [
            "slow = math.round(slowema,9)",
            "fast = math.round(fastema,9)",
            "bull = slow>fast and slow[1]<fast[1]",
            "bear = slow<fast and slow[1]>fast[1]",
            order.replace("ta.crossover(slowema, fastema)", "bull").replace(
                "ta.crossunder(slowema, fastema)", "bear"
            ),
        ]
    )
    pieces.extend(
        f'plot({name}, "{name}")'
        for name in ("closeSeries", "openSeries", "slowema", "fastema")
    )
    pieces.extend(('plot(bull?1:0,"bull")', 'plot(bear?1:0,"bear")'))
    return "\n".join(("//@version=5", 'strategy("Cuathro EMA Strategy")', *pieces, ""))


def weekly_variant(code):
    assert 'tf10 = input("W", title = "Timeframe", type = input.resolution,' in code
    assert 'length = input(24, title = "Period", type = input.integer)' in code
    assert 'shift = input(1, title = "Shift", type = input.integer)' in code
    fund = re.search(
        r"(?m)^hma3\(_src, _length\)=>\n    p = length/2\n    wma\(wma\(close,p/3\)\*3 - wma\(close,p/2\) - wma\(close,p\),p\)",
        code,
    )[0]
    fund = (
        fund.replace("p = length/2", "p = int(length / 2)")
        .replace("p/3", "int(p / 3)")
        .replace("p/2", "int(p / 2)")
        .replace("wma(", "ta.wma(")
    )
    assert "b =security(syminfo.tickerid, tf10, hma3(close, length)[shift])" in code
    assert (
        "close_price = close[0]" in code
        and "len = input(100)" in code
        and "linear_reg = linreg(close_price, len, 0)" in code
    )
    assert (
        "buy=crossover(linear_reg, b)" in code
        and "sell=crossunder(linear_reg, b)" in code
    )
    body = re.search(
        r'(?m)^if buy\n +strategy.entry\("buy", strategy.long\)\nelse if sell\n +strategy.entry\("sell", strategy.short\)',
        code,
    )[0]
    return "\n".join(
        (
            "//@version=5",
            'strategy("Easy stock", overlay=true)',
            "length=input.int(24)",
            "shift=input.int(1)",
            fund,
            'b = request.security(syminfo.tickerid, "W", hma3(close, length)[shift], gaps=barmerge.gaps_off, lookahead=barmerge.lookahead_off)',
            "linear_reg = ta.linreg(close[0], 100, 0)",
            "r = math.round(linear_reg, 9)",
            "w = math.round(b, 9)",
            "buy = r > w and r[1] < w[1]",
            "sell = r < w and r[1] > w[1]",
            body.replace("\n   strategy.entry", "\n    strategy.entry"),
            'plot(b,"Weekly proof")',
            'plot(linear_reg,"Local proof")',
            'plot(buy?1:sell?-1:0,"Direction")',
            "",
        )
    )


def daily_supertrend(daily):
    upper, lower, trend, previous, atr = None, None, 1, None, None
    trs = []
    levels = []
    for _, o, h, low, c, vol in daily:
        tr = (
            max(h - low, abs(h - previous), abs(low - previous))
            if previous is not None
            else h - low
        )
        trs.append(tr)
        if len(trs) >= 3:
            atr = fsum(trs[-3:]) / 3 if atr is None else (2 * atr + tr) / 3
            up = (h + low) / 2 - 3 * atr
            down = (h + low) / 2 + 3 * atr
            state = trend
            if lower is not None and c > lower:
                state = 1
            elif upper is not None and c < upper:
                state = -1
            upper = max(up, upper) if upper is not None and previous > upper else up
            lower = min(down, lower) if lower is not None and previous < lower else down
            trend = state
            levels.append(upper if trend == 1 else lower)
        else:
            levels.append(None)
        previous = c
    return levels


def supertrend_values(payload):
    chart, daily = payload["chart"], payload["daily"]
    days = daily_supertrend(daily)
    market = [r[4] for r in chart]
    previous_day = [None if i < 12 else days[i // 12 - 1] for i in range(len(market))]
    fast = [None] * 6 + [fsum(market[i - 6 : i + 1]) / 7 for i in range(6, len(market))]
    slow = [None] * 19 + [
        fsum(market[i - 19 : i + 1]) / 20 for i in range(19, len(market))
    ]
    last_long = last_short = None
    curr = []
    bull = []
    bear = []
    long_exit = []
    short_exit = []
    for i, (price, filter_level) in enumerate(zip(market, previous_day, strict=True)):
        cross_down = cross_up = False
        if i >= 20:
            current = (round(fast[i], 9), round(slow[i], 9))
            prior = (round(fast[i - 1], 9), round(slow[i - 1], 9))
            cross_down = current[0] < current[1] and prior[0] > prior[1]
            cross_up = current[0] > current[1] and prior[0] < prior[1]
        if cross_down:
            last_long = i
        if cross_up:
            last_short = i
        center = (
            last_long - last_short
            if last_long is not None and last_short is not None
            else None
        )
        curr.append(center)
        bull.append(
            int(
                center is not None
                and center < 0
                and filter_level is not None
                and price >= filter_level
            )
        )
        bear.append(
            int(
                center is not None
                and center > 0
                and filter_level is not None
                and price <= filter_level
            )
        )
        long_exit.append(int(cross_down))
        short_exit.append(int(cross_up))
    return [previous_day, fast, slow, curr, bull, bear, long_exit, short_exit]


def ema_values(chart):
    close = [r[4] for r in chart]
    ema = exponential(close, 14)
    twice = exponential(ema, 14)
    now = [2 * f - s for f, s in zip(ema, twice, strict=True)]
    prior = [None, *now[:-1]]
    spreads = [
        current - previous for current, previous in zip(now[1:], prior[1:], strict=True)
    ]
    slow = [None, *exponential(spreads, 44)]
    fast = [None, *exponential(spreads, 72)]
    bull = [0, 0]
    bear = [0, 0]
    for before, after in pairwise(zip(slow[1:], fast[1:], strict=True)):
        x, y = (round(t, 9) for t in before)
        a, b = (round(t, 9) for t in after)
        bull.append(int(a > b and x < y))
        bear.append(int(a < b and x > y))
    return [now, prior, slow, fast, bull, bear]


def wma(values, size):
    result = []
    weight_total = size * (size + 1) / 2
    for i in range(1, len(values) + 1):
        chosen = values[i - size : i] if i >= size else ()
        result.append(
            fsum(x * j for j, x in enumerate(chosen, 1)) / weight_total
            if chosen and all(x is not None for x in chosen)
            else None
        )
    return result


def weekly_values(chart, weekly):
    periods = [bar[4] for bar in weekly]
    source = [
        None if slow is None else 3 * fast - middle - slow
        for fast, middle, slow in zip(
            *(wma(periods, n) for n in (4, 6, 12)), strict=True
        )
    ]
    hma = [None, *wma(source, 12)[:-1]]
    times = [bar[0] + W for bar in weekly]
    anchor = []
    for row in chart:
        next_index = bisect_right(times, row[0] + H4)
        anchor.append(hma[next_index - 1] if next_index else None)
    prices = [row[4] for row in chart]
    centered = [i - 49.5 for i in range(100)]
    denom = fsum(x * x for x in centered)
    local = [None] * 99
    for end in range(100, len(prices) + 1):
        window = prices[end - 100 : end]
        local.append(
            fsum(window) / 100
            + 49.5 * fsum(x * y for x, y in zip(centered, window, strict=True)) / denom
        )
    dirs = [0]
    for (x, y), (a, b) in pairwise(zip(local, anchor, strict=True)):
        if any(v is None for v in (x, y, a, b)):
            dirs.append(0)
        else:
            x, y, a, b = [round(v, 9) for v in (x, y, a, b)]
            dirs.append(1 if a > b and x < y else -1 if a < b and x > y else 0)
    return [anchor, local, dirs]


SPECS = {
    108: (
        "2h",
        "15m",
        120,
        "2023-08-09",
        "2023-09-08 00:00:00",
        "FMZ Pine · Native 2h · Confirmed daily Supertrend",
        supertrend_variant,
    ),
    351: (
        "4h",
        "15m",
        240,
        "2021-05-08",
        "2022-05-07 23:59:00",
        "FMZ Pine · Native 4h · Confirmed weekly Hull reference",
        weekly_variant,
    ),
    2434: (
        "2h",
        "15m",
        120,
        "2023-08-12",
        "2023-09-11 00:00:00",
        "FMZ Pine · Native 2h · Fixed-unit netting",
        ema_variant,
    ),
}


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
    _, originals = archival_items(archive, rows)
    cases = {}
    with ZipFile(archive) as source:
        for ident, row, doc, confirmed in documents(source, rows):
            text, digest, interval = originals[ident]
            frame, base, _, first, last, _, convert = SPECS[ident]
            fields = dict(
                re.findall(
                    r"(?m)^(start|end|period|basePeriod|exchanges):\s*([^\r\n]+)", doc
                )
            )
            assert digest == confirmed and interval == frame
            assert fields == {
                "start": f"{first} 00:00:00",
                "end": last,
                "period": frame,
                "basePeriod": base,
                "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
            }
            original, _ = strip_fmz_wrapper(text)
            code = original.replace("\r\n", "\n")
            active = re.sub(r"(?m)//[^\n]*", "", code)
            calls = re.findall(r"\bstrategy\.(entry|close|exit|order)\(", active)
            assert (
                calls
                == {
                    108: ["entry", "close", "entry", "close"],
                    351: ["entry", "entry"],
                    2434: ["order", "order"],
                }[ident]
            )
            cases[ident] = (
                row,
                digest,
                fields,
                original.encode(),
                convert(code).encode(),
            )
    return cases


def periods_for(ident):
    _, _, minutes, first, last, _, _ = SPECS[ident]
    width = minutes * 60_000
    begin, end = date_ms(first), date_ms(last) // width * width
    return (
        ("FMZ native window", begin, end),
        ("Next equal window", end, 2 * end - begin),
    )


def weekly_bars(chart_stream, start, stop):
    monday = MONDAY + (start - MONDAY) // W * W
    final = MONDAY + (stop - MONDAY) // W * W
    selected = [row for row in chart_stream if monday <= row[0] < final]
    assert [row[0] for row in selected] == list(range(monday, final, H4))
    return [list(row) for row in aggregate(selected, W // H4)]


def provider_cases(public, four_hour):
    manifest, feeds = [], {}
    current_months = ("2023-08", "2023-09", "2023-10")
    weekly_months = [
        f"{year}-{month:02}"
        for year in range(2021, 2024)
        for month in range(1, 13)
        if "2021-05" <= f"{year}-{month:02}" <= "2023-05"
    ]
    for market in MARKETS:
        streams = {}
        for interval, width, root, months in (
            ("2h", 120 * 60_000, public, current_months),
            ("1d", DAY, public, current_months),
            ("4h", H4, four_hour, weekly_months),
        ):
            archives = verified_archives(root, market, interval, months, manifest)
            streams[interval] = list(
                chain.from_iterable(provider_bars(file, width) for file in archives)
            )
        for ident, (frame, _, minutes, *_) in SPECS.items():
            for label, start, stop in periods_for(ident):
                chart = aligned(streams[frame], start, stop, minutes, minutes)
                assert chart[0][0] == start and chart[-1][0] + minutes * 60_000 == stop
                payload = {"chart": chart, "frame": str(minutes)}
                if ident == 108:
                    daily = aligned(streams["1d"], start, stop, 1440, 1440)
                    resampled = aligned(streams["2h"], start, stop, 1440, 120)
                    assert [row[:5] for row in daily] == [row[:5] for row in resampled]
                    payload["daily"] = daily
                if ident == 351:
                    payload["weekly"] = weekly_bars(streams["4h"], start, stop)
                feeds.setdefault(str(ident), {}).setdefault(label, {})[market] = payload
    return manifest, feeds


def stage(archive, baseline, public, four_hour, runtime, work):
    cases = archive_cases(archive, baseline)
    _, feeds = provider_cases(public, four_hour)
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
    copy2(Path(__file__).with_suffix(".mjs"), work / "run.mjs")
    for ident, (_, _, _, original, variant) in cases.items():
        (work / f"source-{ident}.pine").write_bytes(original)
        (work / f"variant-{ident}.pine").write_bytes(variant)
    write(work / "feeds.json", feeds)


def order_ledger(ident, witnesses):
    orders = []
    if ident == 2434:
        lots = deque()
        for i, (buy, sell) in enumerate(
            zip(witnesses[4][:-1], witnesses[5][:-1], strict=True), 1
        ):
            side = buy - sell
            if not side:
                continue
            if lots and lots[0][1] != side:
                entry, prev_side = lots.popleft()
                orders.append((entry, prev_side, i))
            else:
                lots.append((i, side))
        return orders, len(lots)

    if ident == 108:
        signal_rows = zip(
            *(witnesses[index][:-1] for index in (4, 6, 5, 7)), strict=True
        )
    else:
        signal_rows = (
            (direction == 1, False, direction == -1, False)
            for direction in witnesses[-1][:-1]
        )
    position, entry = 0, None
    for i, (buy, close_buy, sell, close_sell) in enumerate(signal_rows, 1):
        for active, enter, direction in (
            (buy, True, 1),
            (close_buy, False, 1),
            (sell, True, -1),
            (close_sell, False, -1),
        ):
            if not active:
                continue
            if enter and position != direction:
                if position:
                    orders.append((entry, position, i))
                position, entry = direction, i
            elif not enter and position == direction:
                orders.append((entry, position, i))
                position, entry = 0, None
    return orders, int(bool(position))


def verify_case(ident, case, payload):
    chart = payload["chart"]
    timeframe = {108: "D", 351: "W"}.get(ident)
    symbol = f"BINANCE:{case['market']}.P"
    requests = (
        [{"symbol": symbol, "timeframe": timeframe, "lowerTf": False}]
        if timeframe
        else []
    )
    assert case["requested"] == requests
    match ident:
        case 108:
            expected = supertrend_values(payload)
        case 351:
            expected = weekly_values(chart, payload["weekly"])
        case _:
            expected = ema_values(chart)
    for series, actual in zip(expected, case["witnesses"], strict=True):
        for x, y in zip(series, actual, strict=True):
            assert (
                x is None
                and y is None
                or x is not None
                and y is not None
                and isclose(x, y, rel_tol=1e-10, abs_tol=1e-8)
            )
    orders, unsettled = order_ledger(ident, expected)
    assert case["unsettled"] == unsettled and len(case["closed"]) == len(orders)
    times = [row[0] for row in chart]
    events = []
    for trade, (entry, side, exit_bar) in zip(case["closed"], orders, strict=True):
        assert (trade["entryBar"], trade["dir"], trade["exitBar"]) == (
            entry,
            side,
            exit_bar,
        )
        assert (trade["entryPrice"], trade["exitPrice"]) == (
            chart[entry][1],
            chart[exit_bar][1],
        )
        assert chart[entry][5] > 0 and chart[exit_bar][5] > 0
        qty = (
            1 if ident == 2434 else floor(CASH / chart[entry][1] / LOT_STEP) * LOT_STEP
        )
        assert isclose(trade["qty"], qty, rel_tol=1e-10)
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


def finalize(archive, baseline, public, four_hour, work, output):
    expected = archive_cases(archive, baseline)
    manifest, feeds = provider_cases(public, four_hour)
    assert read(work / "feeds.json") == feeds
    isolation = verify_runtime(work)
    receipts = read(work / "receipt.json")
    assert (
        len(receipts) == len(expected)
        and {entry["id"] for entry in receipts} == expected.keys()
    )
    rows, coverage, audits = [], [], {}
    for ident, (row, digest, fields, original, variant) in expected.items():
        source = work / f"source-{ident}.pine"
        normalized = work / f"variant-{ident}.pine"
        assert source.read_bytes() == original and normalized.read_bytes() == variant
        receipt = next(item for item in receipts if item["id"] == ident)
        assert receipt["sourceHash"] == sha256(source) and receipt[
            "variantHash"
        ] == sha256(normalized)
        by_window = {
            (item["period"], item["market"]): item for item in receipt["cases"]
        }
        assert len(by_window) == len(receipt["cases"]) == 4
        group = SPECS[ident][5]
        common = {
            "id": ident,
            "name": row["name"],
            "source": row["source"],
            "source_sha256": digest,
            "executed_source_sha256": receipt["variantHash"],
            "interval": fields["period"],
            "archive_interval": fields["period"],
            "quote_currency": "USDT",
            "group": group,
            "market_data": "Binance USD-M historical futures candles",
            "exit": {
                108: "Source SMA exit or reversal at next chart open",
                351: "Source reversal at next chart open",
                2434: "Original fixed-unit netting at next chart open",
            }[ident],
        }
        closes = 0
        for label, markets in feeds[str(ident)].items():
            pool, open_count = [], 0
            for market, payload in markets.items():
                case = by_window[(label, market)]
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
                closes += len(events)
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
        assert closes > 0
        coverage.append(
            [
                ident,
                f"Tested · {group}",
                "Verified archived timeframe, signal arithmetic, market-order sequencing, fills and fees on both execution backends.",
            ]
        )
        audits[ident] = {
            "archive_settings": fields,
            "source_document_sha256": digest,
            "windows_utc_ms": {
                label: [start, stop] for label, start, stop in periods_for(ident)
            },
            "closed": closes,
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
                for name in ("feeds.json", "run.mjs", "receipt.json")
            },
            "cost_model": {
                "fee_per_side": FEE,
                "execution_buffer_per_side": EXECUTION,
                "lot_step": LOT_STEP,
            },
            "references": [
                "https://www.fmz.com/doc/9293",
                "https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/",
                "https://www.tradingview.com/pine-script-docs/concepts/strategies/",
                "https://github.com/binance/binance-public-data",
            ],
            "method": [
                "Archived Bitcoin USD-M settings and ranges are preserved through the last complete chart bar. ETH uses a comparable USD-M perpetual on the same venue.",
                "BEST Supertrend uses previous completed daily input and the source-defined RMA true range, recursive levels, 2h SMA crossover-exits and market instruction order. Exchange daily OHLC was reconciled separately with its constituent 2h candles.",
                "Easy stock uses the original 4h least-squares endpoint and the source's default WMA-based weekly reference with one weekly bar offset and lookahead off. Complete UTC Monday weeks were aggregated from native 4h candles. Begin-week inputs include only original exchange bars.",
                "Cuathro EMA uses the original chart-equivalent default 120-minute request and both EMA gates. Its literal strategy.order unit was retained. Opposite orders reduce positions by one unit before any reversal, with FIFO matching.",
                "No fee or sizing change was inferred from inactive declarations. Fixed-unit #2434 retains larger possible BTC notional than the two cash-sized cases. Its figures use the same 10,000 USDT comparison capital and fee rates, with no separate margin simulation.",
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
    shared = "archive", "baseline", "public", "four_hour"
    for name, handler, arguments in (
        ("stage", stage, (*shared, "runtime", "work")),
        ("finalize", finalize, (*shared, "work", "output")),
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
