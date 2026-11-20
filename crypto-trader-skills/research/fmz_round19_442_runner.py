"""Audit legacy DI/Donchian signals, one-bar reservations and USD settlements."""

import json
import sys
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from replay_442 import (
    CAPITAL,
    DAY,
    OBS,
    cases,
    engine_options,
    near,
    pine_compat,
    scripts,
    sha256,
)

FEE = 0.00075


def source_signals(chart):
    plus = minus = span = 0.0
    previous_high = previous_low = previous_close = 0.0
    lines = []
    series = []
    for i, bar in enumerate(chart):
        open_, high, low, close = [bar[k] for k in ("open", "high", "low", "close")]
        tr = max(high - low, abs(high - previous_close), abs(low - previous_close))
        up, down = high - previous_high, previous_low - low
        movement_plus = max(up, 0) if up > down else 0
        movement_minus = max(down, 0) if down > up else 0
        span = span - span / 14 + tr
        plus = plus - plus / 14 + movement_plus
        minus = minus - minus / 14 + movement_minus
        di_plus, di_minus = 100 * plus / span, 100 * minus / span
        conversion = None
        if i >= 6:
            recent = chart[i - 6 : i + 1]
            conversion = (
                max(b["high"] for b in recent) + min(b["low"] for b in recent)
            ) / 2
        date = datetime.fromtimestamp(bar["time"] / 1000, UTC)
        session = date.weekday() < 5 and 4 <= date.hour < 15
        buy = (
            session
            and conversion is not None
            and open_ < conversion < close
            and di_plus > 20
        )
        sell = (
            session
            and conversion is not None
            and close < conversion < open_
            and di_minus > 20
        )
        assert not (buy and sell)
        lines.append([conversion, di_plus, di_minus, int(session), int(buy), int(sell)])
        series.append(int(buy) - int(sell))
        previous_close, previous_high, previous_low = close, high, low
    return lines, series


def compare_signals(plot_report, chart):
    source, signals = source_signals(chart)
    curves = [p["values"] for p in plot_report["plots"]]
    assert len(curves) == 6
    for expected, actual in zip(source, zip(*curves, strict=True), strict=True):
        for a, b in zip(expected, actual, strict=True):
            near(a, b)
    return signals


def exit_from_path(children, trade_side, entry, tick):
    reference = Decimal(str(entry))
    target = float(reference + trade_side * 200 * tick)
    stop = float(reference - trade_side * 150 * tick)
    for book in children:
        opening = book["open"]
        if trade_side * (opening - target) >= 0:
            return opening, "target gap", book["time"]
        if trade_side * (opening - stop) <= 0:
            return opening, "stop gap", book["time"]
        high_first = book["high"] - opening < opening - book["low"]
        ends = (
            (book["high"], book["low"]) if high_first else (book["low"], book["high"])
        )
        for price in (*ends, book["close"]):
            if trade_side * (price - target) >= 0:
                return target, "target", book["time"]
            if trade_side * (price - stop) <= 0:
                return stop, "stop", book["time"]
    raise AssertionError("Expected a completed bracket in each verified case.")


def name(side):
    assert side in (-1, 1)
    return "buy" if side == 1 else "sel"


def audit(book, chart, bases, signals, rates, market):
    orders, trades = iter(book["orders"]), iter(book["trades"])
    current = None
    settled = CAPITAL
    tick = Decimal("0.1" if market == "BTCUSDT" else "0.01")
    ledger = []
    cases = Counter()

    def order(expected_id, kind, parent, idx, price):
        match = next(orders)
        assert match["id"] == expected_id and match["direction"] == kind
        assert (
            match["qty"] == 1
            and match["time"] == parent["time"]
            and match["barIndex"] == idx
        )
        near(match["price"], price)

    for idx, (bar, children) in enumerate(zip(chart, bases, strict=True)):
        opening, stamp = bar["open"], bar["time"]
        fx = rates[stamp // DAY * DAY]
        pending = signals[idx - 1] if idx else 0
        previous = current
        if pending:
            near(opening, children[0]["open"])
            order(
                name(pending),
                "strategy.long" if pending == 1 else "strategy.short",
                bar,
                idx,
                opening,
            )
            current = (pending, stamp, opening, idx)
        else:
            current = None
        if previous is not None:
            side, start, basis, open_idx = previous
            assert idx == open_idx + 1
            if pending == -side:
                exit_price, reason, effective = opening, "opposite raw order", stamp
                current = None
            else:
                exit_price, reason, effective = exit_from_path(
                    children, side, basis, tick
                )
                order(f"exit {name(side)}", "strategy.exit", bar, idx, exit_price)
                if pending == side:
                    cases["same_direction_add_before_reserved_exit"] += 1
            closed = next(trades)
            assert closed["id"] == name(side) and closed["qty"] == side
            assert closed["entryTime"] == start and closed["exitTime"] == stamp
            assert closed["entryBarIndex"] == open_idx and closed["exitBarIndex"] == idx
            near(closed["entryPrice"], basis)
            near(closed["exitPrice"], exit_price)
            gross = side * (exit_price - basis) * fx
            near(closed["profit"], gross)
            fx_entry = rates[start // DAY * DAY]
            charge = FEE * (basis * fx_entry + exit_price * fx)
            settled += gross
            ledger.append(
                {
                    **closed,
                    "reason": reason,
                    "effective_base_time": effective,
                    "fx_entry": fx_entry,
                    "fx_exit": fx,
                    "fee_sensitivity": charge,
                    "after_fee_sensitivity": gross - charge,
                }
            )
        marked = settled
        if current:
            side, _, basis, _ = current
            marked += side * (bar["close"] - basis) * fx
        near(book["equity"][idx]["equity"], marked)
    assert current is None and next(orders, None) is None and next(trades, None) is None
    assert book["position"][-1]["size"] == 0
    return ledger, dict(cases)


def reservation_fixture(fx):
    source = """//@version=5
strategy("Raw order reservation", currency=currency.USD, initial_capital=100000)
if bar_index <= 1
    strategy.order("buy", strategy.long, qty=1)
strategy.exit("exit buy", "buy", profit=200, loss=150)
"""
    points = [
        (100, 100, 100, 100),
        (100, 130, 80, 100),
        (125, 149, 105, 125),
        (149, 150, 145, 149),
    ]
    chart = [
        {
            "time": 1702425600000 + i * 1800000,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": 1,
        }
        for i, (o, h, l, c) in enumerate(points)
    ]
    opts = {**engine_options("BTCUSDT"), "chart_timeframe": "30"}
    opts["request_bars"]["$currencyRates"] = fx
    outcome = pine_compat.run_script(source, chart, **opts)
    assert not outcome["diagnostics"] and not outcome["strategy"]["diagnostics"]
    orders = outcome["strategy"]["orders"]
    expected_orders = [
        ("buy", 1, 100, 1),
        ("buy", 2, 125, 1),
        ("exit buy", 2, 125, 1),
        ("exit buy", 3, 149, 1),
    ]
    assert [
        (x["id"], x["barIndex"], x["price"], x["qty"]) for x in orders
    ] == expected_orders, orders
    return {
        "native_orders": orders,
        "first_position_stays_open_through_entry_bar": True,
    }


def run():
    probe = ROOT / "442-replay.json"
    raw = json.loads(probe.read_bytes())
    _, _, chosen = scripts()
    qualified = []
    fx_receipt = None
    for observed, (reference, start, stop, chart, groups, rates, opts) in zip(
        raw, cases(), strict=True
    ):
        assert observed["file"] == reference["file"]
        original, migrated, based = (
            observed[k] for k in ("original", "migrated", "base")
        )
        assert all(
            not r["diagnostics"] and not r["strategy"]["diagnostics"]
            for r in (original, migrated, based)
        )
        assert original["strategy"] == migrated["strategy"] == based["strategy"]
        assert (
            original["plots"][0]["values"]
            == migrated["plots"][0]["values"]
            == based["plots"][0]["values"]
        )
        signals = compare_signals(based, chart)
        ledger, reserved = audit(
            based["strategy"],
            chart,
            [g["bars"] for g in groups],
            signals,
            rates,
            reference["market"],
        )
        parent_ledger, same_reserved = audit(
            original["strategy"],
            chart,
            [[bar] for bar in chart],
            signals,
            rates,
            reference["market"],
        )
        assert reserved == same_reserved
        assert [
            {k: v for k, v in row.items() if k != "effective_base_time"}
            for row in ledger
        ] == [
            {k: v for k, v in row.items() if k != "effective_base_time"}
            for row in parent_ledger
        ]
        if not qualified:
            broken = pine_compat.run_script(
                chosen + OBS,
                chart,
                **opts,
                magnifier_bars={"schemaVersion": 1, "chartBars": groups[:-1]},
            )
            assert [x["code"] for x in broken["diagnostics"]] == [
                "W_MAGNIFIER_FALLBACK"
            ]
            fx_receipt = reservation_fixture(opts["request_bars"]["$currencyRates"])
        qualified.append(
            {
                **reference,
                "start": start,
                "end": stop,
                "signals": sum(sig != 0 for sig in signals),
                "orders": len(based["strategy"]["orders"]),
                "closed": len(ledger),
                "reserved": reserved,
                "ledger": ledger,
            }
        )
    result = {
        "raw_sha256": sha256(probe.read_bytes()),
        "cases": qualified,
        "fixture": fx_receipt,
        "missing_base_warning": "W_MAGNIFIER_FALLBACK",
    }
    (ROOT / "442-verified.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf8"
    )


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "442-verify-error.txt").write_text(
            traceback.format_exc(), encoding="utf8"
        )
        raise
