"""Verify #2514 subchart votes, each reversal and source-aligned USD accounting."""

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from audit_2514 import indicator_votes
from replay_2514 import NAMES, cases, sha256
from replay_2864 import near

DAY = 86_400_000
CAPITAL = 500
FEE = 0.00075
NAMES_BY_SIDE = {1: "My Long Entry Id", -1: "My Short Entry Id"}


def signals(chart, base, plots):
    observed = {p["title"]: p["values"] for p in plots}
    votes = indicator_votes(chart, base)
    for name, expected in zip(NAMES, zip(*(a + b for a, b in votes), strict=True), strict=True):
        assert observed[f"Observed {name} vote"] == list(expected)
    directions = []
    for i, (average, oscillator) in enumerate(votes):
        ma_sum, osc_sum = sum(average), sum(oscillator)
        ma, osc = ma_sum / 15, osc_sum / 11
        rating = (ma + osc) / 2
        near(observed["Moving Averages Rating"][i], ma)
        near(observed["Oscillators Rating"][i], osc)
        near(observed["Rating"][i], rating)
        signs = ma_sum * 11 + osc_sum * 15
        directions.append(int(signs > 0) - int(signs < 0))
    return directions


def audit(chart, hourly, rates, book, direction, position_plots):
    orders, lots, states = (iter(book[k]) for k in ("orders", "trades", "position"))
    current = 0
    realized = 0
    trades, marked, reversal_orders = [], [], []
    index = first = fill = None
    for i, (row, equity, size) in enumerate(zip(chart, book["equity"], position_plots, strict=True)):
        day, price = row["time"], row["open"]
        fx = rates[day]
        assert price == hourly[i * 24]["open"]
        side = direction[i - 1] if i else 0
        if side and side != current:
            arrival = next(orders)
            assert arrival["id"] == NAMES_BY_SIDE[side]
            assert arrival["direction"] == ("strategy.long" if side == 1 else "strategy.short")
            assert (arrival["barIndex"], arrival["time"], arrival["qty"], arrival["price"]) == (i, day, 1 + int(bool(current)), price)
            if current:
                settled = next(lots)
                assert settled["id"] == NAMES_BY_SIDE[current]
                assert settled["qty"] == current
                assert (settled["entryBarIndex"], settled["exitBarIndex"], settled["entryTime"], settled["exitTime"]) == (index, i, first, day)
                assert settled["entryPrice"] == fill and settled["exitPrice"] == price
                gross = current * (price - fill) * fx
                near(settled["profit"], gross)
                realized += gross
                overlay = FEE * (fill * rates[first] + price * fx)
                trades.append({**settled, "side": current, "fx_entry": rates[first], "fx_exit": fx, "fee_overlay": overlay, "after_fee": gross - overlay})
                reversal_orders.append(arrival)
                assert next(states) == {"barIndex": i, "size": 0, "avgPrice": None}
            state = next(states)
            assert (state["barIndex"], state["size"], state["avgPrice"]) == (i, side, price)
            index, first, fill, current = i, day, price, side
        assert size == current
        net = realized + (current * (row["close"] - fill) * fx if current else 0)
        value = current * row["close"] * fx
        assert equity["barIndex"] == i
        near(equity["netProfit"], net)
        near(equity["marketValue"], value)
        near(equity["cash"], CAPITAL + net - value)
        near(equity["equity"], CAPITAL + net)
        marked.append(equity["equity"])
    assert all(next(x, None) is None for x in (orders, lots, states))
    return trades, {"side": current, "entry_bar": index, "entry_time": first, "entry_price": fill}, reversal_orders, marked


def run():
    raw_path = ROOT / "2514-replay.json"
    raw = json.loads(raw_path.read_bytes())
    fixture = raw[0]["lower_fixture"]
    assert fixture["values"] == [[104.5, 110.5, 116.5], [100, 106, 112]]
    assert [x["code"] for x in fixture["diagnostics"]] == ["W_LEGACY_SECURITY_LOOKAHEAD"]
    result = []
    for native, (ref, chart, base, hourly, opts) in zip(raw, cases(), strict=True):
        assert native["file"] == ref["file"]
        rates = {r["effectiveTime"]: r["rate"] for r in opts["request_bars"]["$currencyRates"]["pairs"][0]["rates"]}
        assert list(rates) == [b["time"] for b in chart]
        replay = native["native"]
        book = replay["strategy"]
        assert not replay["diagnostics"] and not book["diagnostics"]
        direction = signals(chart, base, replay["plots"])
        trades, open_, reversals, marked = audit(chart, hourly, rates, book, direction, replay["plots"][-1]["values"])
        result.append({
            **ref, "start": chart[0]["time"], "end": chart[-1]["time"] + DAY,
            "votes_matched": len(chart) * len(NAMES), "long_signal_bars": direction.count(1),
            "short_signal_bars": direction.count(-1), "flat_signal_bars": direction.count(0),
            "final_marked_equity_before_fee_overlay": marked[-1], "minimum_marked_equity_before_fee_overlay": min(marked),
            "closed": trades, "reversals": reversals, "unsettled": open_,
            "gross": math.fsum(trade["profit"] for trade in trades),
            "after_fee": math.fsum(trade["after_fee"] for trade in trades),
        })
    output = {"cases": result, "native_sha256": sha256(raw_path.read_bytes()), "last_4h_fixture": fixture}
    (ROOT / "2514-verified.json").write_text(json.dumps(output, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "2514-verify-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
