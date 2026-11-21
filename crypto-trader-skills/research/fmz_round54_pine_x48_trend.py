"""Verify the X48 author's Trend version on the saved hourly chart."""

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
from research.fmz_round49_pine_stochastic_callback import source_gates

IDENT = 4310
CAPITAL = 1_000_000
HOUR = 3_600_000
START, CUT, STOP = map(date_ms, ("2023-11-17", "2023-12-17", "2024-01-16"))
MONTHS = ("2023-11", "2023-12", "2024-01")
LABEL = {"native": "FMZ native window", "next": "Next equal window"}
WORKER = "fmz_round54_pine_x48_trend_probe.py"


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
        "start": "2023-11-17 00:00:00",
        "end": "2023-12-17 00:00:00",
        "period": "1h",
        "basePeriod": "15m",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    code, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", raw)
    assert n == 1
    code, n = re.subn(
        r"(?m)^import X4815162342/X48_LibaryStrategyStatus/2 as fuLi[ \t]*\n", "", code
    )
    assert n == 1
    masked = re.sub(r"(?m)//.*$", "", code)
    assert "fuLi" not in masked
    for name in ("current_price", "current_pricel", "current_prices"):
        assert len(re.findall(rf"\b{name}\b", masked)) == 1
    code, n = re.subn(r"(?m)^current_price[ls]? = request.security[^\n]*\n", "", code)
    assert n == 3
    for expectation in (
        'strategy("X48 - DayLight Hunter | Strategy | V.01.03", overlay=true)',
        'Trade_Mode = input.string(defval = "Trend"',
        'Risk_Mode = input.string(defval = "Low Risk"',
        "periodK = input.int(15",
        "smoothK = input.int(3",
        "periodD = input.int(3",
        "SMA_High = input.int(defval = 50",
        "SMA_Low = input.int(defval = 50",
        "longcondition and strategy.position_size == 0",
        "shortcondition and strategy.position_size == 0",
        "tp_l = tpsl(input.float(0",
        "tp_s = tpsl(input.float(0",
        "sl = tpsl(input.float(0",
        "tp_pnl = input.float(defval = 1",
        "hedge_point = input.int(defval = 500",
        "hedge_gale = input.float(defval = 2.0",
        "hedge_point_size = hedge_point/100",
        "and hedge_mode == 2",
        "strategy.cancel_all()",
    ):
        assert expectation in code
    return row, digest, fields, code


def inputs(hourly, quarter):
    pack = {}
    receipts = []
    for coin in ("BTC", "ETH"):
        pair = coin + "USDT"
        by_hour = {
            x[0]: list(x)
            for x in cache_bars(hourly, pair, "1h", MONTHS, HOUR, receipts)
        }
        by_quarter = {
            x[0]: list(x)
            for x in cache_bars(quarter, pair, "15m", MONTHS, HOUR // 4, receipts)
        }
        for window, lo, hi in (("native", START, CUT), ("next", CUT, STOP)):
            chart = [by_hour[t] for t in range(lo, hi, HOUR)]
            alt = [by_quarter[t] for t in range(lo, hi, HOUR // 4)]
            assert len(chart) == 720
            assert all(
                list(x[:5]) == y[:5] and isclose(x[5], y[5], rel_tol=1e-12)
                for x, y in zip(aggregate(alt, 4), chart, strict=True)
            )
            pack.setdefault(window, {})[coin] = chart
    return {"data": pack, "archive": receipts}


def source_model(tape, long, short):
    cash = float(CAPITAL)
    holding = []
    side = 0
    queued = None
    orders = []
    trades = []
    eqs = []
    valid = []

    def close_all(index, price):
        nonlocal cash
        for tag, origin, px, qty in holding:
            gross = side * qty * (price - px)
            cash += gross
            trades.append([tag, origin, index, px, price, side * qty, gross])

    for i, (_, op, _, _, cl, _) in enumerate(tape):
        if queued is not None:
            direction, kind, qty = queued
            assert side in (0, direction)
            side = direction
            orders.append([kind, i, op, qty, side])
            holding.append([kind, i, op, qty])
            queued = None
        marked = side * sum(q * (cl - px) for _, d, px, q in holding)
        if marked >= 1:
            valid.append([i, marked])
            close_all(i, cl)
            holding = []
            side = 0
            marked = 0.0
        else:
            assert not (long[i] and short[i])
            direction = 1 if long[i] else -1 if short[i] else 0
            if direction:
                kind = "Long" if direction > 0 else "Short"
                if not side:
                    queued = direction, kind, 1.0
                elif direction == side and side * (holding[-1][2] - cl) >= 5:
                    queued = direction, kind + "2", sum(q for *_, q in holding) * 2
        eqs.append(cash + marked)
    return orders, trades, eqs, len(holding), valid


def verify(chart, receipt):
    window, coin, variant, diagnostics, native, plots, _ = receipt
    assert not diagnostics
    if variant == "literal-noop":
        assert all(x["code"] == "E_STRATEGY_EXIT_PRICE" for x in native["diagnostics"])
    else:
        assert not native["diagnostics"]
    long, short, indicators = source_gates(chart)
    assert [int(v) for v in long] == plots["LongGate"] and [
        int(v) for v in short
    ] == plots["ShortGate"]
    for key, values in indicators.items():
        assert all(
            a is None
            and b is None
            or a is not None
            and b is not None
            and isclose(a, b, abs_tol=1e-8)
            for a, b in zip(values, plots[key], strict=True)
        )
    orders, trades, marked, held, profit_exits = source_model(chart, long, short)
    raw_orders = [
        [
            x["id"],
            x["barIndex"],
            x["price"],
            x["qty"],
            1 if x["direction"] == "strategy.long" else -1,
        ]
        for x in native["orders"]
    ]
    assert orders == raw_orders
    assert all(
        x["time"] == chart[i][0] and x["price"] == chart[i][1]
        for x, (_, i, _, _, _) in zip(native["orders"], orders, strict=True)
    )
    flows = []
    for lot, x in zip(trades, native["trades"], strict=True):
        _, i, j, entry, exit, quantity, gross = lot
        assert lot == [
            x[field]
            for field in (
                "id",
                "entryBarIndex",
                "exitBarIndex",
                "entryPrice",
                "exitPrice",
                "qty",
                "profit",
            )
        ]
        assert (x["entryTime"], x["exitTime"]) == (chart[i][0], chart[j][0])
        assert exit == chart[j][4]
        turnover = abs(quantity) * (entry + exit)
        flows.append(
            (chart[j][0] + HOUR - 1, gross, turnover * FEE, turnover * EXECUTION)
        )
    assert all(
        isclose(v, row["equity"], abs_tol=1e-8)
        for v, row in zip(marked, native["equity"], strict=True)
    )
    return (
        flows,
        held,
        {
            "period": window,
            "market": coin,
            "entry_fills": len(orders),
            "closing_lots": len(flows),
            "actual_immediate_closes": len(profit_exits),
            "terminal_lots": held,
            "diagnostics": len(native["diagnostics"]),
        },
    )


def stage(args, code, data):
    (args.work / "round47-4310.pine").write_text(code, encoding="utf8", newline="\n")
    write(args.work / "round47-4310-feeds.json", data)
    copy2(Path(__file__).with_name(WORKER), args.work / WORKER)


def report(args, item, digest, fields, code, data):
    work = args.work
    worker = Path(__file__).with_name(WORKER)
    receipt = work / "round47-4310-probe.json"
    isolation = read(work / "round3-isolation-python.json")
    assert all(
        isolation[k][0] == "PermissionError" for k in ("file_error", "network_error")
    )
    assert (
        sha256(work / "priced-runtime/pine_compat/pine_compat.pyd")
        == NATIVE_BINARY_HASH
    )
    assert sha256(worker) == sha256(work / WORKER)
    assert (work / "round47-4310.pine").read_text(encoding="utf8") == code
    assert read(work / "round47-4310-feeds.json") == data
    records = read(receipt)
    assert len(records) == 8
    keys = {}
    codes = {}
    findings = []
    for record in records:
        window, coin, variant, *_ = record
        journal, n, proof = verify(data["data"][window][coin], record)
        assert keys.setdefault((window, coin), (journal, n)) == (journal, n)
        assert codes.setdefault(variant, record[-1]) == record[-1]
        findings.append({**proof, "variant": variant})
    assert len(keys) == 4 and len(codes) == 2
    common = {
        "id": IDENT,
        "source": item["source"],
        "source_sha256": digest,
        "executed_source_sha256": codes["guarded-noop"],
        "group": "FMZ Pine · X48 Low Risk Trend mode",
        "interval": "1h",
        "archive_interval": "15m",
        "currency": "USDT",
        "quote_currency": "USDT",
        "market_data": "Official Binance USD-M hourly and underlying 15m bars",
        "exit": "Source immediate 1 USDT marked-P&L close",
    }
    rows = []
    for tag, label in LABEL.items():
        pooled = []
        remaining = 0
        for coin in ("BTC", "ETH"):
            flows, n = keys[tag, coin]
            pooled.extend(flows)
            remaining += n
            rows.append(
                {
                    **common,
                    "period": label,
                    "market": coin + "USDT",
                    **summarize(flows, n, CAPITAL),
                }
            )
        rows.append(
            {
                **common,
                "period": label,
                "market": "BTCUSDT + ETHUSDT",
                **summarize(pooled, remaining, 2 * CAPITAL),
            }
        )
    assert [x["trades"] for x in rows] == [22, 26, 48, 19, 24, 43]
    write(
        args.out,
        {
            "baseline_coverage_sha256": sha256(args.baseline),
            "archive_sha256": FMZ_SHA256,
            "document_sha256": digest,
            "archived_settings": fields,
            "provider_archives": data["archive"],
            "runtime_sha256": NATIVE_BINARY_HASH,
            "offline_isolation": isolation,
            "worker_sha256": sha256(worker),
            "native_receipt_sha256": sha256(receipt),
            "source_control_hashes": codes,
            "marker_receipts": findings,
            "verification": {
                "identically_reconciled_runs": 8,
                "original_resolution_bars": 2880,
                "guarded_nonpooled_source_closes": 91,
                "guarded_nonpooled_orders": 92,
            },
            "cost_model": {
                "source_fee_per_side": 0,
                "comparison_fee_per_side": FEE,
                "execution_buffer_per_side": EXECUTION,
            },
            "method": [
                "The stored v1.03 source is distinct from the previously tested v1.01 author version. It defaults to Trend, Low Risk, flat-only initial entries, same-direction source scale orders after five adverse quote units and a one-quote-unit marked profit threshold. Uses the native fixed default quantity of one and native starting equity, not the marketing lot assumptions mentioned in comments.",
                "The abandoned display-library call and three unused lower-timeframe declarations were removed. Disabled percentage exit orders are guarded against all-NA prices. The calculated and literal native orders, lots, prices, account equity and source entry conditions agree across all four windows. Diagnostic guards change no fill.",
                "Signal confirmation on the hourly close, next hourly opening entry fills, and the source immediate same-hour close price fully reconcile against underlying 15m bars. The historical scope models fees and friction after the source ledger; margin, funding, liquidation, path dependent liquidity and different authored variants are outside this experiment.",
            ],
            "references": [
                "https://www.fmz.com/strategy/435721",
                "https://www.fmz.com/doc/9293",
                "https://github.com/binance/binance-public-data",
            ],
            "coverage": [
                [
                    IDENT,
                    "Tested · FMZ saved X48 Trend mode",
                    "Archived Trend mode, disabling no-price exits, and independent historical replay match all 91 meaningful closures and 92 entry fills on official BTC/ETH 1h/15m archives.",
                ]
            ],
            "results": rows,
        },
    )
    print(f"{len(rows)} verified rows; 91 completed lots and one terminal open lot")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("stage", "report"))
    for name in ("archive", "baseline", "work", "out"):
        p.add_argument(name, type=Path)
    for name in ("hourly", "quarter"):
        p.add_argument(f"--{name}", type=Path, nargs="+", required=True)
    args = p.parse_args()
    item, digest, fields, code = source_record(args.archive, args.baseline)
    data = inputs(args.hourly, args.quarter)
    if args.mode == "stage":
        stage(args, code, data)
    else:
        report(args, item, digest, fields, code, data)


if __name__ == "__main__":
    main()
