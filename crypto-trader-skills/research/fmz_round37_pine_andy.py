"""Verify authored momentum-rotation signals and the original mixed order clocks."""

from __future__ import annotations

import argparse
import re
from itertools import batched
from math import floor, fsum
from pathlib import Path
from shutil import copy2
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, aggregate, date_ms, sha256
from research.fmz_round7_pine import EXECUTION, FEE, summarize
from research.fmz_round18_pine_qqe import executable_lines
from research.fmz_round19_pine_broker import equal
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH
from research.fmz_round28_pine_callback import cache_bars

IDENT = 3277
GROUP = "FMZ Pine · ATR rotation and verified 15m limit/market order chronology"
LABEL = {"native": "FMZ native window", "next": "Next equal window"}
TICKS = 900_000
HOUR = 3_600_000
CAPITAL = 10_000
LOT = 0.001
MODES = ("display-off", "prefix", "first", "magnified")
ORDER_ID = {1: "Andy Buy", -1: "Andy Short"}
DIRECTION = {1: "strategy.long", -1: "strategy.short"}
PRODUCER = "fmz_round37_pine_andy_probe.py"


def record(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (row,) = (r for r in read(baseline)["disposition"] if r["id"] == IDENT)
    assert row["status"].startswith("Pending")
    with ZipFile(archive) as source:
        ((_, datum, doc, digest),) = documents(source, {IDENT: row})
    (raw,) = re.findall(r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", doc)
    fields = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)", raw
        )
    )
    assert fields == {
        "start": "2023-10-17 00:00:00",
        "end": "2023-11-16 00:00:00",
        "period": "1h",
        "basePeriod": "15m",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    assert "//@version=5" in raw
    active = "\n".join(executable_lines(raw))
    for witness in (
        "initial_capital = 10000, default_qty_type = strategy.cash,default_qty_value = 10000)",
        "pyramiding = 1",
        "ema_short = ta.ema(close,5)",
        "ema_middle = ta.ema(close,20)",
        "ema_long = ta.ema(close,40)",
        "bull_cycle = cycle_1 or cycle_2 or cycle_3",
        "bear_cycle = cycle_4 or cycle_5 or cycle_6",
        "a = input(2,",
        "c = input(7,",
        "h = false",
        "nLoss = a * xATR",
        "atr = ta.atr(14)",
        "atr_length = input.int(25)",
        "atr_rsi = ta.rsi(atr,atr_length)",
        "atr_valid = atr_rsi>50",
        "long_condition =  buy and bull_cycle and atr_valid",
        "short_condition =  sell and bear_cycle and atr_valid",
        'strategy.entry("Andy Buy",strategy.long, limit=close,comment="Andy Buy Here")',
        'strategy.entry("Andy Short",strategy.short, limit=close,comment="Andy short Here")',
        'strategy.close("Andy Buy",comment="Andy Buy Out")',
        'strategy.close("Andy Short",comment="Andy short Out")',
        "bar_pnl = eq / eq[1] - 1",
    ):
        assert witness in active, witness
    head, sep, tail = raw.partition(
        "// MONTHLY TABLE PERFORMANCE - Developed by @QuantNomad"
    )
    assert sep and "strategy.entry" in head
    assert set(re.findall(r"strategy\.(\w+)", tail)) == {"equity"}
    assert "commission_" not in active
    return datum, digest, fields, raw.encode()


def feed_data(hourly, base):
    start, stop = map(date_ms, ("2023-10-17", "2023-11-16"))
    end = 2 * stop - start
    months = ("2023-10", "2023-11", "2023-12")
    bags, manifest = {}, []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        basic = [
            r
            for r in cache_bars(base, symbol, "15m", months, TICKS, manifest)
            if start <= r[0] < end
        ]
        bars = [
            r
            for r in cache_bars(hourly, symbol, "1h", months, HOUR, manifest)
            if start <= r[0] < end
        ]
        assert [r[0] for r in basic] == list(range(start, end, TICKS))
        assert [r[0] for r in bars] == list(range(start, end, HOUR))
        for period, lo, hi in (("native", start, stop), ("next", stop, end)):
            bags.setdefault(period, {})[symbol] = {
                "chart": [list(r) for r in bars if lo <= r[0] < hi],
                "base": [list(r) for r in basic if lo <= r[0] < hi],
            }
    return manifest, bags


def stage(archive, baseline, work, hourly, base):
    _, _, _, raw = record(archive, baseline)
    _, bags = feed_data(hourly, base)
    (work / "r37-andy-source.pine").write_bytes(raw)
    write(work / "r37-andy-feeds.json", bags)
    copy2(Path(__file__).with_name(PRODUCER), work / "r37_andy_probe.py")


PLOTS = (
    "Slow EMA",
    "Medium EMA",
    "Fast EMA",
    "ATR stop",
    "ATR RSI",
    "Long",
    "Short",
    "Position",
)


def ema(x, n, first):
    if not first:
        gap = [None] * (n - 1)
        prior = fsum(x[:n]) / n
        i = n
    else:
        gap = []
        prior = x[0]
        i = 1
    alpha = 2 / (n + 1)
    out = [*gap, prior]
    for val in x[i:]:
        prior = alpha * val + (1 - alpha) * prior
        out.append(prior)
    return out


def rma(x, n):
    start = next(j for j, a in enumerate(x) if a is not None)
    cut = start + n - 1
    out = [None] * cut
    prior = fsum(x[start : cut + 1]) / n
    out.append(prior)
    for val in x[cut + 1 :]:
        prior = (prior * (n - 1) + val) / n
        out.append(prior)
    return out


def rsi(x, n):
    diff = [
        None if b is None or a is None else a - b
        for a, b in zip(x, [None, *x[:-1]], strict=True)
    ]
    up = rma([None if a is None else max(0, a) for a in diff], n)
    dn = rma([None if a is None else max(0, -a) for a in diff], n)
    return [
        None if a is None else 100 if b == 0 else 100 - (100 / (1 + a / b))
        for a, b in zip(up, dn, strict=True)
    ]


def indicators(chart, first):
    prices = [r[4] for r in chart]
    slow, mid, fast = [ema(prices, n, first) for n in (40, 20, 5)]
    tr = []
    for i, (_, _, h, l, c, _) in enumerate(chart):
        pre = prices[i - 1] if i else c
        tr.append(max(h - l, abs(h - pre), abs(l - pre)))
    move = rma(tr, 7)
    atr = rsi(rma(tr, 14), 25)
    out = []
    prev = None
    for i, (m, s, md, f, c) in enumerate(
        zip(move, slow, mid, fast, prices, strict=True)
    ):
        old = prev or 0
        past = prices[i - 1] if i else None
        if m is None:
            stop = None
        elif c > old and past is not None and past > old:
            stop = max(old, c - 2 * m)
        elif c < old and past is not None and past < old:
            stop = min(old, c + 2 * m)
        else:
            stop = c - 2 * m if c > old else c + 2 * m
        bull = s is not None and (f > md > s or md > f > s or md > s > f)
        bear = s is not None and (s > md > f or s > f > md or f > s > md)
        valid = atr[i] is not None and atr[i] > 50
        buy = valid and bull and prev is not None and c > stop and past <= prev
        sell = valid and bear and prev is not None and c < stop and past >= prev
        out.append((s, md, f, stop, atr[i], buy, sell))
        prev = stop
    return out


def check_fields(x, y):
    return all(equal(a, b) for a, b in zip(x, y, strict=True))


def check_indicators(tape, receipt, first):
    state = indicators(tape["chart"], first)
    actual = zip(*(receipt["plots"][p] for p in PLOTS[:-1]), strict=True)
    assert all(check_fields(a, b) for a, b in zip(state, actual, strict=True))
    return state


def limit_fill(slices, side, price):
    for row in slices:
        stamp, opening, high, low = row[:4]
        if (opening - price) * side <= 0:
            return stamp, opening, "opening cross"
        if low <= price if side > 0 else high >= price:
            return stamp, price, "first verified range touch"
    raise AssertionError("A submitted order remains live past the audited next hour.")


def replay(tape, state):
    chart, base = tape["chart"], tape["base"]
    mismatch = {
        i
        for i, (large, small) in enumerate(zip(chart, aggregate(base, 4), strict=True))
        if tuple(large[:5]) != tuple(small[:5])
    }
    entries, closed, witnesses, marks, positions = [], [], [], [], []
    cash = CAPITAL
    active = pending = None
    for i, (candle, hourly, signals) in enumerate(
        zip(chart, batched(base, 4, strict=True), state, strict=True)
    ):
        t, o, _, _, c, _ = candle
        if i in mismatch:
            assert pending is None and not any(signals[-2:])
        if pending is not None:
            side, threshold = pending
            if active:
                old_side, open_i, q, paid = active
                assert old_side == -side
                entries.append(
                    (
                        f"Close entry(s) order {ORDER_ID[old_side]}",
                        i,
                        "strategy.close",
                        q,
                        o,
                    )
                )
                closed.append((old_side, open_i, i, q, paid, o))
                cash += old_side * q * o
            subtime, price, rule = limit_fill(hourly, side, threshold)
            quant = floor(CAPITAL / price / LOT + 1e-9) * LOT
            entries.append((ORDER_ID[side], i, DIRECTION[side], quant, price))
            witnesses.append(
                {
                    "chart_timestamp": t,
                    "first_eligible_15m_start": subtime,
                    "price": price,
                    "limit": threshold,
                    "rule": rule,
                    "side": side,
                }
            )
            active = (side, i, quant, price)
            cash -= side * quant * price
        buy, sell = signals[-2:]
        side = int(buy) - int(sell)
        assert not (buy and sell)
        holding = active[0] if active else 0
        pending = (side, c) if side and side != holding else None
        qty = active[0] * active[2] if active else 0
        marks.append((cash, qty * c, cash + qty * c))
        positions.append(qty)
    assert pending is None
    return entries, closed, marks, positions, witnesses, mismatch


def verify(tape, receipt):
    state = check_indicators(tape, receipt, True)
    orders, closed, marks, positions, witness, mismatch = replay(tape, state)
    strategy = receipt["strategy"]
    chart = tape["chart"]
    assert check_fields(positions, receipt["plots"]["Position"])
    assert not strategy["diagnostics"]
    assert {
        int(re.search(r"bar (\d+)", d["message"])[1])
        for d in receipt["diagnostics"]
        if d["code"] == "W_MAGNIFIER_FALLBACK"
    } == mismatch
    assert len(receipt["diagnostics"]) == len(mismatch)
    for (order_id, i, side, qty, price), fill in zip(
        orders, strategy["orders"], strict=True
    ):
        assert (
            fill["id"],
            fill["barIndex"],
            fill["direction"],
            fill["price"],
            fill["time"],
        ) == (order_id, i, side, price, chart[i][0])
        assert equal(qty, fill["qty"])
    for i, (mark, actual) in enumerate(zip(marks, strategy["equity"], strict=True)):
        assert i == actual["barIndex"]
        assert check_fields(
            (*mark, mark[-1] - CAPITAL),
            (actual[k] for k in ("cash", "marketValue", "equity", "netProfit")),
        )
    cashflows = []
    for (side, i, j, qty, paid, received), fill in zip(
        closed, strategy["trades"], strict=True
    ):
        assert fill["id"] == ORDER_ID[side]
        assert (fill["entryTime"], fill["exitTime"]) == (chart[i][0], chart[j][0])
        assert check_fields(
            (i, j, side * qty, paid, received),
            (
                fill[k]
                for k in (
                    "entryBarIndex",
                    "exitBarIndex",
                    "qty",
                    "entryPrice",
                    "exitPrice",
                )
            ),
        )
        gross = side * qty * (received - paid)
        assert equal(fill["profit"], gross)
        turnover = qty * (paid + received)
        cashflows.append((chart[j][0], gross, turnover * FEE, turnover * EXECUTION))
    return (
        cashflows,
        int(bool(positions[-1])),
        {
            "chart_bars": len(chart),
            "lower_bars": len(tape["base"]),
            "closed": len(closed),
            "filled_orders": len(orders),
            "ending_marked_equity_before_external_costs": marks[-1][-1],
            "terminal_qty": positions[-1],
            "entry_limit_receipts": witness,
            "fallback_no_order_chart_opens": [chart[i][0] for i in sorted(mismatch)],
        },
    )


def finalize(archive, baseline, work, hourly, base, output):
    datum, digest, settings, raw = record(archive, baseline)
    manifest, bags = feed_data(hourly, base)
    staged = work / "r37-andy-source.pine"
    tape = work / "r37-andy-feeds.json"
    probe = Path(__file__).with_name(PRODUCER)
    assert raw == staged.read_bytes() and read(tape) == bags
    assert probe.read_bytes() == (work / "r37_andy_probe.py").read_bytes()
    assert (
        sha256(work / "priced-runtime/pine_compat/pine_compat.pyd")
        == NATIVE_BINARY_HASH
    )
    isolation = read(work / "round3-isolation-python.json")
    assert all(
        isolation[k][0] == "PermissionError" for k in ("file_error", "network_error")
    )
    error = work / "r37-andy-literal-error.txt"
    literal_error = error.read_text().splitlines()[-1]
    assert (
        literal_error
        == "ValueError: array index 0 is out of bounds for array of size 0"
    )
    paths = [staged, tape, probe, error]
    hashes, receipts = {}, {}
    for mode in MODES:
        path = work / f"r37-andy-{mode}.json"
        assert (work / f"r37-andy-{mode}.exit").read_text().strip() == "0"
        records = read(path)
        index = {(item["period"], item["market"]): item for item in records}
        assert len(records) == len(index) == 4
        (hashes[mode],) = {item["executed_source_sha256"] for item in records}
        paths.append(path)
        receipts[mode] = index
    assert len(set(hashes.values())) == len(MODES)
    meta = {
        "id": IDENT,
        "name": datum["name"],
        "source": datum["source"],
        "source_sha256": digest,
        "executed_source_sha256": hashes["magnified"],
        "group": GROUP,
        "interval": "1h",
        "archive_interval": "1h",
        "quote_currency": "USDT",
        "comparison_fee": FEE,
        "market_data": "Checksummed Binance USD-M 1h/15m candles",
        "exit": "Opposite gated signal creates a market close and reverse limit order",
    }
    rows, counts = [], []
    for period, assets in bags.items():
        whole, outstanding = [], 0
        for market, chart in assets.items():
            scope = (period, market)
            result = {mode: receipts[mode][scope] for mode in MODES}
            for mode, r in result.items():
                check_indicators(chart, r, mode in ("first", "magnified"))
                if mode != "magnified":
                    assert not r["diagnostics"] and not r["strategy"]["diagnostics"]
            for field in ("plots", "strategy"):
                assert result["display-off"][field] == result["prefix"][field]
            for field in ("orders", "trades", "position", "equity"):
                sample = result["magnified"]["strategy"][field]
                assert all(
                    result[m]["strategy"][field] == sample for m in ("prefix", "first")
                )
            flows, terminal, audit = verify(chart, result["magnified"])
            counts.append({"period": LABEL[period], "market": market, **audit})
            whole.extend(flows)
            outstanding += terminal
            rows.append(
                {
                    **meta,
                    "period": LABEL[period],
                    "market": market,
                    **summarize(flows, terminal, CAPITAL),
                }
            )
        rows.append(
            {
                **meta,
                "period": LABEL[period],
                "market": "BTCUSDT + ETHUSDT",
                **summarize(whole, outstanding, 2 * CAPITAL),
            }
        )
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(baseline),
            "archive_sha256": FMZ_SHA256,
            "pine_compat_binary_sha256": NATIVE_BINARY_HASH,
            "isolation_probe": isolation,
            "source_audit": {
                "document_sha256": digest,
                "archive_settings": settings,
                "unmodified_literal_runtime_error": literal_error,
                "display_off_exact_order_equivalence": True,
                "first_price_vs_engine_sma_seed_exact_order_equivalence": True,
                "standard_vs_magnified_exact_order_equivalence": True,
                "executed_variants_sha256": hashes,
                "source_order_fee": 0,
                "native_spot_or_live_order_qualification": False,
            },
            "provider_archives": manifest,
            "artifacts": {r.name: sha256(r) for r in paths},
            "per_case_fill_audit": counts,
            "method": [
                "The archived v5 monthly reporting table errors in the isolated literal run. Turning off its own display setting reproduces exactly the active trading prefix. The suffix reads strategy equity but contains no order instructions. None of the four order calls or signal defaults were changed.",
                "Independent ATR7 and ATR14 Wilder averages, the 2×ATR trail, RSI25 of ATR14, and the 5/20/40 EMA ordering match every chart-bar signal. A separate first-price EMA version and the native SMA-seeded variant produce the same orders, trades, and equity in these four histories.",
                "An independent broker replays market closes at the next hourly opening print. Each submitted limit crosses that opening print or reaches its price in the first eligible official 15-minute candle. It checks the better-price rule, source cash sizing and the 0.001 quantity-step comparison assumption. Candle range touches model execution without order-queue information.",
                "Two Bitcoin chart hours disagree with the 15-minute reconstruction on 2023-11-10. Their source positions remain marked to native hourly prices. The audit proves neither hour has an outstanding order, new signal, or fill.",
                "Native zero-commission order math is preserved. Workbook net figures apply the project comparison commission of 0.059% per side and separate 0.03% per-side execution buffer to settled trades. No position is closed synthetically at window end, and the small sample does not qualify the strategy for promotion.",
            ],
            "references": [
                "https://www.tradingview.com/pine-script-docs/v5/concepts/strategies/",
                "https://www.tradingview.com/support/solutions/43000628599-strategy-properties/",
                "https://www.tradingview.com/pine-script-reference/v5/#fun_ta.ema",
                "https://github.com/binance/binance-public-data",
            ],
            "coverage": [
                [
                    IDENT,
                    f"Tested · {GROUP}",
                    "Turned off the archived reporting-only table, verified unchanged orders against the trading prefix, and independently matched 15m price eligibility, market closes, cash quantities and equity.",
                ]
            ],
            "results": rows,
        },
    )
    closed = sum(item["closed"] for item in counts)
    print(
        f"Verified {IDENT}: {len(rows)} workbook results, {closed} closed lots, {len(MODES) * len(counts)} successful scope runs."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "finalize"))
    for name in ("archive", "baseline", "work", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for name in ("hourly", "base"):
        parser.add_argument(f"--{name}", type=Path, nargs="+", required=True)
    args = parser.parse_args()
    common = (args.archive, args.baseline, args.work, args.hourly, args.base)
    if args.mode == "stage":
        stage(*common)
    else:
        finalize(*common, args.output)


if __name__ == "__main__":
    main()
