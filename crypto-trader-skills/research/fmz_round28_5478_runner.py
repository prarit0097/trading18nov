"""Audit #5478 active PSAR/EMA decisions, USD sizing and native commissions."""

import json
import math
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from replay_5478 import cases, sha256
from replay_2864 import near
from verify_2994 import mean_stream

DAY, FEE, INITIAL = 86_400_000, .001, 5000


def parabolic(chart):
    points = [None]
    for i, row in enumerate(chart[1:], 1):
        high, low = row["high"], row["low"]
        previous = chart[i - 1]
        first = i == 1
        if first:
            rising = row["close"] > previous["close"]
            endpoint = high if rising else low
            result = previous["low"] if rising else previous["high"]
            acceleration = .02
        result += acceleration * (endpoint - result)
        if rising and result > low:
            rising, first = False, True
            result, endpoint, acceleration = max(high, endpoint), low, .02
        elif not rising and result < high:
            rising, first = True, True
            result, endpoint, acceleration = min(low, endpoint), high, .02
        if not first:
            if rising and high > endpoint:
                endpoint, acceleration = high, min(.2, acceleration + .02)
            elif not rising and low < endpoint:
                endpoint, acceleration = low, min(.2, acceleration + .02)
        prior_bars = chart[max(0, i - 2):i]
        if rising:
            result = min(result, *(x["low"] for x in prior_bars))
        else:
            result = max(result, *(x["high"] for x in prior_bars))
        points.append(result)
    return points


def signals(chart, plots):
    close = [r["close"] for r in chart]
    psar, fast, slow = parabolic(chart), mean_stream(close, 9, "ema"), mean_stream(close, 21, "ema")
    observed = {p["title"]: p["values"] for p in plots[-10:]}
    prior_direction = None
    confirmation = 0
    decisions = []
    for i, (sar, f, s, price) in enumerate(zip(psar, fast, slow, close, strict=True)):
        direction = 1 if sar is not None and sar < price else -1
        if f is not None and s is not None and f != s:
            confirmation = 1 if f > s else -1
        rising = int(direction == 1 and prior_direction == -1)
        falling = int(direction == -1 and prior_direction == 1)
        probes = (sar, direction, f, s, rising, falling, int(confirmation == 1), int(confirmation == -1), 1, 0)
        for expected, line in zip(probes, observed.values(), strict=True):
            near(expected, line[i])
        decisions.append(rising if confirmation == 1 else -falling if confirmation == -1 else 0)
        prior_direction = direction
    return decisions


def qty(equity, opening, fx):
    unit = Decimal("0.001")
    budget = Decimal(f"{equity * 0.2:.9e}")
    fee_adjusted_quote = Decimal(str(opening)) * Decimal(str(fx)) * Decimal("1.001")
    return float(budget / fee_adjusted_quote // unit * unit)


def reconcile(chart, base, fx, flags, strategy):
    balance = INITIAL
    active = None
    equity = strategy["equity"]
    fills, trades, positions = (iter(strategy[name]) for name in ("orders", "trades", "position"))
    ledger = []
    for i, bar in enumerate(chart):
        stamp, opening = bar["time"], bar["open"]
        first = base[i * 9]
        assert (first["time"], first["open"]) == (stamp, opening) and first["volume"] > 0
        rate = fx[stamp // DAY * DAY]
        action = flags[i - 1] if i else 0
        if action == 1 and active is None:
            amount = qty(balance, opening, rate)
            actual = next(fills)
            assert actual == {"id": "long", "barIndex": i, "time": stamp, "direction": "strategy.long", "qty": amount, "price": opening}, (i, amount, balance, rate, actual)
            assert next(positions) == {"barIndex": i, "size": amount, "avgPrice": opening}
            entry_cost = opening * amount * FEE * rate
            active = (i, stamp, opening, amount, rate, entry_cost)
        if action == -1 and active:
            entry_i, entered, entry, amount, entry_fx, entry_cost = active
            assert next(fills) == {"id": "Close entry(s) order long", "barIndex": i, "time": stamp, "direction": "strategy.close", "qty": amount, "price": opening}
            assert next(positions) == {"barIndex": i, "size": 0, "avgPrice": None}
            lot = next(trades)
            assert (lot["id"], lot["entryBarIndex"], lot["exitBarIndex"], lot["qty"]) == ("long", entry_i, i, amount)
            assert (lot["entryTime"], lot["exitTime"], lot["entryPrice"], lot["exitPrice"]) == (entered, stamp, entry, opening)
            gross = (opening - entry) * amount * rate
            fees = entry_cost + opening * amount * FEE * rate
            net = gross - fees
            near(lot["profit"], net)
            ledger.append({**lot, "commission": fees, "gross": gross, "entry_fx": entry_fx, "exit_fx": rate, "equity_at_entry": balance})
            balance += net
            active = None
        notional = active[3] * bar["close"] * rate if active else 0
        floating = (bar["close"] - active[2]) * rate * active[3] - active[-1] if active else 0
        near(equity[i]["equity"], balance + floating)
        near(equity[i]["marketValue"], notional)
        near(equity[i]["cash"], balance + floating - notional)
        near(equity[i]["netProfit"], balance + floating - INITIAL)
    assert all(next(stream, None) is None for stream in (fills, trades, positions)) and active is None
    return ledger


def run():
    raw = ROOT / "5478-replay.json"
    reports = json.loads(raw.read_bytes())
    results = []
    for sample, (ref, data, chart, base, opts) in zip(reports, cases(), strict=True):
        assert sample["market"] == ref["market"]
        a, b = sample["primary"], sample["other_clock"]
        assert not a["diagnostics"] and not a["strategy"]["diagnostics"]
        assert not b["diagnostics"] and a["strategy"] == b["strategy"]
        assert a["plots"][-10:] == b["plots"][-10:]
        flags = signals(chart, a["plots"])
        rates = {r["effectiveTime"]: r["rate"] for r in opts["request_bars"]["$currencyRates"]["pairs"][0]["rates"]}
        ledger = reconcile(chart, base, rates, flags, a["strategy"])
        results.append({**ref, "start": data["start"], "end": data["end"], "trade_flags": {"enter": flags.count(1), "close": flags.count(-1)}, "ledger": ledger, "finished_flat": True})
    (ROOT / "5478-verified.json").write_text(json.dumps({"cases": results, "raw_sha256": sha256(raw.read_bytes())}, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "5478-verify-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
