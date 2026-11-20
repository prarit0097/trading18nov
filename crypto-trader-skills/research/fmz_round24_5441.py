"""Verify the causal period-to-date variant of FMZ #5441."""

import bisect
import math
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path

from research.fmz_round7_magnifier import (
    date_ms,
    ledger_metrics,
    raw_ohlcv,
    read,
    sha256,
    verified_archives,
    write,
)
from research.fmz_round18_5745 import DAY, ENGINE_SHA, FEEDS, FIELDS
from research.fmz_round21_1988 import ema

SOURCE_SHA = "a49b557d7c3421ae4417c0989a25ea35c36913d95606cc7deff75efad6dd3a9b"
START, END = map(date_ms, ("2023-01-11", "2024-01-11"))
HOURLY_START = date_ms("2023-11-01")
HOUR = 3_600_000
CAPITAL = 1_000_000
FEE = 0.00075
OBSERVE = """
plot(longCondition?1:0,title="Entry gate")
plot(monthopen,title="Monthly open")
plot(weekopen,title="Weekly open")
plot(monthclose,title="Monthly close")
plot(weekclose,title="Weekly close")
plot(emaslowmonthly,title="Monthly slow")
plot(emaslowweekly,title="Weekly slow")
plot(emafastmonthly,title="Monthly fast")
plot(emafastweekly,title="Weekly fast")
"""


def objects(rows):
    return [dict(zip(FIELDS, r, strict=True)) for r in rows]


def calendar(daily):
    series = {"W": defaultdict(list), "M": defaultdict(list)}
    for row in daily:
        dt = datetime.fromtimestamp(row[0] / 1000, UTC)
        for tag, base in [
            ("W", dt - timedelta(days=dt.weekday())),
            ("M", dt.replace(day=1)),
        ]:
            stamp = int(base.timestamp() * 1000)
            series[tag][stamp].append(row)
    return {
        tag: objects(
            [
                (
                    stamp,
                    rows[0][1],
                    max(r[2] for r in rows),
                    min(r[3] for r in rows),
                    rows[-1][4],
                    math.fsum(r[5] for r in rows),
                )
                for stamp, rows in values.items()
                if rows[0][0] == stamp
            ]
        )
        for tag, values in series.items()
    }


def month_end(stamp):
    value = datetime.fromtimestamp(stamp / 1000, UTC)
    later = (value.replace(day=28) + timedelta(days=4)).replace(day=1)
    return int(later.timestamp() * 1000)


def aligned(upper, daily, monthly):
    times = [b["time"] for b in upper]
    ends = [month_end(t) if monthly else t + 7 * DAY for t in times]
    close = [b["close"] for b in upper]
    fast, slow = (ema(close, n) for n in (8, 21))
    facts = []
    for day in daily:
        t = day["time"]
        active = bisect.bisect_right(times, t) - 1
        complete = bisect.bisect_right(ends, t + DAY) - 1
        assert min(active, complete) >= 0
        facts.append((upper[active]["open"], fast[complete], slow[complete]))
    return facts


def oracle(chart, reference):
    monthly = aligned(reference["M"], chart, True)
    weekly = aligned(reference["W"], chart, False)
    closes = [b["close"] for b in chart]
    f, s, middle, long = (ema(closes, n) for n in (8, 21, 50, 200))
    flags = []
    for i, bar in enumerate(chart):
        mo, mf, ms = monthly[i]
        wo, wf, ws = weekly[i]
        c = closes[i]
        ready = i >= 199 and all(x is not None for x in (mf, ms, wf, ws))
        entry = (
            ready
            and mf > ms
            and c > mf
            and wf > ws
            and c > wf
            and middle[i] > long[i]
            and f[i] > s[i]
            and c > f[i]
            and c > mo
            and c > wo
            and c > bar["open"]
            and chart[i - 1]["low"] <= f[i - 1]
            and c > chart[i - 1]["high"]
            and chart[i - 1]["high"] < chart[i - 2]["high"]
            and all(f[i - j] > s[i - j] for j in (1, 2, 3))
        )
        flags.append(int(entry))
    return monthly, weekly, flags


def cash_witness(chart, flags, hourly):
    by_day = defaultdict(list)
    for bar in hourly:
        by_day[bar["time"] // DAY * DAY].append(bar)
    entry = None
    pending = False
    bracket = None
    rounds = []
    fills = []
    for i, day in enumerate(chart):
        if pending:
            assert entry is None
            entry = i
            fills.append((i, day["open"], "Long"))
            pending = False
        if entry is not None:
            base = by_day[day["time"]]
            assert len(base) == 24
            for bar in base:
                loss = bar["low"] <= bracket[0]
                profit = bar["high"] >= bracket[1]
                assert not (loss and profit), (day["time"], bar, bracket)
                if loss or profit:
                    price = (
                        min(bracket[0], bar["open"])
                        if loss
                        else max(bracket[1], bar["open"])
                    )
                    rounds.append((entry, i, price, bar, bracket))
                    fills.append((i, price, "Exit"))
                    entry = None
                    break
        if flags[i]:
            pending = entry is None
            basis = day["close"] * 0.1
            anchor = chart[entry]["open"] if entry is not None else chart[i + 1]["open"]
            bracket = (
                float(
                    Decimal(str(anchor - basis)).quantize(
                        Decimal(".01"), rounding=ROUND_FLOOR
                    )
                ),
                float(
                    Decimal(str(anchor + basis)).quantize(
                        Decimal(".01"), rounding=ROUND_CEILING
                    )
                ),
            )
    assert entry is None and not pending
    return rounds, fills


def near(a, b):
    return math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-8)


def replay(engine, original, variant, market, chart, reference, hourly):
    symbol = f"BINANCE:{market}"
    options = {
        "chart_symbol": symbol,
        "chart_timeframe": "D",
        "request_bars": {
            **{symbol + ":" + tag: values for tag, values in reference.items()},
            "$chart": {
                "minMove": 1,
                "priceScale": 100,
                "pointValue": 1,
                "quantityStep": "0.001",
                "minContract": "0.001",
                "currency": "USDT",
            },
        },
    }
    historical = engine.run_script(original + OBSERVE, chart, **options)
    canonical = engine.run_script(variant, chart, **options)
    observed = engine.run_script(variant + OBSERVE, chart, **options)
    assert canonical["strategy"] == observed["strategy"] and not observed["diagnostics"]
    raw_plots = {p["title"]: p["values"] for p in historical["plots"]}
    plots = {p["title"]: p["values"] for p in observed["plots"]}
    monthly, weekly, flags = oracle(chart, reference)
    for label, rows in (("Monthly", monthly), ("Weekly", weekly)):
        assert plots[label + " close"] == [d["close"] for d in chart]
        assert plots[label + " open"] == [x[0] for x in rows]
        for j, type in ((1, "fast"), (2, "slow")):
            for i, x in enumerate(rows):
                actual = plots[label + " " + type][i]
                assert near(actual, x[j]), (market, label, type, i, actual, x[j])
    assert plots["Entry gate"] == flags
    for i, day in enumerate(chart):
        if day["time"] >= HOURLY_START:
            parts = hourly[
                (day["time"] - HOURLY_START) // HOUR : (day["time"] - HOURLY_START)
                // HOUR
                + 24
            ]
            assert (
                len(parts) == 24
                and parts[0]["open"] == day["open"]
                and parts[-1]["close"] == day["close"]
            )
            assert (
                max(b["high"] for b in parts) == day["high"]
                and min(b["low"] for b in parts) == day["low"]
            )
    rounds, orders = cash_witness(chart, flags, hourly)
    broker = canonical["strategy"]
    assert not broker["diagnostics"]
    priced = []
    for o, (i, px, ident) in zip(broker["orders"], orders, strict=True):
        assert (o["id"], o["barIndex"], o["qty"], o["time"]) == (
            ident,
            i,
            1,
            chart[i]["time"],
        )
        assert near(o["price"], px), (market, o, px)
    for lot, (entry, exit, xp, base, levels) in zip(
        broker["trades"], rounds, strict=True
    ):
        ep = chart[entry]["open"]
        assert (lot["entryBarIndex"], lot["exitBarIndex"], lot["entryPrice"]) == (
            entry,
            exit,
            ep,
        )
        assert near(lot["exitPrice"], xp) and near(lot["profit"], xp - ep)
        fee = FEE * (xp + ep)
        priced.append(
            {
                **lot,
                "dir": 1,
                "commission": fee,
                "profit": xp - ep - fee,
                "witness_hour": base["time"],
                "stop_target": levels,
            }
        )
    return {
        "market": market,
        "changed_raw_entry_dates": [
            chart[i]["time"]
            for i, (a, b) in enumerate(zip(raw_plots["Entry gate"], flags, strict=True))
            if a != b
        ],
        "original_order_prices_lookahead_control": [
            o["price"] for o in historical["strategy"]["orders"]
        ],
        "causal_orders": broker["orders"],
        "settled": priced,
    }


def run(source_path, feeds, hourly_path, engine_root, output):
    assert (
        sha256(source_path) == SOURCE_SHA
        and sha256(engine_root / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    )
    sys.path.insert(0, str(engine_root))
    import pine_compat as engine

    (source,) = re.findall(
        r"(?ms)^```[^\n]*\n(.*?)^```", source_path.read_text(encoding="utf-8")
    )
    source, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", source)
    assert n == 1
    causal, n = re.subn(r"(?m)^(monthclose|weekclose)\s*=.*$", r"\1 = close", source)
    assert n == 2
    manifest = []
    cases = []
    for market, digest in FEEDS.items():
        path = feeds / f"5411-feed-{market}.json"
        assert sha256(path) == digest
        daily = read(path)
        chart = objects([row for row in daily if START <= row[0] < END])
        assert [r["time"] for r in chart] == list(range(START, END, DAY))
        archives = verified_archives(
            hourly_path, market, "1h", ("2023-11", "2023-12", "2024-01"), manifest
        )
        raw = [
            r
            for archive in archives
            for r in raw_ohlcv(archive, HOUR)
            if HOURLY_START <= r[0] < END
        ]
        assert [row[0] for row in raw] == list(range(HOURLY_START, END, HOUR))
        cases.append(
            replay(engine, source, causal, market, chart, calendar(daily), objects(raw))
        )
    common = {
        "id": 5441,
        "group": "FMZ · Causal week/month close variant",
        "period": "Binance USD-M · 2023-01-11 to 2024-01-11 UTC exclusive",
        "exit": "Source 10% signal-price relative bracket",
        "archive_interval": "1d",
        "interval": "1d",
        "currency": "USDT",
    }
    results = [
        {**common, "market": c["market"], **ledger_metrics(c["settled"], CAPITAL, 0)}
        for c in cases
    ]
    results.append(
        {
            **common,
            "market": "BTCUSDT + ETHUSDT",
            **ledger_metrics(
                [lot for c in cases for lot in c["settled"]], CAPITAL * 2, 0
            ),
        }
    )
    write(
        output,
        {
            "schema": "FMZ 5441 · Causal period-to-date close repair",
            "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
            "source_sha256": SOURCE_SHA,
            "engine_sha256": ENGINE_SHA,
            "daily_sha256": FEEDS,
            "hourly_archives": manifest,
            "notes": {
                "repair": "The original daily historical source requested completed weekly and monthly closes before the periods ended. The causal comparison uses the current completed daily close as the period-to-date close for each candle comparison. Period opens remain known from their first bar, and weekly and monthly EMA series use completed periods with explicit prehistory.",
                "original_control": "The original is retained solely as a timing diagnostic. The causal computation changes an ETH entry gate and subsequent bracket. Workbook performance uses the repaired comparison only.",
                "orders": "Same archived EMA, candle, pullback, stop and target logic. A one-unit 100%-margin market entry uses the next daily open. The signal close supplies the original ten-percent bracket distance. Each fill is independently followed through the complete hourly source prices. Source zero fees define gross results and 0.075% is applied as an unchanged-fill overlay.",
            },
            "coverage": [
                [
                    5441,
                    "Tested · Causal week/month close variant",
                    "Replaced the two early higher-timeframe close reads with observable period-to-date closes. Confirmed completed weekly/monthly EMA and every entry gate. All five closed lots reconciled to complete one-hour execution prices.",
                ]
            ],
            "results": results,
            "scopes": cases,
        },
    )


if __name__ == "__main__":
    run(*map(Path, sys.argv[1:]))
