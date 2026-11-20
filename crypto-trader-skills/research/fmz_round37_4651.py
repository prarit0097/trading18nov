"""Replay #4651 with source eager branches, USD conversion and observed minute paths."""

import math
import re
import sys
from collections import deque
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path

from research.fmz_round7_magnifier import (
    aggregate,
    date_ms,
    ledger_metrics,
    sha256,
    verified_archives,
    write,
)
from research.fmz_round18_5745 import DAY, ENGINE_SHA, FIELDS
from research.fmz_round26_977 import prices
from research.fmz_round32_trailing_offset import daily_rates

SOURCE_SHA = "c74c1d07f5d28c87a665ff23ffc452fc099bae880fbf3e67d5dfb3b4dc42d7c1"
BEGIN, END = map(date_ms, ("2023-09-20", "2023-09-27"))
FEE, STEP = Decimal(".0004"), Decimal(".001")
CAPITAL = 10000
PLOTS = (
    "nLongs",
    "nShorts",
    "quanTity",
    "Volume_Factor_Leverage",
    "last_dynamic_Leverage_long",
    "last_dynamic_Leverage_short",
    "last_open_longCondition",
    "last_open_shortCondition",
    "tp_long",
    "tp_short",
    "sl",
)
FLAGS = (
    "_longCondition",
    "_shortCondition",
    "Final_long_BB",
    "Final_short_BB",
    "testPeriod",
)


def original(document):
    assert sha256(document) == SOURCE_SHA
    fence = chr(96) * 3
    (body,) = re.findall(
        r"(?ms)^" + fence + r" pinescript[^\n]*\n(.*?)^" + fence,
        document.read_text(encoding="utf8"),
    )
    source, count = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", body)
    assert count == 1 and source.count("//@version=4") == 1
    assert 'currency = "USD"' in source and "commission_value = 0.04)" in source
    return source


def v5_control(source):
    header = "//@version=5"
    code = source.replace(
        "//@version=4",
        header
        + "\neager_pick(bool condition, float yes, float no) => condition ? yes : no",
        1,
    )
    renamed = {}
    for space, names in (
        (
            "math",
            (
                "abs",
                "pow",
                "max",
                "min",
                "round",
                "sqrt",
                "exp",
                "log",
                "ceil",
                "floor",
                "sign",
                "sum",
                "avg",
            ),
        ),
        (
            "ta",
            (
                "ema",
                "sma",
                "rma",
                "wma",
                "change",
                "atr",
                "sar",
                "vwma",
                "crossover",
                "crossunder",
                "cross",
                "stdev",
                "rsi",
                "highest",
                "lowest",
                "cum",
                "valuewhen",
                "barssince",
                "linreg",
                "tr",
                "macd",
            ),
        ),
    ):
        renamed.update({n: f"{space}.{n}" for n in names})
    renamed["iff"] = "eager_pick"

    def update_input(line):
        arg = re.search(
            r"\btype\s*=\s*input\.(source|bool|integer|float|string)\s*,?", line
        )
        if arg:
            method = {"integer": "int"}.get(arg[1], arg[1])
            line = re.sub(
                r",\s*type\s*=\s*input\.(?:source|bool|integer|float|string)(?!\w)",
                "",
                line,
            )
            line = re.sub(r"\binput\s*\(", f"input.{method}(", line, count=1)
        elif re.search(r'\binput\(\s*".*?options\s*=\s*\[', line):
            line = line.replace("input(", "input.string(", 1)
        return line

    code = "\n".join(update_input(line) for line in code.splitlines())
    calls = r"(?<![\w.])(" + "|".join(renamed) + r")(?=\s*\()"
    code = re.sub(calls, lambda m: renamed[m[1]], code)
    return re.sub(r"(?<![\w.])tr\b", "ta.tr", code)


def approx(actual, expected):
    return math.isclose(actual, float(expected), rel_tol=1e-11, abs_tol=1e-8)


def decimal(value):
    return Decimal(str(value))


def close_proof(price, avg_before, side, index, held, plots, minutes, tick):
    counts, previous_open, fraction = (
        ("nLongs", "last_open_longCondition", "tp_long")
        if side > 0
        else ("nShorts", "last_open_shortCondition", "tp_short")
    )
    prev = index - 1
    last_open = decimal(plots[previous_open][prev])
    fraction = decimal(plots[fraction][prev])
    stop_distance = decimal(plots["sl"][prev]) / 100
    if held and plots[counts][prev] >= 1:
        target = avg_before * (1 + side * fraction)
        stop = avg_before * (1 - side * stop_distance)
    else:
        target = avg_before + side * last_open * fraction
        stop = avg_before - side * last_open * stop_distance
    # The source's two relative distances are zero on some entries. The
    # emulator can close at the opening price when the bracket starts there.
    for minute in minutes:
        stamp, opening, high, low, _, volume = minute
        opening, high, low = map(decimal, (opening, high, low))
        take = high >= target if side > 0 else low <= target
        lose = low <= stop if side > 0 else high >= stop
        if not (take or lose):
            continue
        choices = []
        if take:
            choices.append(max(opening, target) if side > 0 else min(opening, target))
        if lose:
            choices.append(min(opening, stop) if side > 0 else max(opening, stop))
        assert all(approx(choices[0], candidate) for candidate in choices), (
            index,
            choices,
        )
        assert approx(float(price), choices[0]) and volume > 0, (
            index,
            price,
            choices,
            minute,
        )
        # For any off-tick chart fill, also prove that the nearest admissible
        # limit or stop tick on the same side is reached by that same minute.
        ticks = price / tick
        if ticks != ticks.to_integral_value():
            rounding = ROUND_CEILING if (side > 0) == take else ROUND_FLOOR
            quote = ticks.to_integral_value(rounding=rounding) * tick
            assert low <= quote <= high, (price, quote, minute)
        return stamp, target, stop
    raise AssertionError((index, price, target, stop, "no minute touched either exit"))


def reconcile(symbol, chart, raw, rates, strategy, plots):
    broker = strategy["orders"]
    reported = iter(strategy["trades"])
    openings = {}
    for order in broker:
        openings.setdefault(order["barIndex"], []).append(order)
    lots, trades, witnesses = deque(), [], []
    cash = Decimal(CAPITAL)
    unit = Decimal(".1") if symbol == "BTCUSDT" else Decimal(".01")
    for i, bar in enumerate(chart):
        day = bar["time"] // DAY * DAY
        fx = rates[day]
        for order in openings.get(i, []):
            origin = i - 1
            px, qty = decimal(order["price"]), decimal(order["qty"])
            assert i > 0 and order["time"] == bar["time"] and qty > 0
            assert approx(float(qty), qty.quantize(STEP)), (symbol, i, qty)
            qty = qty.quantize(STEP)
            side = 1 if order["id"] in ("long", "Tpl") else -1
            reversing = bool(lots and lots[0]["side"] != side)
            held_qty = sum((lot["qty"] for lot in lots), Decimal())
            close_quantity = Decimal()
            if order["direction"] == "strategy.exit":
                assert not reversing and held_qty == qty, (symbol, i, held_qty, qty)
                avg = sum(x["px"] * x["qty"] for x in lots) / held_qty
                preexisting = any(x["index"] < i for x in lots)
                stamp, target, stop = close_proof(
                    px,
                    avg,
                    side,
                    i,
                    preexisting,
                    plots,
                    raw[i * 10 : (i + 1) * 10],
                    unit,
                )
                witnesses.append(
                    {
                        "bar": i,
                        "market_minute": stamp,
                        "target": float(target),
                        "stop": float(stop),
                        "price": float(px),
                        "off_tick": px % unit != 0,
                    }
                )
                close_quantity = qty
            else:
                assert px == decimal(bar["open"]) and raw[i * 10][5] > 0
                which = "long" if side > 0 else "short"
                assert plots["testPeriod"][origin]
                assert (
                    plots[f"_{which}Condition"][origin]
                    or plots[f"Final_{which}_BB"][origin]
                )
                leverage = (
                    plots[f"last_dynamic_Leverage_{which}"][origin]
                    if plots[f"Final_{which}_BB"][origin]
                    else plots["Volume_Factor_Leverage"][origin]
                )
                prior_equity = decimal(strategy["equity"][origin]["equity"])
                prior_close = decimal(chart[origin]["close"])
                base_qty = prior_equity / prior_close * Decimal(".08")
                assert approx(plots["quanTity"][origin], base_qty)
                wanted_qty = (base_qty * decimal(leverage) // STEP) * STEP
                assert approx(
                    float(qty), wanted_qty + (held_qty if reversing else 0)
                ), (symbol, i, qty, wanted_qty)
                close_quantity = held_qty if reversing else Decimal()
            remaining = close_quantity
            while remaining:
                lot = lots[0]
                amount = min(lot["qty"], remaining)
                old = next(reported)
                assert (
                    old["entryBarIndex"],
                    old["exitBarIndex"],
                    old["entryTime"],
                    old["exitTime"],
                ) == (lot["index"], i, lot["time"], bar["time"])
                assert approx(old["qty"], amount * lot["side"])
                assert approx(old["entryPrice"], lot["px"]) and approx(
                    old["exitPrice"], px
                )
                gross = (px - lot["px"]) * amount * lot["side"] * fx
                charged = (lot["px"] * lot["fx"] + px * fx) * amount * FEE
                assert approx(old["profit"], gross - charged)
                cash += gross - px * amount * fx * FEE
                trades.append(
                    {
                        **old,
                        "qty": float(amount),
                        "dir": lot["side"],
                        "commission": float(charged),
                        "quote_entry_price": float(lot["px"]),
                        "quote_exit_price": float(px),
                        "entryPrice": float(lot["px"] * fx),
                        "exitPrice": float(px * fx),
                    }
                )
                remaining -= amount
                lot["qty"] -= amount
                if not lot["qty"]:
                    lots.popleft()
            new_qty = qty - close_quantity
            if new_qty:
                cash -= px * new_qty * fx * FEE
                lots.append(
                    {
                        "index": i,
                        "time": bar["time"],
                        "px": px,
                        "qty": new_qty,
                        "side": side,
                        "fx": fx,
                    }
                )
        unrealized = sum(
            (decimal(bar["close"]) - x["px"]) * x["qty"] * x["side"] * fx for x in lots
        )
        assert approx(strategy["equity"][i]["equity"], cash + unrealized), (
            symbol,
            i,
            cash,
            unrealized,
            strategy["equity"][i],
        )
    assert next(reported, None) is None
    return {
        "market": symbol,
        "unsettled": len(lots),
        "fills": broker,
        "settled": trades,
        "minute_exit_checks": witnesses,
    }


def main(document, data, currency_data, runtime, output):
    assert sha256(runtime / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(runtime))
    import pine_compat

    source = original(document)
    witness = "".join(f'\nplot({p}, "audit {p}")' for p in PLOTS) + "".join(
        f'\nplot({p} ? 1 : 0, "audit {p}")' for p in FLAGS
    )
    metered = source + witness
    recent = v5_control(metered)
    recent_with_minutes = recent.replace(
        "commission_value = 0.04)",
        "commission_value = 0.04, use_bar_magnifier=true)",
        1,
    )
    assert recent_with_minutes != recent
    rates, currency_provenance = daily_rates(currency_data)
    envelope = {
        "schemaVersion": 1,
        "pairs": [
            {
                "from": "USDT",
                "to": "USD",
                "rates": [
                    {"effectiveTime": date, "rate": float(rates[date])}
                    for date in range(BEGIN, END, DAY)
                ],
            }
        ],
    }
    raw_provenance, cases = [], []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        raw = prices(
            verified_archives(data, symbol, "1m", ("2023-09",), raw_provenance),
            BEGIN,
            END,
            60_000,
        )
        chart = [dict(zip(FIELDS, r, strict=True)) for r in aggregate(raw, 10)]
        minute = [dict(zip(FIELDS, r, strict=True)) for r in raw]
        groups = [
            {"chartBarIndex": i, "bars": minute[i * 10 : (i + 1) * 10]}
            for i in range(len(chart))
        ]
        opts = {
            "chart_symbol": "BINANCE:" + symbol,
            "chart_timeframe": "10",
            "execution_times": [END] * len(chart),
            "request_bars": {
                "$chart": {
                    "minMove": 1,
                    "priceScale": 10 if symbol == "BTCUSDT" else 100,
                    "quantityStep": ".001",
                    "minContract": ".001",
                    "pointValue": 1,
                    "currency": "USDT",
                },
                "$currencyRates": envelope,
            },
        }
        records = [
            pine_compat.run_script(p, chart, **opts) for p in (source, metered, recent)
        ]
        records.append(
            pine_compat.run_script(
                recent_with_minutes,
                chart,
                **opts,
                magnifier_bars={"schemaVersion": 1, "chartBars": groups},
            )
        )
        assert all(not x["diagnostics"] for x in records)
        strategy = records[0]["strategy"]
        assert not strategy["diagnostics"] and all(
            x["strategy"] == strategy for x in records
        )
        plots = [
            {
                x["title"].removeprefix("audit "): x["values"]
                for x in r["plots"]
                if x["title"].startswith("audit ")
            }
            for r in records[1:]
        ]
        assert plots[0] == plots[1] == plots[2]
        case = reconcile(symbol, chart, raw, rates, strategy, plots[0])
        case["minute_bars"] = len(raw)
        cases.append(case)
    common = {
        "id": 4651,
        "group": "FMZ Pine v4 · Instrumented indicator verification",
        "period": "2023-09-20 to 2023-09-27 UTC exclusive",
        "exit": "Named take profit and stop or reversal",
        "interval": "10m",
        "archive_interval": "10m",
        "currency": "USD",
        "pine_source_version": "4",
        "order_family": "Market entries with named brackets",
    }
    rows = [
        {
            **common,
            "market": c["market"],
            **ledger_metrics(c["settled"], CAPITAL, c["unsettled"]),
        }
        for c in cases
    ]
    rows.append(
        {
            **common,
            "market": "BTCUSDT + ETHUSDT",
            **ledger_metrics(
                [t for c in cases for t in c["settled"]],
                2 * CAPITAL,
                sum(c["unsettled"] for c in cases),
            ),
        }
    )
    write(
        output,
        {
            "schema": "FMZ #4651 historical indicator and bracket replay",
            "source_sha256": SOURCE_SHA,
            "native_engine_sha256": ENGINE_SHA,
            "source_url": "https://www.fmz.com/strategy/428070",
            "archives": raw_provenance,
            "usd_prior_day_rates": currency_provenance,
            "notes": {
                "timing": "Original 10m chart and 1m base. Timestamps pin timenow to the saved end. Four source-preserving engine variants produce identical fill and equity traces.",
                "broker": "USD 10,000 starting equity. 0.04% source fee per side converted with the prior confirmed Coinbase close. Optional named brackets reproduce at the first supporting minute. The source sometimes supplies zero distances before its stored entry reference initializes; these modeled same-open closures incur source fees. One ETH limit has extra precision. A conservative venue tick on the correct side is reachable in the same minute, while the simulated ledger retains the raw formula price. This model omits bid/ask spread and funding.",
                "reconciliation": "Matched entry gate, cash-based sizing, quantity floor, one-minute price eligibility, FIFO settlement, FX conversion, fees and marked equity for every chart bar.",
                "reference": "https://www.tradingview.com/pine-script-docs/v5/migration-guides/to-pine-version-5/",
            },
            "coverage": [
                [
                    4651,
                    "Tested · archived eager Pine v4 rules and minute bracket chronology",
                    "Recovered the unchanged Pine v4 strategy and verified the same results under compatibility and 1m controls. Source fills, FX, costs and FIFO settle independently on BTC and ETH.",
                ]
            ],
            "cases": cases,
            "results": rows,
        },
    )


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
