"""Replay the archived Volume ValueWhen Velocity on independently audited clocks."""

from __future__ import annotations

import argparse
import json
import re
from bisect import bisect_right
from hashlib import sha256 as hash_bytes
from itertools import batched
from math import ceil, floor, fsum, isclose
from pathlib import Path
from shutil import copy2
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, sha256
from research.fmz_round7_pine import EXECUTION, FEE, summarize
from research.fmz_round19_pine_broker import average_wilder, relative_strength
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH
from research.fmz_round55_pine_volume_reference_stage import source_inputs

IDENT = 3664
CAPITAL = 1_000_000
H = 3_600_000
M = 60_000
D = 24 * H
CAUSAL = "39-fmz-causal"
LITERAL = "39-fmz-native"
SENSITIVITY = "39-binance-sensitivity"
WORKER = "fmz_round55_pine_volume_reference_probe.py"
EXACT_CONTROL = "169c1a54f372869683379d07585786e70ea6be9fcaa877ea55fef84e9b4e2759"


def source_record(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (record,) = [row for row in read(baseline)["disposition"] if row["id"] == IDENT]
    assert record["status"].startswith("Pending")
    with ZipFile(archive) as book:
        ((_, _, doc, digest),) = documents(book, {IDENT: record})
    (raw,) = re.findall(r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", doc)
    fields = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)", raw
        )
    )
    assert fields == {
        "start": "2023-10-24 00:00:00",
        "end": "2023-11-23 00:00:00",
        "period": "1h",
        "basePeriod": "15m",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    code, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", raw)
    assert n == 1 and code.count("//@version=5") == 1
    assert all(
        mark in code
        for mark in (
            "strategy(title='Volume ValueWhen Velocity', overlay=true)",
            'request.security(syminfo.tickerid, "39", volume)[bar]',
            "if buy_signal and in_date_range",
            "strategy.entry('Long', strategy.long",
            "loss=long_stoploss_percentage, profit=long_takeprofit_percentage",
        )
    )
    return record, digest, fields, code


def tr(bars):
    for i, (_, _, hi, lo, _, _) in enumerate(bars):
        yield (
            hi - lo if not i else max(hi - lo, hi - bars[i - 1][4], bars[i - 1][4] - lo)
        )


def obscheck(x, y):
    return (
        x is None
        and y is None
        or x is not None
        and y is not None
        and isclose(x, y, rel_tol=1e-10, abs_tol=1e-8)
    )


def gates(panel, label):
    chart = panel["chart"]
    a15 = list(average_wilder(list(tr(chart)), 15))
    rs = relative_strength([x[4] for x in chart], 40)
    lowframes = panel["30"]
    lowend = [x[0] + 30 * M - 1 for x in lowframes]
    lr = list(tr(lowframes))
    a5 = list(average_wilder(lr, 5))
    a14 = list(average_wilder(lr, 14))
    xf = panel[label]
    ends = [b[0] for b in xf]
    day = panel["D"]
    day_times = [b[0] + D - 1 for b in day]
    week = panel["W"]
    week_times = [b[0] + 7 * D - 1 for b in week]
    minute = panel["1"]
    m_times = [b[0] + M - 1 for b in minute]
    dd = []
    vol = []
    ago = None
    oversold = None
    events = []
    for i, bar in enumerate(chart):
        at = bar[0] + H - 1
        n = bisect_right(ends, at) - 1
        vol.append(None if n < 0 else xf[n][-1])
        d = bisect_right(day_times, at) - 1
        dd.append(None if d < 0 else day[d][5])
        w = bisect_right(week_times, at) - 1
        a = bisect_right(lowend, at) - 1
        m = bisect_right(m_times, at) - 1
        f1 = None if d < 2 else int(day[d - 2][4] > day[d - 1][1])
        f2 = None if m < 2 else int(minute[m - 2][4] > minute[m][1])
        f3 = None if w < 1 else int(week[w - 1][4] > week[w - 1][1])
        color = int(
            f1 is not None and f2 is not None and f3 is not None and f1 + f2 > f3
        )
        w_os = (i - oversold <= 10) if oversold is not None else False
        if rs[i] is not None and rs[i] <= 60:
            oversold = i
            w_os = True
        close = bar[4]
        if i >= 12 and close > fsum(x[4] for x in chart[i - 12 : i + 1]) / 13:
            ago = i
            events.append(close)
        diff = events[-6] - events[-2] if len(events) >= 6 else None
        sma_count = None if ago is None else i - ago
        cond = (
            i >= 110
            and all(dd[i - k] is not None for k in (49, 90, 110))
            and all(vol[i - k] is not None for k in (3, 7, 30, 55))
            and dd[i - 90] > 0.5 * dd[i - 49]
            and dd[i - 110] > 0.62 * dd[i - 49]
            and vol[i - 30] > 0.4 * vol[i - 55]
            and vol[i - 7] > 0.4 * vol[i - 3]
        )
        av = bool(a15[i] is not None and (a15[i] > 140 or a15[i] < 123))
        at1 = bool(a >= 0 and a14[a] is not None and a5[a] < a14[a])
        buy = (
            cond
            and av
            and color == 0
            and w_os
            and diff is not None
            and diff > 170
            and at1
            and sma_count is not None
            and sma_count < 5
        )
        yield {
            "DAILY": dd[-1],
            "39m": vol[-1],
            "F1": f1,
            "F2": f2,
            "F3": f3,
            "ATR1": at1,
            "ATR3": a15[i],
            "Difference": diff,
            "RSI": rs[i],
            "Original above SMA": sma_count,
            "Volume gates": bool(cond),
            "Oversold": w_os,
            "Buy": bool(buy),
        }


def ledger(bars, lower, signals, tick):
    cash = 1e6
    holding = None
    bracket = None
    queued = None
    learned = None
    orders = []
    trades = []
    marks = []
    for i, (bar, minutes, signal) in enumerate(
        zip(bars, batched(lower, 60, strict=True), signals, strict=True)
    ):
        t, o, _, _, c, _ = bar
        assert minutes[0][0] == t and minutes[0][1] == o and minutes[-1][4] == c
        if queued:
            holding = (i, o)
            orders.append((i, "strategy.long", o))
            queued = None
        if holding and learned is not None:
            j, base = holding
            bracket = (
                ceil((base + learned * 0.02) / tick - 1e-9) * tick,
                floor((base - learned * 0.03) / tick + 1e-9) * tick,
            )
            learned = None
        if holding:
            j, base = holding
            limit, stop = bracket
            for ts, m0, mh, ml, mc, v in minutes:
                assert not (ml <= stop and mh >= limit), (
                    "one-minute order ambiguity",
                    i,
                    ts,
                    stop,
                    limit,
                )
                if ml <= stop or mh >= limit:
                    price = min(m0, stop) if ml <= stop else max(m0, limit)
                    orders.append((i, "strategy.exit", price))
                    cash += price - base
                    trades.append((j, i, base, price, price - base, ts))
                    holding = None
                    bracket = None
                    break
        if signal:
            if holding is None:
                queued = True
            learned = c
        marks.append(
            (int(holding is not None), cash + (c - holding[1]) if holding else cash)
        )
    return orders, trades, marks, int(holding is not None)


def audit_clock(panel, variant):
    clocks = panel[variant]
    contributors = {
        label: available for label, available, *_ in panel["39-fmz-reviewed"]
    }
    labels = [row[0] for row in clocks]
    gaps = []
    for i, chart in enumerate(panel["chart"]):
        cut = chart[0] + H
        q = bisect_right(labels, cut - 1) - 1
        if q < 0:
            continue
        stamp = labels[q]
        available = contributors[stamp] if variant == LITERAL else stamp + 1
        if available > cut:
            gaps.append([i, cut, stamp, available, clocks[q][-1]])
    return len(gaps), gaps[0] if gaps else None


def verify(panel, receipt):
    scope, coin, variant, diagnostics, broker, observations, _ = receipt
    assert not diagnostics and not broker["diagnostics"]
    expected = list(gates(panel, variant))
    for i, values in enumerate(expected):
        assert all(obscheck(observations[key][i], v) for key, v in values.items())
    bars = panel["chart"]
    orders, trades, marks, open_lots = ledger(
        bars,
        panel["1"],
        observations["Buy"],
        0.1 if coin == "BTC" else 0.01,
    )
    for (idx, direction, price), row in zip(orders, broker["orders"], strict=True):
        assert (idx, direction, bars[idx][0], 1.0) == (
            row["barIndex"],
            row["direction"],
            row["time"],
            row["qty"],
        )
        assert isclose(price, row["price"], abs_tol=1e-9)
    flows = []
    for (i, j, entry, exit, gross, stamp), row in zip(
        trades, broker["trades"], strict=True
    ):
        assert (i, j, bars[i][0], bars[j][0], 1.0, "Long") == (
            row["entryBarIndex"],
            row["exitBarIndex"],
            row["entryTime"],
            row["exitTime"],
            row["qty"],
            row["id"],
        )
        assert all(
            isclose(x, y, abs_tol=1e-9)
            for x, y in (
                (entry, row["entryPrice"]),
                (exit, row["exitPrice"]),
                (gross, row["profit"]),
            )
        )
        turnover = entry + exit
        flows.append((stamp, gross, turnover * FEE, turnover * EXECUTION))
    assert (
        len(marks)
        == len(observations["Original pos"])
        == len(observations["Original equity"])
    )
    for i, ((size, equity), row) in enumerate(
        zip(marks, broker["equity"], strict=True)
    ):
        assert size == observations["Original pos"][i]
        assert isclose(equity, observations["Original equity"][i], abs_tol=1e-7)
        assert isclose(equity, row["equity"], abs_tol=1e-7)
    future, example = audit_clock(panel, variant)
    assert (
        future == (665 if scope == "native" else 664)
        if variant == LITERAL
        else future == 0
    )
    return (
        flows,
        open_lots,
        {
            "period": scope,
            "market": coin,
            "variant": variant,
            "closes": len(trades),
            "terminal_open_lots": open_lots,
            "order_fills": len(orders),
            "signal_bars": sum(observations["Buy"]),
            "future_reference_bars": future,
            "first_future_reference": example,
        },
    )


def synthesize(meta, app, data, records):
    item, digest, fields, code = meta
    assert len(records) == 12
    exact_controls = [row for row in records if row[2] != SENSITIVITY]
    assert (
        hash_bytes(
            json.dumps(exact_controls, separators=(",", ":")).encode()
        ).hexdigest()
        == EXACT_CONTROL
    )
    curves = {}
    controls = {}
    findings = []
    hashes = set()
    for record in records:
        scope, coin, variant, *_, pin = record
        key = scope, coin, variant
        assert key not in curves
        flows, open_lots, proof = verify(data["data"][scope][coin], record)
        curves[key] = flows, open_lots
        controls[key] = record[4], record[5]
        hashes.add(pin)
        findings.append(proof)
    assert len(hashes) == 1
    sensitivity = []
    for scope in ("native", "next"):
        for coin in ("BTC", "ETH"):
            broker, plot = controls[scope, coin, CAUSAL]
            shadow, trial = controls[scope, coin, SENSITIVITY]
            delta = {
                key: sum(a != b for a, b in zip(values, trial[key], strict=True))
                for key, values in plot.items()
                if values != trial[key]
            }
            sensitivity.append(
                {
                    "period": scope,
                    "market": coin,
                    "changed_plot_bars": delta,
                    "identical_orders_closed_lots_and_equity": broker == shadow,
                }
            )
    assert [
        len(curves[k][0])
        for k in (
            ("native", "BTC", LITERAL),
            ("native", "BTC", CAUSAL),
            ("next", "BTC", LITERAL),
            ("next", "BTC", CAUSAL),
        )
    ] == [7, 8, 7, 7]
    common = {
        "id": IDENT,
        "source": item["source"],
        "source_sha256": digest,
        "executed_source_sha256": next(iter(hashes)),
        "group": "FMZ Pine · Volume ValueWhen Velocity causal reference",
        "interval": "1h",
        "archive_interval": "15m",
        "currency": "USDT",
        "quote_currency": "USDT",
        "market_data": "FMZ 39m volume and timestamp; Binance USD-M chart and confirmed 1m path",
        "exit": "Original price-relative native bracket, with independently verified 1m first touch",
    }
    rows = []
    for scope, label in (
        ("native", "FMZ native dates · causal reference"),
        ("next", "Next equal dates · causal reference"),
    ):
        pooled = []
        terminal = 0
        for coin in ("BTC", "ETH"):
            flows, open_lots = curves[scope, coin, CAUSAL]
            rows.append(
                {
                    **common,
                    "period": label,
                    "market": coin + "USDT",
                    **summarize(flows, open_lots, CAPITAL),
                }
            )
            pooled.extend(flows)
            terminal += open_lots
        rows.append(
            {
                **common,
                "period": label,
                "market": "BTCUSDT + ETHUSDT",
                **summarize(pooled, terminal, 2 * CAPITAL),
            }
        )
    assert [row["trades"] for row in rows] == [8, 0, 8, 7, 0, 7]
    return {
        **app,
        "document_sha256": digest,
        "source_sha256": hash_bytes(code.encode()).hexdigest(),
        "archived_settings": fields,
        "binance_public_archive": data["proof"],
        "binance_replacements": data["binance_replacements"],
        "fmz_public_archive": data["fmz_public_archive"],
        "cost_model": {
            "source_fee_per_side": 0,
            "comparison_fee_per_side": FEE,
            "execution_buffer_per_side": EXECUTION,
            "source_size_base_asset": 1,
        },
        "verification": {
            "native_runs": len(records),
            "verified_hourly_observations": len(records) * 720,
            "causal_source_closes": 15,
            "causal_terminal_lots": 1,
            "clock_primary_and_literal_controls": findings,
            "stale_quarter_corrected_volume_sensitivity": sensitivity,
        },
        "method": [
            "Archived Pine v5 defaults and BTC window are intact. ETH and the next equal dates are extension tests with the same rules. Exact published FMZ 39-minute rows were reconstructed from the original 15-minute constituent feed. For each instrument, all 2,254 interior custom rows reconcile exactly with 901 two-quarter and 1,353 three-quarter groups by epoch-labelled start.",
            "The Pine Compat literal 39-minute label series can read a row before its last contributing quarter finishes. The causal evaluation exposes a custom volume only at its final constituent quarter close. This is a labelled causal source replay with the original arithmetic and a separately observed future-reading diagnostic.",
            "Binance corrected public one-minute trade candles reconcile with the hourly and daily archive OHLCV. These provide the executable price path. FMZ's published quarter feed differs from four Binance quarter records. A separately isolated sensitivity replaces only their volume contributions at the same causal availability times.",
            "Independent daily, weekly, hourly and lower-timeframe selection and arithmetic reconcile all thirteen source markers, order prices, per-lot P&L and portfolio equity. One-base-asset source quantities and one million USDT starting equity are used. Existing terminal positions stay open. Cost and friction scenarios are assessed on completed turnover after the zero-fee source ledger. This historical evaluation provides no demo or live qualification.",
        ],
        "references": [
            "https://www.fmz.com/strategy/433102",
            "https://www.fmz.com/doc/9293",
            "https://www.tradingview.com/pine-script-docs/faq/other-data-and-timeframes/",
            "https://github.com/binance/binance-public-data",
        ],
        "coverage": [
            [
                IDENT,
                "Tested · FMZ Pine 39m causal source replay",
                "Archived Pine and public FMZ custom-volume constituents reconcile; causal timestamp and independent Binance fill checks verify 15 BTC closed lots. ETH completed no lots in either window.",
            ]
        ],
        "results": rows,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("stage", "report"))
    for name in ("archive", "baseline", "work", "raw", "out"):
        p.add_argument(name, type=Path)
    for name in ("minute", "hour", "day"):
        p.add_argument(f"--{name}", type=Path, nargs="+", required=True)
    args = p.parse_args()
    meta = source_record(args.archive, args.baseline)
    data = source_inputs(args.raw, args.minute, args.hour, args.day)
    feed = args.work / "r47-3664-exact-feeds.json"
    source = args.work / "r47-3664.pine"
    worker = Path(__file__).with_name(WORKER)
    if args.mode == "stage":
        write(feed, data)
        source.write_text(meta[-1], encoding="utf8", newline="\n")
        copy2(worker, args.work / WORKER)
        return
    assert (
        read(feed) == read_encoded(data)
        and source.read_text(encoding="utf8") == meta[-1]
    )
    assert sha256(worker) == sha256(args.work / WORKER)
    assert (
        sha256(args.work / "priced-runtime/pine_compat/pine_compat.pyd")
        == NATIVE_BINARY_HASH
    )
    isolation = read(args.work / "round3-isolation-python.json")
    assert (
        isolation["file_error"][0] == isolation["network_error"][0] == "PermissionError"
    )
    probe = args.work / "r47-3664-final.json"
    app = {
        "baseline_coverage_sha256": sha256(args.baseline),
        "archive_sha256": FMZ_SHA256,
        "native_runtime_sha256": NATIVE_BINARY_HASH,
        "offline_isolation": isolation,
        "worker_sha256": sha256(worker),
        "native_receipt_sha256": sha256(probe),
        "original_eight_run_receipt_sha256": EXACT_CONTROL,
        "staged_feeds_sha256": sha256(feed),
    }
    report = synthesize(meta, app, data, read(probe))
    write(args.out, report)
    print(
        f"{len(report['results'])} verified rows; 15 completed lots and one terminal open lot"
    )


def read_encoded(data):
    return json.loads(json.dumps(data))


if __name__ == "__main__":
    main()
