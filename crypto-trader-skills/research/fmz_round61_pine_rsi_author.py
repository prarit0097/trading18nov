"""Verify the public FMZ #1404 direction receipt and causal minute executions."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from itertools import batched
from math import isclose
from pathlib import Path
from shutil import copy2
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, aggregate, date_ms, sha256
from research.fmz_round7_pine import EXECUTION, FEE, summarize
from research.fmz_round12_pine_authored import provider_bars
from research.fmz_round19_pine_broker import relative_strength
from research.fmz_round20_1404_stage import ARCHIVES
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH

IDENT = 1404
CAPITAL = 50_000
MINUTE = 60_000
HOUR = 60 * MINUTE
SOURCE = "4680d886ec40d847a9b7547624cdedc3b00e4045fc36d61051ad9c6275df442e"
IMAGE = "aeb104136794c305633fe787d737f9462722aabc8c1ee64e29ebfbcbf9366854"
WORKER = "fmz_round61_pine_rsi_author_probe.py"
START = date_ms("2023-12-19") - 8 * HOUR
STOP = date_ms("2023-12-26") - 8 * HOUR
REFERENCE_URL = "https://www.fmz.com/upload/asset/1b28de5ca210cbe9cfd.png"


def archive_source(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (item,) = [r for r in read(baseline)["disposition"] if r["id"] == IDENT]
    assert item["status"].startswith("Pending")
    with ZipFile(archive) as book:
        ((_, _, doc, source_pin),) = documents(book, {IDENT: item})
    assert source_pin == SOURCE
    (source,) = re.findall(
        r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", doc
    )
    assert all(
        line in source
        for line in (
            "start: 2023-12-19 00:00:00",
            "end: 2023-12-26 00:00:00",
            "period: 3m",
            "basePeriod: 1m",
            "//@version=4",
            "myPosition := buy==1 ? 0 : sell==1 or myPosition[1]==1 ? 1 : 0",
            "strategy.initial_capital = 50000",
            "size = 1",
            'strategy.entry("long",1,size,when=buy and myPosition[1]==1 )',
            'strategy.entry("short",0,size,when=sell and myPosition[1]==0)',
        )
    )
    return item, doc


def tape(provider):
    values = {}
    pins = []
    for coin in ("BTC", "ETH"):
        pair = coin + "USDT"
        path = provider / f"{pair}-1m-2023-12.zip"
        assert sha256(path) == ARCHIVES[path.name]
        minute = [
            list(row) for row in provider_bars(path, MINUTE) if START <= row[0] < STOP
        ]
        assert [row[0] for row in minute] == list(range(START, STOP, MINUTE))
        assert len(minute) == 10080 and all(row[5] > 0 for row in minute)
        values[coin] = {
            "chart": [list(row) for row in aggregate(minute, 3)],
            "minute": minute,
        }
        pins.append(
            {
                "sha256": ARCHIVES[path.name],
                "url": f"https://data.binance.vision/data/futures/um/monthly/klines/{pair}/1m/{path.name}",
            }
        )
    return values, pins


def compare(chart, minute, source, tick):
    broker = source["strategy"]
    rv, b, s, state, *_, position = source["plots"]
    close = [bar[4] for bar in chart]
    values = relative_strength(close, 14)
    buys = []
    sells = []
    order_queue = []
    sim_pos = []
    st = []
    holding = 0
    for i, x in enumerate(values):
        y = values[i - 1] if i else None
        if y is not None and x is not None:
            buy = int(y <= 75 and x > 75)
            sell = int(y >= 25 and x < 25)
        else:
            buy = sell = 0
        direction = 1 if buy and holding == 1 else -1 if sell and holding == 0 else 0
        buys.append(buy)
        sells.append(sell)
        order_queue.append(direction)
        holding = 0 if buy else 1 if sell else holding
        st.append(holding)
    assert all(
        x is None
        and y is None
        or x is not None
        and y is not None
        and isclose(x, y, abs_tol=1e-9)
        for x, y in zip(values, rv, strict=True)
    )
    assert buys == b and sells == s and st == state
    pending = 0
    opened = None
    closings = []
    orders = []
    uncertainty = []
    for i, (bar, lower, signal) in enumerate(
        zip(chart, batched(minute, 3, strict=True), order_queue, strict=True)
    ):
        price = bar[1]
        if pending and (opened is None or pending != opened[0]):
            assert opened is None
            opened = (pending, i, price)
            orders.append((i, "long" if pending > 0 else "short", price, 1))
        pending = signal
        if opened:
            direction, index, entry = opened
            stop = round((entry - direction * 250 * tick) / tick) * tick
            target = round((entry + direction * 2500 * tick) / tick) * tick
            for stamp, o, h, l, c, v in lower:
                if direction > 0:
                    stop_hit = l <= stop
                    target_hit = h >= target
                    out = (
                        min(stop, o)
                        if stop_hit
                        else max(target, o)
                        if target_hit
                        else None
                    )
                else:
                    stop_hit = h >= stop
                    target_hit = l <= target
                    out = (
                        max(stop, o)
                        if stop_hit
                        else min(target, o)
                        if target_hit
                        else None
                    )
                if stop_hit and target_hit:
                    uncertainty.append((i, stamp))
                if out is not None:
                    orders.append(
                        (i, "exit_long" if direction > 0 else "exit_short", out, 1)
                    )
                    closings.append(
                        (
                            index,
                            i,
                            stamp,
                            entry,
                            out,
                            direction * (out - entry),
                            direction,
                        )
                    )
                    opened = None
                    break
        sim_pos.append(opened[0] if opened else 0)
    assert not uncertainty and opened is None and not pending
    assert sim_pos == position
    for (bar, key, price, quantity), native in zip(
        orders, broker["orders"], strict=True
    ):
        assert (bar, key, chart[bar][0], quantity) == (
            native["barIndex"],
            native["id"],
            native["time"],
            native["qty"],
        )
        assert isclose(price, native["price"], abs_tol=1e-8)
    flows = []
    for (i, j, minute_close, entry, exit, gross, side), native in zip(
        closings, broker["trades"], strict=True
    ):
        assert (i, j, chart[i][0], chart[j][0], side) == (
            native["entryBarIndex"],
            native["exitBarIndex"],
            native["entryTime"],
            native["exitTime"],
            native["qty"],
        )
        assert all(
            isclose(a, b, abs_tol=1e-8)
            for a, b in (
                (entry, native["entryPrice"]),
                (exit, native["exitPrice"]),
                (gross, native["profit"]),
            )
        )
        turnover = entry + exit
        flows.append((minute_close, gross, turnover * FEE, turnover * EXECUTION))
    ledger_cash = CAPITAL
    realized = {j: gross for _, j, _, _, _, gross, _ in closings}
    for i, native in enumerate(broker["equity"]):
        ledger_cash += realized.get(i, 0.0)
        open_lot = next((lot for lot in closings if lot[0] <= i < lot[1]), None)
        mark = 0.0 if open_lot is None else open_lot[-1] * (chart[i][4] - open_lot[3])
        assert isclose(ledger_cash + mark, native["equity"], abs_tol=1e-8)
    return flows


def verify_report(args, item, prices, pins, worker, receipt):
    isolation = read(args.work / "round3-isolation-python.json")
    assert all(
        isolation[key][0] == "PermissionError"
        for key in ("file_error", "network_error")
    )
    assert (
        sha256(args.work / "priced-runtime/pine_compat/pine_compat.pyd")
        == NATIVE_BINARY_HASH
    )
    assert sha256(worker) == sha256(args.work / WORKER)
    native = read(receipt)
    screenshot_price = [43664.2, 43671.5, 43653, 43661]
    assert prices["BTC"]["chart"][-1][1:5] == screenshot_price
    assert round(prices["BTC"]["chart"][-1][5], 2) == 240.42
    assert prices["BTC"]["chart"][-1][0] == 1703519820000
    pooled = []
    rows = []
    audit = []
    shared = {
        "id": IDENT,
        "source": item["source"],
        "source_sha256": SOURCE,
        "group": "FMZ Pine · publisher-confirmed Dual RSI direction",
        "period": "FMZ published local dates · verified UTC+8",
        "interval": "3m",
        "archive_interval": "1m",
        "currency": "USDT",
        "quote_currency": "USDT",
        "market_data": "Official Binance USD-M minute archive, 3m chart OHLCV independently formed",
        "exit": "Original 250/2500-tick brackets, 1m-confirmed touch",
    }
    for coin in ("BTC", "ETH"):
        strict, v4, v5, compare_v5 = (
            native[coin][code]
            for code in (
                "literal-v4",
                "boolean-v4",
                "boolean-v5-magnifier",
                "literal-v5-magnifier",
            )
        )
        assert all(
            not test["diagnostics"] and not test["strategy"]["diagnostics"]
            for test in (strict, v4, v5, compare_v5)
        )
        assert v4["strategy"] == v5["strategy"] == compare_v5["strategy"]
        assert v4["plots"][:4] == v5["plots"][:4] == compare_v5["plots"][:4]
        assert strict["plots"][:3] == v5["plots"][:3]
        old = Counter(row["id"] for row in strict["strategy"]["trades"])
        better = Counter(row["id"] for row in v5["strategy"]["trades"])
        edge = {"BTC": 4, "ETH": 6}[coin]
        assert better == {"long": edge, "short": edge}
        assert old == {"short": 8 if coin == "BTC" else 13}
        panel = prices[coin]
        flows = compare(
            panel["chart"], panel["minute"], v5, 0.1 if coin == "BTC" else 0.01
        )
        stats = summarize(flows, 0, CAPITAL)
        assert stats["trades"] == 2 * edge and isclose(
            stats["gross"], 350 if coin == "BTC" else -2.5
        )
        audit.append(
            {
                "market": coin + "USDT",
                "literal_v4_closed_positions": dict(old),
                "publisher_confirmed_variant_closed_positions": dict(better),
                "orders": len(v5["strategy"]["orders"]),
                "staged_code_fingerprints": {
                    mode: row["code_sha256"] for mode, row in native[coin].items()
                },
            }
        )
        rows.append(
            {
                **shared,
                "market": coin + "USDT",
                "executed_source_sha256": v5["code_sha256"],
                **stats,
            }
        )
        pooled.extend(flows)
    assert len(pooled) == 20
    rows.append(
        {
            **shared,
            "market": "BTCUSDT + ETHUSDT",
            "executed_source_sha256": rows[0]["executed_source_sha256"],
            **summarize(pooled, 0, 2 * CAPITAL),
        }
    )
    return {
        "baseline_coverage_sha256": sha256(args.baseline),
        "archive_sha256": FMZ_SHA256,
        "public_minute_archives": pins,
        "runtime_sha256": NATIVE_BINARY_HASH,
        "worker_sha256": sha256(worker),
        "native_receipt_sha256": sha256(receipt),
        "offline_isolation": isolation,
        "publisher_backtest": {
            "url": REFERENCE_URL,
            "image_sha256": IMAGE,
            "market": "Futures_Binance BTC_USDT:swap",
            "first_date_displayed": "2023-12-19 00:00:00",
            "last_date_displayed": "2023-12-25 23:57:00",
            "chart_display_offset_hours": 8,
            "last_chart_stamp_utc_ms": 1703519820000,
            "last_chart_ohlcv": [*screenshot_price, 240.42],
            "initial_quote_equity": 50000,
            "displayed_trade_count": 16,
            "long_fill_arrow_and_short_position_visible": True,
            "closeout_gross_usdt": 380.784,
            "commission_usdt": 69.31008,
            "estimated_return_usdt": 320.55045450900007,
            "closed_at_cutoff": True,
        },
        "replay_utc_epoch_ms": [START, STOP],
        "cost_model": {
            "fee_per_side": FEE,
            "execution_buffer_per_side": EXECUTION,
            "quote_capital_per_market": CAPITAL,
            "position_base_units": 1,
        },
        "verification": audit,
        "method": [
            "The official FMZ page attaches a completed Binance BTC swap backtest with the exact authored start and stop display, 50,000 USDT starting equity, a visible entry labelled long and a separately visible short position segment. This is direct evidence against the strict all-short Pine Compat v4 interpretation. The screenshot\u2019s last exact candle OHLC and rounded volume match Binance at 15:57 UTC, eight hours earlier than its 23:57 display.",
            "The two archived comparisons are represented with explicit boolean conditions. v4 explicit conditions, v5 literal coercion and v5 explicit conditions with 1m magnification give identical fills. The authored constant size remains one. A separate Wilder RSI calculation and price-time queue match every gate, mark and first 1m stop/target touch, with no dual hit.",
            "This is a causal Binance historical replay of the publisher-confirmed behavior. The published FMZ screenshot records gross 380.784 USDT, while the independently executed next-3m-open model records 350.00 USDT on BTC. The actual historical FMZ fill-by-fill ledger and other platform account components are absent. The screenshot values are retained separately and are not used to populate comparative P&L. ETH applies the same authored settings and market-time window.",
        ],
        "references": [
            "https://www.fmz.com/strategy/436754",
            REFERENCE_URL,
            "https://github.com/binance/binance-public-data",
        ],
        "coverage": [
            [
                IDENT,
                "Tested · publisher-confirmed Dual RSI direction replay",
                "FMZ publisher screenshot confirms long and short behavior and clock against real 3m data. Independent 1m chronological replay verifies 20 BTC and ETH closed lots with explicit boolean state. Original FMZ accounting is shown separately.",
            ]
        ],
        "results": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "report"))
    for name in ("archive", "baseline", "provider", "screenshot", "work", "out"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    assert sha256(args.screenshot) == IMAGE
    item, doc = archive_source(args.archive, args.baseline)
    prices, pins = tape(args.provider)
    here = Path(__file__).with_name(WORKER)
    inputs = args.work / "r51-1404-authored-inputs.json"
    if args.mode == "stage":
        (args.work / "source-1404.md").write_text(doc, encoding="utf8", newline="\n")
        assert sha256(args.work / "source-1404.md") == SOURCE
        inputs.write_text(json.dumps(prices, separators=(",", ":")), encoding="utf8")
        copy2(here, args.work / WORKER)
        return
    assert read(inputs) == prices and sha256(args.work / "source-1404.md") == SOURCE
    recorded = args.work / "r51-1404-authored-native.json"
    write(args.out, verify_report(args, item, prices, pins, here, recorded))
    print("Verified 20 closed lots and the original public FMZ direction witness.")


if __name__ == "__main__":
    main()
