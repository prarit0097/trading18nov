"""Independently audit #2121 recurrences and flag ambiguous hourly bracket order."""

import json
import math
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from replay_2121 import VARS, cases, sha256
from replay_2864 import near

FEE = 0.00075


def raw_bands(rows):
    last = None
    result = []
    for r in rows:
        high, low, close = (r[k] for k in ("high", "low", "close"))
        midpoint = (high + low) / 2
        tr = high - low if last is None else max(high - low, abs(high - last), abs(low - last))
        result.append((midpoint - tr, midpoint + tr, close))
        last = close
    return result


def trail(raw):
    levels = []
    previous_upper = previous_lower = previous_close = None
    side = 1
    for up, down, price in raw:
        new_up = max(up, previous_upper) if previous_upper is not None and previous_close > previous_upper else up
        new_down = min(down, previous_lower) if previous_lower is not None and previous_close < previous_lower else down
        if previous_lower is not None and price > previous_lower:
            side = 1
        elif previous_upper is not None and price < previous_upper:
            side = -1
        levels.append((new_up, new_down, side, new_up if side == 1 else new_down))
        previous_upper, previous_lower, previous_close = new_up, new_down, price
    return levels


def decisions(chart, lower, observation):
    primary = raw_bands(chart)
    secondary = raw_bands(lower)[11::12]
    state, aux = trail(primary), trail(secondary)
    plots = {p["title"]: p["values"] for p in observation["plots"]}
    signals = []
    for i, (a, b, c, d) in enumerate(zip(primary, secondary, state, aux, strict=True)):
        direction, auxiliary = c[2], d[2]
        row = [*a[:2], *b, *c[:2], *d[:2], direction, auxiliary, c[3], d[3]]
        for var, value in zip(VARS, row, strict=True):
            near(value, plots[f"Observed {var}"][i])
        change = i and direction != state[i - 1][2] and direction == auxiliary
        signals.append(direction if change else 0)
        assert plots["Observed long"][i] == int(signals[-1] == 1)
        assert plots["Observed short"][i] == int(signals[-1] == -1)
    return signals


def find_exit(children, position, min_tick):
    side, _, _, entry = position
    price = Decimal(str(entry))
    target = float(price + side * 500 * min_tick)
    stop = float(price - side * 400 * min_tick)
    for b in children:
        o, h, low = (b[k] for k in ("open", "high", "low"))
        stamp = b["time"]
        if side * (o - target) >= 0:
            return o, stamp, "target gap", False, target, stop
        if side * (o - stop) <= 0:
            return o, stamp, "stop gap", False, target, stop
        both = low <= min(stop, target) and h >= max(stop, target)
        high_first = h - o < o - low
        extrema = (h, low) if high_first else (low, h)
        for p in extrema:
            if side * (p - target) >= 0:
                return target, stamp, "target", both, target, stop
            if side * (p - stop) <= 0:
                return stop, stamp, "stop", both, target, stop
    return None


def reconcile(result, chart, execution, signals, tick):
    broker = result["strategy"]
    assert not result["diagnostics"] and not broker["diagnostics"]
    initial_capital = broker["equity"][0]["cash"]
    orders, trades, positions = (iter(broker[k]) for k in ("orders", "trades", "position"))
    position = None
    realized = 0.0
    order_counts = Counter()
    ledger = []

    def side_name(side):
        return "Buy" if side == 1 else "Sell"

    def settle(i, stamp, price, order_stamp, reason, both, target, stop):
        nonlocal position, realized
        side, first, first_stamp, entry = position
        trade = next(trades)
        assert trade["id"] == side_name(side) and trade["qty"] == side
        assert (trade["entryBarIndex"], trade["exitBarIndex"], trade["entryTime"], trade["exitTime"]) == (first, i, first_stamp, stamp)
        near(trade["entryPrice"], entry)
        near(trade["exitPrice"], price)
        gross = side * (price - entry)
        near(trade["profit"], gross)
        fee = FEE * (entry + price)
        ledger.append({**trade, "after_fee": gross - fee, "fee": fee, "effective_base_exit": order_stamp, "reason": reason, "both_price_levels_hit": both, "target": target, "stop": stop})
        flat = next(positions)
        assert flat == {"barIndex": i, "size": 0, "avgPrice": None}
        order_counts[reason] += 1
        realized += gross
        position = None

    for i, (bar, children, equity, end_size) in enumerate(zip(chart, execution, broker["equity"], result["plots"][-1]["values"], strict=True)):
        stamp, opening = bar["time"], bar["open"]
        signal = signals[i - 1] if i else 0
        if signal and (position is None or signal != position[0]):
            actual = next(orders)
            side = "long" if signal == 1 else "short"
            assert actual["id"] == side_name(signal) and actual["direction"] == f"strategy.{side}"
            assert (actual["time"], actual["barIndex"], actual["qty"]) == (stamp, i, 1 + int(position is not None))
            near(actual["price"], opening)
            if position:
                settle(i, stamp, opening, stamp, "reverse", False, None, None)
            position = (signal, i, stamp, opening)
            live = next(positions)
            assert live == {"barIndex": i, "size": signal, "avgPrice": opening}
            order_counts["entry"] += 1
        if position:
            possible = find_exit(children, position, tick)
            if possible:
                expected, effective, reason, both, target, stop = possible
                actual = next(orders)
                assert actual["id"] == f"Close {side_name(position[0])}" and actual["direction"] == "strategy.exit", (i, possible, actual)
                assert (actual["time"], actual["barIndex"], actual["qty"]) == (stamp, i, 1)
                near(actual["price"], expected)
                settle(i, stamp, expected, effective, reason, both, target, stop)
        current = position[0] if position else 0
        assert current == end_size
        floating = current * (bar["close"] - position[-1]) if position else 0
        value = current * bar["close"]
        near(equity["netProfit"], realized + floating)
        near(equity["marketValue"], value)
        near(equity["equity"], initial_capital + realized + floating)
        near(equity["cash"], initial_capital + realized + floating - value)
    assert all(next(stream, None) is None for stream in (orders, trades, positions))
    return {"capital": initial_capital, "open": position, "order_counts": dict(order_counts), "ledger": ledger}


def run():
    source = ROOT / "2121-replay.json"
    raw = json.loads(source.read_bytes())
    results = []
    for known, (ref, chart, lower, groups, _) in zip(raw, cases(), strict=True):
        assert known["file"] == ref["file"]
        errors = known["invalid"]["exceptions"]
        assert any(x.startswith("E_LEGACY_VERSION_FEATURE") for x in errors)
        assert known["legacy"]["strategy"] == known["migrated"]["strategy"]
        signals = decisions(chart, lower, known["legacy"])
        assert signals == decisions(chart, lower, known["migrated"]) == decisions(chart, lower, known["magnified"])
        tick = Decimal("0.1" if ref["market"] == "BTCUSDT" else "0.01")
        coarse = reconcile(known["legacy"], chart, [[b] for b in chart], signals, tick)
        exact = reconcile(known["magnified"], chart, [g["bars"] for g in groups], signals, tick)
        results.append({
            **ref, "signals": {"up": signals.count(1), "down": signals.count(-1)},
            "coarse": coarse, "hourly": exact,
            "ambiguities": [x for x in exact["ledger"] if x["both_price_levels_hit"]],
        })
    (ROOT / "2121-verified.json").write_text(json.dumps({"native_sha256": sha256(source.read_bytes()), "results": results}, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "2121-verify-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
