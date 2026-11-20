"""Replay FMZ #1781 and verify its active orders from completed hourly data."""

import math
import re
import sys
from itertools import pairwise
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
from research.fmz_round31_dema_tsi import PINE_EMA, ema

SOURCE_SHA = "b6cee15cd190951fd548c99b9128092a0deed28cd47051928d8ed8973686f880"
REVISION = "7853bb2bf262c4567ac238d3552d97f0e50cb801"
START, END = "2022-10-11", "2023-10-17"
HOUR = 3_600_000
CAPITAL, FEE = 1_000_000, 0.00075
SIZES = (1, 2, 4, 8, 5, 6, 7, 8, 9, 10)
FRACTIONS = (0, 0.21, 0.30, 0.50, 0.62, 0.70, 1.0)
STAGE_EXCLUSIONS = (
    (),
    (),
    (1,),
    (2,),
    (2, 3),
    (3, 4),
    (2, 4, 5),
    (2, 4, 5, 6),
    (2, 4, 5, 6, 7),
    (2, 4, 5, 6, 7, 8),
)
EXITS = tuple(
    f"short{stage or ''}_{reason}" for reason in ("tp", "sl") for stage in range(4)
)
SIGNALS = (
    tuple(
        f"{side}{stage or ''}_signal"
        for stage in range(10)
        for side in ("long", "short")
    )
    + EXITS
)
ORDERS = tuple(
    (
        f"{side}{stage or ''}_signal",
        ("Long" if side == "long" else short_id),
        side,
        size,
    )
    for stage, size in enumerate(SIZES)
    for side, short_id in (
        ("long", ""),
        ("short", f"Short{stage if 1 <= stage <= 3 else ''}"),
    )
)
CLOSES = tuple((name, name.split("_")[0].capitalize()) for name in EXITS)


def source_program(path, engine):
    assert sha256(path) == SOURCE_SHA
    fence = chr(96) * 3
    (saved,) = re.findall(
        r"(?ms)^" + fence + r" pinescript[^\n]*\n(.*?)^" + fence,
        path.read_text(encoding="utf-8"),
    )
    source, count = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", saved)
    assert count == 1 and source.startswith("//@version=2\n")
    try:
        engine.compile_script(source)
    except ValueError as exc:
        diagnostic = str(exc)
        assert "E_LEGACY_VERSION_FEATURE" in diagnostic
    else:
        raise AssertionError("Expected the original mixed-version diagnostics")
    active = "\n".join(line.partition("//")[0] for line in source.splitlines())
    for i in range(11):
        assert len(re.findall(rf"\bhfib{i}\b", active)) == 1
    assert len(re.findall(r"\bdata2\b", active)) == 12
    assert len(re.findall(r"\bres5\b", active)) == 12
    source, count = re.subn(r"(?m)^(?:hfib[0-9]+|data2|res5)\s*=.*\n", "", source)
    assert count == 13
    typed = []

    def explicit_history(match):
        name, rhs = match.groups()
        if re.search(rf"\b{name}\s*\[", rhs):
            typed.append(name)
            return f"float {name} = na\n{name} := {rhs}"
        return match.group()

    source = re.sub(r"(?m)^(\w+)[ \t]*=[ \t]*([^=\n].*)$", explicit_history, source)
    assert len(typed) == len(set(typed)) == 70
    instrumented = source + "".join(
        f'\nplot({name} ? 1 : 0, "{name}")' for name in SIGNALS
    )
    compatibility = instrumented.replace(
        "//@version=2\n", "//@version=2\n" + PINE_EMA + "\n", 1
    )
    return (
        instrumented,
        re.sub(r"\bema\(", "compat_ema(", compatibility),
        diagnostic,
        typed,
    )


def rsi45(closes):
    moves = [b - a for a, b in pairwise(closes)]
    gains = [max(0, d) for d in moves]
    losses = [max(0, -d) for d in moves]
    up, down = sum(gains[:45]) / 45, sum(losses[:45]) / 45
    output = [None] * 45
    for i in range(44, len(moves)):
        if i >= 45:
            up = (up * 44 + gains[i]) / 45
            down = (down * 44 + losses[i]) / 45
        output.append(100 - 100 / (1 + up / down) if down else 100)
    return output


def market_inputs(candles, stable_pivots):
    highs, lows, closes = (
        [c[name] for c in candles] for name in ("high", "low", "close")
    )
    hist = [a - b for a, b in zip(ema(closes, 12), ema(closes, 26), strict=True)]
    hist = [a - b for a, b in zip(hist, ema(hist, 9), strict=True)]
    rsi = rsi45(closes)
    fibs = []
    trailing_extremes = [[], []]
    rolling_total = [0.0, 0.0]
    pivots = [None, None]
    for i in range(len(candles)):
        if i >= 13:
            for p, (values, extremum) in enumerate(((highs, max), (lows, min))):
                current = extremum(values[i - 13 : i + 1])
                history = trailing_extremes[p]
                rolling_total[p] -= history[-14] if len(history) >= 14 else 0.0
                rolling_total[p] += current
                history.append(current)
                # A missing deviation is false in this v2 conditional. Once initialized,
                # zero requires exact equality even when rolling float arithmetic drifts.
                ready = len(history) >= 14
                mean = rolling_total[p] / 14
                window = history[-14:]
                flat = (
                    min(window) == max(window)
                    if stable_pivots
                    else all(value == mean for value in window)
                )
                if not ready or flat:
                    pivots[p] = current
        high, low = pivots
        if high is None or low is None:
            fibs.append([None] * len(FRACTIONS))
        else:
            fibs.append([(high - low) * part + low for part in FRACTIONS])
    return closes, hist, rsi, fibs


def independent_signals(candles, stable_pivots=False):
    closes, hist, rsi, fibs = market_inputs(candles, stable_pivots)
    raw_stamp = [[0] * 10 for _ in range(2)]
    signal_stamp = [[0] * 10 for _ in range(2)]
    previous_raw = [[None] * 10 for _ in range(2)]
    short_open = [0.0] * 4
    records = []

    def cross(i, level):
        now, previous = fibs[i][level], fibs[i - 1][level]
        if not i or now is None or previous is None:
            return False
        return (closes[i] > now and closes[i - 1] <= previous) or (
            closes[i] < now and closes[i - 1] >= previous
        )

    for i, candle in enumerate(candles):
        time = candle["time"]
        old_raw = [s[:] for s in raw_stamp]
        old_signal = [s[:] for s in signal_stamp]
        active = [[False] * 10 for _ in range(2)]
        triggers = [[False] * 10 for _ in range(2)]

        momentum = [False, False]
        if i >= 47:
            momentum[0] = hist[i] > 0 and 90 > rsi[i] > rsi[i - 1] > rsi[i - 2]
            momentum[1] = hist[i] < 0 and 10 < rsi[i] < rsi[i - 1] < rsi[i - 2]
        for d in (0, 1):
            triggers[d][0] = momentum[d] and cross(i, (0, 6)[d])
            if triggers[d][0]:
                raw_stamp[d][0] = time
        for d in (0, 1):
            opposite = 1 - d
            active[d][0] = (
                i > 0
                and raw_stamp[d][0] > raw_stamp[opposite][0]
                and old_raw[d][0] <= old_raw[opposite][0]
            )
            if active[d][0]:
                signal_stamp[d][0] = time
        for d in (0, 1):
            opposing = signal_stamp[1 - d][0]
            for stage in range(1, 10):
                first_signal = old_signal[d][0] > opposing
                if stage >= 2:
                    first_signal = (
                        first_signal
                        and signal_stamp[d][1] > old_signal[d][0]
                        and not active[d][1]
                    )
                if stage < 4:
                    level = (stage, 6 - stage)[d]
                    raw = first_signal and momentum[d] and cross(i, level)
                else:
                    raw = first_signal and triggers[d][0]
                triggers[d][stage] = raw
                if raw:
                    raw_stamp[d][stage] = time
                activate = (
                    i > 0
                    and raw_stamp[d][stage] > signal_stamp[d][stage - 1]
                    and old_raw[d][stage] <= old_signal[d][stage - 1]
                    and not any(active[d][e] for e in STAGE_EXCLUSIONS[stage])
                )
                active[d][stage] = activate
                if activate:
                    signal_stamp[d][stage] = time
        for stage in range(4):
            if triggers[1][stage]:
                short_open[stage] = candle["open"]
        gate = [value is False for value in previous_raw[1][:4]]
        tp = [
            ok and candle["low"] <= price - 30
            for ok, price in zip(gate, short_open, strict=True)
        ]
        sl = [
            ok and candle["high"] >= price + 10
            for ok, price in zip(gate, short_open, strict=True)
        ]
        flags = (
            [
                flag
                for stage in range(10)
                for flag in (active[0][stage], active[1][stage])
            ]
            + tp
            + sl
        )
        records.append(dict(zip(SIGNALS, flags, strict=True)))
        previous_raw = triggers
    return records


def independently_settle(candles, rows, signals):
    fills, trades, open_lots = [], [], []
    for i in range(1, len(candles)):
        candle, children, gate = candles[i], rows[24 * i : 24 * (i + 1)], signals[i - 1]
        assert candle["time"] == children[0][0] and candle["open"] == children[0][1]
        stamp, price = children[0][:2]
        open_on_signal = open_lots[:]
        for trigger, ident, side, quantity in ORDERS:
            if not gate[trigger]:
                continue
            direction = 1 if side == "long" else -1
            opposing = (
                open_lots if open_lots and open_lots[0]["qty"] * direction < 0 else []
            )
            if not opposing and len(open_lots) >= 10:
                continue
            if opposing:
                for lot in opposing:
                    trades.append(
                        {
                            **lot,
                            "exitBarIndex": i,
                            "exitTime": stamp,
                            "exitPrice": price,
                            "profit": lot["qty"] * (price - lot["entryPrice"]),
                        }
                    )
                open_lots = []
            fills.append(
                {
                    "id": ident,
                    "barIndex": i,
                    "time": stamp,
                    "direction": "strategy." + side,
                    "qty": quantity + sum(abs(lot["qty"]) for lot in opposing),
                    "price": price,
                }
            )
            open_lots.append(
                {
                    "id": ident,
                    "entryBarIndex": i,
                    "entryTime": stamp,
                    "entryPrice": price,
                    "qty": direction * quantity,
                }
            )
            assert children[0][5] > 0
        for trigger, ident in CLOSES:
            matching = [
                lot for lot in open_on_signal if lot["id"] == ident and lot in open_lots
            ]
            if not gate[trigger] or not matching:
                continue
            for lot in matching:
                open_lots.remove(lot)
                trades.append(
                    {
                        **lot,
                        "exitBarIndex": i,
                        "exitTime": stamp,
                        "exitPrice": price,
                        "profit": lot["qty"] * (price - lot["entryPrice"]),
                    }
                )
            fills.append(
                {
                    "id": "Close entry(s) order " + ident,
                    "barIndex": i,
                    "time": stamp,
                    "direction": "strategy.close",
                    "qty": sum(abs(lot["qty"]) for lot in matching),
                    "price": price,
                }
            )
            assert children[0][5] > 0
    return fills, trades, open_lots


def verify_market(engine, literal, compatible, symbol, raw):
    candles = [dict(zip(FIELDS, row, strict=True)) for row in aggregate(raw, 24)]
    assert len(candles) == 371
    options = {
        "chart_symbol": f"BINANCE:{symbol}",
        "chart_timeframe": "D",
        "request_bars": {
            "$chart": {
                "minMove": 1,
                "priceScale": 10 if symbol == "BTCUSDT" else 100,
                "quantityStep": ".001",
                "minContract": ".001",
                "pointValue": 1,
                "currency": "USDT",
            }
        },
    }
    first = engine.run_script(literal, candles, **options)
    measured = engine.run_script(compatible, candles, **options)
    assert first["strategy"] == measured["strategy"], symbol
    signal_flags = independent_signals(candles)
    plots = {plot["title"]: plot["values"] for plot in measured["plots"]}
    literal_plots = {plot["title"]: plot["values"] for plot in first["plots"]}
    assert plots == literal_plots
    for name in SIGNALS:
        assert len(plots[name]) == len(signal_flags)
        for i, actual in enumerate(plots[name]):
            assert actual == int(signal_flags[i][name]), (
                symbol,
                name,
                i,
                actual,
                signal_flags[i],
            )
    fills, trades, ending = independently_settle(candles, raw, signal_flags)
    strategy = measured["strategy"]
    assert not measured["diagnostics"] and not strategy["diagnostics"]
    assert fills == strategy["orders"], (symbol, fills, strategy["orders"])
    assert trades == strategy["trades"]
    expected_size = sum(lot["qty"] for lot in ending)
    assert expected_size == strategy["position"][-1]["size"]

    for i, candle in enumerate(candles):
        realized = sum(t["profit"] for t in trades if t["exitBarIndex"] <= i)
        inventory = [*ending, *(t for t in trades if t["exitBarIndex"] > i)]
        mark = sum(
            t["qty"] * (candle["close"] - t["entryPrice"])
            for t in inventory
            if t["entryBarIndex"] <= i
        )
        actual = strategy["equity"][i]
        assert actual["barIndex"] == i
        assert math.isclose(actual["equity"], CAPITAL + realized + mark, abs_tol=1e-7)
    adjusted = []
    for t in trades:
        qty = abs(t["qty"])
        fee = qty * (t["entryPrice"] + t["exitPrice"]) * FEE
        adjusted.append(
            {
                **t,
                "qty": qty,
                "dir": 1 if t["qty"] > 0 else -1,
                "commission": fee,
                "profit": t["profit"] - fee,
            }
        )
    stable_signals = independent_signals(candles, stable_pivots=True)
    differences = [
        {
            "bar_index": i,
            "time": candles[i]["time"],
            "commands": [name for name in SIGNALS if actual[name] != stable[name]],
        }
        for i, (actual, stable) in enumerate(
            zip(signal_flags, stable_signals, strict=True)
        )
        if actual != stable
    ]
    return {
        "market": symbol,
        "fills": fills,
        "closed_lots": adjusted,
        "ending_lots": ending,
        "evaluated_daily_bars": len(candles),
        "checked_command_flags": len(candles) * len(SIGNALS),
        "mathematical_pivot_sensitivity": differences,
    }


def main(document, data, runtime, output):
    assert sha256(runtime / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(runtime))
    import pine_compat

    literal, compatible, diagnostic, history = source_program(document, pine_compat)
    months = ("2022-10", "2022-11", "2022-12", *(f"2023-{i:02}" for i in range(1, 11)))
    inputs = []
    cases = []
    start, end = map(date_ms, (START, END))
    for symbol in ("BTCUSDT", "ETHUSDT"):
        raw = prices(
            verified_archives(data, symbol, "1h", months, inputs), start, end, HOUR
        )
        cases.append(verify_market(pine_compat, literal, compatible, symbol, raw))
    common = {
        "id": 1781,
        "group": "FMZ Pine v2 · Incremental Fibonacci orders",
        "period": "2022-10-11 to 2023-10-17 UTC exclusive",
        "interval": "1d",
        "archive_interval": "1d",
        "currency": "USDT",
        "pine_source_version": "2",
        "exit": "Next daily open following an authored short close or reversal",
        "order_family": "Market entries and strategy.close",
        "repairs": [
            "Explicit recursive initialization",
            "Unused higher-timeframe variables removed",
        ],
    }
    result = [
        {
            **common,
            "market": case["market"],
            **ledger_metrics(case["closed_lots"], CAPITAL, len(case["ending_lots"])),
        }
        for case in cases
    ]
    result.append(
        {
            **common,
            "market": "BTCUSDT + ETHUSDT",
            **ledger_metrics(
                [trade for case in cases for trade in case["closed_lots"]],
                CAPITAL * 2,
                sum(len(case["ending_lots"]) for case in cases),
            ),
        }
    )
    write(
        output,
        {
            "schema": "FMZ #1781 fixed-source daily replay",
            "source_revision": REVISION,
            "source_sha256": SOURCE_SHA,
            "native_engine_sha256": ENGINE_SHA,
            "market_inputs": inputs,
            "archived_compile_diagnostic": diagnostic,
            "explicit_recursive_states": history,
            "notes": {
                "replay": "Source BTC archive dates and timeframe, with ETH using the same UTC dates. Both cases independently verify decision flags, next-open rows, closed lots and every native marked equity snapshot.",
                "costs": "Source omits commissions. Report overlays 0.075% per side on closed lots. No independent spread, slippage or funding data is claimed and reported drawdown uses realized P&L.",
                "positions": "The native default starts each separate market at 1M USDT and retains authored base-unit sizing. No order on the terminal date is filled outside the documented period.",
                "scope": "Historical compatibility execution using documented source defaults. The deleted higher-timeframe graph has no consumers outside itself.",
                "pivot_precision": "The source treats the numeric deviation as a boolean. The pinned engine uses an incremental rolling sum and exact zero. Mathematically flat windows can fail this gate under floating-point rounding. The separate sensitivity records all changed command flags under a stable exact-price flatness check.",
                "order_timing_reference": "https://www.tradingview.com/pine-script-docs/faq/strategies/",
            },
            "coverage": [
                [
                    1781,
                    "Tested · FMZ Pine v2 restored recursive Fibonacci entries",
                    "Original BTC daily window plus matched ETH. Independently reconciled all 28 order flags on each bar, 17 market fills, 10 closed FIFO lots and EMA-initialization control. Results use the pinned runtime floating-point deviation gate.",
                ]
            ],
            "cases": cases,
            "results": result,
        },
    )


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
