"""Verify archived ABCD entries, causal trailing signal exits and source timestamps."""

from __future__ import annotations

import argparse
import re
from math import isclose
from pathlib import Path
from shutil import copy2
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, aggregate, date_ms, sha256
from research.fmz_round7_pine import EXECUTION, FEE, summarize
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH
from research.fmz_round28_pine_callback import cache_bars

IDENT = 2575
START, CUT, STOP = map(date_ms, ("2024-02-11", "2024-02-18", "2024-02-25"))
HOUR = 3_600_000
QUARTER = HOUR // 4
CAPITAL = 1_000_000
LABEL = {"native": "FMZ native window", "next": "Next equal window"}
WORKER = "fmz_round52_pine_abcd_probe.py"


def source_record(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (row,) = tuple(r for r in read(baseline)["disposition"] if r["id"] == IDENT)
    assert row["status"].startswith("Pending")
    with ZipFile(archive) as book:
        ((_, _, doc, digest),) = documents(book, {IDENT: row})
    (raw,) = re.findall(r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", doc)
    fields = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)", raw
        )
    )
    assert fields == {
        "start": "2024-02-11 00:00:00",
        "end": "2024-02-18 00:00:00",
        "period": "1h",
        "basePeriod": "15m",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    stage, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", raw)
    assert n == 1
    for token in (
        "// @version=4",
        "lapos_x = timenow + round(change(time)*12)",
        "filterBW = input(false",
        "valuewhen(zigzag, zigzag, 4)",
        "abc >= 0.382 and abc <= 0.886",
        "bcd >= 1.13 and bcd <= 2.618",
        'strategy.entry("Long", 1, when=isLong)',
        'strategy.entry("Short", 0,  when=isShort)',
        'strategy.close("Long", when=close_long)',
        'strategy.close("Short", when=close_short)',
        "plot(zigzag, title= 'ZigZag', color=color.black, offset=-2)",
    ):
        assert token in stage
    assert len(re.findall(r"\blapos_x\b", stage)) == 1
    assert re.search(r"\b(?:security|request\.security)\s*\(", stage) is None
    return row, digest, fields, stage


def inputs(hourly, quarter):
    tape = {}
    receipts = []
    for coin in ("BTC", "ETH"):
        market = coin + "USDT"
        hours = {
            r[0]: list(r)
            for r in cache_bars(hourly, market, "1h", ("2024-02",), HOUR, receipts)
        }
        subs = {
            r[0]: list(r)
            for r in cache_bars(quarter, market, "15m", ("2024-02",), QUARTER, receipts)
        }
        for tag, left, right in (("native", START, CUT), ("next", CUT, STOP)):
            chart = [hours[t] for t in range(left, right, HOUR)]
            lower = [subs[t] for t in range(left, right, QUARTER)]
            assert len(chart) == 168
            assert all(
                list(x[:5]) == y[:5] and isclose(x[5], y[5], rel_tol=1e-12)
                for x, y in zip(aggregate(lower, 4), chart, strict=True)
            )
            tape.setdefault(tag, {})[coin] = chart
    return {"data": tape, "archive": receipts}


def source_gates(bars):
    hi = [x[2] for x in bars]
    lo = [x[3] for x in bars]
    last_top = last_bottom = None
    pivots = []
    prev_bull = prev_bear = None
    last_long = last_short = None
    latest = 0
    trail = [[0.0], [999999.0], [0.0], [999999.0]]
    triggers = [False] * 4
    for i, (_, _, h, l, _, _) in enumerate(bars):
        top = (
            i >= 4
            and hi[i - 4] < hi[i - 2]
            and hi[i - 3] <= hi[i - 2]
            and hi[i - 2] >= hi[i - 1]
            and hi[i - 2] > h
        )
        bottom = (
            i >= 4
            and lo[i - 4] > lo[i - 2]
            and lo[i - 3] >= lo[i - 2]
            and lo[i - 2] <= lo[i - 1]
            and lo[i - 2] < l
        )
        if last_top is not None and last_bottom is not None:
            if top and last_top < last_bottom:
                pivots.append(hi[i - 2])
            elif bottom and last_top > last_bottom:
                pivots.append(lo[i - 2])
        if top:
            last_top = i
        if bottom:
            last_bottom = i
        bull = bear = None
        if len(pivots) >= 4:
            a, b, c0, d = pivots[-4:]
            abc = abs(b - c0) / abs(a - b) if a != b else None
            bcd = abs(c0 - d) / abs(b - c0) if b != c0 else None
            pattern = (
                abc is not None
                and bcd is not None
                and 0.382 <= abc <= 0.886
                and 1.13 <= bcd <= 2.618
            )
            bull = pattern and d < c0
            bear = pattern and d > c0
        long = bool(bull and not prev_bull)
        short = bool(bear and not prev_bear)
        prev_bull, prev_bear = bull, bear
        if long:
            last_long = i
        if short:
            last_short = i
        old = latest
        latest = (
            0
            if last_long is None or last_short is None
            else 1
            if last_short < last_long
            else -1
            if last_short > last_long
            else 0
        )
        if latest > 0:
            entry = bars[last_long][4]
            triggers[0] |= h >= entry * 1.02
            triggers[2] |= h >= entry * 1.03
        if latest < 0:
            entry = bars[last_short][4]
            triggers[1] |= l <= entry * 0.98
            triggers[3] |= l <= entry * 0.97
        oldtrail = [j[-1] for j in trail]
        newtrail = [max(l * 0.97, j[-1]) if latest > 0 else 0 for j in trail[:1]]
        newtrail.extend(
            (
                min(h * 1.03, trail[1][-1]) if latest < 0 else 999999,
                max(h * 1.01, trail[2][-1]) if latest > 0 else 0,
                min(l * 0.99, trail[3][-1]) if latest < 0 else 999999,
            )
        )
        slope = (
            (l, lo[i - 1], -1),
            (h, hi[i - 1], 1),
            (h, hi[i - 1], 1),
            (l, lo[i - 1], -1),
        )
        exits = []
        for idx, (cur, prev, sign) in enumerate(slope):
            vals = trail[idx]
            age = latest == (1 if idx % 2 == 0 else -1)
            exits.append(
                bool(
                    i >= 2
                    and age
                    and triggers[idx]
                    and sign * (cur - oldtrail[idx]) > 0
                    and sign * (prev - vals[-2]) <= 0
                )
            )
            vals.append(newtrail[idx])
        if latest * old < 0:
            triggers = [False] * 4
        yield long, short, exits[0] or exits[2], exits[1] or exits[3]


def ledger(chart, gates):
    direction = 0
    cash = 1e6
    entry = None
    next_phase = None
    orders = []
    trades = []
    marks = []
    for i, (_, op, _, _, cl, _) in enumerate(chart):
        if next_phase is not None:
            if direction:
                j, openpx = entry
                pnl = direction * (op - openpx)
                trades.append(
                    (
                        "Long" if direction > 0 else "Short",
                        j,
                        i,
                        direction,
                        openpx,
                        op,
                        pnl,
                    )
                )
                cash += pnl
            orders.append(
                (
                    i,
                    "strategy.long"
                    if next_phase == 1
                    else "strategy.short"
                    if next_phase == -1
                    else "strategy.close",
                    op,
                    1 + (int(bool(direction)) if next_phase else 0),
                )
            )
            direction = next_phase
            entry = (i, op) if direction else None
        long, short, out_l, out_s = gates[i]
        next_phase = (
            1
            if long and direction != 1
            else -1
            if short and direction != -1
            else 0
            if direction == 1 and out_l or direction == -1 and out_s
            else None
        )
        equity = cash + direction * (cl - entry[1]) if entry else cash
        marks.append([direction, equity])
    return orders, trades, marks, int(bool(direction))


def verify(record, chart):
    window, coin, variant, issues, native, plots, _ = record
    assert not issues and not native["diagnostics"]
    gates = list(source_gates(chart))
    names = ("Long gate", "Short gate", "Long exit gate", "Short exit gate")
    assert gates == list(zip(*(plots[key] for key in names), strict=True)), (
        window,
        coin,
        variant,
    )
    orders, trades, marks, unsettled = ledger(chart, gates)
    assert orders == [
        (x["barIndex"], x["direction"], x["price"], x["qty"]) for x in native["orders"]
    ]
    cashflows = []
    for expected, x in zip(trades, native["trades"], strict=True):
        assert expected == (
            x["id"],
            x["entryBarIndex"],
            x["exitBarIndex"],
            x["qty"],
            x["entryPrice"],
            x["exitPrice"],
            x["profit"],
        )
        _, i, j, _, entry, exit, gross = expected
        assert (x["entryTime"], x["exitTime"]) == (chart[i][0], chart[j][0])
        volume = entry + exit
        cashflows.append((chart[j][0], gross, volume * FEE, volume * EXECUTION))
    assert all(
        a == p and isclose(b, q, rel_tol=1e-12, abs_tol=1e-8)
        for (a, b), p, q in zip(marks, plots["Pos"], plots["Eq"], strict=True)
    )
    assert unsettled == 1
    return cashflows, unsettled


def stage(args, code, pack):
    (args.work / "round47-2575.pine").write_text(code, encoding="utf8", newline="\n")
    write(args.work / "round47-2575-feeds.json", pack)
    copy2(Path(__file__).with_name(WORKER), args.work / WORKER)


def report(args, root, digest, fields, code, pack):
    work = args.work
    worker = Path(__file__).with_name(WORKER)
    receipt = work / "round47-2575-probe.json"
    isolation = read(work / "round3-isolation-python.json")
    assert (
        sha256(work / "priced-runtime/pine_compat/pine_compat.pyd")
        == NATIVE_BINARY_HASH
    )
    assert sha256(work / WORKER) == sha256(worker)
    assert all(
        isolation[k][0] == "PermissionError" for k in ("file_error", "network_error")
    )
    assert (work / "round47-2575.pine").read_text(encoding="utf8") == code
    assert read(work / "round47-2575-feeds.json") == pack
    rows = read(receipt)
    assert len(rows) == 8
    snapshots, hashes = {}, {}
    for record in rows:
        window, coin, variant, *_ = record
        key = window, coin
        local = verify(record, pack["data"][window][coin])
        assert snapshots.setdefault(key, local) == local
        assert hashes.setdefault(variant, record[-1]) == record[-1]
    assert len(snapshots) == 4 and len(hashes) == 2
    facts = {
        "id": IDENT,
        "source": root["source"],
        "source_sha256": digest,
        "executed_source_sha256": hashes["literal-clock"],
        "group": "FMZ Pine · Confirmed ABCD and trailing market exits",
        "interval": "1h",
        "archive_interval": "15m",
        "market_data": "Official Binance BTC/ETH USD-M hourly and 15m candles",
        "currency": "USDT",
        "quote_currency": "USDT",
        "exit": "Confirmed trailing stop/profit gate or opposite entry; next open",
    }
    book = []
    for window, label in LABEL.items():
        combined = []
        for coin in ("BTC", "ETH"):
            flows, n = snapshots[window, coin]
            combined.extend(flows)
            book.append(
                {
                    **facts,
                    "period": label,
                    "market": coin + "USDT",
                    **summarize(flows, n, CAPITAL),
                }
            )
        book.append(
            {
                **facts,
                "period": label,
                "market": "BTCUSDT + ETHUSDT",
                **summarize(combined, 2, 2 * CAPITAL),
            }
        )
    assert [x["trades"] for x in book] == [0, 0, 0, 4, 3, 7]
    write(
        args.out,
        {
            "baseline_coverage_sha256": sha256(args.baseline),
            "archive_sha256": FMZ_SHA256,
            "document_sha256": digest,
            "archived_settings": fields,
            "native_runtime_sha256": NATIVE_BINARY_HASH,
            "worker_sha256": sha256(worker),
            "native_receipt_sha256": sha256(receipt),
            "offline_isolation": isolation,
            "provider_archives": pack["archive"],
            "executed_source_controls": hashes,
            "verifications": {
                "source_and_clock_control_runs": 8,
                "unique_chart_bars": 672,
                "closed_lots": 7,
                "terminal_open_lots": 4,
                "independent_entry_and_exit_gates_per_bar": 4,
            },
            "cost_model": {
                "original_fee_per_side": 0,
                "comparison_fee_per_side": FEE,
                "execution_allowance_per_side": EXECUTION,
            },
            "method": [
                "Normalize the authored spaced version comment so the original Pine v4 grammar is selected. Retain the archived source arithmetic and all strategy calls. The local runtime needs explicit timenow, which is supplied at each historical hourly close; removing the clock assignment, whose value is unused, gives identical orders and settlement.",
                "Fractal confirmation observes all five source bars. The negative plot offset affects the visual line. It does not start orders at the earlier pivot. Independent last-confirmed fractal selection, ABCD ratios, trend recency, trailing stop/take-profit gates and next-open broker reconcile across all four asset/windows.",
                "Four margin-free one-base-unit scopes use default simulator starting equity, with independent 15m lows/highs, closes and opening prices reconciled to hourly parents. Both archived positions stay open, so their closed P&L is zero and their win rate is undefined. Synthetic fees and execution buffer are applied on settled next-open cashflows. Funding and liquidation are outside this replay.",
            ],
            "references": [
                "https://www.tradingview.com/pine-script-docs/v4/language/operators/",
                "https://www.tradingview.com/pine-script-docs/v5/language/type-system/#bool",
                "https://www.tradingview.com/pine-script-docs/concepts/strategies/",
                "https://github.com/binance/binance-public-data",
            ],
            "coverage": [
                [
                    IDENT,
                    "Tested · FMZ causal ABCD source replay",
                    "Chronological and dead-clock controls agree across all four BTC/ETH scopes. Independent fractal gates, stops/profit signals, fills, lots and equity match. Seven forward closes and no native settlements.",
                ]
            ],
            "results": book,
        },
    )
    print("6 verified rows, 7 closed lots and 4 terminal open units")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("stage", "report"))
    for name in ("archive", "baseline", "work", "out"):
        p.add_argument(name, type=Path)
    for name in ("hourly", "quarter"):
        p.add_argument(f"--{name}", type=Path, nargs="+", required=True)
    args = p.parse_args()
    root, digest, fields, body = source_record(args.archive, args.baseline)
    pack = inputs(args.hourly, args.quarter)
    if args.mode == "stage":
        stage(args, body, pack)
    else:
        report(args, root, digest, fields, body, pack)


if __name__ == "__main__":
    main()
