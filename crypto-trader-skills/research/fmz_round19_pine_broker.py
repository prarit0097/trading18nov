"""Reconcile Pine ABCD brackets and kNN equity sizing using provider subbars."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from collections import Counter, deque
from hashlib import sha512
from itertools import batched, chain, pairwise
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
from research.fmz_round7_pine import EXECUTION, FEE, PINER_PIN, PINER_VERSION, summarize
from research.fmz_round12_pine_authored import provider_bars
from research.fmz_round18_pine_qqe import executable_lines

CAPITAL = 10_000
MARKETS = ("BTCUSDT", "ETHUSDT")
CASES = {
    1666: ("2023-09-16", "2023-09-23", "2023-09-30", 45, 5, FEE, ("2023-09",)),
    2959: (
        "2023-11-07",
        "2023-12-07",
        "2024-01-06",
        60,
        15,
        0.002,
        ("2023-11", "2023-12", "2024-01"),
    ),
}
GROUPS = {
    1666: "FMZ Pine · Native 45m signals and 5m bracket fills",
    2959: "FMZ Pine · Native 1h kNN and 15m ATR protective fills",
}
EXITS = {
    1666: "Authored 20/100 USDT stop/target or reversal",
    2959: "Authored 2× ATR(7) stop, opposite signal market close or reversal",
}

ABCD_PINE = """//@version=5
strategy("BEST ABCD Pattern Strategy")
top=high[4]<high[2] and high[3]<=high[2] and high[2]>=high[1] and high[2]>high
bot=low[4]>low[2] and low[3]>=low[2] and low[2]<=low[1] and low[2]<low
topcount=ta.barssince(top)
botcount=ta.barssince(bot)
zigzag=top and topcount[1]>botcount[1]?high[2]:bot and topcount[1]<botcount[1]?low[2]:na
pivot=not na(zigzag) and zigzag!=0
a=ta.valuewhen(pivot,zigzag,3)
b=ta.valuewhen(pivot,zigzag,2)
c=ta.valuewhen(pivot,zigzag,1)
d=ta.valuewhen(pivot,zigzag,0)
abc=math.abs(b-c)/math.abs(a-b)
bcd=math.abs(c-d)/math.abs(b-c)
valid=abc>=0.382 and abc<=0.886 and bcd>=1.13 and bcd<=2.618
bull=valid and d<c
bear=valid and d>c
isLong=bull and not bull[1]
isShort=bear and not bear[1]
buyPrice=ta.valuewhen(isLong,close,0)
sellPrice=ta.valuewhen(isShort,close,0)
buyTrend=ta.barssince(isShort)>ta.barssince(isLong)
sellTrend=ta.barssince(isShort)<ta.barssince(isLong)
tp=buyTrend?buyPrice+100:sellPrice-100
sl=buyTrend?buyPrice-20:sellPrice+20
strategy.entry("Long",strategy.long,when=isLong)
strategy.exit("XL","Long",limit=tp,when=buyTrend,stop=sl)
strategy.entry("Short",strategy.short,when=isShort)
strategy.exit("XS","Short",limit=tp,when=sellTrend,stop=sl)
plot(zigzag,"Zigzag")
plot(isLong?1:0,"Long")
plot(isShort?1:0,"Short")
plot(buyTrend?1:0,"Buy trend")
plot(sellTrend?1:0,"Sell trend")
plot(tp,"Target")
plot(sl,"Stop")
plot(strategy.position_size,"Position")
"""


def abcd(chart):
    highs = [bar[2] for bar in chart]
    lows = [bar[3] for bar in chart]
    latest_top = latest_bot = None
    pivots = deque(maxlen=4)
    prior_bull = prior_bear = False
    long_signal = short_signal = None
    for i, bar in enumerate(chart):
        top = (
            i >= 4
            and highs[i - 4] < highs[i - 2] >= highs[i - 3]
            and highs[i - 2] >= highs[i - 1]
            and highs[i - 2] > highs[i]
        )
        bot = (
            i >= 4
            and lows[i - 4] > lows[i - 2] <= lows[i - 3]
            and lows[i - 2] <= lows[i - 1]
            and lows[i - 2] < lows[i]
        )
        zigzag = None
        if latest_top is not None and latest_bot is not None:
            if top and latest_top < latest_bot:
                zigzag = highs[i - 2]
            elif bot and latest_top > latest_bot:
                zigzag = lows[i - 2]
        if top:
            latest_top = i
        if bot:
            latest_bot = i
        if zigzag:
            pivots.append(zigzag)
        bull = bear = False
        if len(pivots) == 4:
            a, b, c, d = pivots
            ab, bc, cd = abs(a - b), abs(b - c), abs(c - d)
            valid = bool(
                ab and bc and 0.382 <= bc / ab <= 0.886 and 1.13 <= cd / bc <= 2.618
            )
            bull = valid and d < c
            bear = valid and d > c
        enter_long = bull and not prior_bull
        enter_short = bear and not prior_bear
        prior_bull, prior_bear = bull, bear
        if enter_long:
            long_signal = (i, bar[4])
        if enter_short:
            short_signal = (i, bar[4])
        buy = sell = False
        if long_signal is not None and short_signal is not None:
            buy = long_signal[0] > short_signal[0]
            sell = not buy
        tp = (
            long_signal[1] + 100
            if buy
            else short_signal[1] - 100
            if short_signal
            else None
        )
        sl = (
            long_signal[1] - 20
            if buy
            else short_signal[1] + 20
            if short_signal
            else None
        )
        yield zigzag, enter_long, enter_short, buy, sell, tp, sl


def average_wilder(values, length):
    vals = []
    val = None
    for item in values:
        if item is None:
            yield None
            continue
        vals.append(item)
        if val is None and len(vals) == length:
            val = fsum(vals) / length
        elif val is not None:
            val = (val * (length - 1) + item) / length
        yield val


def relative_strength(px, length):
    changes = [None] + [b - a for a, b in pairwise(px)]
    up = average_wilder([None if d is None else max(0, d) for d in changes], length)
    dn = average_wilder([None if d is None else max(0, -d) for d in changes], length)
    return [
        None if u is None else 100 if d == 0 else 100 - (100 / (1 + u / d))
        for u, d in zip(up, dn, strict=True)
    ]


def volatility(chart):
    return list(
        average_wilder(
            [
                bar[2] - bar[3]
                if i == 0
                else max(
                    bar[2] - bar[3],
                    abs(bar[2] - chart[i - 1][4]),
                    abs(bar[3] - chart[i - 1][4]),
                )
                for i, bar in enumerate(chart)
            ],
            7,
        )
    )


def knn(chart):
    px = [b[4] for b in chart]
    averages = volatility(chart)
    rr = relative_strength(px, 29)
    rf = relative_strength(px, 8)
    prediction_set = deque(maxlen=20)
    training = []
    prior = 0
    for i, (a, b) in enumerate(zip(rr, rf, strict=True)):
        direction = (px[i - 1] > px[i]) - (px[i - 1] < px[i]) if i else 0
        if a is not None and b is not None:
            training.append((a, b, direction))
            farthest = -999.0
            for x, y, d in training:
                dist = ((a - x) ** 2 + (b - y) ** 2) ** 0.5
                if dist > farthest:
                    farthest = dist
                    prediction_set.append(d)
        prediction = sum(prediction_set)
        signal = (prediction > 0) - (prediction < 0)
        start_long = signal == 1 and prior != signal
        start_short = signal == -1 and prior != signal
        basis = fsum(px[i - 39 : i + 1]) / 40 if i >= 39 else None
        long = start_long and basis is not None and px[i] > basis
        short = start_short and basis is not None and px[i] < basis
        prior = signal
        yield (
            prediction if prediction_set else None,
            signal,
            long,
            short,
            start_short,
            start_long,
            averages[i],
        )


def brackets(chart, lower, signals):
    barsize = (chart[1][0] - chart[0][0]) // (lower[1][0] - lower[0][0])
    market = 0
    bracket = None
    trade = None
    done = []
    poses = []
    for i, (bar, signal) in enumerate(zip(chart, signals, strict=True)):
        if market and (trade is None or trade[0] != market):
            if trade:
                done.append((*trade, i, bar[1], "reversal", bar[0]))
            trade = (market, i, bar[1])
        market = 0
        if trade and bracket and bracket[0] == trade[0]:
            side, target, stop = bracket
            for t, op, hi, lo, _, _ in lower[i * barsize : (i + 1) * barsize]:
                st = lo <= stop if side == 1 else hi >= stop
                lim = hi >= target if side == 1 else lo <= target
                gapst = op <= stop if side == 1 else op >= stop
                gaplim = op >= target if side == 1 else op <= target
                assert not (st and lim and not (gapst or gaplim)), (
                    i,
                    t,
                    trade,
                    bracket,
                )
                if st or lim:
                    if gapst:
                        price, tag = op, "stop gap"
                    elif gaplim:
                        price, tag = op, "target gap"
                    elif st:
                        price, tag = stop, "stop"
                    else:
                        price, tag = target, "target"
                    done.append((*trade, i, price, tag, t))
                    trade = None
                    bracket = None
                    break
        poses.append(trade[0] if trade else 0)
        _, long, short, buy, sell, tp, sl = signal
        if long or short:
            market = 1 if long else -1
        if buy and (market == 1 or trade and trade[0] == 1):
            bracket = 1, tp, sl
        elif sell and (market == -1 or trade and trade[0] == -1):
            bracket = -1, tp, sl
    return done, poses, trade


def equal(x, y):
    return (
        (x is None and y is None)
        or x is not None
        and y is not None
        and isclose(x, y, rel_tol=1e-9, abs_tol=1e-9)
    )


def risk_ledger(chart, lower, signals):
    rate = CASES[2959][5]
    ratio = (chart[1][0] - chart[0][0]) // (lower[1][0] - lower[0][0])
    market = None
    market_exit = 0
    stop = None
    trade = None
    done = []
    state = []
    cash = CAPITAL
    prior = 0
    long_stop = short_stop = None
    for idx, (bar, micro, inp) in enumerate(
        zip(chart, batched(lower, ratio), signals, strict=True)
    ):
        _, _, enter_long, enter_short, shifts_short, shifts_long, atr = inp
        dir = trade[0] if trade else 0
        market_dir = market[0] if market else 0

        def settle(price, t, why, exit_bar):
            nonlocal trade, cash, stop
            side, i, price_in, qty = trade
            gross = side * qty * (price - price_in)
            fee = rate * price * qty
            cash += gross - fee
            done.append((side, i, price_in, exit_bar, price, qty, why, t))
            trade = None
            stop = None

        if dir and ((market_dir and market_dir != dir) or dir == market_exit):
            settle(bar[1], bar[0], "reversal" if market_dir else "signal close", idx)
        if market and trade is None:
            trade = market[0], idx, bar[1], market[1]
            cash -= bar[1] * market[1] * rate
        market = None
        market_exit = 0
        if trade and stop is not None:
            for t, o, h, l, _, _ in micro:
                side = trade[0]
                if side == 1 and l <= stop or side == -1 and h >= stop:
                    px = min(o, stop) if side == 1 else max(o, stop)
                    settle(px, t, "stop gap" if px != stop else "stop", idx)
                    break
        side, _, price, qty = trade if trade else (0, 0, 0, 0)
        pos = side * qty
        eq = cash + pos * (bar[4] - price)
        if pos != prior:
            long_stop = price - atr * 2 if trade else None
            short_stop = price + atr * 2 if trade else None
            stop = long_stop if pos > 0 else short_stop
        state.append(
            (pos, eq, long_stop, short_stop, price if trade else None, int(bool(trade)))
        )
        if enter_long or enter_short:
            market = (1 if enter_long else -1, eq * 0.02 / (2 * atr))
        if trade and ((side == 1 and shifts_short) or (side == -1 and shifts_long)):
            market_exit = side
        prior = pos
    return done, state, trade


def source_variant(ident, source):
    active = executable_lines(source)
    active_text = "\n".join(active)
    if ident == 1666:
        for witness in (
            'filterBW = input(false, title="filter Bill Williams Fractals?")',
            "_r = timeframe.period",
            "lapos_x = timenow + round(change(time)*12)",
            "filteredtopf = filterBW ? isRegularFractal(1, _high, _low) : isBWFractal(1, _high, _low)",
            "filteredbotf = filterBW ? isRegularFractal(-1, _high, _low) : isBWFractal(-1, _high, _low)",
            "ret = mode == 1 ? _high[4] < _high[2] and _high[3] <= _high[2] and _high[2] >= _high[1] and _high[2] > _high[0] :",
            "mode == -1 ? _low[4] > _low[2] and _low[3] >= _low[2] and _low[2] <= _low[1] and _low[2] < _low[0] : false",
            "zigzag = (istop and topcount[1] > botcount[1] ? _high[2] :",
            "isbot and topcount[1] < botcount[1] ? _low[2] : na)",
            "_abc = abc >= 0.382 and abc <= 0.886",
            "_bcd = bcd >= 1.13 and bcd <= 2.618",
            'input(100, "Backtest Profit Goal (in USD)",minval=0)*fx_pips_value',
            'input(20, "Backtest STOP Goal (in USD)",minval=0)*fx_pips_value',
            'strategy.entry("Long", 1, when=isLong)',
            'strategy.entry("Short", 0,  when=isShort)',
            'strategy.exit("XL","Long", limit=tp,  when=buy_trend, stop=sl)',
            'strategy.exit("XS","Short", when=sell_trend, limit=tp, stop=sl)',
        ):
            assert witness in active_text, witness
        assert active_text.count("lapos_x") == 1
        assert not re.search(
            r"\b(?:strategy\(|request\.security\(|import )", active_text
        )
        return ABCD_PINE
    for witness in (
        "pyramiding=1, commission_type=strategy.commission.percent, commission_value=0.2, initial_capital=10000",
        "inTradeWindow = true",
        "bool window = true",
        "if d > maxdist",
        "maxdist := d",
        "array.shift(predictions)",
        "math.floor(math.sqrt(BaseK))",
        "prediction := array.sum(predictions)",
        "class_label = int(math.sign(close[1] - close[0]))",
        "Filter     = input.bool  (false",
        "Indicator  = input.string('RSI'",
        "ShortWinow = input.int   (8,",
        "LongWindow = input.int   (29,",
        "BaseK      = input.int   (400,",
        'defval="SMA", group="MA Inputs"',
        'input.int(defval=40, title="MA Length"',
        'input(close, title="MA Source"',
        "LongPositions   = input.bool(title='On/Off Long Postion', defval=true",
        "ShortPositions  = input.bool(title='On/Off Short Postion', defval=true",
        "MAFilter        = input.bool(title='Use MA as Filter', defval=true",
        'input.int(7, "ATR Length"',
        'input.float(2, title="% of Equity at Risk"',
        "sl := lastEntryPrice - (_atr * sl_atr_multiplier)",
        "sl_short := lastEntryPrice + (_atr * sl_atr_multiplier_short)",
        'sl_atr_multiplier        = input.float(title="Long Position - Stop Loss - ATR Multiplier", defval=2,',
        'sl_atr_multiplier_short  = input.float(title="Short Position - Stop Loss - ATR Multiplier", defval=2,',
    ):
        assert witness in active_text, witness
    source = source.replace("\r\n", "\n")
    atr_filter = "bool filter = Filter ? ta.atr(10) > ta.atr(40) : true"
    assert source.count(atr_filter) == 1
    source = source.replace(atr_filter, "bool filter = true")
    left = source.index("MovAvgType1(averageType1, averageSource1, averageLength1) =>")
    right = source.index("ma_plot = ", left)
    source = source[:left] + "ma = ta.sma(close, 40)\n" + source[right:]
    for side in ("Long", "Short"):
        action = f'    strategy.close("{side}", when = ({side.lower()}_exit), comment="Close {side}")'
        assert source.count(action) == 1
        explicit = f'    if {side.lower()}_exit\n        strategy.close("{side}", comment="Close {side}")'
        source = source.replace(action, explicit)
    return (
        source
        + """
plot(prediction,"Prediction")
plot(signal,"Signal")
plot(long_entry?1:0,"Long")
plot(short_entry?1:0,"Short")
plot(long_exit?1:0,"Long close")
plot(short_exit?1:0,"Short close")
plot(_atr,"ATR")
plot(strategy.position_size,"Position")
plot(strategy.equity,"Equity")
plot(sl,"Long stop")
plot(sl_short,"Short stop")
plot(lastEntryPrice,"Last entry price")
plot(strategy.opentrades,"Open count")
"""
    )


def archived_sources(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    pending = {
        r["id"]: r
        for r in read(baseline)["disposition"]
        if r["status"].startswith("Pending")
    }
    sources = {}
    with ZipFile(archive) as source:
        for ident, row, document, digest in documents(
            source, {i: pending[i] for i in CASES}
        ):
            (fenced,) = re.findall(
                r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", document
            )
            start, end, _, frame, base, _, _ = CASES[ident]
            settings = dict(
                re.findall(
                    r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)",
                    fenced,
                )
            )
            assert settings == {
                "start": f"{start} 00:00:00",
                "end": f"{end} 00:00:00",
                "period": "1h" if frame == 60 else f"{frame}m",
                "basePeriod": f"{base}m",
                "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
            }
            assert f"@version={4 if ident == 1666 else 5}" in fenced
            code = re.sub(r"(?ms)^/\*backtest\r?\n.*?^\*/\r?\n", "", fenced, count=1)
            sources[ident] = (
                row,
                digest,
                settings,
                code.encode(),
                source_variant(ident, code).encode(),
            )
    return sources


def provider_cases(abcd_public, knn_public):
    manifests, feeds = {}, {}
    for ident, (start, end, forward, frame, base, _, months) in CASES.items():
        public = abcd_public if ident == 1666 else knn_public
        manifest = manifests[ident] = []
        cases = feeds[str(ident)] = {}
        step = base * 60_000
        for market in MARKETS:
            files = verified_archives(public, market, f"{base}m", months, manifest)
            stream = list(
                chain.from_iterable(provider_bars(path, step) for path in files)
            )
            for label, beg, fin in (
                ("FMZ native window", start, end),
                ("Next equal window", end, forward),
            ):
                low, high = date_ms(beg), date_ms(fin)
                subbars = [bar for bar in stream if low <= bar[0] < high]
                assert [bar[0] for bar in subbars] == list(range(low, high, step))
                chart = aggregate(subbars, frame // base)
                cases.setdefault(label, {})[market] = {
                    "chart": [list(bar) for bar in chart],
                    "lower": [list(bar) for bar in subbars],
                    "frame": str(frame),
                }
    return manifests, feeds


def stage(archive, baseline, abcd_public, knn_public, work):
    sources = archived_sources(archive, baseline)
    _, feeds = provider_cases(abcd_public, knn_public)
    for ident, (_, _, _, source, variant) in sources.items():
        (work / f"broker-source-{ident}.pine").write_bytes(source)
        (work / f"broker-variant-{ident}.pine").write_bytes(variant)
    copy2(Path(__file__).with_suffix(".mjs"), work / "fractal-knn-run.mjs")
    write(work / "fractal-knn-feeds.json", feeds)


def runtime_attestation(work):
    assert (work / "fractal-knn-run.exit").read_text().strip() == "0"
    assert (work / "fractal-knn-run.mjs").read_bytes() == Path(__file__).with_suffix(
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


def reconcile(ident, case, payload):
    chart, base = payload["chart"], payload["lower"]
    assert not case["requested"]
    if ident == 1666:
        signals = list(abcd(chart))
        ledger, positions, unsettled = brackets(chart, base, signals)
        series = [(*s, p) for s, p in zip(signals, positions, strict=True)]
        observed = case["witnesses"]
        fills = [(d, i, p, j, o, 1, kind, t) for d, i, p, j, o, kind, t in ledger]
    else:
        signals = list(knn(chart))
        fills, positions, unsettled = risk_ledger(chart, base, signals)
        observed = case["witnesses"]
        assert len(observed) == 13
        series = [
            (*signal, *state) for signal, state in zip(signals, positions, strict=True)
        ]
    assert len(observed) == len(series[0])
    checked = 0
    for i, (truth, actual) in enumerate(
        zip(series, zip(*observed, strict=True), strict=True)
    ):
        for j, (expected, value) in enumerate(zip(truth, actual, strict=True)):
            assert equal(expected, value), (ident, i, j, expected, value)
            checked += 1
    assert int(unsettled is not None) == case["unsettled"]
    fee = CASES[ident][5]
    events, by_kind = [], Counter()
    cumulative = 0.0
    for (side, entry_bar, entry, exit_bar, exit_price, qty, kind, t), closed in zip(
        fills, case["closed"], strict=True
    ):
        assert (side, entry_bar, exit_bar, "Long" if side > 0 else "Short") == (
            closed["dir"],
            closed["entryBar"],
            closed["exitBar"],
            closed["entryId"],
        )
        assert all(
            equal(x, y)
            for x, y in (
                (entry, closed["entryPrice"]),
                (exit_price, closed["exitPrice"]),
                (qty, closed["qty"]),
            )
        )
        assert (
            chart[entry_bar][0]
            == closed["entryTime"]
            <= closed["exitTime"]
            == chart[exit_bar][0]
            <= t
        )
        assert chart[entry_bar][5] > 0 and chart[exit_bar][5] > 0
        notional = qty * (entry + exit_price)
        gross, fees = side * qty * (exit_price - entry), notional * fee
        cumulative += gross - fees
        assert equal(closed["commission"], fees)
        assert equal(closed["profit"], gross - fees)
        assert equal(closed["cumProfit"], cumulative)
        events.append((t, gross, fees, notional * EXECUTION))
        by_kind[kind] += 1
    return events, {
        "witnesses_checked": checked,
        "chart_bars": len(chart),
        "subbars": len(base),
        "closed": len(events),
        "open_at_cutoff": case["unsettled"],
        "exit_types": dict(by_kind),
    }


METHOD = {
    1666: [
        "Uses the archived default Williams fractals and consecutive alternating pivots. Historical chart marks may draw two bars back, but orders wait for the five-candle fractal to close. ABC and BCD ratio edges, latest signal prices, reversal, and the exact 20/100 quoted-price bracket match independently on all windows.",
        "FMZ permits an omitted Pine declaration. The source's commented strategy declaration is inactive, and timenow only assigns an unused visual coordinate. A unit-size research broker uses a one-base-unit order, 10,000 USDT accounting base and 0.059% per side because the archive omitted broker sizing and fees. Those settings allow unit-P&L comparison.",
        "Market entries and reversals fill at the next 45-minute open. Active protective brackets process the original five-minute bars in chronological order, using the first observed gap price or the bracket level. No relevant five-minute subbar crosses both stop and target without a decisive opening quote.",
    ],
    2959: [
        "Uses the archived default RSI(29/8), persistent 20-label array, increasing-distance scan, classifier signs, SMA(40), ATR(7), dynamic 2% equity risk sizing and 2×ATR stops. The archived source appends the current known observation and its backward return label. The independent implementation preserves the scan and the persistent FIFO exactly.",
        "The archived false volatility filter and SMA selection are specialized to their exact active defaults. The optional legacy when guards on strategy.close become explicitly equivalent conditional blocks because the Piner raw close dispatch ignored those named guards in a witnessed historical case.",
        "The authored 0.20% commission per fill affects equity and subsequent sizes. Both Pine backends and the independent 15-minute broker agree on every filled quantity, price and signal/bar timing. The independent check recalculates floating position equity, entry-price-based ATR stops and realized P&L.",
    ],
}


def report(archive, baseline, abcd_public, knn_public, work, output, ident):
    sources = archived_sources(archive, baseline)
    manifests, feeds = provider_cases(abcd_public, knn_public)
    assert feeds == read(work / "fractal-knn-feeds.json")
    isolation = runtime_attestation(work)
    (receipt,) = [
        row for row in read(work / "fractal-knn-receipt.json") if row["id"] == ident
    ]
    assert "error" not in receipt
    row, digest, settings, source, variant = sources[ident]
    raw = work / f"broker-source-{ident}.pine"
    executed = work / f"broker-variant-{ident}.pine"
    assert raw.read_bytes() == source and sha256(raw) == receipt["sourceHash"]
    assert (
        executed.read_bytes() == variant and sha256(executed) == receipt["variantHash"]
    )
    _, _, _, frame, base, fee, _ = CASES[ident]
    assert receipt["model"]["initialCapital"] == CAPITAL
    assert equal(receipt["model"]["commissionValue"] / 100, fee)
    cases = {(c["period"], c["market"]): c for c in receipt["cases"]}
    assert len(cases) == len(receipt["cases"]) == 4
    common = {
        "id": ident,
        "name": row["name"],
        "source": row["source"],
        "source_sha256": digest,
        "executed_source_sha256": receipt["variantHash"],
        "interval": settings["period"],
        "archive_interval": f"{base}m",
        "quote_currency": "USDT",
        "market_data": f"Official Binance USD-M {base}m candles aggregated into {frame}m bars",
        "group": GROUPS[ident],
        "exit": EXITS[ident],
    }
    results, counts = [], []
    for label, markets in feeds[str(ident)].items():
        combined, opened = [], 0
        for market, payload in markets.items():
            case = cases[(label, market)]
            cashflows, proof = reconcile(ident, case, payload)
            results.append(
                {
                    **common,
                    "period": label,
                    "market": market,
                    **summarize(cashflows, case["unsettled"], CAPITAL),
                }
            )
            combined.extend(cashflows)
            opened += case["unsettled"]
            counts.append({"period": label, "market": market, **proof})
        results.append(
            {
                **common,
                "period": label,
                "market": "BTCUSDT + ETHUSDT",
                **summarize(combined, opened, 2 * CAPITAL),
            }
        )
    closed = sum(item["closed"] for item in counts)
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(baseline),
            "archive_sha256": FMZ_SHA256,
            "isolation_probe": isolation,
            "published_binance_candles": manifests[ident],
            "piner_version": PINER_VERSION,
            "piner_tarball_sha512": PINER_PIN,
            "artifacts": {
                name: sha256(work / name)
                for name in (
                    "fractal-knn-feeds.json",
                    "fractal-knn-run.mjs",
                    "fractal-knn-receipt.json",
                )
            },
            "cost_model": {"fee_per_side": fee, "execution_buffer_per_side": EXECUTION},
            "references": [
                "https://www.fmz.com/doc/9293",
                "https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-6/#removal-of-when-parameter",
                "https://www.tradingview.com/pine-script-docs/concepts/strategies/",
                "https://github.com/binance/binance-public-data",
            ],
            "method": [
                *METHOD[ident],
                "BTC preserves the archived Binance Futures source market and historical window. ETH uses its own same-venue OHLCV. Each next equal-length window resets all strategy state. Metrics use chronological realized closes and preserve terminal open trades without artificial settlement.",
                "Gross and after-fee P&L use independently reconciled fills. The workbook net column deducts the separately labelled 0.03% per fill standardized execution buffer. That comparison buffer is not an observed fill cost or an extra modeled change to the original signals.",
            ],
            "source_audits": {
                ident: {
                    "archive_settings": settings,
                    "source_document_sha256": digest,
                    "closed": closed,
                }
            },
            "per_case_order_counts": counts,
            "coverage": [
                [
                    ident,
                    f"Tested · {GROUPS[ident]}",
                    "Archived default order logic, native BTC historical window, provider subbar fill sequence, and gross/fee-adjusted cashflows independently reconciled.",
                ]
            ],
            "results": results,
        },
    )
    print(f"ID {ident}: {closed} closed positions, {len(results)} workbook rows.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, handler in (("stage", stage), ("finalize", report)):
        cmd = commands.add_parser(name)
        for arg in ("archive", "baseline", "abcd_public", "knn_public", "work"):
            cmd.add_argument(arg, type=Path)
        if name == "finalize":
            cmd.add_argument("output", type=Path)
            cmd.add_argument("ident", type=int, choices=CASES)
        cmd.set_defaults(handler=handler)
    settings = vars(parser.parse_args())
    settings.pop("command")
    settings.pop("handler")(**settings)


if __name__ == "__main__":
    main()
