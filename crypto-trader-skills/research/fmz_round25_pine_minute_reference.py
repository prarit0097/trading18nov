"""Reconcile two lower-timeframe Pine strategies with causal lot sizing and bracket fills."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from collections import Counter, deque
from hashlib import sha512
from itertools import batched
from math import floor, fsum
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
from research.fmz_round19_pine_broker import equal, relative_strength

STEP = 0.001
DAY = 86_400_000
MINUTE = 60_000
HOUR = 3_600_000
SPECS = {
    1586: ("2023-11-12", "2023-12-12", ("2023-11", "2023-12", "2024-01"), 1000),
    2751: ("2023-09-06", "2023-10-06", ("2023-09", "2023-10", "2023-11"), 1_000_000),
}
GROUPS = {
    1586: "FMZ Pine · Hourly DMA · Causal pyramided sizes",
    2751: "FMZ Pine · Hourly MACD with 1m signals and verified brackets",
}

PINE_1586 = """//@version=5
strategy("DRSI DMA Scalping Strategy",shorttitle="DRSIDMA",overlay=false,initial_capital=1000,pyramiding=2,default_qty_type=strategy.percent_of_equity,default_qty_value=100)
avgSlope() =>
    a=ta.ema(close,5)
    b=ta.ema(a,5)
    c=ta.ema(b,5)
    tema=3*(a-b)+c
    ta.sma(tema/tema[3]-1,5)
validAverage(v,length) =>
    var values=array.new_float(0)
    if not na(v)
        array.push(values,v)
        if array.size(values)>length
            array.shift(values)
    array.size(values)==length?array.avg(values):na
momSlope() =>
    mom=ta.rsi(ta.roc(close,3),3)
    ratio=mom[8]==0?na:mom/mom[8]-1
    validAverage(ratio,7)
mAvg=request.security(syminfo.tickerid,"1",avgSlope(),lookahead=barmerge.lookahead_off)*130
mMom=request.security(syminfo.tickerid,"1",momSlope(),lookahead=barmerge.lookahead_off)
chartAvg=ta.sma(close,28)
v=ta.sma((1-low/high)*100,10)
badVol=v<2.5
quietDown=chartAvg[3]-chartAvg[1]>.05
quietUp=chartAvg[3]-chartAvg[1]<-.05
long=badVol?quietUp:mAvg>.02 and mMom>.02
short=badVol?quietDown:mAvg<-.03 and mMom<-.03
if long
    strategy.entry("Buy",strategy.long)
if short
    strategy.entry("Sell",strategy.short)
plot(mAvg,"Minute TEMA slope")
plot(mMom,"Minute RSI slope")
plot(v,"Volatility")
plot(chartAvg,"Quiet mode average")
plot(badVol?1:0,"Quiet")
plot(long?1:0,"Long")
plot(short?1:0,"Short")
plot(strategy.position_size,"Position")
plot(strategy.equity,"Equity")
"""

PINE_2751 = """//@version=5
strategy("5 Minute Scalp",overlay=true,margin_long=100,margin_short=100)
macdHistogram() =>
    wave=ta.ema(close,12)-ta.ema(close,26)
    wave-ta.ema(wave,9)
ref=request.security(syminfo.tickerid,"1",macdHistogram(),lookahead=barmerge.lookahead_off)
highBand=ta.sma(ref,83)+2*ta.stdev(ref,83)
lowBand=ta.sma(ref,94)-2*ta.stdev(ref,94)
e9=ta.ema(close,9)
e50=ta.ema(close,50)
e200=ta.ema(close,200)
r11=ta.rsi(close,11)
r29=ta.rsi(close,29)
goLong=ref<=lowBand and e9>e50 and e50>e200 and r11>=51 and ref<=-10
goShort=ref>=highBand and e9<e50 and e50<e200 and r29<=49 and ref>=35
if goLong
    strategy.entry("Long",strategy.long)
if strategy.position_size>0
    strategy.exit("close long","Long",stop=strategy.position_avg_price*.997,limit=strategy.position_avg_price*1.005)
if goShort
    strategy.entry("short ",strategy.short)
if strategy.position_size<0
    strategy.exit("close short",stop=strategy.position_avg_price*1.003,limit=strategy.position_avg_price*.995)
plot(ref,"Minute histogram")
plot(highBand,"Upper")
plot(lowBand,"Lower")
plot(e9,"EMA9")
plot(e50,"EMA50")
plot(e200,"EMA200")
plot(r11,"RSI11")
plot(r29,"RSI29")
plot(goLong?1:0,"Long")
plot(goShort?1:0,"Short")
plot(strategy.position_size,"Position")
"""


def exponential(values, n):
    result = None
    for x in values:
        if x is not None:
            result = x if result is None else (x * 2 + result * (n - 1)) / (n + 1)
        yield result


def rolling(values, n, fn):
    history = deque(maxlen=n)
    for x in values:
        if x is not None:
            history.append(x)
        yield fn(history) if len(history) == n else None


def minute_rows(payload):
    chart, sub = payload["chart"], payload["reference"]
    index = {row[0]: i for i, row in enumerate(sub)}
    select = [index[bar[0] + 59 * 60_000] for bar in chart]
    return chart, sub, select


def relative_change(values, start, n):
    return [
        None if i < n or v is None or not values[i - n] else v / values[i - n] - start
        for i, v in enumerate(values)
    ]


def signals_dma(payload):
    chart, lower, last = minute_rows(payload)
    close = [r[4] for r in lower]
    ea = list(exponential(close, 5))
    eb = list(exponential(ea, 5))
    ec = list(exponential(eb, 5))
    tema = [3 * (a - b) + c for a, b, c in zip(ea, eb, ec, strict=True)]
    avg = list(rolling(relative_change(tema, 1, 3), 5, lambda a: fsum(a) / 5))
    roc = [r * 100 for r in relative_change(close, 1, 3)[3:]]
    rsi = [None] * 3 + relative_strength(roc, 3)
    mom = list(rolling(relative_change(rsi, 1, 8), 7, lambda a: fsum(a) / 7))
    vol = list(
        rolling([(1 - r[3] / r[2]) * 100 for r in chart], 10, lambda a: fsum(a) / 10)
    )
    calm = list(rolling([r[4] for r in chart], 28, lambda a: fsum(a) / 28))
    for i, j in enumerate(last):
        ma, mo = avg[j] * 130, mom[j]
        quiet = vol[i] is not None and vol[i] < 2.5
        delta = (
            calm[i - 3] - calm[i - 1] if i >= 3 and calm[i - 3] is not None else None
        )
        buy = (
            (delta is not None and delta < -0.05)
            if quiet
            else ma > 0.02 and mo is not None and mo > 0.02
        )
        sell = (
            (delta is not None and delta > 0.05)
            if quiet
            else ma < -0.03 and mo is not None and mo < -0.03
        )
        yield ma, mo, vol[i], calm[i], quiet, buy, sell


def signals_macd(payload):
    chart, lower, last = minute_rows(payload)
    sub = [r[4] for r in lower]
    wave = [
        a - b for a, b in zip(exponential(sub, 12), exponential(sub, 26), strict=True)
    ]
    hist = [a - b for a, b in zip(wave, exponential(wave, 9), strict=True)]
    gathered = [hist[i] for i in last]
    hi = list(rolling(gathered, 83, lambda v: fsum(v) / 83 + 2 * pstdev(v)))
    lo = list(rolling(gathered, 94, lambda v: fsum(v) / 94 - 2 * pstdev(v)))
    close = [r[4] for r in chart]
    r11, r29 = (relative_strength(close, n) for n in (11, 29))
    for i, (one, two, three) in enumerate(
        zip(*(exponential(close, n) for n in (9, 50, 200)), strict=True)
    ):
        signal = gathered[i]
        buy = (
            lo[i] is not None
            and signal <= lo[i]
            and one > two > three
            and r11[i] >= 51
            and signal <= -10
        )
        sell = (
            hi[i] is not None
            and signal >= hi[i]
            and one < two < three
            and r29[i] <= 49
            and signal >= 35
        )
        yield signal, hi[i], lo[i], one, two, three, r11[i], r29[i], buy, sell


def dma_broker(chart, signals, fee, mode):
    cash = 1000.0
    side = 0
    lots = []
    desired = 0
    fills = []
    poss = []
    opens = []
    for i, (bar, signal) in enumerate(zip(chart, signals, strict=True)):
        _, op, _, _, close, _ = bar
        if desired:
            equity = cash + side * fsum((op - entry) * qty for _, entry, qty in lots)
            if side and side != desired:
                for j, entry, qty in lots:
                    cash += side * qty * (op - entry) - fee * qty * op
                    fills.append((side, qty, j, entry, i, op))
                lots = []
                side = 0
            if len(lots) < 2:
                if mode == "causal":
                    # The v4 broker sizes the incoming order before settling the reversal.
                    budget = float(f"{equity:.9e}") / (1 + fee)
                else:
                    # Piner exposes a current-bar close for open-time percentage sizing.
                    budget = cash + side * fsum(
                        (close - entry) * qty for _, entry, qty in lots
                    )
                qty = floor(budget / op / STEP + 1e-9) * STEP
                if qty > 0:
                    cash -= fee * op * qty
                    lots.append((i, op, qty))
                    opens.append((desired, qty, i, op))
                    side = desired
        poss.append(
            (
                side * sum(qty for _, _, qty in lots),
                cash + side * sum(qty * (close - pr) for _, pr, qty in lots),
            )
        )
        a, b = signal[-2:]
        assert not (a and b)
        desired = 1 if a else -1 if b else 0
    return fills, poss, lots, opens


def broker_macd(chart, sub, signals):
    first = chart[0][0]
    sub = [r for r in sub if r[0] >= first]
    side = 0
    held = None
    bracket = None
    desired = 0
    fills = []
    position = []
    for i, (bar, tape, signal) in enumerate(
        zip(chart, batched(sub, 60), signals, strict=True)
    ):
        ts, op, _, _, _, _ = bar
        if desired and desired != side:
            if side:
                entry_idx, entry = held
                fills.append((side, entry_idx, entry, i, op, "reversal", ts))
            side = desired
            held = (i, op)
            bracket = None
        if side and bracket:
            target, stop = bracket
            for t, o, h, l, _, _ in tape:
                stop_gap = side * (stop - o) >= 0
                target_gap = side * (o - target) >= 0
                hit_stop = l <= stop if side > 0 else h >= stop
                hit_take = h >= target if side > 0 else l <= target
                assert not (hit_stop and hit_take and not (stop_gap or target_gap)), (
                    side,
                    t,
                    o,
                    h,
                    l,
                    target,
                    stop,
                )
                if hit_stop or hit_take:
                    out, kind = (
                        (o, "stop gap")
                        if stop_gap
                        else (o, "take gap")
                        if target_gap
                        else (stop, "stop")
                        if hit_stop
                        else (target, "target")
                    )
                    j, p = held
                    fills.append((side, j, p, i, out, kind, t))
                    side = 0
                    held = bracket = None
                    break
        if side:
            p = held[1]
            bracket = p * (1 + side * 0.005), p * (1 - side * 0.003)
        position.append(side)
        b, s = signal[-2:]
        assert not (b and s)
        desired = 1 if b else -1 if s else 0
    return fills, position, held


def source_cases(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    pending = {
        r["id"]: r
        for r in read(baseline)["disposition"]
        if r["status"].startswith("Pending")
    }
    witnesses = {
        1586: (
            "initial_capital=1000, pyramiding=2, default_qty_type=strategy.percent_of_equity, default_qty_value=100",
            "matype             = input(7,",
            "malen              = input(5,",
            "maderiv            = input(3,",
            "masmooth           = input(5,",
            "momtype            = input(3,",
            "momlen             = input(3,",
            "momderiv           = input(8,",
            "momsmooth          = input(7,",
            'higherTf           = input("1",',
            "higherTfmult       = input(130,",
            "buffup             = input(0.02,",
            "bufflow            = input(-0.03,",
            "lowVolMALength     = input(28,",
            "MAlength           = input(10,",
            "MAThresh           = input(0.05,",
            "Volminimum         = input(2.5,",
            "security(_symbol, _res, _src[barstate.isrealtime ? 1 : 0])",
            "bad_vol            = chng_MA < Volminimum",
            "longCondition = bad_vol ? low_vol_up : MAout > buffup and Momout > buffup",
            "shortCondition = bad_vol ? low_vol_down : MAout < bufflow and Momout < bufflow",
            'strategy.entry("Buy", strategy.long)',
            'strategy.entry("Sell", strategy.short)',
        ),
        2751: (
            'strategy("5 Minute Scalp", overlay=true, margin_long=100, margin_short=100)',
            'fast_length = input(title="Fast Length", defval=12)',
            'slow_length = input(title="Slow Length", defval=26)',
            'signal_length = input.int(title="Signal Smoothing",  minval = 1, maxval = 50, defval = 9)',
            'defval="EMA", options=["SMA", "EMA"]',
            'hist_1m = request.security(syminfo.tickerid,"1",hist [barstate.isrealtime ? 1 : 0])',
            'input.int(94,title = "LengthBB Long"',
            'input.int(83,title = "LengthBB Short"',
            "multBB = input.float(2.0,",
            "len1 = input.int(9,",
            "len2 = input.int(50,",
            "len3 = input.int(200,",
            'input.int(defval = 11, title = "Rsi Length Long"',
            'input.int(defval = 29, title = "Rsi Length Short"',
            "longhight = input(defval=-10,",
            "shorthight = input(defval=35,",
            "TP = input.float(defval = 0.5,",
            "SL = input.float(defval = 0.3,",
            'strategy.entry("Long", strategy.long)',
            'strategy.entry("short ", strategy.short)',
            'strategy.exit(id ="close long",from_entry="Long",stop=longstop,limit=longprofit)',
            'strategy.exit(id ="close short",stop=shortstop,limit=shortprofit)',
        ),
    }
    result = {}
    with ZipFile(archive) as source:
        for ident, row, document, digest in documents(
            source, {i: pending[i] for i in SPECS}
        ):
            (block,) = re.findall(
                r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", document
            )
            start, end, _, _ = SPECS[ident]
            config = dict(
                re.findall(
                    r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)",
                    block,
                )
            )
            assert config == {
                "start": f"{start} 00:00:00",
                "end": f"{end} 00:00:00",
                "period": "1h",
                "basePeriod": "15m",
                "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
            }
            active = "\n".join(executable_lines(block))
            for proof in witnesses[ident]:
                assert proof in active, (ident, proof)
            assert f"//@version={4 if ident == 1586 else 5}" in block
            variant = PINE_1586 if ident == 1586 else PINE_2751
            result[ident] = row, digest, config, block.encode(), variant.encode()
    return result


def provider_inputs(hourly, minute):
    manifest, feeds = {}, {}
    for ident, (start, stop, months, _) in SPECS.items():
        windows = {}
        files = manifest[ident] = []
        a, z = map(date_ms, (start, stop))
        for market in ("BTCUSDT", "ETHUSDT"):
            native = []
            for archive in verified_archives(hourly, market, "1h", months, files):
                native.extend(provider_bars(archive, HOUR))
            streams = []
            for month in months:
                name = f"{market}-1m-{month}.zip"
                folder = next(p for p in minute if (p / name).is_file())
                (path,) = verified_archives(folder, market, "1m", (month,), files)
                streams.extend(provider_bars(path, MINUTE))
            for label, lo, hi in (
                ("FMZ native window", a, z),
                ("Next equal window", z, 2 * z - a),
            ):
                lower = [r for r in streams if lo - DAY <= r[0] < hi]
                assert [r[0] for r in lower] == list(range(lo - DAY, hi, MINUTE))
                chart = aggregate([r for r in lower if r[0] >= lo], 60)
                assert [r[:5] for r in chart] == [
                    r[:5] for r in native if lo <= r[0] < hi
                ]
                windows.setdefault(label, {})[market] = {
                    "chart": [list(r) for r in chart],
                    "reference": [list(r) for r in lower],
                    "frame": "60",
                }
        feeds[str(ident)] = windows
    return manifest, feeds


def stage(archive, baseline, work, hourly, minute):
    sources = source_cases(archive, baseline)
    _, feeds = provider_inputs(hourly, minute)
    for ident, (_, _, _, archived, variant) in sources.items():
        (work / f"minute-reference-source-{ident}.pine").write_bytes(archived)
        (work / f"minute-reference-variant-{ident}.pine").write_bytes(variant)
    copy2(Path(__file__).with_suffix(".mjs"), work / "minute-reference-run.mjs")
    write(work / "minute-reference-feeds.json", feeds)


def runtime(work):
    assert (work / "minute-reference-run.exit").read_text().strip() == "0"
    assert (work / "minute-reference-run.mjs").read_bytes() == Path(
        __file__
    ).with_suffix(".mjs").read_bytes()
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


def compare_state(expected, witnessed):
    for index, (a, b) in enumerate(zip(expected, witnessed, strict=True)):
        assert all(equal(x, y) for x, y in zip(a, b, strict=True)), (index, a, b)


def validate_dma(payload, case, legacy):
    chart = payload["chart"]
    signals = list(signals_dma(payload))
    legacy_plots = legacy["plots"]
    source_plots = [
        legacy_plots[k] for k in ("Low volume mode", "Long gate", "Short gate")
    ]
    compare_state((s[-3:] for s in signals), zip(*source_plots, strict=True))
    model = legacy["strategy"]
    assert not model["diagnostics"]
    trades, state, lots, opens = dma_broker(chart, signals, FEE, "causal")
    compare_state(
        state, zip(legacy_plots["Position"], legacy_plots["Equity"], strict=True)
    )
    closed_bar_positions = {r["barIndex"]: r["size"] for r in model["position"]}
    size = 0
    for index, (expected, recorded) in enumerate(
        zip(state, model["equity"], strict=True)
    ):
        size = closed_bar_positions.get(index, size)
        assert recorded["barIndex"] == index
        compare_state((expected,), ((size, recorded["equity"]),))
    for (side, qty, index, price), row in zip(opens, model["orders"], strict=True):
        previous_size = state[index - 1][0]
        reversal_size = abs(previous_size) if previous_size * side < 0 else 0
        assert row["direction"] == ("strategy.long" if side > 0 else "strategy.short")
        assert row["id"] == ("Buy" if side > 0 else "Sell")
        compare_state(
            ((index, chart[index][0], price, qty + reversal_size),),
            ((row["barIndex"], row["time"], row["price"], row["qty"]),),
        )
    quote_times = [bar[0] for bar in chart]
    realized = []
    for expected, observed in zip(trades, model["trades"], strict=True):
        side, qty, entry_i, entry, exit_i, exit = expected
        gross = side * qty * (exit - entry)
        turnover = qty * (entry + exit)
        fee = turnover * FEE
        wanted = (
            side * qty,
            entry_i,
            entry,
            exit_i,
            exit,
            quote_times[entry_i],
            quote_times[exit_i],
            gross - fee,
        )
        actual = tuple(
            observed[field]
            for field in (
                "qty",
                "entryBarIndex",
                "entryPrice",
                "exitBarIndex",
                "exitPrice",
                "entryTime",
                "exitTime",
                "profit",
            )
        )
        compare_state((wanted,), (actual,))
        assert observed["id"] == ("Buy" if side == 1 else "Sell")
        realized.append((quote_times[exit_i], gross, fee, turnover * EXECUTION))
    # The alternate engine reproduces order times and prices. Its future close leaks into size.
    alternate, alternate_state, _, _ = dma_broker(chart, signals, FEE, "alternate")
    compare_state(alternate_state, zip(*case["witnesses"][-2:], strict=True))
    tied = 0
    for causal, piner, expected in zip(trades, case["closed"], alternate, strict=True):
        verify_trade(piner, quote_times)
        got = tuple(
            piner[field]
            for field in (
                "dir",
                "qty",
                "entryBar",
                "entryPrice",
                "exitBar",
                "exitPrice",
            )
        )
        compare_state((expected,), (got,))
        compare_state((causal[:1] + causal[2:],), (got[:1] + got[2:],))
        tied += not equal(causal[1], got[1])
    assert len(lots) == case["unsettled"]
    empty_minutes = [
        bar[0] for bar in payload["reference"] if bar[0] >= chart[0][0] and bar[-1] == 0
    ]
    assert all(
        timestamp % HOUR and signals[(timestamp - chart[0][0]) // HOUR][-3]
        for timestamp in empty_minutes
    )
    return (
        realized,
        len(lots),
        {
            "closed": len(realized),
            "opening_fills": len(opens),
            "position_equity_rows_reconciled": len(state),
            "quiet_gate_true": sum(s[-3] for s in signals),
            "provider_no_print_minutes": empty_minutes,
            "alternate_quantity_disagreements": tied,
            "terminal_open_lots": len(lots),
            "terminal_marked_equity": state[-1][1],
            "terminal_unsettled_position": state[-1][0],
        },
    )


def validate_macd(payload, case):
    chart = payload["chart"]
    signals = list(signals_macd(payload))
    trades, state, held = broker_macd(chart, payload["reference"], signals)
    compare_state(zip(state, strict=True), zip(case["witnesses"][-1], strict=True))
    assert case["unsettled"] == int(held is not None)
    quote_times = [bar[0] for bar in chart]
    realized = []
    details = Counter()
    touched = []
    for expected, observed in zip(trades, case["closed"], strict=True):
        fields = ("dir", "entryBar", "entryPrice", "exitBar", "exitPrice")
        assert observed["qty"] == 1
        compare_state((expected[:5],), (tuple(observed[field] for field in fields),))
        _, gross, fee, buffer = verify_trade(observed, quote_times)
        kind, minute = expected[-2:]
        assert all(
            row[-1] > 0
            for row in payload["reference"]
            if row[0] in (quote_times[expected[1]], minute)
        )
        realized.append((minute, gross, fee, buffer))
        details[kind] += 1
        touched.append(minute)
    return (
        realized,
        case["unsettled"],
        {
            "closed": len(realized),
            "causal_bracket_exit_types": dict(details),
            "one_minute_close_times": touched,
            "position_rows_reconciled": len(state),
            "terminal_open_lots": case["unsettled"],
        },
    )


def check_pine_signals(ident, payload, case):
    expected = (signals_dma if ident == 1586 else signals_macd)(payload)
    plots = case["witnesses"][: (-2 if ident == 1586 else -1)]
    compare_state(expected, zip(*plots, strict=True))
    requested = case["requested"]
    assert requested and all(
        r["symbol"] == f"BINANCE:{case['market']}.P"
        and r["timeframe"] == "1"
        and not r["lowerTf"]
        for r in requested
    )
    return len(plots) * len(payload["chart"])


def report(archive, baseline, work, hourly, minute, legacy, output):
    sources = source_cases(archive, baseline)
    manifest, feeds = provider_inputs(hourly, minute)
    assert read(work / "minute-reference-feeds.json") == feeds
    isolation = runtime(work)
    legacy_isolation = read(legacy / "round3-isolation-python.json")
    assert all(
        legacy_isolation[k][0] == "PermissionError"
        for k in ("file_error", "network_error")
    )
    native = legacy / "priced-runtime/pine_compat/pine_compat.pyd"
    native_path = (
        legacy
        / "r25-dma-causal-native-BTCUSDT-native-ETHUSDT-next-BTCUSDT-next-ETHUSDT.json"
    )
    assert (
        sha256(native)
        == "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
    )
    assert read(legacy / "r25-dma-feeds.json") == feeds["1586"]
    assert (legacy / "r25-dma-source.pine").read_bytes().replace(
        b"\r\n", b"\n"
    ) == sources[1586][3].replace(b"\r\n", b"\n")
    legacy_script = Path(__file__).with_name("fmz_round25_pine_legacy_dma_probe.py")
    assert (
        legacy_script.read_bytes() == (legacy / "r25_dma_legacy_probe.py").read_bytes()
    )
    legacy_rows = read(native_path)
    legacy_cases = {
        (c["period"], c["market"]): c["results"]["with comparison fee"]
        for c in legacy_rows
    }
    assert len(legacy_cases) == len(legacy_rows) == 4
    receipts = {r["id"]: r for r in read(work / "minute-reference-receipt.json")}
    results, checks, coverage, audits = [], [], [], {}
    for ident, (original, digest, settings, archived, variant) in sources.items():
        receipt = receipts[ident]
        assert "error" not in receipt, receipt
        raw = work / f"minute-reference-source-{ident}.pine"
        transformed = work / f"minute-reference-variant-{ident}.pine"
        assert raw.read_bytes() == archived and receipt["sourceHash"] == sha256(raw)
        assert transformed.read_bytes() == variant and receipt["variantHash"] == sha256(
            transformed
        )
        capital = SPECS[ident][3]
        model = receipt["model"]
        assert model["initialCapital"] == capital and equal(
            model["commissionValue"] / 100, FEE
        )
        if ident == 1586:
            assert (
                model["qtyType"],
                model["qtyValue"],
                model["marginLong"],
                model["marginShort"],
            ) == ("percent_of_equity", 100, 0, 0)
        else:
            assert (model["marginLong"], model["marginShort"]) == (100, 100)
        cases = {(c["period"], c["market"]): c for c in receipt["cases"]}
        assert len(cases) == len(receipt["cases"]) == 4
        common = {
            "id": ident,
            "name": original["name"],
            "source": original["source"],
            "source_sha256": digest,
            "executed_source_sha256": sha256(raw)
            if ident == 1586
            else receipt["variantHash"],
            "interval": "1h",
            "archive_interval": "1h",
            "quote_currency": "USDT",
            "market_data": "Binance USD-M official hourly and one-minute archives",
            "group": GROUPS[ident],
            "exit": "Opposite signal reversal, up to two lots"
            if ident == 1586
            else "0.3% stop, 0.5% target, or reversal",
        }
        count = 0
        for period, markets in feeds[str(ident)].items():
            pooled = []
            terminal = 0
            for market, payload in markets.items():
                case = cases[(period, market)]
                observations = check_pine_signals(ident, payload, case)
                if ident == 1586:
                    ledger, open_lots, audit = validate_dma(
                        payload, case, legacy_cases[(period, market)]
                    )
                else:
                    ledger, open_lots, audit = validate_macd(payload, case)
                count += len(ledger)
                pooled.extend(ledger)
                terminal += open_lots
                checks.append(
                    {
                        "id": ident,
                        "period": period,
                        "market": market,
                        "indicator_values_checked": observations,
                        **audit,
                    }
                )
                results.append(
                    {
                        **common,
                        "period": period,
                        "market": market,
                        **summarize(ledger, open_lots, capital),
                    }
                )
            results.append(
                {
                    **common,
                    "period": period,
                    "market": "BTCUSDT + ETHUSDT",
                    **summarize(pooled, terminal, capital * 2),
                }
            )
        audits[ident] = {
            "archive_settings": settings,
            "source_document_sha256": digest,
            "archive_pine_sha256": sha256(raw),
            "signal_replay_variant_sha256": sha256(transformed),
            "verified_closed_lots": count,
        }
        explanation = (
            "Original Pine v4 signals and causal next-open fee-reserved sizing match independent arithmetic; "
            "alternate engine mark-at-close contamination was measured."
            if ident == 1586
            else "Independent one-minute chronology reproduces all hourly engine brackets and fees."
        )
        coverage.append([ident, f"Tested · {GROUPS[ident]}", explanation])
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(baseline),
            "archive_sha256": FMZ_SHA256,
            "piner_version": PINER_VERSION,
            "piner_tarball_sha512": PINER_PIN,
            "isolation_probe": isolation,
            "native_isolation_probe": legacy_isolation,
            "pine_compat_binary_sha256": sha256(native),
            "legacy_artifacts": {
                f.name: sha256(f)
                for f in (
                    legacy_script,
                    native_path,
                    legacy / "r25-dma-feeds.json",
                    legacy / "r25-dma-source.pine",
                )
            },
            "provider_archives": manifest,
            "artifacts": {
                name: sha256(work / name)
                for name in (
                    "minute-reference-feeds.json",
                    "minute-reference-run.mjs",
                    "minute-reference-receipt.json",
                )
            },
            "references": [
                "https://github.com/binance/binance-public-data",
                "https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/",
                "https://www.tradingview.com/support/solutions/43000628599-strategy-properties/",
                "https://www.tradingview.com/pine-script-docs/concepts/strategies/",
            ],
            "cost_model": {
                "comparison_fee_per_side": FEE,
                "execution_buffer_per_side": EXECUTION,
                "quantity_step": STEP,
            },
            "method": [
                "Each isolated scenario uses the source-selected one-hour chart, confirmed one-minute historical inputs and its own BTCUSDT or ETHUSDT feed. Checksummed minute bars aggregate to each venue-native hourly open, high, low and close. ETH and next equal windows are explicit comparisons.",
                "DMA retains source 100% equity, $1,000 capital and pyramiding of two. The original Pine v4 source adds the comparison commission. Its exact trades and marked equity match a separately written causal model that sizes a reversal at fill-open using pre-reversal equity and entry-commission reservation. Piner is a cross-check of signals and fill prices. Its current-bar-close quantity differences are counted separately.",
                "MACD retains the authored 100% margin and one fixed unit. It uses Pine's documented default capital, $1,000,000, where the source omits capital. The next-open orders and all active stop/target decisions reconcile to official one-minute prices, and no exit requires ordering both levels within a minute.",
                "Reported P&L before and after fees uses the same realized fills. Net also deducts a stated hypothetical execution buffer. Realized drawdown and pooled results use closed cashflows. Terminal open lots are counted separately and remain open in the evidence.",
            ],
            "source_audits": audits,
            "per_case_order_counts": checks,
            "coverage": coverage,
            "results": results,
        },
    )
    print(
        f"Verified {len(coverage)} strategies, {len(results)} results, and {sum(a['closed'] for a in checks)} closed lots."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "finalize"))
    for name in ("archive", "baseline", "work", "hourly", "legacy", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--minute", type=Path, nargs="+", required=True)
    args = parser.parse_args()
    common = (args.archive, args.baseline, args.work, args.hourly, args.minute)
    if args.mode == "stage":
        stage(*common)
        copy2(
            Path(__file__).with_name("fmz_round25_pine_legacy_dma_probe.py"),
            args.legacy / "r25_dma_legacy_probe.py",
        )
        copy2(
            args.work / "minute-reference-source-1586.pine",
            args.legacy / "r25-dma-source.pine",
        )
        write(
            args.legacy / "r25-dma-feeds.json",
            read(args.work / "minute-reference-feeds.json")["1586"],
        )
    else:
        report(*common, args.legacy, args.output)


if __name__ == "__main__":
    main()
