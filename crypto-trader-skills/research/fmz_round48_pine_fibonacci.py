"""Reconcile the FMZ Fibonacci strategy with independent causal fixed-point order lots."""

from __future__ import annotations

import argparse
import re
from collections import deque
from itertools import pairwise
from math import ceil, floor, isclose
from pathlib import Path
from shutil import copy2
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, date_ms, sha256
from research.fmz_round7_pine import EXECUTION, summarize
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH
from research.fmz_round28_pine_callback import cache_bars

IDENT = 5230
GATES = ("Strong", "Middle", "Sideways")
FEE = 0.0005
QUANT = 0.001
CAPITAL = 10000
DAY = 86_400_000
MINUTE = 60_000
WEEK_BARS = 10080
FX_SHA = "e95df5720b22fc782ffd7dfd4f989c9035e418bf552e4441c86892362b468d60"
FX_LINK = "https://api.exchange.coinbase.com/products/USDT-USD/candles?granularity=86400&start=2023-11-06T00%3A00%3A00Z&end=2024-02-28T00%3A00%3A00Z"
BEGIN, CUT, STOP = map(date_ms, ("2023-12-17", "2023-12-24", "2023-12-31"))
LABEL = {"native": "FMZ native window", "next": "Next equal window"}
PROBE = "fmz_round48_pine_fibonacci_probe.py"


def source_record(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (row,) = (r for r in read(baseline)["disposition"] if r["id"] == IDENT)
    assert row["status"].startswith("Pending")
    with ZipFile(archive) as book:
        ((_, _, body, digest),) = documents(book, {IDENT: row})
    (raw,) = re.findall(r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", body)
    code, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", raw)
    assert n == 1
    assert re.search(
        r"(?ms)^/\*backtest\nstart: 2023-12-17 00:00:00\nend: 2023-12-24 00:00:00\nperiod: 1m\nbasePeriod: 1m\nexchanges: \[\{\"eid\":\"Futures_Binance\",\"currency\":\"BTC_USDT\"\}\]\n\*/",
        raw,
    )
    source_oracles = (
        "pyramiding=15, process_orders_on_close=true, calc_on_every_tick=true, initial_capital=10000",
        "currency = currency.USD, default_qty_value=100, default_qty_type=strategy.percent_of_equity",
        "commission_value=0.05, slippage=2",
        'if whichOffset == "% as offset" and whichSL == "low/high as SL" and enableSL',
        "input.float(1.4, title=",
        "input.float(4, title=",
        "input.float(1.6, title=",
        "ta.barssince(StrongBand_Buy_Alert or MiddleBand_Buy_Alert or SidewaysBand_Buy_Alert) < 2 and barsSinceLastEntry() < 2",
        "ta.barssince(StrongBand_Sell_Alert or MiddleBand_Sell_Alert or SidewaysBand_Sell_Alert) < 2 and barsSinceLastEntry() < 2",
        "strategy.exit(id='longTP-SL', from_entry='Bull', limit=longTP1, stop=longSlLow)",
        "strategy.exit(id='shortTP-SL', from_entry='Bear', limit=shortTP, stop=shortSlLow)",
    )
    assert all(x in code for x in source_oracles)
    assert code.count("strategy.entry(") == 6 and code.count("ta.ema(") == 9
    return row, digest, code


def inputs(folders, fx_path):
    receipt = []
    feed = {}
    for coin in ("BTC", "ETH"):
        vol = list(
            cache_bars(folders, coin + "USDT", "1m", ("2023-12",), MINUTE, receipt)
        )
        bars = [list(row) for row in vol if BEGIN <= row[0] < STOP]
        assert [row[0] for row in bars] == list(range(BEGIN, STOP, MINUTE))
        feed[coin] = bars
    assert sha256(fx_path) == FX_SHA
    rates = []
    for stamp, low, high, opening, close, volume in read(fx_path):
        effective = stamp * 1000 + DAY
        if BEGIN <= effective <= STOP:
            assert (
                0 < low <= min(opening, close) <= max(opening, close) <= high
                and volume > 0
            )
            rates.append([effective, close])
    assert [a for a, _ in sorted(rates)] == list(range(BEGIN, STOP + 1, DAY))
    return [feed, rates], receipt


def extrema(src, n, high):
    out = []
    q = deque()
    for i, v in enumerate(src):
        if v is not None:
            while q and (src[q[-1]] <= v if high else src[q[-1]] >= v):
                q.pop()
            q.append(i)
        while q and q[0] < i + 1 - n:
            q.popleft()
        out.append(src[q[0]] if q and i >= n - 1 else None)
    return out


def average(values, span):
    result = []
    previous = None
    alpha = 2.0 / (span + 1)
    for value in values:
        if value is not None:
            previous = (
                value if previous is None else alpha * value + (1.0 - alpha) * previous
            )
        result.append(previous)
    return result


def sma(src, n):
    return [None] * (n - 1) + [sum(src[i - n : i]) / n for i in range(n, len(src) + 1)]


def since(truth):
    age = None
    out = []
    for flag in truth:
        age = 0 if flag else None if age is None else age + 1
        out.append(age)
    return out


def move(src, sign):
    return [False] + [
        sign * round(b - a, 9) > 0 if a is not None and b is not None else False
        for a, b in pairwise(src)
    ]


def flat(src):
    return [False] + [
        (round(b - a, 9) == 0 if a is not None and b is not None else False)
        for a, b in pairwise(src)
    ]


def fib_extreme(ls, hs, ratio, on):
    return (
        [
            (h - l) * (1 - ratio) + l if l is not None and h is not None else None
            for l, h in zip(ls, hs)
        ]
        if on
        else [None] * len(ls)
    )


def source_signals(tape):
    lo, hi, c = [[x[i] for x in tape] for i in (3, 2, 4)]
    all_bands = []
    for rng, span, ratio_l, ratio_s, short_on in (
        (400, 120, 0.236, 0.382, False),
        (900, 400, 0.618, 0.382, True),
        (4000, 150, 0.6, 0.5, True),
    ):
        ls, hs = extrema(lo, rng, False), extrema(hi, rng, True)
        bull, bear = [
            average(fib_extreme(ls, hs, ratio, on), span)
            for ratio, on in ((ratio_l, True), (ratio_s, short_on))
        ]
        up, down, flat0 = [
            [p or q for p, q in zip(fn(bull), fn(bear))]
            for fn in (lambda a: move(a, 1), lambda a: move(a, -1), flat)
        ]
        chosen = [
            s if down[i] else l if up[i] or flat0[i] else None
            for i, (l, s) in enumerate(zip(bull, bear))
        ]
        all_bands.append((up, down, flat0, chosen))
    bars = len(c)
    output = {}
    for i, (
        band,
        (up, down, side, chosen),
        avg_l,
        avg_s,
        blo,
        bhi,
        hside,
        risk,
    ) in enumerate(
        zip(
            ("Strong", "Middle", "Sideways"),
            all_bands,
            (average(lo, 10), average(c, 20), average(lo, 80)),
            (sma(hi, 10), sma(hi, 9), sma(hi, 20)),
            (15, 10, 150),
            (15, 10, 20),
            (15, 10, 15),
            (0.005, 0.0065, 0.0065),
        )
    ):
        candidates = all_bands[i:]
        agg_up, agg_down, agg_side = (
            [any(block[k][p] for block in candidates) for p in range(bars)]
            for k in range(3)
        )
        wants = [a or b and not d for a, b, d in zip(agg_side, agg_up, agg_down)]
        all_down = [all(block[1][p] for block in candidates) for p in range(bars)]
        sl_win = extrema(lo, blo, False)
        hi_win = extrema(hi, bhi, True)
        cl_win = extrema(chosen, blo, False)
        ch_win = extrema(chosen, hside, True)
        fresh_l, fresh_s = since(down), since(up)
        output[band + "Buy"] = [
            bool(
                chosen[p] is not None
                and avg_l[p] is not None
                and (fresh_l[p] is None or fresh_l[p] > 50)
                and cl_win[p] is not None
                and sl_win[p] is not None
                and cl_win[p] - sl_win[p] < c[p] * risk
                and lo[p] < chosen[p] < c[p]
                and avg_l[p] > chosen[p]
                and wants[p]
            )
            for p in range(bars)
        ]
        output[band + "Sell"] = [
            bool(
                chosen[p] is not None
                and avg_s[p] is not None
                and fresh_s[p] is not None
                and fresh_s[p] > 50
                and hi_win[p] is not None
                and ch_win[p] is not None
                and hi_win[p] - ch_win[p] < c[p] * risk
                and c[p] < chosen[p] < hi[p]
                and avg_s[p] < chosen[p]
                and all_down[p]
                and not wants[p]
            )
            for p in range(bars)
        ]
        output[("Strong Trend", "Normal Trend", "Sidewaysd")[i]] = chosen
    return output


def bracket_price(side, limit, stop, bar, tick):
    stop = (floor(stop / tick + 1e-9) if side > 0 else ceil(stop / tick - 1e-9)) * tick
    limit = (
        ceil(limit / tick - 1e-9) if side > 0 else floor(limit / tick + 1e-9)
    ) * tick
    _, o, h, l, _, _ = bar
    if side * (o - stop) <= 0:
        return o - side * 2 * tick
    if side * (o - limit) >= 0:
        return o
    take = side * ((h if side > 0 else l) - limit) >= 0
    loss = side * ((l if side > 0 else h) - stop) <= 0
    if loss and (not take or side * (o - l - (h - o)) < 0):
        return stop - side * 2 * tick
    return limit if take else None


def replay(tape, gates, tick, fx):
    cash = 10000.0
    holding = []
    side = 0
    bracket = None
    age = {1: 10, -1: 10}
    filled = []
    closed = []
    snapshots = []

    def liquidation(i, price, rate):
        nonlocal cash
        for j, num, origin in holding:
            q = num * QUANT
            gross = side * q * (price - origin) * rate
            ra = fx[tape[j][0] // 86400000 * 86400000]
            fee = q * (origin * ra + price * rate) * FEE
            cash += gross - q * price * rate * FEE
            closed.append((j, i, side * q, origin, price, gross, fee))

    for i, bar in enumerate(tape):
        ts, _, _, _, cl, _ = bar
        rate = fx[ts // 86400000 * 86400000]
        price = bracket_price(side, *bracket, bar, tick) if bracket else None
        if price is not None:
            liquidation(i, price, rate)
            filled.extend(
                (i, "strategy.exit", num * QUANT, price) for _, num, _ in holding
            )
            holding = []
            side = 0
            bracket = None
        latest = {}
        for sign, word in ((1, "Buy"), (-1, "Sell")):
            latest[sign] = any(gates[x + word][i] for x in GATES)
            age[sign] = 0 if latest[sign] else age[sign] + 1
        pos = side * sum(num for _, num, _ in holding) * QUANT
        eq = cash + side * sum(num * QUANT * (cl - px) * rate for _, num, px in holding)
        snapshots.append((pos, eq))
        if holding and age[side] < 2 and i - holding[-1][0] < 2:
            basis = sum(num * px for _, num, px in holding) / sum(
                num for _, num, _ in holding
            )
            stop = (
                min(b[3] for b in tape[max(0, i - 4) : i + 1]) * 0.986
                if side > 0
                else max(b[2] for b in tape[max(0, i - 4) : i + 1]) * 1.014
            )
            target = basis * (1.04 if side > 0 else 0.984)
            bracket = target, stop
        wanted = [sign for sign in (1, -1) if latest[sign]]
        assert len(wanted) <= 1
        if wanted:
            sign = wanted[0]
            if sign == side and len(holding) >= 15:
                continue
            price = round(cl / tick + sign * 2) * tick
            num = floor(eq / (price * rate * (1 + FEE)) / QUANT + 1e-9)
            if num <= 0:
                continue
            total = num
            if sign != side:
                total += sum(n for _, n, _ in holding)
                liquidation(i, price, rate)
                holding = []
                bracket = None
            side = sign
            cash -= num * QUANT * price * rate * FEE
            holding.append((i, num, price))
            filled.append(
                (
                    i,
                    "strategy.long" if sign > 0 else "strategy.short",
                    total * QUANT,
                    price,
                )
            )
    return filled, closed, holding, snapshots


def known(a, b):
    return isclose(a, b, abs_tol=1e-7, rel_tol=1e-11)


def signature(order):
    return (
        order["barIndex"],
        order["direction"],
        round(order["qty"], 7),
        round(order["price"], 6),
    )


def scoped_flows(record, feed, fx):
    _, coin, period, diagnostics, native, plots, _ = record
    assert not diagnostics and not native["diagnostics"]
    bars = feed[coin]
    chart = bars[:WEEK_BARS] if period == "native" else bars[WEEK_BARS:]
    assert len(chart) == WEEK_BARS
    gates = source_signals(chart)
    for name, model in gates.items():
        logged = plots[name]
        assert len(model) == len(logged)
        if name.endswith(("Buy", "Sell")):
            assert all(m == bool(x) for m, x in zip(model, logged, strict=True))
        else:
            assert all(
                (m is None and x is None)
                or (m is not None and x is not None and known(m, x))
                for m, x in zip(model, logged, strict=True)
            )
    tick = 0.1 if coin == "BTC" else 0.01
    orders, lots, opened, snapshots = replay(chart, gates, tick, fx)
    positive_orders = [signature(x) for x in native["orders"] if abs(x["qty"]) > 1e-9]
    expected = [(i, name, round(q, 7), round(p, 6)) for i, name, q, p in orders]
    failures = [
        (i, a, b) for i, (a, b) in enumerate(zip(expected, positive_orders)) if a != b
    ]
    dust = [x for x in native["trades"] if abs(x["qty"]) < 1e-9]
    if (coin, period) == ("ETH", "native"):
        offset, model, raw = failures[0]
        assert offset == 62 and model == (4956, "strategy.long", 3.265, 2215.04)
        assert raw == (5525, "strategy.exit", 2.972, 2182.37)
        (residual,) = tuple(
            x for x in dust if x["entryBarIndex"] == 3749 and x["exitBarIndex"] == 5525
        )
        assert 0 < residual["qty"] < 1e-9
        assert all(
            known(pos, plots["AggPos"][i]) and known(eq, plots["MarkedEquity"][i])
            for i, (pos, eq) in enumerate(snapshots[:4957])
        )
        witness = {
            "first_different_bar": 4956,
            "first_different_bar_open_ms": chart[4956][0],
            "source_model_order": model,
            "native_next_order": raw,
            "native_residual_consumes_slot": residual,
        }
    else:
        assert expected == positive_orders
        positives = [x for x in native["trades"] if abs(x["qty"]) > 1e-9]
        for modeled, expected_lot in zip(lots, positives, strict=True):
            i, j, q, entry, exit, gross, fee = modeled
            assert (
                expected_lot["entryBarIndex"] == i and expected_lot["exitBarIndex"] == j
            )
            assert known(q, expected_lot["qty"]) and known(
                entry, expected_lot["entryPrice"]
            )
            assert known(exit, expected_lot["exitPrice"]) and known(
                gross - fee, expected_lot["profit"]
            )
        assert all(
            known(pos, plots["AggPos"][i]) and known(eq, plots["MarkedEquity"][i])
            for i, (pos, eq) in enumerate(snapshots)
        )
        witness = None
    flow = []
    for i, j, q, entry, exit, gross, fee in lots:
        start, end = chart[i][0], chart[j][0]
        turnover = abs(q) * (
            entry * fx[start // DAY * DAY] + exit * fx[end // DAY * DAY]
        )
        assert known(turnover * FEE, fee)
        flow.append((end, gross, fee, turnover * EXECUTION))
    return (
        flow,
        len(opened),
        {
            "coin": coin,
            "window": period,
            "source_orders": len(orders),
            "pine_positive_orders": len(positive_orders),
            "source_closes": len(lots),
            "native_raw_closes": len(native["trades"]),
            "native_dust_closes": len(dust),
            "source_open": len(opened),
            "first_difference": witness,
        },
    )


def stage(args, source, feed):
    args.work.mkdir(parents=True, exist_ok=True)
    (args.work / "round47-5230.pine").write_text(source, encoding="utf-8", newline="\n")
    write(args.work / "round47-probe-feeds.json", feed)
    copy2(Path(__file__).with_name(PROBE), args.work / PROBE)


def report(args, row, digest, code, feed, files):
    work = args.work
    engine = work / "priced-runtime/pine_compat/pine_compat.pyd"
    isolated = read(work / "round3-isolation-python.json")
    assert all(
        isolated[k][0] == "PermissionError" for k in ("file_error", "network_error")
    )
    assert sha256(engine) == NATIVE_BINARY_HASH
    probe = Path(__file__).with_name(PROBE)
    assert sha256(work / PROBE) == sha256(probe)
    assert (work / "round47-5230.pine").read_text(encoding="utf-8") == code
    staged = read(work / "round47-probe-feeds.json")
    assert staged == feed
    runs = work / "round47-5230-rounded.json"
    ctrl = work / "round47-5230-probe.json"
    corrected = read(runs)
    samples = read(ctrl)
    assert len(samples) == 8 and len(corrected) == 4
    assert len({row[-1] for row in corrected}) == 1
    assert all(not row[3] and not row[4]["diagnostics"] for row in samples)
    assert len({(record[1], record[2]) for record in corrected}) == 4
    book, details = [], []
    pooled = {tag: ([], 0) for tag in LABEL}
    common = {
        "id": IDENT,
        "source": row["source"],
        "source_sha256": digest,
        "executed_source_sha256": corrected[0][-1],
        "group": "FMZ Pine · Documented Fibonacci and fixed-point lots",
        "currency": "USD",
        "quote_currency": "USD",
        "interval": "1m",
        "archive_interval": "1m",
        "market_data": "Official Binance USD-M 1m; prior Coinbase USDT/USD close",
        "exit": "Stored five-bar range stop, period take profit, or signal reversal",
    }
    for record in corrected:
        coin, tag = record[1:3]
        flow, n_open, summary = scoped_flows(record, feed[0], dict(feed[1]))
        book.append(
            {
                **common,
                "period": LABEL[tag],
                "market": coin + "USDT",
                **summarize(flow, n_open, CAPITAL),
            }
        )
        all_lots, all_open = pooled[tag]
        pooled[tag] = (all_lots + flow, all_open + n_open)
        details.append(summary)
    for tag, (flow, open_n) in pooled.items():
        book.append(
            {
                **common,
                "period": LABEL[tag],
                "market": "BTCUSDT + ETHUSDT",
                **summarize(flow, open_n, 2 * CAPITAL),
            }
        )
    assert tuple(r["source_closes"] for r in details) == (19, 40, 58, 64)
    assert tuple(r["source_open"] for r in details) == (15, 5, 14, 0)
    assert sum(r["native_dust_closes"] for r in details) == 7
    status = "Tested · FMZ integer-lot Fibonacci model"
    write(
        args.out,
        {
            "baseline_coverage_sha256": sha256(args.baseline),
            "archive_sha256": FMZ_SHA256,
            "document_sha256": digest,
            "native_runtime_sha256": NATIVE_BINARY_HASH,
            "offline_isolation": isolated,
            "worker_sha256": sha256(probe),
            "rounded_runtime_receipt_sha256": sha256(runs),
            "ema_sensitivity_receipt_sha256": sha256(ctrl),
            "providers": files,
            "fx_provider": {"sha256": FX_SHA, "url": FX_LINK},
            "model_costs": {
                "author_fee_per_side": FEE,
                "author_tick_slippage_market_stop": 2,
                "buffer_per_side": EXECUTION,
            },
            "verification": {
                "independent_signal_bars": 4 * WEEK_BARS,
                "gates_per_bar": 6,
                "source_comparison": details,
            },
            "ema_sensitivity": [
                {
                    "variant": "literal built-in EMA" if literal else "first-value EMA",
                    "asset": coin,
                    "window": tag,
                    "native_raw_closed_lots": len(trader["trades"]),
                    "source_sha256": executed,
                }
                for literal, coin, tag, _, trader, _, executed in samples
            ],
            "method": [
                "The archive uses one-minute chart and base data, with three distinct rolling Fibonacci lengths. Inputs and six order gates follow the body; no saved inputs alter the defaults. FMZ's documented first-value EMA and nine-decimal Pine comparison control replace differing local EMA startup and near-flat slope handling. The independent rolling extremes, EMA recurrences and six decisions match all 40,320 annotated bars.",
                "Market entries and reversals fill on the signal candle close with two directional ticks. Exits activate from the applicable source order after close, with five-bar 1.4% stop, long 4% or short 1.6% take profit, directional tick quantization and gap handling. The independently reconstructed closed-lot USD ledger and marked equity match every positive native fill in three of four scopes.",
                "Archived ETH differs after a native residual of approximately 1.8e-15 contracts consumes one pyramiding slot. The independent broker uses integer counts of the 0.001-lot step and a maximum of 15 actual lots. Its first extra valid entry is 3.265 ETH at 2215.04. This integer-lot model supplies all rows. Tiny native dust closes do not contribute to metrics.",
                "Starting account model is $10,000 each. Fees follow the authored 0.05% per side with daily prior Coinbase close for USD conversion. Additional execution allowance stays separately visible. Terminal holdings remain open. The test excludes funding, financing, liquidation and exchange queue priority; it models historical OHLC order timing and does not qualify the strategy for paper or live execution.",
            ],
            "references": [
                "https://www.fmz.com/strategy/436513",
                "https://www.fmz.com/doc/9293",
                "https://www.tradingview.com/pine-script-docs/language/type-system/#float",
                "https://www.tradingview.com/pine-script-docs/concepts/strategies/#process_orders_on_close",
                "https://github.com/binance/binance-public-data",
            ],
            "coverage": [
                [
                    IDENT,
                    status,
                    "First-value EMA and documented slope precision checked against six independent gates on 40,320 original-resolution BTC/ETH bars. Independently rebuilt USD fills, sizing, brackets and equity, using integer 0.001-lot accounting to remove a native pyramiding dust discrepancy.",
                ]
            ],
            "results": book,
        },
    )
    print(
        f"{len(book)} workbook rows, {sum(r['source_closes'] for r in details)} settled nonzero lots, four verified historical scopes."
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("stage", "report"))
    for name in ("archive", "baseline", "work", "fx", "out"):
        p.add_argument(name, type=Path)
    p.add_argument("--daily", nargs="+", type=Path, required=True)
    args = p.parse_args()
    r, h, code = source_record(args.archive, args.baseline)
    feed, files = inputs(args.daily, args.fx)
    if args.mode == "stage":
        stage(args, code, feed)
    else:
        report(args, r, h, code, feed, files)


if __name__ == "__main__":
    main()
