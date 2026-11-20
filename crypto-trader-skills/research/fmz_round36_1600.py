"""Replay #1600 with prior calendar pivots and reconcile whole-lot executions."""

import calendar
import math
import re
import sys
from collections import deque
from datetime import UTC, datetime
from decimal import Decimal
from itertools import groupby
from pathlib import Path

from research.fmz_round7_magnifier import (
    aggregate,
    date_ms,
    ledger_metrics,
    sha256,
    verified_archives,
    write,
)
from research.fmz_round18_5745 import ENGINE_SHA, FIELDS
from research.fmz_round26_977 import prices

SOURCE_SHA = "2a09d73eaaf3c4d39aad94d7835aa7179b3a02c7a24c5a323e31c864fb271307"
REVISION = "7853bb2bf262c4567ac238d3552d97f0e50cb801"
HOUR, DAY = 3_600_000, 86_400_000
BEGIN, END, MONTH_START = map(date_ms, ("2022-11-27", "2023-12-03", "2022-10-01"))
FEE = Decimal(".00075")
LOTS_PER_UNIT = 1000
CAPITAL = Decimal(1000000)
PLOTS = {
    "PP": "PP",
    "Requested buy calls": "requestBuys",
    "Requested sell calls": "requestSells",
    "Initial grid reference": "OpenPrice",
    "Final grid reference": "FinalOpenPrice",
    "Average price reference": "AveragePrice",
    "Down origin": "PPdownOrigin",
    "Up origin": "PPupOrigin",
}


def source_program(document):
    assert sha256(document) == SOURCE_SHA
    fence = chr(96) * 3
    (saved,) = re.findall(
        r"(?ms)^" + fence + r" pinescript[^\n]*\n(.*?)^" + fence,
        document.read_text(encoding="utf-8"),
    )
    original, count = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", saved)
    assert count == 1 and original.splitlines().count("//@version=4") == 1
    assert (
        original.count(
            "security(_symbol, _res, _src[1], lookahead = barmerge.lookahead_on)"
        )
        == 1
    )
    marker = "for _i = 1 to 15\n    if fBuyCondition(_i)\n"
    assert original.count(marker) == 1
    program = original.replace(
        marker,
        "int requestBuys = 0\nint requestSells = 0\n"
        + marker
        + "        requestBuys := requestBuys + 1\n",
    )
    marker = "    if fSellCondition(_i)\n        nBuys"
    assert program.count(marker) == 1
    program = program.replace(
        marker,
        "    if fSellCondition(_i)\n        requestSells := requestSells + 1\n        nBuys",
    )
    witness = "".join(
        f'\nplot({name}, "{title}")' for title, name in PLOTS.items() if title != "PP"
    )
    original_with_witness = program + witness
    equivalent, count = re.subn(
        r"(?ms)(^fGrid\(_1, _2, _n\) =>\n).*?(?=^// .+ Initial Open Price)",
        r"\1    _1 + (_n - 1) * _2\n\n",
        original_with_witness,
    )
    assert count == 1
    prefix, marker, _ = program.partition("// ————— Plotting Pivot Points")
    assert (
        marker
        and prefix.count("strategy.entry(") == prefix.count("strategy.close(") == 1
    )
    return original_with_witness, equivalent, prefix + '\nplot(PP, "PP")' + witness


def year_month(stamp):
    value = datetime.fromtimestamp(stamp / 1000, UTC)
    return value.year, value.month


def split_candles(rows):
    chart = [bar for bar in aggregate(rows, 24) if bar[0] >= BEGIN]
    # Aggregate the monthly feed directly from hours, independently of daily reconstruction.
    monthly = {}
    for (year, month), sequence in groupby(rows, key=lambda bar: year_month(bar[0])):
        part = list(sequence)
        if len(part) == calendar.monthrange(year, month)[1] * 24:
            monthly[(year, month)] = aggregate(part, len(part))[0]
    assert len(chart) == 371 and len(monthly) == 14
    expected = []
    for stamp, *_ in chart:
        year, month = year_month(stamp)
        previous = monthly[(year, month - 1) if month > 1 else (year - 1, 12)]
        assert previous[0] < stamp
        expected.append(sum(Decimal(str(price)) for price in previous[2:5]) / 3)
    # Supply the opening timestamp for the last partial month so the [1] offset
    # sees November throughout December. No December close values are projected.
    first_partial = next(row for row in rows if year_month(row[0]) == (2023, 12))
    assert first_partial[0] == date_ms("2023-12-01")
    return chart, [*monthly.values(), first_partial], expected


def close_enough(a, b):
    return math.isclose(a, float(b), rel_tol=1e-12, abs_tol=1e-9)


def rounded_units(float_units):
    ticks = round(float_units * LOTS_PER_UNIT)
    assert close_enough(float_units, Decimal(ticks) / LOTS_PER_UNIT)
    return ticks


def independent_ledger(instrument, chart, order_calls, strategy):
    lots = deque()
    closed, fills, ghosts = [], [], []
    raw_orders = {x["barIndex"]: x for x in strategy["orders"]}
    assert len(raw_orders) == len(strategy["orders"])
    raw_closed = [t for t in strategy["trades"] if rounded_units(t["qty"])]
    actual_equity = strategy["equity"]
    realized = Decimal(0)
    peak, marked_dd = CAPITAL, Decimal(0)
    buy_calls, sell_calls = order_calls
    for i, (time, bar_open, _, _, close, volume) in enumerate(chart):
        if i:
            buy_now, sell_now = buy_calls[i - 1], sell_calls[i - 1]
            assert not (buy_now and sell_now), (instrument, i)
        else:
            buy_now = sell_now = 0
        # The same-ID market entry queues once for the next open. A named close
        # requests two units, limited to the inventory present when it was queued.
        close_prev = Decimal(str(chart[i - 1][4]))
        buy_ticks = int(Decimal(10000) / close_prev * LOTS_PER_UNIT) if buy_now else 0
        sell_ticks = (
            min(2 * LOTS_PER_UNIT, sum(lot["ticks"] for lot in lots)) if sell_now else 0
        )
        expected_ticks = buy_ticks or sell_ticks
        raw_order = raw_orders.get(i)
        if raw_order and not rounded_units(raw_order["qty"]):
            ghosts.append(
                {
                    "bar_index": i,
                    "quantity": raw_order["qty"],
                    "price": raw_order["price"],
                }
            )
            raw_order = None
        assert bool(raw_order) == bool(expected_ticks), (
            instrument,
            i,
            raw_order,
            expected_ticks,
        )
        price = Decimal(str(bar_open))
        if raw_order:
            assert volume > 0
            assert (
                raw_order["time"] == time and Decimal(str(raw_order["price"])) == price
            )
            assert rounded_units(raw_order["qty"]) == expected_ticks, (
                instrument,
                i,
                raw_order,
                expected_ticks,
            )
            if buy_ticks:
                assert (raw_order["id"], raw_order["direction"]) == (
                    "BUY",
                    "strategy.long",
                )
                lots.append(
                    {"bar_index": i, "time": time, "price": price, "ticks": buy_ticks}
                )
            else:
                assert (raw_order["id"], raw_order["direction"]) == (
                    "Close entry(s) order BUY",
                    "strategy.close",
                )
                remaining = sell_ticks
                while remaining:
                    lot = lots[0]
                    amount = min(remaining, lot["ticks"])
                    qty = Decimal(amount) / LOTS_PER_UNIT
                    gross = (price - lot["price"]) * qty
                    fees = (price + lot["price"]) * qty * FEE
                    native = raw_closed[len(closed)]
                    assert (
                        native["entryBarIndex"],
                        native["exitBarIndex"],
                        native["entryTime"],
                        native["exitTime"],
                    ) == (lot["bar_index"], i, lot["time"], time)
                    assert (
                        rounded_units(native["qty"]),
                        Decimal(str(native["entryPrice"])),
                        Decimal(str(native["exitPrice"])),
                    ) == (amount, lot["price"], price)
                    assert close_enough(native["profit"], gross)
                    closed.append(
                        {
                            "entryBar": lot["bar_index"],
                            "exitBar": i,
                            "entryTime": lot["time"],
                            "exitTime": time,
                            "entryPrice": float(lot["price"]),
                            "exitPrice": float(price),
                            "qty": float(qty),
                            "dir": 1,
                            "commission": float(fees),
                            "profit": float(gross - fees),
                        }
                    )
                    realized += gross
                    lot["ticks"] -= amount
                    remaining -= amount
                    if not lot["ticks"]:
                        lots.popleft()
            fills.append(raw_order)
        mark = (
            CAPITAL
            + realized
            + sum(
                (Decimal(str(close)) - lot["price"]) * lot["ticks"] / LOTS_PER_UNIT
                for lot in lots
            )
        )
        assert actual_equity[i]["barIndex"] == i and close_enough(
            actual_equity[i]["equity"], mark
        )
        peak = max(peak, mark)
        marked_dd = max(marked_dd, peak - mark)
    assert len(raw_closed) == len(closed)
    assert rounded_units(strategy["position"][-1]["size"]) == sum(
        lot["ticks"] for lot in lots
    )
    return {
        "market": instrument,
        "market_fills": fills,
        "closed": closed,
        "unsettled_lots": len(lots),
        "native_sub_lot_orders": ghosts,
        "native_sub_lot_trades": len(strategy["trades"]) - len(closed),
        "buy_command_evaluations": sum(buy_calls),
        "close_command_evaluations": sum(sell_calls),
        "gross_marked_dd": float(marked_dd),
    }


def replay(engine, programs, symbol, rows):
    chart, monthly, expected = split_candles(rows)

    def encode(dataset):
        return [dict(zip(FIELDS, row, strict=True)) for row in dataset]

    market = "BINANCE:" + symbol
    frames = {
        market + ":M": encode(monthly),
        market + ":1M": encode(monthly),
        "$chart": {
            "minMove": 1,
            "priceScale": 10 if symbol == "BTCUSDT" else 100,
            "quantityStep": ".001",
            "minContract": ".001",
            "pointValue": 1,
            "currency": "USDT",
        },
    }
    expected_warnings = {"W_LEGACY_SECURITY_LOOKAHEAD"}
    output, events = [], []
    for program in programs:
        result = engine.run_script(
            program,
            encode(chart),
            chart_symbol=market,
            chart_timeframe="D",
            request_bars=frames,
        )
        strategy = result["strategy"]
        assert {
            x["code"] for x in result["diagnostics"]
        } == expected_warnings and not strategy["diagnostics"]
        plots = {
            x["title"]: x["values"] for x in result["plots"] if x["title"] in PLOTS
        }
        assert plots.keys() == PLOTS.keys()
        assert all(
            close_enough(value, reference)
            for value, reference in zip(plots["PP"], expected, strict=True)
        )
        events.append(plots)
        output.append(strategy)
    assert output[0] == output[1] == output[2], (
        symbol,
        [len(x["orders"]) for x in output],
    )
    assert events[0] == events[1] == events[2], symbol
    receipt = independent_ledger(
        symbol,
        chart,
        (events[0]["Requested buy calls"], events[0]["Requested sell calls"]),
        output[0],
    )
    receipt["monthly_pivot_checks"] = len(expected)
    receipt["monthly_input_groups"] = len(monthly)
    return receipt


def main(document, data, runtime, output):
    assert sha256(runtime / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(runtime))
    import pine_compat

    months = ("2022-10", "2022-11", "2022-12", *(f"2023-{i:02}" for i in range(1, 13)))
    programs, feeds, cases = source_program(document), [], []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        campaign = prices(
            verified_archives(data, symbol, "1h", months, feeds), MONTH_START, END, HOUR
        )
        cases.append(replay(pine_compat, programs, symbol, campaign))
    common = {
        "id": 1600,
        "group": "FMZ Pine v4 · Prior-month grid",
        "period": "2022-11-27 to 2023-12-03 UTC exclusive",
        "interval": "1d",
        "archive_interval": "1d",
        "currency": "USDT",
        "pine_source_version": "4",
        "exit": "Source grid market reductions at the next daily open",
        "order_family": "Market entry and named partial close",
    }
    results = [
        {
            **common,
            "market": case["market"],
            **ledger_metrics(case["closed"], float(CAPITAL), case["unsettled_lots"]),
        }
        for case in cases
    ]
    results.append(
        {
            **common,
            "market": "BTCUSDT + ETHUSDT",
            **ledger_metrics(
                [lot for case in cases for lot in case["closed"]],
                2 * float(CAPITAL),
                sum(case["unsettled_lots"] for case in cases),
            ),
        }
    )
    write(
        output,
        {
            "schema": "FMZ #1600 prior completed monthly pivots and market orders",
            "source_revision": REVISION,
            "source_sha256": SOURCE_SHA,
            "native_engine_sha256": ENGINE_SHA,
            "data_archives": feeds,
            "notes": {
                "timing": "All chart decisions use completed daily bars. Every monthly source uses the previous completed UTC month, which an independent calculation matches on every date. Every modeled market fill is at the actual next hour open starting its UTC session.",
                "source": "The source-published trade path, grid levels and parameters remain unchanged. Instrumentation, an algebraically equivalent constant-step grid control and the trade-only prefix produce the same order events and account history.",
                "execution": "Native broker default capital is 1M USDT and source default size is 10,000 USDT per entry. The independent broker verifies each named close and each FIFO settlement at the explicit 0.001 base-unit step. Sub-step floating remnants cannot be filled and are recorded separately outside performance.",
                "costs": "0.075% per-side fee overlay on closed lots. No funding or other execution charges are included. Workbook drawdown is realized and the report also records gross marked drawdown.",
            },
            "coverage": [
                [
                    1600,
                    "Tested · FMZ Pine v4 prior-month grid orders",
                    "Every prior UTC-month pivot, next-open order, FIFO lot and daily marked balance independently reconcile across BTC and ETH. The exact source and two behavior-preserving controls matched.",
                ]
            ],
            "cases": cases,
            "results": results,
        },
    )


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
