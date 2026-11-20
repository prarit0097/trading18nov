"""Probe the narrowly scoped archived #3604 initial-capital relocation."""

import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from replay_2864 import engine_options, near, pine_compat, sha256

CAPITAL = 50_000
FEE_OVERLAY = 0.00075
HOUR = 3_600_000
INPUTS = {
    "feed-BTCUSDT-60-10-2026-08-01.json": "a5755ee6025dfdcab4cfb9ac9b3aadbace660d5b55ff17506fcb6efded2e8c0f",
    "feed-BTCUSDT-60-10-2026-09-01.json": "3a81c4ede2336c5d0c73c8046370f4c57447d900591dbc4af98c0f7231610a92",
    "feed-ETHUSDT-60-10-2026-08-01.json": "93dc2ba45c253f976e815145566c72b4479912f4af8d3faa8514d764a4061697",
    "feed-ETHUSDT-60-10-2026-09-01.json": "8ee222940f301fc9b88523d9c873d34323aa4bbf9656eeda3b4c66f7558f238a",
}

OBSERVER = """
plot(entryLongSignal ? 1 : 0, title="Check bullish block")
plot(entryShortSignal ? 1 : 0, title="Check bearish block")
plot(strategy.initial_capital + strategy.netprofit, title="Check settled denominator")
"""


def programs():
    raw = (ROOT / "wallet-3604.md").read_bytes()
    assert (
        sha256(raw)
        == "901f3dcc56cbaccc1a604972e410972b92da4ac87be57818f829e33c90f35e36"
    )
    (code,) = re.findall(r"(?m)^``` pinescript\n(.*?)^```", raw.decode(), re.DOTALL)
    code, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", code)
    assert n == 1
    declaration = 'strategy("[Backtest] Order Block Finder", overlay = true)'
    replacement = 'strategy("[Backtest] Order Block Finder", overlay = true, initial_capital = 50000)'
    assert code.count(declaration) == 1 and code.count("strategy.initial_capital") == 5
    edited, n = re.subn(r"(?m)^strategy\.initial_capital = 50000[ \t]*\n", "", code)
    assert n == 1
    migrated = edited.replace(declaration, replacement)
    return (
        code,
        migrated,
        migrated.replace("strategy.initial_capital", "50000"),
        edited.replace("strategy.initial_capital", "50000"),
    )


def archive_rejection(archive):
    try:
        pine_compat.compile_script(archive)
    except ValueError as failure:
        archive_error = str(failure).splitlines()
        assert archive_error == ["E_PARSE_EXPR:Error:219:26: expected expression"]
        assert "strategy.initial_capital = 50000" in archive.splitlines()[218]
        return archive_error
    else:
        raise AssertionError(
            "Expected a rejected namespaced assignment in the archived Pine."
        )


def options_for(market):
    return {**engine_options(market), "chart_timeframe": "60"}


def fixture_ordering():
    prefix = """//@version=4
strategy("Entry close ordering", initial_capital=50000)
if bar_index == 0
    strategy.entry("Long Entry", strategy.long)
if bar_index == 1
    strategy.entry("TARGET", SIDE)
    strategy.close("Long Entry")
"""
    feed = [
        {
            "time": i * HOUR,
            "open": price,
            "high": price + 1,
            "low": price - 1,
            "close": price,
            "volume": 1,
        }
        for i, price in enumerate((100, 101, 102, 103))
    ]
    samples = {}
    for label, target, side in (
        ("reversal", "Short Entry", "strategy.short"),
        ("repeat", "Long Entry", "strategy.long"),
    ):
        code = prefix.replace("TARGET", target).replace("SIDE", side)
        outcome = pine_compat.run_script(code, feed, **options_for("BTCUSDT"))
        assert not outcome["diagnostics"] and not outcome["strategy"]["diagnostics"]
        samples[label] = outcome["strategy"]["orders"]
    return samples


def load_feed(name, checksum):
    raw = (ROOT / name).read_bytes()
    assert sha256(raw) == checksum
    record = json.loads(raw)
    keys = ("time", "open", "high", "low", "close", "volume")
    chart = [dict(zip(keys, row, strict=True)) for row in record["chart"]]
    assert [bar["time"] for bar in chart] == list(
        range(record["from"], record["to"], HOUR)
    )
    return record["symbol"], record["from"], record["to"], chart


def entry_patterns(chart):
    signals = [0] * 6
    candle_sides = [
        (bar["close"] > bar["open"]) - (bar["close"] < bar["open"]) for bar in chart
    ]
    for i in range(6, len(chart)):
        pos = candle_sides[i - 6] == -1 and candle_sides[i - 5 : i] == [1] * 5
        neg = candle_sides[i - 6] == 1 and candle_sides[i - 5 : i] == [-1] * 5
        assert not (pos and neg)
        signals.append(int(pos) - int(neg))
    return signals


def id_for(side):
    assert side in (-1, 1)
    return "Long Entry" if side == 1 else "Short Entry"


def audit(actual, observed, chart):
    assert not actual["diagnostics"] and not actual["strategy"]["diagnostics"]
    assert actual["strategy"] == observed["strategy"] and not observed["diagnostics"]
    broker = actual["strategy"]
    bull, bear, balances = [p["values"] for p in observed["plots"][-3:]]
    signals = entry_patterns(chart)
    assert bull == [int(s == 1) for s in signals] and bear == [
        int(s == -1) for s in signals
    ]
    order_iterator = iter(broker["orders"])
    trade_iterator = iter(broker["trades"])
    balance = CAPITAL
    current_side = entry_stamp = entry_price = 0
    pending_open = pending_close = 0
    ledger = []

    def read_order(i, bar, id_, direction, qty):
        order = next(order_iterator)
        assert order["id"] == id_ and order["direction"] == direction, (
            i,
            order,
            id_,
            direction,
        )
        assert (
            order["barIndex"] == i
            and order["time"] == bar["time"]
            and order["qty"] == qty
        )
        near(order["price"], bar["open"])

    def settle(bar, kind):
        nonlocal balance, current_side
        native = next(trade_iterator)
        price = bar["open"]
        assert native["id"] == id_for(current_side) and native["qty"] == current_side
        assert native["entryTime"] == entry_stamp and native["exitTime"] == bar["time"]
        near(native["entryPrice"], entry_price)
        near(native["exitPrice"], price)
        gross = current_side * (price - entry_price)
        near(native["profit"], gross)
        fee = FEE_OVERLAY * (price + entry_price)
        ledger.append(
            {
                **native,
                "reason": kind,
                "fee_sensitivity": fee,
                "after_fee_sensitivity": gross - fee,
            }
        )
        balance += gross
        current_side = 0

    for i, (bar, signal) in enumerate(zip(chart, signals, strict=True)):
        if pending_close and pending_close == current_side:
            read_order(
                i,
                bar,
                f"Close entry(s) order {id_for(current_side)}",
                "strategy.close",
                1,
            )
            move = current_side * (chart[i - 1]["close"] - entry_price)
            settle(bar, "take_profit" if move / balance >= 0.02 else "stop_loss")
        if pending_open:
            target_id = id_for(pending_open)
            read_order(
                i,
                bar,
                target_id,
                ("strategy.long" if pending_open == 1 else "strategy.short"),
                1 + abs(current_side),
            )
            if current_side:
                settle(bar, "reversal")
            current_side, entry_stamp, entry_price = (
                pending_open,
                bar["time"],
                bar["open"],
            )
        near(balance, balances[i])
        pending_open = signal if signal != current_side else 0
        open_profit = current_side * (bar["close"] - entry_price)
        threshold = open_profit / balance
        pending_close = current_side if threshold >= 0.02 or threshold <= -0.01 else 0
    assert next(order_iterator, None) is None and next(trade_iterator, None) is None
    last = broker["position"][-1] if broker["position"] else {"size": 0}
    near(last["size"], current_side)
    equity = balance + current_side * (chart[-1]["close"] - entry_price)
    near(broker["equity"][-1]["equity"], equity)
    assert math.isfinite(equity)
    return ledger, last, signals


def run():
    archive, relocated, literal, default = programs()
    versions = [
        pine_compat.compile_script(code)
        for code in (relocated, literal, relocated + OBSERVER)
    ]
    archive_errors = archive_rejection(archive)
    orders = fixture_ordering()
    expected_controls = {
        "reversal": [
            ("Long Entry", 1),
            ("Close entry(s) order Long Entry", 1),
            ("Short Entry", 1),
        ],
        "repeat": [("Long Entry", 1), ("Close entry(s) order Long Entry", 1)],
    }
    assert {
        key: [(r["id"], r["qty"]) for r in rows] for key, rows in orders.items()
    } == expected_controls, orders
    runs = []
    for name, checksum in INPUTS.items():
        market, start, stop, chart = load_feed(name, checksum)
        options = options_for(market)
        actual, control, observed = [
            engine.run(chart, **options) for engine in versions
        ]
        assert actual == control
        assert actual["strategy"]["equity"][0]["equity"] == CAPITAL
        ledger, position, signals = audit(actual, observed, chart)
        if not runs:
            different_account = pine_compat.run_script(default, chart, **options)
            assert different_account["strategy"]["equity"][0]["equity"] == 1_000_000
            for key in ("orders", "trades", "position"):
                assert actual["strategy"][key] == different_account["strategy"][key]
        runs.append(
            {
                "market": market,
                "start": start,
                "stop": stop,
                "feed": name,
                "feed_sha256": checksum,
                "chart_bars": len(chart),
                "orders": len(actual["strategy"]["orders"]),
                "long_signals": signals.count(1),
                "short_signals": signals.count(-1),
                "closed": len(ledger),
                "ending_position": position,
                "ledger": ledger,
            }
        )
    result = {
        "archive_error": archive_errors,
        "order_conflict_controls": orders,
        "migrated_sha256": sha256(relocated.encode()),
        "runs": runs,
    }
    (ROOT / "3604-replay.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf8"
    )


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "3604-error.txt").write_text(traceback.format_exc(), encoding="utf8")
        raise
