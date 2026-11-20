"""Reconcile source fill callbacks with a causal historical hourly clock."""

from __future__ import annotations

import argparse
import re
from collections import Counter
from datetime import UTC, datetime
from math import floor, fsum
from pathlib import Path
from shutil import copy2
from statistics import pstdev
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
from research.fmz_round7_pine import EXECUTION, summarize
from research.fmz_round12_pine_authored import provider_bars
from research.fmz_round18_pine_qqe import executable_lines
from research.fmz_round19_pine_broker import equal
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH

IDENT = 4483
DAY = 86_400_000
HOUR = 3_600_000
CAPITAL = 1000
FEE = 0.0001
LOT = 0.001
GROUP = "FMZ Pine · Causal 1h order-fill callback replay"
LABELS = {"native": "FMZ native window", "next": "Next equal window"}
PROBES = {
    "r28_bb_hours_native.py": "fmz_round28_pine_callback_probe.py",
    "r28_bb_snapshot.py": "fmz_round28_pine_callback_fixture.py",
}


def source_record(path, baseline):
    assert sha256(path) == FMZ_SHA256
    (row,) = (r for r in read(baseline)["disposition"] if r["id"] == IDENT)
    assert row["status"].startswith("Pending")
    with ZipFile(path) as archive:
        ((_, row, doc, digest),) = documents(archive, {IDENT: row})
    (raw,) = re.findall(r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", doc)
    fields = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)", raw
        )
    )
    assert fields == {
        "start": "2022-12-04 00:00:00",
        "end": "2023-12-10 00:00:00",
        "period": "1d",
        "basePeriod": "1h",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    assert "//@version=4" in raw
    active = "\n".join(executable_lines(raw))
    for witness in (
        "initial_capital = 1000, default_qty_type = strategy.percent_of_equity, default_qty_value = 100",
        "commission_type = strategy.commission.percent, pyramiding = 1, commission_value = 0.01, calc_on_order_fills = true",
        "BBLength = input(100",
        "StdDev = 10",
        "useMovingAverage = input(true)",
        'defval="rma"',
        "lookbackPeriod = input(22",
        'defval="hma"',
        "AtrLength = input(10)",
        "AtrMult = input(4)",
        "wicks = input(false)",
        "considerYearlyHighLow = input(false)",
        "considerNewLongTermHighLows = input(false)",
        "defval=strategy.direction.all",
        "inDateRange = true",
        "buyCondition = dir==1 and yearlyHighCondition and newHighS",
        "sellCondition = dir == -1 and yearlyLowCondition and newLowS",
        'strategy.entry("Buy", strategy.long, when=buyCondition and inDateRange, oca_name="oca_buy")',
        'strategy.entry("Sell", strategy.short, when=sellCondition and inDateRange, oca_name="oca_sell")',
        'strategy.close("Buy", when=exitBuyCondition)',
        'strategy.close("Sell", when=exitSellCondition)',
    ):
        assert witness in active, witness
    return row, digest, fields, raw.encode()


def cache_bars(folders, symbol, interval, months, step, manifest):
    for month in months:
        name = f"{symbol}-{interval}-{month}.zip"
        folder = next(
            d
            for d in folders
            if (d / name).is_file() and (d / (name + ".CHECKSUM")).is_file()
        )
        (path,) = verified_archives(folder, symbol, interval, (month,), manifest)
        yield from provider_bars(path, step)


def feed_data(daily, hourly):
    a, b = map(date_ms, ("2022-12-04", "2023-12-10"))
    c = 2 * b - a
    complete = tuple(f"{y}-{m:02d}" for y in range(2021, 2025) for m in range(1, 13))
    used = sorted(
        {
            datetime.fromtimestamp(t / 1000, UTC).strftime("%Y-%m")
            for t in range(a, c, DAY)
        }
    )
    charts, hours, years, manifest = {}, {}, {}, []
    for market in ("BTCUSDT", "ETHUSDT"):
        raw = list(cache_bars(daily, market, "1d", complete, DAY, manifest))
        one_hour = list(cache_bars(hourly, market, "1h", used, HOUR, manifest))
        annual = []
        for year in range(2021, 2025):
            start, stop = map(date_ms, (f"{year}-01-01", f"{year + 1}-01-01"))
            yearbars = [row for row in raw if start <= row[0] < stop]
            assert [row[0] for row in yearbars] == list(range(start, stop, DAY))
            annual.append(
                [
                    start,
                    yearbars[0][1],
                    max(row[2] for row in yearbars),
                    min(row[3] for row in yearbars),
                    yearbars[-1][4],
                    sum(row[5] for row in yearbars),
                ]
            )
        years[market] = annual
        for period, lo, hi in (("native", a, b), ("next", b, c)):
            chart = [list(row) for row in raw if lo <= row[0] < hi]
            tape = [list(row) for row in one_hour if lo <= row[0] < hi]
            assert [row[0] for row in chart] == list(range(lo, hi, DAY))
            assert [row[0] for row in tape] == list(range(lo, hi, HOUR))
            assert [list(row[:5]) for row in aggregate(tape, 24)] == [
                row[:5] for row in chart
            ]
            charts.setdefault(period, {})[market] = chart
            hours.setdefault(period, {})[market] = tape
    return manifest, charts, hours, years


def stage(archive, baseline, work, daily, hourly):
    _, _, _, source = source_record(archive, baseline)
    _, charts, hours, years = feed_data(daily, hourly)
    (work / "round28-bb-source.pine").write_bytes(source)
    write(work / "round28-bb-feeds.json", charts)
    write(work / "round28-bb-hours.json", hours)
    write(work / "round28-bb-years.json", years)
    for target, filename in PROBES.items():
        copy2(Path(__file__).with_name(filename), work / target)


def weighted(seq, n):
    q = seq[-n:]
    return (
        None
        if len(q) < n or any(qi is None for qi in q)
        else fsum(i * v for i, v in enumerate(q, 1)) / (n * (n + 1) / 2)
    )


def model(chart):
    raw, percent, moves = ([], [], [])
    fast, ranges = [], []
    direction = 1
    old_lo, old_hi = None, None
    for row in chart:
        raw.append(row[1:5])
        b = None
        if len(raw) >= 100:
            b = []
            for items, now in zip(zip(*raw[-100:], strict=True), raw[-1], strict=True):
                avg = fsum(items) / 100
                width = pstdev(items) * 10
                b.append(
                    (now - (avg - width)) * 100 / (2 * width) if width > 0 else None
                )
        percent.append(b)
        if len(percent) >= 22 and all(x is not None for x in percent[-22:]):
            if not moves or moves[-1] is None:
                n = [fsum(q) / 22 for q in zip(*percent[-22:], strict=True)]
            else:
                n = [(21 * a + b) / 22 for a, b in zip(moves[-1], b, strict=True)]
        else:
            n = None
        prev_close = moves[-1][3] if moves and moves[-1] else None
        moves.append(n)
        ranges.append(
            max(n[1], prev_close) - min(n[2], prev_close)
            if n is not None and prev_close is not None
            else None
        )
        a, slow = weighted(ranges, 5), weighted(ranges, 10)
        fast.append(2 * a - slow if a is not None and slow is not None else None)
        hma = weighted(fast, 3)
        atr = hma * 4 if hma is not None else None
        low, high = (None, None) if atr is None else (n[3] - atr, n[3] + atr)
        last_low = old_lo if old_lo is not None else low
        last_high = old_hi if old_hi is not None else high
        if (
            last_low is not None
            and prev_close is not None
            and low is not None
            and prev_close > last_low
        ):
            low = max(low, last_low)
        if (
            last_high is not None
            and prev_close is not None
            and high is not None
            and prev_close < last_high
        ):
            high = min(high, last_high)
        if n is not None:
            if direction == -1 and last_high is not None and n[3] > last_high:
                direction = 1
            elif direction == 1 and last_low is not None and n[3] < last_low:
                direction = -1
        old_lo, old_hi = low, high
        yield (
            n[3] if n else None,
            atr,
            low,
            high,
            direction,
            1,
            1,
            int(direction == 1),
            int(direction == -1),
        )


def compare_fixture(path, charts):
    fixtures = []
    rows = read(path)
    assert len(rows) == 8
    for full, opening in zip(rows[::2], rows[1::2], strict=True):
        stamp = (full["period"], full["market"], full["bar"])
        assert stamp == (opening["period"], opening["market"], opening["bar"])
        assert (full["mode"], opening["mode"]) == ("full candle", "opening snapshot")
        idx = stamp[2]
        chart = charts[stamp[0]][stamp[1]]
        log = []
        for entry in (full, opening):
            assert not entry["diagnostics"] and not entry["strategy"]["diagnostics"]
            orders = entry["strategy"]["orders"]
            previous = [o for o in orders if o["barIndex"] < idx]
            immediate = [o for o in orders if o["barIndex"] == idx]
            assert all(o["price"] == chart[idx][1] for o in immediate)
            log.append((previous, immediate))
        assert log[0][0] == log[1][0]
        if log[0][1] != log[1][1]:
            assert len(log[0][1]) == len(log[1][1]) + 1
        fixtures.append(
            {
                "period": LABELS[stamp[0]],
                "market": stamp[1],
                "chart_bar": idx,
                "time": chart[idx][0],
                "ohlc": chart[idx][1:5],
                "full_daily_snapshot_orders": log[0][1],
                "open_only_snapshot_orders": log[1][1],
            }
        )
    assert [
        (r["period"], r["market"])
        for r in fixtures
        if r["full_daily_snapshot_orders"] != r["open_only_snapshot_orders"]
    ] == [("FMZ native window", "ETHUSDT"), ("Next equal window", "BTCUSDT")]
    return fixtures


def order_ledger(case, chart, hours):
    observed = case["observations"]
    names = (
        "New close",
        "ATR",
        "Long stop",
        "Short stop",
        "Direction",
        "Year high",
        "Year low",
        "Buy",
        "Sell",
    )
    for index, (expected, actual) in enumerate(
        zip(model(chart), zip(*(observed[n] for n in names), strict=True), strict=True)
    ):
        assert all(equal(a, b) for a, b in zip(expected, actual, strict=True)), (
            index,
            expected,
            actual,
        )
    ticks = {
        key: (phase, price)
        for t, o, _, _, c, _ in hours
        for key, phase, price in ((t, "hour open", o), (t + HOUR - 1, "hour close", c))
    }
    assert not case["strategy"]["diagnostics"]
    for tag in ("orders", "trades"):
        assert [t["row"] for t in case["events"][tag]] == case["strategy"][tag]
    orders = case["events"]["orders"]
    assert [t["event_time"] for t in orders] == sorted(t["event_time"] for t in orders)
    cash, position, entry = CAPITAL, 0, None
    closed = []
    by_phase = Counter()
    states = {}
    for recorded in orders:
        item = recorded["row"]
        fill_time = recorded["event_time"]
        assert ticks[fill_time] == (recorded["phase"], item["price"])
        by_phase[recorded["phase"]] += 1
        index = item["barIndex"]
        assert item["time"] == chart[index][0] <= fill_time < chart[index][0] + DAY
        price, qty = item["price"], item["qty"]
        direction = {"strategy.long": 1, "strategy.short": -1, "strategy.close": 0}[
            item["direction"]
        ]
        marked = cash if entry is None else cash + position * (price - entry[2])
        budget = float(f"{marked:.9e}")
        new_size = floor(budget / (price * (1 + FEE)) / LOT + 1e-9) * LOT
        if position and position * direction <= 0:
            assert entry is not None
            start, entry_i, entry_price = entry
            gross = position * (price - entry_price)
            turnover = abs(position) * (price + entry_price)
            cash += gross - abs(position) * price * FEE
            closed.append(
                (
                    start,
                    fill_time,
                    entry_i,
                    index,
                    position,
                    entry_price,
                    price,
                    gross,
                    turnover,
                )
            )
            qty -= abs(position)
            entry = None
            position = 0
        if direction:
            assert entry is None and equal(qty, new_size)
            assert item["id"] == ("Buy" if direction > 0 else "Sell")
            cash -= qty * price * FEE
            entry = (fill_time, index, price)
            position = direction * qty
        else:
            assert equal(qty, 0)
        states[index] = (position, entry, cash)

    state = (0, None, CAPITAL)
    for index, (bar, balance, witness) in enumerate(
        zip(chart, case["strategy"]["equity"], observed["Position"], strict=True)
    ):
        state = states.get(index, state)
        pos, position_entry, balance_without_mark = state
        value = (
            balance_without_mark
            if position_entry is None
            else balance_without_mark + pos * (bar[4] - position_entry[2])
        )
        assert balance["barIndex"] == index and equal(balance["equity"], value)
        assert equal(witness, pos)

    ledger = []
    for record, independent in zip(case["events"]["trades"], closed, strict=True):
        start, stop, entry_i, exit_i, size, entry_px, exit_px, gross, turnover = (
            independent
        )
        raw = record["row"]
        fee = turnover * FEE
        assert record["event_time"] == stop and start <= stop
        assert raw["entryBarIndex"] == entry_i and raw["exitBarIndex"] == exit_i
        assert (
            raw["entryTime"] == chart[entry_i][0]
            and raw["exitTime"] == chart[exit_i][0]
        )
        assert raw["id"] == ("Buy" if size > 0 else "Sell")
        assert all(
            equal(a, b)
            for a, b in zip(
                (raw["qty"], raw["entryPrice"], raw["exitPrice"], raw["profit"]),
                (size, entry_px, exit_px, gross - fee),
                strict=True,
            )
        )
        ledger.append((stop, gross, fee, turnover * EXECUTION))
    return (
        ledger,
        int(bool(position)),
        {
            "closed": len(ledger),
            "chart_days": len(chart),
            "orders_by_observation": dict(by_phase),
            "terminal_position": position,
        },
    )


def report(archive, baseline, work, daily, hourly, output):
    old, digest, fields, raw = source_record(archive, baseline)
    manifest, charts, hours, years = feed_data(daily, hourly)
    assert (
        sha256(work / "priced-runtime/pine_compat/pine_compat.pyd")
        == NATIVE_BINARY_HASH
    )
    isolation = read(work / "round3-isolation-python.json")
    assert all(
        isolation[k][0] == "PermissionError" for k in ("file_error", "network_error")
    )
    runners = {}
    for target, filename in PROBES.items():
        original = Path(__file__).with_name(filename)
        assert original.read_bytes() == (work / target).read_bytes()
        runners[filename] = sha256(original)
    archived = work / "round28-bb-source.pine"
    assert archived.read_bytes() == raw
    for suffix, values in (("feeds", charts), ("hours", hours), ("years", years)):
        assert read(work / f"round28-bb-{suffix}.json") == values
    snap = work / "round28-bb-snapshot-results.json"
    diagnostics = compare_fixture(snap, charts)
    receipt = [
        work / f"round28-bb-hour-results-{m}.json" for m in ("BTCUSDT", "ETHUSDT")
    ]
    cases = [case for p in receipt for case in read(p)]
    replay = {(case["period"], case["market"]): case for case in cases}
    assert len(replay) == len(cases) == 4
    meta = {
        "id": IDENT,
        "name": old["name"],
        "source": old["source"],
        "source_sha256": digest,
        "executed_source_sha256": sha256(archived),
        "group": GROUP,
        "interval": "1d",
        "archive_interval": "1d",
        "quote_currency": "USDT",
        "market_data": "Official Binance USD-M daily and 1h OHLCV",
        "exit": "Signal reversal and authored order-fill callbacks",
        "comparison_fee": FEE,
    }
    results, checks = [], []
    for period, markets in charts.items():
        pooled = []
        open_count = 0
        for market, chart in markets.items():
            ledger, unsettled, stats = order_ledger(
                replay[(period, market)], chart, hours[period][market]
            )
            checks.append(
                {"id": IDENT, "period": LABELS[period], "market": market, **stats}
            )
            results.append(
                {
                    **meta,
                    "period": LABELS[period],
                    "market": market,
                    **summarize(ledger, unsettled, CAPITAL),
                }
            )
            pooled.extend(ledger)
            open_count += unsettled
        results.append(
            {
                **meta,
                "period": LABELS[period],
                "market": "BTCUSDT + ETHUSDT",
                **summarize(pooled, open_count, 2 * CAPITAL),
            }
        )
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(baseline),
            "archive_sha256": FMZ_SHA256,
            "pine_compat_binary_sha256": NATIVE_BINARY_HASH,
            "isolation_probe": isolation,
            "native_runners": runners,
            "provider_archives": manifest,
            "private_source_dependency": False,
            "source_audit": {
                "document_sha256": digest,
                "archive_pine_sha256": sha256(archived),
                "archive_settings": fields,
            },
            "artifacts": {
                p.name: sha256(p)
                for p in receipt
                + [archived, snap]
                + [work / f"round28-bb-{s}.json" for s in ("feeds", "hours", "years")]
            },
            "causal_lookahead_diagnostic": diagnostics,
            "per_case_order_counts": checks,
            "references": [
                "https://github.com/binance/binance-public-data",
                "https://www.tradingview.com/pine-script-docs/v5/concepts/strategies/",
                "https://www.tradingview.com/pine-script-docs/v5/concepts/repainting/",
            ],
            "method": [
                "The original source uses daily candles and enables order-fill callbacks. Its saved FMZ base period is one hour. Each simulation presents the observed hourly open and completed hourly close in chronological order, with only high/low/volume observed up to that event. Cumulative daily OHLC reconciles to the provider's independent daily archives.",
                "Whole daily bars permit callback orders to observe prices that occur after the day's open. A paired prefix experiment holds the same past and opening price fixed and demonstrates two extra same-open reversals disappearing when later high, low and close are withheld. The workbook uses the causal 1h observation replay.",
                "The initial candle's close seeds pending orders. Later runtime deltas retain previous prices, quantities and arrival events. A separate implementation verifies every completed-day signal, fill timestamp/price, pre-reversal equity sizing, trade amount and mark-to-market equity. The 1h observation clock does not resolve all exchange ticks inside the hour.",
                "Eligible annual input consists of previously confirmed calendar years and both disabled yearly gates remain true. Trades use the authored 100% account equity, 0.001 lot grid, 1,000 initial capital and 0.01% commission per side. Net P&L separately deducts the project 0.03% execution buffer. Drawdown uses realized cashflows.",
            ],
            "coverage": [
                [
                    IDENT,
                    f"Tested · {GROUP}",
                    "Authored callback stays active. Each fill uses only the known hourly event price, and source signals, sizes, equity and fees reconcile independently.",
                ]
            ],
            "results": results,
        },
    )
    print(
        f"Verified {IDENT}: {len(results)} workbook rows and {sum(row['closed'] for row in checks)} closed lots."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "finalize"))
    for name in ("archive", "baseline", "work", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for name in ("daily", "hourly"):
        parser.add_argument(f"--{name}", type=Path, nargs="+", required=True)
    flag = parser.parse_args()
    args = (flag.archive, flag.baseline, flag.work, flag.daily, flag.hourly)
    if flag.mode == "stage":
        stage(*args)
    else:
        report(*args, flag.output)


if __name__ == "__main__":
    main()
