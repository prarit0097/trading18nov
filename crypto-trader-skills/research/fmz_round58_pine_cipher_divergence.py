"""Audit #3184's Pine v4 local call history and historical limit/exit fills."""

from __future__ import annotations

import argparse
import re
from itertools import batched
from math import ceil, floor, fsum, isclose
from pathlib import Path
from shutil import copy2
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, aggregate, date_ms, sha256
from research.fmz_round7_pine import EXECUTION, FEE, summarize
from research.fmz_round12_pine_authored import provider_bars
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH
from research.fmz_round28_pine_callback import cache_bars

IDENT = 3184
CAPITAL = 1_000_000
HOUR = 3_600_000
QUARTER = HOUR // 4
START, CUT, STOP = map(date_ms, ("2023-01-01", "2023-12-25", "2024-01-24"))
WORKER = "fmz_round58_pine_cipher_divergence_probe.py"
FIVE_SHA = "2dc35b1e7c14e83cf1d839bd6ba7428bf0f183ea978f11edb473af668c3704dd"
DAY_SHA = "60fbc08c0a73afa5f04d8bc9b8b960cb782435147c1a1080a2b449714db1ea20"
SOURCE_OBS = '\nplot(validlong?1:0,"LongGate")\nplot(validshort?1:0,"ShortGate")\nplot(wt1,"WT1")\nplot(wt2,"WT2")\nplot(basis,"LocalBasis")\nplot(limit_price,"Entry-limit")\nplot(tradeTargetPrice,"Target")\nplot(tradeStopPrice,"Stop")\n'


def archived(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (item,) = [r for r in read(baseline)["disposition"] if r["id"] == IDENT]
    assert item["status"].startswith("Pending")
    with ZipFile(archive) as book:
        ((_, _, doc, digest),) = documents(book, {IDENT: item})
    (raw,) = re.findall(r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", doc)
    fields = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)", raw
        )
    )
    assert fields == {
        "start": "2023-01-01 00:00:00",
        "end": "2023-12-25 00:00:00",
        "period": "1h",
        "basePeriod": "15m",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    src, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", raw)
    assert n == 1 and src.count("//@version=4") == 1
    assert all(
        token in src
        for token in (
            'Div_1=input(title="Only divergencies for long", defval=true',
            'Div_2=input(title="Only divergencies for short", defval=true',
            'localFilter_frame=input(title="Local trend filter timeframe", defval="60"',
            "stochShowDiv = input(false,",
            "rsiShowDiv = input(false,",
            "wtShowDiv = input(true,",
            'limit_checkbox = input(title="Shift open position?", defval=false',
            'a_1_div=input(title="TP long div", defval=0.95,',
            'a_2=input(title="TP short", defval=0.95,',
            'b_1=input(title="SL long", defval=5,',
            'b_2=input(title="SL short", defval=5,',
            "if cancel_in and barssince(validlong) == cancel_in_num or barssince(validshort) == cancel_in_num",
            'cancel_in =  input(title="Cancel position in #bars?", defval=false',
            'cancel_in_num =  input(title="Number of bars", defval=96',
            'Cancel_all=input(title="Cancel all positions if price crosses local sma? (yellow line)", defval=false',
        )
    )
    literal = src + SOURCE_OBS
    subset = projection(literal)
    compatible = documented(subset)
    scripts = {
        "archive": literal,
        "projected": subset,
        "documented": compatible,
        "documented-explicit": persistent_source(compatible),
    }
    return item, digest, fields, scripts


def projection(s0):
    s = s0
    for exp, n in [
        (r"^\[(?:sommiBearish,|sommiBearishDiamond,|macdWT1Color,)[^\n]*\n", 3),
        (r"^(?:emaValue|marketPrice|regimeFilter|reverse_regime)\s*=.*\n", 4),
        (r"^bgcolor\(Global\?.*\n", 1),
    ]:
        s, n0 = re.subn(exp, "", s, flags=re.MULTILINE)
        assert n0 == n, (exp, n0, n)
    for side in ("long", "short"):
        p = rf"^(valid{side} = )sommi_diamond_on[^\n]* :\s+(valid(?:low|high) and.*)$"
        s, n = re.subn(p, r"\1\2", s, flags=re.MULTILINE)
        assert n == 1
    assert s0.count("sommi_diamond_on") == 3
    assert s0.count("sommiBearishDiamond") == 2 and s0.count("sommiBullishDiamond") == 2
    assert s0.count("marketPrice") == 5
    assert '=input(title="Sommi diamond alerts", defval=false' in s0.replace(" =", "=")
    # Preserve chart-only inputs and all active order guards, inlining the source's same-chart request.
    s, n = re.subn(
        r"^basis = security\(syminfo\.tickerid, localFilter_frame, ema\(close, localFilter_length\)\)$",
        "basis = ema(close, localFilter_length)",
        s,
        flags=re.MULTILINE,
    )
    assert n == 1
    s, n = re.subn(
        r"^sma =security\(syminfo\.tickerid, '60', ema\(close, 15\)\)$",
        "sma = ema(close, 15)",
        s,
        flags=re.MULTILINE,
    )
    assert n == 1
    begin = s.index("f_wavetrend(src,")
    end = s.index("\n\n", begin)
    before = s[begin:end]
    aft = (
        before.replace("security(syminfo.tickerid, tf, src)", "src")
        .replace("security(syminfo.tickerid, tf, ema(ci, avg))", "ema(ci, avg)")
        .replace("security(syminfo.tickerid, tf, sma(wt1, malen))", "sma(wt1, malen)")
    )
    s = s.replace(before, aft)
    s, n = re.subn(
        r"^rsiMFI = f_rsimfi\(rsiMFIperiod, rsiMFIMultiplier, timeframe.period\)$",
        "rsiMFI = sma(((close - open) / (high - low)) * rsiMFIMultiplier, rsiMFIperiod) - rsiMFIPosY",
        s,
        flags=re.MULTILINE,
    )
    assert n == 1
    return s


def documented(s):
    start = s.index("    wtVwap = wt1 - wt2")
    end = s.index("    [wt1, wt2,", start)
    derived = "\n".join(line[4:] for line in s[start:end].splitlines())
    rename = {
        "wtCrosslast": "wtCross_last",
        "wtCrossUplast": "wtCrossUp_last",
        "wtCrossDownlast": "wtCrossDown_last",
    }
    for old, new in rename.items():
        derived = derived.replace(old, new)
    old = next(
        line
        for line in s.splitlines()
        if line.startswith("[wt1, wt2, wtOversold") and "timeframe.period)" in line
    )
    adapt = """chartBasis = 0.0
    chartRate = 2.0/(wtChannelLen + 1)
    chartBasis := na(chartBasis[1]) ? wtMASource : chartRate * wtMASource + (1 - chartRate) * chartBasis[1]
    chartDevInput = abs(wtMASource - chartBasis)
    chartDev = 0.0
    chartDev := na(chartDev[1]) ? chartDevInput : chartRate * chartDevInput + (1 - chartRate) * chartDev[1]
    chartIndex = chartDev == 0 ? na : (wtMASource - chartBasis) / (0.015 * chartDev)
    wt1 = 0.0
    waveRate = 2.0 / (wtAverageLen + 1)
    wt1 := na(wt1[1]) ? chartIndex : waveRate * chartIndex + (1 - waveRate) * wt1[1]
    wt2 = sma(wt1, wtMALen)
    """
    s = s.replace(old, adapt + derived)
    assert s.count("basis = ema(close, localFilter_length)") == 1
    s = s.replace(
        "basis = ema(close, localFilter_length)",
        """basis = 0.0
    localRate = 2.0 / (localFilter_length + 1)
    basis := na(basis[1]) ? close : localRate * close + (1 - localRate) * basis[1]""",
    )
    return s


def persistent_source(s):
    code, n = re.subn(
        r"(?m)^f_fractalize\(src\) => f_top_fractal\(src\) \? 1 : f_bot_fractal\(src\) \? -1 : 0$",
        "f_fractalize(src) =>\n    top = f_top_fractal(src)\n    float low0 = na\n    float low1 = na\n    float low2 = na\n    float low3 = na\n    float low4 = na\n    low0 := top ? low0[1] : src\n    low1 := top ? low1[1] : low0[1]\n    low2 := top ? low2[1] : low1[1]\n    low3 := top ? low3[1] : low2[1]\n    low4 := top ? low4[1] : low3[1]\n    low = low4 > low2 and low3 > low2 and low1 > low2 and low0 > low2\n    top ? 1 : low ? -1 : 0",
        s,
    )
    assert n == 1
    return code


def source_inputs(hour_paths, quarter_paths, replacements):
    result = {}
    receipts = []
    months = tuple(f"2023-{m:02d}" for m in range(1, 13)) + ("2024-01",)
    direct = replacements / "BTCUSDT-1m-2023-11-10.zip"
    assert sha256(direct) == DAY_SHA
    repaired = {
        row[0]: list(row)
        for row in aggregate(list(provider_bars(direct, 60_000)), 15)
        if 1699628400000 <= row[0] < 1699635600000
    }
    assert len(repaired) == 8
    for coin in ("BTC", "ETH"):
        market = coin + "USDT"
        hours = [
            list(x)
            for x in cache_bars(hour_paths, market, "1h", months, HOUR, receipts)
            if START <= x[0] < STOP
        ]
        quarter = [
            list(x)
            for x in cache_bars(quarter_paths, market, "15m", months, QUARTER, receipts)
            if START <= x[0] < STOP
        ]
        assert [x[0] for x in hours] == list(range(START, STOP, HOUR))
        assert [x[0] for x in quarter] == list(range(START, STOP, QUARTER))
        if coin == "BTC":
            assert [
                x[0]
                for x, y in zip(aggregate(quarter, 4), hours, strict=True)
                if list(x[:5]) != y[:5]
            ] == [1699628400000, 1699632000000]
            quarter = [repaired.get(x[0], x) for x in quarter]
        assert all(
            list(x[:5]) == y[:5] and isclose(x[5], y[5], rel_tol=1e-12)
            for x, y in zip(aggregate(quarter, 4), hours, strict=True)
        )
        result[coin] = {
            "native": [
                [x for x in series if x[0] < CUT] for series in (hours, quarter)
            ],
            "next": [[x for x in series if x[0] >= CUT] for series in (hours, quarter)],
        }
    return {"data": result, "receipts": receipts}


def ema(values, length, sma_seed):
    current = None
    initial = []
    rate = 2 / (length + 1)
    for value in values:
        if value is None:
            yield None
            continue
        if current is not None:
            current = rate * value + (1 - rate) * current
        elif not sma_seed:
            current = value
        else:
            initial.append(value)
            if len(initial) == length:
                current = fsum(initial) / length
        yield current


def waves(bars, sma_seed):
    hlc3 = [(bar[2] + bar[3] + bar[4]) / 3 for bar in bars]
    basis = list(ema(hlc3, 9, sma_seed))
    deviation = ema(
        (
            None if base is None else abs(value - base)
            for base, value in zip(basis, hlc3, strict=True)
        ),
        9,
        sma_seed,
    )
    osc = (
        None if dev in (None, 0) else (value - base) / (0.015 * dev)
        for base, dev, value in zip(basis, deviation, hlc3, strict=True)
    )
    fast = list(ema(osc, 12, sma_seed))
    window = []
    slow = []
    for value in fast:
        if value is not None:
            window = [*window[-2:], value]
        slow.append(fsum(window) / 3 if len(window) == 3 else None)
    return fast, slow


def divs(wave, hours, high_cut, low_cut):
    events = []
    upper = []
    lower = []
    top = bot = None
    low_calls = []
    for i in range(len(hours)):
        bear = bull = False

        group = wave[max(0, i - 4) : i + 1]
        is_top = (
            len(group) == 5
            and None not in group
            and group[2] > max(group[:2] + group[3:])
        )
        if not is_top:
            low_calls.append(wave[i])
        g = low_calls[-5:]
        is_bot = (
            not is_top and len(g) == 5 and None not in g and g[2] < min(g[:2] + g[3:])
        )
        v = wave[i - 2] if i >= 2 else None
        if v and is_top and v >= high_cut:
            mark = hours[i - 2][2]
            before = upper[i - 2]
            bear = before is not None and v < before[0] and mark > before[1]
            top = v, mark
        if v and is_bot and v <= low_cut:
            mark = hours[i - 2][3]
            before = lower[i - 2]
            bull = before is not None and v > before[0] and mark < before[1]
            bot = v, mark
        upper.append(top)
        lower.append(bot)
        events.append((bull, bear))
    return events


def signals(bars, seed):
    fast, slow = waves(bars, seed)
    basis = list(ema([r[4] for r in bars], 20, seed))
    d1 = divs(slow, bars, 45, -65)
    d2 = divs(slow, bars, 15, -40)
    return (
        fast,
        slow,
        basis,
        [
            (
                int(base is not None and c > base and (a[0] or b[0])),
                int(base is not None and c < base and (a[1] or b[1])),
            )
            for (_, _, _, _, c, _), base, a, b in zip(bars, basis, d1, d2, strict=True)
        ],
    )


def same(a, b):
    return (
        a is None
        and b is None
        or a is not None
        and b is not None
        and isclose(a, b, abs_tol=1e-8, rel_tol=1e-10)
    )


def ref_fills(chart, quarter, signal, tick):
    ledger = []
    flow = []
    marks = []
    rejects = []
    clipped = []
    waiting = {}
    hold = None
    target = stop = 0.0
    call_limit = 0.0
    realized = 0.0
    bracket_live = False
    latest_short = None
    for i, (hour, children, (lg, sg)) in enumerate(
        zip(chart, batched(quarter, 4, strict=True), signal, strict=True)
    ):
        ts, op, _maxh, _minl, cl, _ = hour
        assert ts == children[0][0] and op == children[0][1] and cl == children[-1][4]
        for t, o, h, l, c, v in children:
            if hold is not None and bracket_live:
                side, ent, entry_px = hold
                if side > 0:
                    low = stop
                    high = target
                    lo, hi = l <= low, h >= high
                    if lo and hi:
                        rejects.append((i, t, "long"))
                    exit_px = min(o, low) if lo else max(o, high) if hi else None
                else:
                    high = stop
                    low = target
                    lo, hi = l <= low, h >= high
                    if lo and hi:
                        rejects.append((i, t, "short"))
                    exit_px = min(o, low) if lo else max(o, high) if hi else None
                if exit_px is not None:
                    # Both stop and target are addressed to the current exact source entry.
                    pnl = side * (exit_px - entry_px)
                    ledger.append(
                        (
                            i,
                            t,
                            "Long Exit" if side > 0 else "Short Exit",
                            "strategy.exit",
                            exit_px,
                        )
                    )
                    flow.append((ent, i, t, entry_px, exit_px, side, pnl))
                    hold = None
                    bracket_live = False
                    realized += pnl
            eligible = [
                (side, price)
                for side, price in waiting.items()
                if (l <= price if side > 0 else h >= price)
            ]
            if eligible:
                assert len(eligible) == 1 and hold is None, (i, t, eligible, hold)
                side, price = eligible[0]
                entry_px = min(o, price) if side > 0 else max(o, price)
                hold = side, i, entry_px
                del waiting[side]
                ledger.append(
                    (
                        i,
                        t,
                        "Long" if side > 0 else "Short",
                        "strategy.long" if side > 0 else "strategy.short",
                        entry_px,
                    )
                )
        lg, sg = bool(lg and hold is None), bool(sg and hold is None)
        clipped.append((int(lg), int(sg)))
        if lg or sg:
            assert not (lg and sg)
            call_limit = cl
            if lg:
                target = ceil(cl * 1.0095 / tick - 1e-9) * tick
                stop = floor(cl * 0.95 / tick + 1e-9) * tick
            else:
                target = floor(cl * 0.9905 / tick + 1e-9) * tick
                stop = ceil(cl * 1.05 / tick - 1e-9) * tick
                latest_short = i
        if latest_short is not None and i - latest_short == 96:
            waiting.clear()
        if lg or sg:
            waiting[1 if lg else -1] = call_limit
        bracket_live = hold is not None
        marks.append(CAPITAL + realized + (hold[0] * (cl - hold[2]) if hold else 0))
    return ledger, flow, marks, hold, rejects, clipped


def proven_ledger(coin, bars, lower, record):
    assert not record["diag"] and not record["strategy"]["diagnostics"]
    fast, slow, basis, source = signals(bars, False)
    obs = record["plots"]
    for key, values in (("WT1", fast), ("WT2", slow), ("LocalBasis", basis)):
        assert all(same(a, b) for a, b in zip(values, obs[key], strict=True))
    orders, settlements, marks, held, rejected, flags = ref_fills(
        bars, lower, source, 0.1 if coin == "BTC" else 0.01
    )
    assert held is None and not rejected
    assert flags == list(zip(obs["LongGate"], obs["ShortGate"], strict=True))
    book = record["strategy"]
    for (i, _, key, direction, px), actual in zip(orders, book["orders"], strict=True):
        assert (i, bars[i][0], key, direction, 1) == (
            actual["barIndex"],
            actual["time"],
            actual["id"],
            actual["direction"],
            actual["qty"],
        )
        assert same(px, actual["price"])
    flows = []
    for (i, j, at, entry, exit, side, gross), row in zip(
        settlements, book["trades"], strict=True
    ):
        assert (i, j, bars[i][0], bars[j][0], side) == (
            row["entryBarIndex"],
            row["exitBarIndex"],
            row["entryTime"],
            row["exitTime"],
            row["qty"],
        )
        assert all(
            same(a, b)
            for a, b in (
                (entry, row["entryPrice"]),
                (exit, row["exitPrice"]),
                (gross, row["profit"]),
            )
        )
        turnover = entry + exit
        flows.append((at, gross, turnover * FEE, turnover * EXECUTION))
    assert all(
        same(v, row["equity"]) for v, row in zip(marks, book["equity"], strict=True)
    )
    return flows, len(orders)


def validated(args, meta, data, paths, worker):
    item, digest, fields, _ = meta
    month = read(paths["month"])
    assert month["archived"] == month["cross-feed-shift"] == month["projection"]
    assert not month["archived"]["diag"] and len(month["archived"]["orders"]) == 6
    old = read(paths["projected"])
    seed = read(paths["documented"])
    current = read(paths["event"])
    assert len(old) == len(seed) == len(current) == 4
    assert all(seed[key]["strategy"] == row["strategy"] for key, row in old.items())
    added = [
        row
        for row in current["ETH:native"]["strategy"]["trades"]
        if row not in old["ETH:native"]["strategy"]["trades"]
    ]
    assert len(added) == 1
    assert (added[0]["entryBarIndex"], added[0]["exitBarIndex"], added[0]["qty"]) == (
        7944,
        7960,
        1,
    )
    assert same(added[0]["profit"], 19.27)
    assert current["ETH:native"]["plots"]["LongGate"][7943] == 1
    assert old["ETH:native"]["plots"]["LongGate"][7943] == 0
    common = {
        "id": IDENT,
        "source": item["source"],
        "source_sha256": digest,
        "executed_source_sha256": sha256(
            args.work / "r49-3184-documented-explicit.pine"
        ),
        "group": "FMZ Pine · Cipher B v4 sampled fractal history",
        "interval": "1h",
        "archive_interval": "15m",
        "currency": "USDT",
        "quote_currency": "USDT",
        "market_data": "Official Binance USD-M hourly and repaired quarter-hour archive",
        "exit": "Source limit and stop prices, confirmed with causal 15-minute fills",
    }
    rows = []
    findings = []
    for scope, label in (
        ("native", "FMZ native dates · v4 sampled history"),
        ("next", "Next 30 days · v4 sampled history"),
    ):
        pooled = []
        for coin in ("BTC", "ETH"):
            chart, lower = data["data"][coin][scope]
            flows, order_n = proven_ledger(
                coin, chart, lower, current[f"{coin}:{scope}"]
            )
            pooled.extend(flows)
            rows.append(
                {
                    **common,
                    "market": coin + "USDT",
                    "period": label,
                    **summarize(flows, 0, CAPITAL),
                }
            )
            findings.append(
                {
                    "market": coin,
                    "period": scope,
                    "chart_bars": len(chart),
                    "base_bars": len(lower),
                    "fills": order_n,
                    "closed_lots": len(flows),
                    "terminal_positions": 0,
                }
            )
        rows.append(
            {
                **common,
                "market": "BTCUSDT + ETHUSDT",
                "period": label,
                **summarize(pooled, 0, 2 * CAPITAL),
            }
        )
    assert [r["trades"] for r in rows] == [34, 37, 71, 3, 0, 3]
    isolation = read(args.work / "round3-isolation-python.json")
    assert all(
        isolation[key][0] == "PermissionError"
        for key in ("file_error", "network_error")
    )
    return {
        "baseline_coverage_sha256": sha256(args.baseline),
        "archive_sha256": FMZ_SHA256,
        "document_sha256": digest,
        "archived_settings": fields,
        "native_runtime_sha256": NATIVE_BINARY_HASH,
        "probe_sha256": sha256(worker),
        "offline_isolation": isolation,
        "receipt_sha256": {k: sha256(path) for k, path in paths.items()},
        "binance_provider_archives": data["receipts"],
        "btc_november_repair": {
            "sha256": DAY_SHA,
            "url": "https://data.binance.vision/data/futures/um/daily/klines/BTCUSDT/1m/BTCUSDT-1m-2023-11-10.zip",
            "reconstructed_quarter_count": 8,
            "reconciled_hour_count": 2,
        },
        "exact_fmz_january_control_feed": {
            "sha256": FIVE_SHA,
            "url": "https://q.fmz.com/data/history?detail=true&round=true&feeder=local&event=feed&eid=Futures_Binance&depth=5&trades=0&custom=0&period=300000&symbol=BTC_USDT.swap&from=1672531200&to=1680307200",
            "source_control_fills": 6,
        },
        "verification": {
            "scopes": findings,
            "closed_lots": 74,
            "restored_local_history_lot": added[0],
            "unadapted_runtime_closed_lots": 73,
            "same_native_record_across_ema_seed_controls": True,
        },
        "cost_model": {
            "source_fee_per_side": 0,
            "comparison_fee_per_side": FEE,
            "execution_buffer_per_side": EXECUTION,
            "base_asset_position_size": 1,
        },
        "method": [
            "Archived default orders at the hourly Binance perpetual close use WaveTrend divergences and the same-chart 20-period basis. Original January BTC orders, flags and observations match both the full source run with authentic FMZ auxiliary data and its perturbed auxiliary controls. In the all-window projection, only the documented inactive external and visual paths are dropped and equal-timeframe requests are inlined.",
            "Original v4 ternary invokes the bottom-fractal function only when no top fractal is identified. Its local history therefore samples successive executions. The explicit five-observation local state reproduces the documented sparse history rather than reading the most recent five chart rows. It recovers ETH native bar 7,943 and the independently filled 2,027.57 to 2,046.84 closure omitted by the compatibility runtime's unadjusted history.",
            "Recorded first-sample and SMA-seed controls agree on the raw gates and broker in each full scope. Primary results implement the venue's documented first-sample EMA and explicit local call context. Independent oscillator/divergence and quarter-bar limit, bracket, order cancellation, rounding and equity checks match all 148 fills. No quarter with two competing bracket hits occurs.",
            "The publisher's dates are reproduced at its saved chart and base intervals. ETH is a same-settings comparative replay and the immediate 30-day forward window is shown separately. Results use one base-asset unit, postprocessed fees and execution buffer, and no terminal close, funding or demo qualification.",
        ],
        "references": [
            "https://www.tradingview.com/pine-script-docs/v4/language/functions-and-annotations/",
            "https://www.fmz.com/doc/9293",
            "https://github.com/binance/binance-public-data",
        ],
        "coverage": [
            [
                IDENT,
                "Tested · FMZ Pine v4 sampled divergence history",
                "Published book and independent 1h/15m replay verify 74 closes after modelling Pine v4 local call history. An unadapted comparator misses one actual ETH close.",
            ]
        ],
        "results": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "report"))
    for name in ("archive", "baseline", "work", "raw", "out"):
        parser.add_argument(name, type=Path)
    for name in ("hour", "quarter"):
        parser.add_argument(f"--{name}", type=Path, nargs="+", required=True)
    args = parser.parse_args()
    meta = archived(args.archive, args.baseline)
    data = source_inputs(args.hour, args.quarter, args.raw)
    worker = Path(__file__).with_name(WORKER)
    qc = args.raw / "3184-fmz-btc-5m-2023-01-01.json"
    assert sha256(qc) == FIVE_SHA
    path = args.work / "r49-3184-fulltape.json"
    if args.mode == "stage":
        write(path, data)
        for tag, src in meta[-1].items():
            suffix = "" if tag == "archive" else "-" + tag
            (args.work / f"r49-3184{suffix}.pine").write_text(
                src, encoding="utf8", newline="\n"
            )
        h, q = data["data"]["BTC"]["native"]
        write(args.work / "r49-3184-feeds.json", {"1h": h[:744], "15m": q[:2976]})
        copy2(qc, args.work / "r49-3184-sample-q5.json")
        copy2(worker, args.work / WORKER)
        return
    assert read(path) == data and sha256(worker) == sha256(args.work / WORKER)
    assert (
        sha256(args.work / "priced-runtime/pine_compat/pine_compat.pyd")
        == NATIVE_BINARY_HASH
    )
    for tag, src in meta[-1].items():
        suffix = "" if tag == "archive" else "-" + tag
        assert (args.work / f"r49-3184{suffix}.pine").read_text(encoding="utf8") == src
    reports = {
        tag: args.work
        / (f"r49-3184-{tag}-full.json" if tag != "month" else "r49-3184-month.json")
        for tag in ("month", "projected", "documented", "event")
    }
    report = validated(args, meta, data, reports, worker)
    write(args.out, report)
    print("Verified 74 closed lots, 148 individual fills, six workbook comparison rows")


if __name__ == "__main__":
    main()
