"""Verify #388 decision parity and simulate separate relative exits for each lot."""

import math
import re
import sys
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
from research.fmz_round18_5745 import ENGINE_SHA, FIELDS
from research.fmz_round26_977 import prices

SOURCE = "daf13b100e92cbd1b8f1f1c13d6c96f932b153e3ca10c1f938c0835b49ecd007"
BEGIN, END = map(date_ms, ("2024-01-01", "2024-02-01"))
CAPITAL, STEP, FEE, ALLOCATION = (
    Decimal(10000),
    Decimal(".001"),
    Decimal(".0003"),
    Decimal(".5"),
)
TP = (Decimal(".009"), Decimal(".017"))
SL = Decimal(".07")
PLOTS = {
    "long": "long and ACT_BT and testPeriod ? 1 : 0",
    "short": "short and ACT_BT and testPeriod ? 1 : 0",
    "reference_long": "last_open_longCondition",
    "reference_short": "last_open_shortCondition",
    "prior_daily": "src4h",
    "tp_first": "tp",
    "tp_second": "tp2",
    "sl": "sl",
}


def source_program(document):
    assert sha256(document) == SOURCE
    fence = chr(96) * 3
    (source,) = re.findall(
        r"(?ms)^" + fence + r"[^\n]*\n(.*?)^" + fence,
        document.read_text(encoding="utf-8"),
    )
    assert "//@version" not in source
    assert all(
        word not in source
        for word in (
            "strategy.position_",
            "strategy.equity",
            "strategy.open",
            "strategy.closed",
        )
    )
    assert "default_qty_value = 50" in source and "commission_value=0.03" in source
    repaired, count = re.subn(
        r"(?m)^(\s*\w+_\d_h\s*=\s*iff\([^\n]+\)),[ \t]*$", r"\1", source
    )
    assert count == 2
    repaired = re.sub(
        r"\b(?:ta|math|request)\.(\w+)\b",
        r"\1",
        repaired.replace("length_/2)", "int(length_/2))"),
    )
    assert repaired.count("lookahead=barmerge.lookahead_on") == 1
    assert "zl ? close[1]" in repaired
    section = repaired.splitlines()
    stripped = [
        line for line in section if not re.match(r"^\s*strategy\.(entry|exit)\(", line)
    ]
    order_guards = [
        i
        for i, line in enumerate(stripped)
        if re.match(r"^if\s*\(?(long|short)\)?\s*$", line)
    ]
    assert len(order_guards) == 2
    for i in reversed(order_guards):
        del stripped[i]
    witnesses = "".join(
        f'\nplot({expr}, title="model {name}")' for name, expr in PLOTS.items()
    )
    return "//@version=4\n" + repaired + witnesses, "//@version=4\n" + "\n".join(
        stripped
    ) + witnesses


def signal_rows(engine, chart, programs, market, price_tick):
    def objects(data):
        return [dict(zip(FIELDS, row, strict=True)) for row in data]

    name = "BINANCE:" + market
    hours = objects(chart)
    days = objects(aggregate(chart, 24))
    metadata = {
        "minMove": 1,
        "priceScale": int(1 / price_tick),
        "quantityStep": "1",
        "minContract": "1",
        "pointValue": float(STEP),
        "currency": "USDT",
    }
    opts = {
        "chart_symbol": name,
        "chart_timeframe": "60",
        "request_bars": {
            f"{name}:60": hours,
            f"{name}:D": days,
            f"{name}:1440": days,
            "$chart": metadata,
        },
    }
    normal, isolated = (
        engine.run_script(program, hours, **opts) for program in programs
    )
    assert not normal["strategy"]["diagnostics"] and not isolated["strategy"]["orders"]
    assert {w["code"] for w in normal["diagnostics"]} == {
        w["code"] for w in isolated["diagnostics"]
    }
    ledgers = [
        {
            p["title"][6:]: p["values"]
            for p in r["plots"]
            if p.get("title", "").startswith("model ")
        }
        for r in (normal, isolated)
    ]
    assert ledgers[0] == ledgers[1]
    flags = ledgers[0]
    assert all(len(x) == len(chart) for x in flags.values())
    assert flags["prior_daily"] == [None] * 24 + [
        days[i // 24 - 1]["close"] for i in range(24, len(chart))
    ]
    assert (
        flags["tp_first"] == [0.9] * len(chart)
        and flags["tp_second"] == [1.7] * len(chart)
        and flags["sl"] == [7] * len(chart)
    )
    assert all(a + b <= 1 for a, b in zip(flags["long"], flags["short"], strict=True))
    gates = [
        (a - b, buy, sell)
        for a, b, buy, sell in zip(
            flags["long"],
            flags["short"],
            flags["reference_long"],
            flags["reference_short"],
            strict=True,
        )
    ]
    return (
        gates,
        normal["strategy"]["orders"][:2],
        sorted({w["code"] for w in normal["diagnostics"]}),
    )


def tick_round(price, tick, greater):
    return (price / tick).to_integral_value(
        rounding=ROUND_CEILING if greater else ROUND_FLOOR
    ) * tick


def replay(chart, minutes, gates, price_tick, high_first, bracket_priority):
    """Resolve price eligibility per entry and settle exposure oldest lot first."""
    cash = CAPITAL
    lots = []
    closed, orders, bracket_fills = [], [], []
    gap_coincidences = 0
    peak, marked_dd = CAPITAL, Decimal()

    def close(quantity, exit_price, stamp, reason, signal_id):
        nonlocal cash
        while quantity:
            lot = lots[0]
            qty = min(quantity, lot["qty"])
            entry_fee = qty * lot["price"] * FEE
            exit_fee = qty * exit_price * FEE
            gross = lot["side"] * qty * (exit_price - lot["price"])
            cash += gross - exit_fee
            closed.append(
                {
                    "id": lot["id"],
                    "entryTime": lot["time"],
                    "exitTime": stamp,
                    "dir": lot["side"],
                    "qty": float(qty),
                    "entryPrice": float(lot["price"]),
                    "exitPrice": float(exit_price),
                    "commission": float(entry_fee + exit_fee),
                    "profit": float(gross - entry_fee - exit_fee),
                    "exit_reason": reason,
                    "requested_bracket_lot": signal_id,
                }
            )
            quantity -= qty
            lot["qty"] -= qty
            if not lot["qty"]:
                del lots[0]

    def levels(lot, buy_ref, sell_ref):
        side = lot["side"]
        reference = buy_ref if side == 1 else sell_ref
        target = lot["price"] + side * reference * TP[lot["leg"]]
        stop = lot["price"] - side * reference * SL
        return tick_round(target, price_tick, side > 0), tick_round(
            stop, price_tick, side < 0
        )

    def fire(lot, price, stamp, reason):
        quantity = lot["qty"]
        lot["armed"] = False
        bracket_fills.append(
            {
                "reference_lot": lot["id"],
                "reference_entry_time": lot["time"],
                "price": float(price),
                "qty": float(quantity),
                "time": stamp,
                "reason": reason,
            }
        )
        close(quantity, price, stamp, reason, lot["time"])

    def opening_matches(stamp, opening, buy_ref, sell_ref):
        for lot in lots[:]:
            if not lot["armed"] or not lot["qty"]:
                continue
            target, stop = levels(lot, buy_ref, sell_ref)
            side = lot["side"]
            if (opening - target) * side >= 0:
                fire(lot, opening, stamp, "target at open")
            elif (opening - stop) * side <= 0:
                fire(lot, opening, stamp, "stop at open")

    def follow_segment(stamp, before, after, buy_ref, sell_ref):
        upward = after > before
        while before != after and lots:
            candidates = []
            for index, lot in enumerate(lots):
                if not lot["armed"]:
                    continue
                target, stop = levels(lot, buy_ref, sell_ref)
                take = (lot["side"] > 0) == upward
                price = target if take else stop
                reached = (
                    before <= price <= after if upward else after <= price <= before
                )
                if reached:
                    candidates.append((abs(price - before), index, price, lot, take))
            if not candidates:
                break
            _, _, price, lot, take = min(candidates)
            fire(lot, price, stamp, "target" if take else "stop")
            before = price

    for i, hourly in enumerate(chart):
        assert minutes[60 * i][0] == hourly[0]
        if not i:
            continue
        direction, long_ref, short_ref = gates[i - 1]
        buy_ref, sell_ref = (Decimal(str(x or 0)) for x in (long_ref, short_ref))
        for lot in lots:
            lot["armed"] = True
        for minute, (stamp, vopen, vhigh, vlow, vclose, volume) in enumerate(
            minutes[i * 60 : (i + 1) * 60]
        ):
            opening, high, low, closing = (
                Decimal(str(x)) for x in (vopen, vhigh, vlow, vclose)
            )
            if minute == 0 and direction:
                if bracket_priority:
                    at_start = len(bracket_fills)
                    opening_matches(stamp, opening, buy_ref, sell_ref)
                    gap_coincidences += len(bracket_fills) - at_start
                if lots and lots[0]["side"] != direction:
                    close(
                        sum(lot["qty"] for lot in lots),
                        opening,
                        stamp,
                        "opposite market entry",
                        None,
                    )
                for leg in range(2):
                    if len(lots) >= 100:
                        break
                    ident = f"{'L' if direction > 0 else 'S'}_{leg + 1}"
                    equity = cash + sum(
                        (opening - x["price"]) * x["qty"] * x["side"] for x in lots
                    )
                    qty = (
                        max(equity, Decimal())
                        * ALLOCATION
                        / (opening * (1 + FEE))
                        // STEP
                    ) * STEP
                    if not qty:
                        continue
                    cash -= qty * opening * FEE
                    lots.append(
                        {
                            "id": ident,
                            "leg": leg,
                            "side": direction,
                            "price": opening,
                            "qty": qty,
                            "time": stamp,
                            "armed": True,
                        }
                    )
                    orders.append(
                        {
                            "id": ident,
                            "chart_bar": i,
                            "time": stamp,
                            "price": float(opening),
                            "qty": float(qty),
                        }
                    )
                    assert volume > 0
            opening_matches(stamp, opening, buy_ref, sell_ref)
            extremes = (high, low) if high_first else (low, high)
            previous = opening
            for current in (*extremes, closing):
                follow_segment(stamp, previous, current, buy_ref, sell_ref)
                previous = current
            equity = cash + sum(
                (closing - x["price"]) * x["qty"] * x["side"] for x in lots
            )
            peak = max(peak, equity)
            marked_dd = max(marked_dd, peak - equity)
    paid_closed = math.fsum(t["profit"] for t in closed)
    paid_open = sum(lot["qty"] * lot["price"] * FEE for lot in lots)
    assert math.isclose(
        float(cash), float(CAPITAL - paid_open) + paid_closed, rel_tol=1e-12
    )
    return {
        "orders": orders,
        "closed": closed,
        "unsettled": len(lots),
        "bracket_fills": bracket_fills,
        "existing_gap_matches_before_new_entry": gap_coincidences,
        "cash": float(cash),
        "end_equity": float(equity),
        "marked_drawdown": float(marked_dd),
    }


def compare_outcomes(a, b):
    def financial(trades):
        return sorted(
            tuple(
                x[k]
                for k in (
                    "id",
                    "entryTime",
                    "exitTime",
                    "qty",
                    "entryPrice",
                    "exitPrice",
                    "profit",
                )
            )
            for x in trades
        )

    return (
        a["orders"] == b["orders"]
        and financial(a["closed"]) == financial(b["closed"])
        and a["cash"] == b["cash"]
    )


def verify_market_priority(engine):
    program = """//@version=4
strategy("Queue priority", pyramiding=10, initial_capital=10000, commission_value=.03)
if bar_index == 0
    strategy.entry("A", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("B", strategy.long, qty=1)
strategy.exit("Bracket A", "A", profit=10, loss=10)
"""
    bars = [
        {
            "time": i * 3_600_000,
            "open": price,
            "high": price + 1,
            "low": price,
            "close": price,
            "volume": 100,
        }
        for i, price in enumerate((100, 100, 85, 85), 1)
    ]
    metadata = {
        "minMove": 1,
        "priceScale": 1,
        "quantityStep": "1",
        "minContract": "1",
        "pointValue": 1,
        "currency": "USDT",
    }
    receipts = []
    for version in (4, 5):
        result = engine.run_script(
            program.replace("//@version=4", f"//@version={version}"),
            bars,
            chart_timeframe="60",
            request_bars={"$chart": metadata},
        )
        assert not result["diagnostics"] and not result["strategy"]["diagnostics"]
        receipts.append(result["strategy"])
    assert receipts[0] == receipts[1]
    assert [(x["id"], x["barIndex"], x["price"]) for x in receipts[0]["orders"]] == [
        ("A", 1, 100),
        ("B", 2, 85),
        ("Bracket A", 2, 85),
    ]
    return {
        "program": program,
        "synthetic_bars": bars,
        "orders_in_both_versions": receipts[0]["orders"],
    }


def main(document, data, runtime, output):
    assert sha256(runtime / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(runtime))
    import pine_compat

    programs = source_program(document)
    queue_test = verify_market_priority(pine_compat)
    archives, cases = [], []
    for market, tick in (("BTCUSDT", Decimal(".1")), ("ETHUSDT", Decimal(".01"))):
        raw = prices(
            verified_archives(data, market, "1m", ("2024-01",), archives),
            BEGIN,
            END,
            60_000,
        )
        quarters = prices(
            verified_archives(data, market, "15m", ("2024-01",), archives),
            BEGIN,
            END,
            900_000,
        )
        chart = aggregate(quarters, 4)
        assert all(
            x[:5] == y[:5] for x, y in zip(chart, aggregate(raw, 60), strict=True)
        )
        gates, first_two, warnings = signal_rows(
            pine_compat, chart, programs, market, tick
        )
        primary = replay(chart, raw, gates, tick, True, False)
        reversed_path = replay(chart, raw, gates, tick, False, False)
        bracket_first = replay(chart, raw, gates, tick, True, True)
        assert compare_outcomes(primary, reversed_path), (
            market,
            "minute sequence materially matters",
        )
        primary["stop_first_sensitivity"] = {
            "same_financial_ledger": compare_outcomes(primary, bracket_first),
            "net_closed": math.fsum(t["profit"] for t in bracket_first["closed"]),
            "closed": len(bracket_first["closed"]),
            "terminal_equity": bracket_first["end_equity"],
            "gap_first_matches": bracket_first["existing_gap_matches_before_new_entry"],
        }
        for independent, native in zip(primary["orders"][:2], first_two, strict=True):
            assert independent["price"] == native["price"] and math.isclose(
                independent["qty"], float(STEP) * native["qty"], abs_tol=1e-9
            )
        primary["market"] = market
        primary["gap_priority_control_matches"] = bracket_first[
            "existing_gap_matches_before_new_entry"
        ]
        primary["input_flags"] = {
            "long": sum(a > 0 for a, *_ in gates),
            "short": sum(a < 0 for a, *_ in gates),
        }
        primary["warnings"] = warnings
        cases.append(primary)
    common = {
        "id": 388,
        "group": "FMZ · per-entry relative bracket and causal cash sizing",
        "period": "Binance USD-M · January 2024 UTC",
        "interval": "1h + recorded 1m",
        "archive_interval": "60m",
        "currency": "USDT",
        "exit": "Original relative stops and targets by individual entry",
        "order_family": "50% equity sibling entries with separate relative exits",
    }
    results = [
        {
            **common,
            "market": c["market"],
            **ledger_metrics(c["closed"], float(CAPITAL), c["unsettled"]),
        }
        for c in cases
    ]
    results.append(
        {
            **common,
            "market": "BTCUSDT + ETHUSDT",
            **ledger_metrics(
                [v for c in cases for v in c["closed"]],
                2 * float(CAPITAL),
                sum(c["unsettled"] for c in cases),
            ),
        }
    )
    write(
        output,
        {
            "schema": "FMZ #388 independent per-entry relative-bracket replay",
            "source_sha256": SOURCE,
            "native_indicator_engine": ENGINE_SHA,
            "market_archives": archives,
            "same_open_queue_fixture": queue_test,
            "notes": {
                "data": "744 confirmed chart hours per symbol. Official 1m and 15m parents match all OHLC values. All previous daily levels equal confirmed daily closes. The source has no saved backtest window.",
                "model": "Closed-hour signals match the same compilation without broker calls. Each next-open sibling uses half of marked equity with the source fee and whole 0.001 base-unit lots. Each relative bracket uses its own entry and is moved to a legal tick while preserving its directional protection. The exit removes inventory in FIFO order.",
                "control": "Both within-minute high/low orders produce identical realized results and position sizes. The observed priority fixture places new same-open market orders before an existing bracket. The stop-first sensitivity quantifies the alternative. No funding or added slippage.",
                "primary_reference": "https://www.tradingview.com/pine-script-docs/v5/concepts/strategies/#exits-for-multiple-entries",
            },
            "coverage": [
                [
                    388,
                    "Tested · source signals and independent per-entry minute brackets",
                    "Preserved the archived two-sibling entry logic. Reconciled 1m and 15m chart parents and independently modeled documented per-entry exits with source commission, causal lot sizing and FIFO cost attribution. Both minute paths agree under the verified market-first priority; the alternate priority is measured separately.",
                ]
            ],
            "cases": cases,
            "results": results,
        },
    )


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
