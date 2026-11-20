"""Audit the native BTC #3111 instructions and isolate the ETH future-candle leak."""

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from replay_3111 import cases, sha256
from replay_2864 import near

FEE = .00075
DIRECTIONS = {1: ("KAMAL", "strategy.long"), -1: ("KAMAS", "strategy.short")}


def weighted(vals, length):
    result = []
    for i in range(len(vals)):
        window = vals[max(0, i - length + 1): i + 1]
        value = None
        if len(window) == length and None not in window:
            value = math.fsum(n * v for n, v in enumerate(window, 1)) / (length * (length + 1) / 2)
        result.append(value)
    return result


def source_rules(chart):
    close = [b["close"] for b in chart]
    kama = []
    prior = 0
    for i, row in enumerate(chart):
        ratio = 0
        if i >= 8:
            volatility = math.fsum(abs(close[j] - close[j - 1]) for j in range(i - 7, i + 1))
            if volatility:
                ratio = abs(close[i] - close[i - 7]) / volatility
        smooth = (ratio * (.666666 - .064516) + .064516) ** 2
        prior += smooth * ((row["high"] + row["low"]) / 2 - prior)
        kama.append(prior)
    delta = [None if a is None or b is None else 2 * a - b for a, b in zip(weighted(close, 3), weighted(close, 7), strict=True)]
    hma = weighted(delta, 3)
    signals = []
    for i, value in enumerate(hma):
        previous = hma[i - 1] if i else None
        ready = value is not None and previous is not None
        buy = ready and value > previous
        sell = ready and value < previous and close[i] < kama[i]
        signals.append(int(buy) - int(sell))
    return kama, hma, signals


def reproduce_flags(chart, variant):
    kama, hma, signals = source_rules(chart)
    plots = {p["title"]: p["values"] for p in variant["plots"][-6:]}
    for name, expected in (("Observed KAMA", kama), ("Observed HMA", hma), ("Observed prior HMA", [None] + hma[:-1])):
        for a, b in zip(plots[name], expected, strict=True):
            near(a, b)
    assert plots["Observed buy"] == [int(n == 1) for n in signals]
    assert plots["Observed sell"] == [int(n == -1) for n in signals]
    return signals


def ledger(chart, groups, signals, native):
    orders, trades, states = (iter(native[key]) for key in ("orders", "trades", "position"))
    cash = native["equity"][0]["cash"]
    realized = 0
    position = None
    verified_lots = []
    for i, (bar, group, equity) in enumerate(zip(chart, groups, native["equity"], strict=True)):
        stamp, opened = bar["time"], bar["open"]
        first = group["bars"][0]
        assert first["time"] == stamp and first["open"] == opened and first["volume"] > 0
        side = signals[i - 1] if i else 0
        if side and (position is None or side != position[0]):
            if position:
                old, first_i, first_t, entry = position
                order = next(orders)
                assert order == {"id": f"Close entry(s) order {DIRECTIONS[old][0]}", "barIndex": i, "time": stamp, "direction": "strategy.close", "qty": 1, "price": opened}
                lot = next(trades)
                assert (lot["id"], lot["qty"], lot["entryBarIndex"], lot["exitBarIndex"]) == (DIRECTIONS[old][0], old, first_i, i)
                assert (lot["entryTime"], lot["exitTime"], lot["entryPrice"], lot["exitPrice"]) == (first_t, stamp, entry, opened)
                assert first_i < i
                gross = old * (opened - entry)
                near(gross, lot["profit"])
                fee = FEE * (entry + opened)
                realized += gross
                verified_lots.append({**lot, "after_fee": gross - fee, "fee": fee})
                assert next(states) == {"barIndex": i, "size": 0, "avgPrice": None}
            name, label = DIRECTIONS[side]
            assert next(orders) == {"id": name, "barIndex": i, "time": stamp, "direction": label, "qty": 1, "price": opened}
            assert next(states) == {"barIndex": i, "size": side, "avgPrice": opened}
            position = (side, i, stamp, opened)
        if position:
            active_side, _, _, open_price = position
            open_pnl = active_side * (bar["close"] - open_price)
            value = active_side * bar["close"]
        else:
            open_pnl = value = 0
        mark = cash + realized + open_pnl
        near(equity["equity"], mark)
        near(equity["cash"], mark - value)
        near(equity["netProfit"], realized + open_pnl)
        near(equity["marketValue"], value)
    assert all(next(it, None) is None for it in (orders, trades, states))
    return verified_lots, position, mark, cash


def run():
    path = ROOT / "3111-replay.json"
    modes = json.loads(path.read_bytes())
    records = []
    for variant, (ref, chart, groups, _) in zip(modes, cases(), strict=True):
        assert variant["file"] == ref["file"]
        expect = variant["legacy_same_context"]
        native = variant["typed"]
        assert expect["strategy"] == native["strategy"] == variant["typed_same_context"]["strategy"] == variant["typed_magnifier"]["strategy"]
        assert [p["values"] for p in expect["plots"][-6:]] == [p["values"] for p in native["plots"][-6:]]
        assert variant["typed_unrounded"]["strategy"] != native["strategy"]
        assert not native["diagnostics"] and not native["strategy"]["diagnostics"]
        independent = reproduce_flags(chart, variant["typed_close_only"])
        record = {**ref, "start": chart[0]["time"], "end": chart[-1]["time"] + 2_700_000}
        if ref["market"] == "BTCUSDT":
            assert variant["typed_close_only"]["strategy"] == native["strategy"]
            assert independent == reproduce_flags(chart, native)
            assert not variant["available_at_open_control"]
            lots, remaining, mark, capital = ledger(chart, groups, independent, native["strategy"])
            assert len(lots) == 29 and len(native["strategy"]["orders"]) == 59 and remaining
            record.update({"ledger": lots, "unsettled": remaining, "mark": mark, "capital": capital})
        else:
            assert variant["typed_close_only"]["strategy"] != native["strategy"]
            controls = variant["available_at_open_control"]
            assert [x["lot"]["entryBarIndex"] for x in controls] == [76, 110]
            for x in controls:
                i = x["lot"]["entryBarIndex"]
                o = chart[i]["open"]
                available = {**chart[i], "high": o, "low": o, "close": o}
                assert source_rules([*chart[:i], available])[-1][-1] == 1 and independent[i] == -1
                assert x["open_only_flags"] == {"Observed buy": 1, "Observed sell": 0}
                assert x["full_bar_flags"] == {"Observed buy": 0, "Observed sell": 1}
            record["unresolved_eth_controls"] = controls
        records.append(record)
    (ROOT / "3111-verified.json").write_text(json.dumps({"results": records, "raw_sha256": sha256(path.read_bytes())}, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "3111-verify-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
