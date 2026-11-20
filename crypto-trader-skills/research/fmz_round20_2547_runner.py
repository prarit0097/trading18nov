"""Verify saved source indicators, every trade, and observable no-print effects."""

import json
import math
import sys
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from replay_2547 import OBS, cases, engine_options, pine_compat, scripts, sha256
from replay_2864 import near

HOUR = 3_600_000
CAPITAL = 50_000
FEE = 0.00075


def curves(chart):
    close = [b["close"] for b in chart]
    hl2 = [(b["high"] + b["low"]) / 2 for b in chart]
    lines = []
    for n, values in ((3, hl2), (6, hl2), (9, hl2), (50, close), (200, close)):
        line = [None] * (n - 1)
        line.append(math.fsum(values[:n]) / n)
        for value in values[n:]:
            prior = line[-1]
            if n == 200:
                alpha = 2 / (n + 1)
                line.append(alpha * value + (1 - alpha) * prior)
            else:
                line.append((prior * (n - 1) + value) / n)
        lines.append(line)
    expected = []
    for i, row in enumerate(chart):
        date = datetime.fromtimestamp(row["time"] / 1_000, UTC)
        session = date.weekday() < 5 and 3 <= date.hour <= 10
        points = [row["close"], *(line[i] for line in lines)]
        ready = all(point is not None for point in points)
        long = ready and all(a > b for a, b in zip(points, points[1:]))
        short = ready and all(a < b for a, b in zip(points, points[1:]))
        expected.append([*points[1:], int(session), int(long), int(short), 0])
    return expected


def bracket(children, side, entry, tick):
    entry = Decimal(str(entry))
    target = float(entry + side * 300 * tick)
    stop = float(entry - side * 300 * tick)
    for row in children:
        opening, high, low, close = (row[k] for k in ("open", "high", "low", "close"))
        if side * (opening - target) >= 0:
            return opening, row["time"], "target gap"
        if side * (opening - stop) <= 0:
            return opening, row["time"], "stop gap"
        high_first = high - opening < opening - low
        ends = (high, low) if high_first else (low, high)
        for price in (*ends, close):
            if side * (price - target) >= 0:
                return target, row["time"], "target"
            if side * (price - stop) <= 0:
                return stop, row["time"], "stop"
    raise AssertionError("Expected a same-hour closed bracket in this saved case.")


def audit(result, chart, groups, tick, expectations):
    book = result["strategy"]
    assert not result["diagnostics"] and not book["diagnostics"]
    for expected, actual in zip(expectations, zip(*(p["values"] for p in result["plots"]), strict=True), strict=True):
        for a, b in zip(expected, actual, strict=True):
            near(a, b)
    fills, trades, states = (iter(book[k]) for k in ("orders", "trades", "position"))
    ledger = []
    pnl = 0
    groups = [g["bars"] for g in groups]
    for i, (parent, children, equity) in enumerate(zip(chart, groups, book["equity"], strict=True)):
        side = expectations[i - 1][-3] - expectations[i - 1][-2] if i else 0
        if side:
            stamp, entry = parent["time"], children[0]["open"]
            close, execution_exit, reason = bracket(children, side, entry, tick)
            key = "long" if side == 1 else "short"
            entry_order, exit_order = next(fills), next(fills)
            for order, ident, direction, price in (
                (entry_order, key, f"strategy.{key}", entry),
                (exit_order, f"close{key}", "strategy.exit", close),
            ):
                assert order["id"] == ident and order["direction"] == direction, order
                assert order["time"] == stamp and order["barIndex"] == i and order["qty"] == 1
                near(order["price"], price)
            live, flat = next(states), next(states)
            assert live == {"barIndex": i, "size": side, "avgPrice": entry}, live
            assert flat == {"barIndex": i, "size": 0, "avgPrice": None}, flat
            trade = next(trades)
            assert trade["id"] == key and trade["qty"] == side
            assert trade["entryTime"] == trade["exitTime"] == stamp
            assert trade["entryBarIndex"] == trade["exitBarIndex"] == i
            near(trade["entryPrice"], entry)
            near(trade["exitPrice"], close)
            profit = side * (close - entry)
            near(trade["profit"], profit)
            fee = FEE * (entry + close)
            pnl += profit
            ledger.append({**trade, "effective_entry": children[0]["time"], "effective_exit": execution_exit, "reason": reason, "modeled_fees": fee, "after_fee_pnl": profit - fee})
        assert equity["barIndex"] == i
        near(equity["marketValue"], 0)
        near(equity["netProfit"], pnl)
        near(equity["cash"], CAPITAL + pnl)
        near(equity["equity"], CAPITAL + pnl)
    for stream in (fills, trades, states):
        assert next(stream, None) is None
    return ledger


def session_fixture():
    source = '''//@version=4
strategy("Session probe")
london = time(timeframe.period, "0300-1045") != 0
if bar_index == 0
    strategy.entry("long", 1, 1)
strategy.exit("closelong", "long", profit=300, loss=300)
strategy.close_all(when = not london, comment="london finish")
plot(london ? 1 : 0)
plot(strategy.position_size)
'''
    first = int(datetime(2023, 11, 6, 9, tzinfo=UTC).timestamp() * 1000)
    bars = [
        {"time": first + i * HOUR, "open": price, "high": price + 1, "low": price - 1, "close": price, "volume": 1}
        for i, price in enumerate((100, 100, 101, 102, 102))
    ]
    options = {**engine_options("BTCUSDT"), "chart_timeframe": "60"}
    r = pine_compat.run_script(source, bars, **options)
    assert not r["diagnostics"] and not r["strategy"]["diagnostics"]
    assert [p["values"] for p in r["plots"]] == [[1, 1, 0, 0, 0], [0, 1, 1, 0, 0]]
    orders = r["strategy"]["orders"]
    assert [(o["barIndex"], o["price"], o["qty"]) for o in orders] == [(1, 100, 1)], orders
    (trade,) = r["strategy"]["trades"]
    assert (trade["entryBarIndex"], trade["exitBarIndex"], trade["exitPrice"], trade["profit"]) == (1, 3, 102, 2)
    return {"signal_session": [1, 1, 0, 0, 0], "native_orders": orders, "closed_lot": trade}


def run():
    blob = (ROOT / "2547-replay.json").read_bytes()
    native = json.loads(blob)
    result = []
    negative = None
    for observed, (ref, chart, groups, options) in zip(native, cases(), strict=True):
        assert observed["file"] == ref["file"]
        error, = observed["invalid"]["exception"]
        assert error == "E_PARSE_EXPR:Error:77:27: expected expression"
        assert observed["original"]["strategy"] == observed["migrated"]["strategy"]
        assert [p["values"] for p in observed["original"]["plots"]] == [p["values"] for p in observed["migrated"]["plots"]]
        market = ref["market"]
        tick = Decimal("0.1" if market == "BTCUSDT" else "0.01")
        signals = curves(chart)
        bracket_1h = audit(observed["original"], chart, [{"bars": [row]} for row in chart], tick, signals)
        bracket_15m = audit(observed["base"], chart, groups, tick, signals)
        zero = [b["time"] for group in groups for b in group["bars"] if b["volume"] == 0]
        assert zero == ref["zero_print_timestamps"]
        filtered = [{**group, "bars": [b for b in group["bars"] if b["time"] not in zero]} for group in groups]
        primary = bracket_15m
        stale = []
        if zero:
            primary = audit(observed["drop_zero_children"], chart, filtered, tick, signals)
            assert observed["drop_zero_children"]["strategy"] == observed["first_print_execution_chart"]["strategy"]
            assert observed["drop_zero_children"]["plots"] == observed["first_print_execution_chart"]["plots"] == observed["base"]["plots"]
            stale = [{"unfiltered": a, "activity_only": b} for a, b in zip(bracket_15m, primary, strict=True) if a != b]
            assert len(stale) == 1
            before, after = stale[0]["unfiltered"], stale[0]["activity_only"]
            assert before["effective_entry"] in zero and after["effective_entry"] == max(zero) + 15 * 60_000
            assert after["entryPrice"] == before["exitPrice"]
            negative = pine_compat.run_script(scripts()[-1] + OBS, chart, **options, magnifier_bars={"schemaVersion": 1, "chartBars": filtered[:-1]})
            assert [x["code"] for x in negative["diagnostics"]] == ["W_MAGNIFIER_FALLBACK"]
        assert all(t["effective_entry"] not in zero and t["effective_exit"] not in zero for t in primary)
        result.append({
            **ref,
            "start": chart[0]["time"],
            "end": chart[-1]["time"] + HOUR,
            "long_signals": sum(s[-3] for s in signals),
            "short_signals": sum(s[-2] for s in signals),
            "finished_flat": True,
            "chart_vs_full_base_changed_lots": sum(a != b for a, b in zip(observed["original"]["strategy"]["trades"], observed["base"]["strategy"]["trades"], strict=True)),
            "hourly_gross": math.fsum(t["profit"] for t in bracket_1h),
            "unfiltered_base_gross": math.fsum(t["profit"] for t in bracket_15m),
            "primary_gross": math.fsum(t["profit"] for t in primary),
            "primary_after_fees": math.fsum(t["after_fee_pnl"] for t in primary),
            "primary_reasons": dict(Counter(t["reason"] for t in primary)),
            "stale_fill_difference": stale,
            "ledger": primary,
        })
    assert negative is not None
    output = {"results": result, "legacy_compile_error": error, "raw_sha256": sha256(blob), "missing_base_warning": "W_MAGNIFIER_FALLBACK", "session_exit_fixture": session_fixture()}
    (ROOT / "2547-verified.json").write_text(json.dumps(output, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "2547-verify-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
