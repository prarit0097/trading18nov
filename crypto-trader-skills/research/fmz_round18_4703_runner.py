"""Independently verify the archived #4703 daily signals and broker ledger."""

import json
import re
import sys
from collections import Counter
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from probe_4703 import DAY, FEEDS, candles, engine_options, inputs, pine_compat, sha256
from replay_2864 import near

CAPITAL = 1_000_000
FEE = 0.00075
HOUR = 3_600_000


def hourly_for(market, chart):
    days = {bar["time"]: bar for bar in chart}
    rows = json.loads((ROOT / "4703-hourly-manifest.json").read_bytes())
    day_base = {}
    references = []
    for item in rows:
        if item["market"] != market:
            continue
        stamp = item["date"]
        raw = (ROOT / item["file"]).read_bytes()
        assert sha256(raw) == item["sha256"]
        data = json.loads(raw)
        assert [row[0] for row in data] == list(range(stamp, stamp + DAY, HOUR))
        assert all(row[6] == row[0] + HOUR - 1 for row in data)
        hours = [[r[0], *map(Decimal, r[1:6])] for r in data]
        day = days[stamp]
        aggregate = [
            hours[0][1],
            max(r[2] for r in hours),
            min(r[3] for r in hours),
            hours[-1][4],
            sum(r[5] for r in hours),
        ]
        for a, key in zip(
            aggregate, ("open", "high", "low", "close", "volume"), strict=True
        ):
            near(float(a), day[key])
        day_base[stamp] = hours
        references.append(item)
    return day_base, references


def fix_unavailable_warmup(source):
    pattern = r'(?m)^(strategy\.exit\("exit", "buy",\s+loss = mxloss\)[ \t]*\n)(strategy\.exit\("exit", "Sell",\s+loss = mxloss\)[ \t]*\n)'
    edited, count = re.subn(pattern, r"if not na(mxloss)\n    \1    \2", source)
    assert count == 1
    return edited


def verify_inputs(raw, chart, clock):
    result = raw["authored"]
    observed = raw["observed"]
    warnings = Counter(r["code"] for r in result["diagnostics"])
    assert warnings == {"W_LEGACY_SECURITY_LOOKAHEAD": 5}
    assert Counter(r["code"] for r in observed["diagnostics"]) == warnings
    assert observed["strategy"] == result["strategy"]
    broker = result["strategy"]
    assert [d["code"] for d in broker["diagnostics"]] == ["E_STRATEGY_EXIT_TICKS"] * 2
    pure = fix_unavailable_warmup(inputs())
    opts = {
        **engine_options(raw["market"]),
        "chart_timeframe": "D",
        "execution_times": [clock] * len(chart),
    }
    guarded = pine_compat.run_script(pure, chart, **opts)
    assert guarded["strategy"] == {**broker, "diagnostics": []}
    assert [p["values"] for p in guarded["plots"]] == [
        p["values"] for p in result["plots"]
    ]
    high, low, close, pivot, distance = [p["values"] for p in observed["plots"][-5:]]
    assert [high[0], low[0], close[0], pivot[0], distance[0]] == [None] * 5
    pivots = [None]
    for i, prior in enumerate(chart[:-1], 1):
        p = (prior["high"] + prior["low"] + prior["close"]) / 3
        assert [high[i], low[i], close[i]] == [
            prior["high"],
            prior["low"],
            prior["close"],
        ]
        near(pivot[i], p)
        near(distance[i], prior["close"] * 0.5)
        pivots.append(p)
    return broker, pivots


def audit_ledger(case, broker, pivots, chart, hour_map):
    orders = iter(broker["orders"])
    trades = iter(broker["trades"])
    equity = CAPITAL
    held = should_open = False
    entry_price = entry_time = 0
    tick = Decimal("0.1" if case["market"] == "BTCUSDT" else "0.01")
    closed = []
    matched_base = []

    def check_order(i, stamp, price, id_, direction):
        order = next(orders)
        assert (
            order["id"] == id_ and order["direction"] == direction and order["qty"] == 1
        )
        assert order["time"] == stamp and order["barIndex"] == i
        near(order["price"], price)

    for i, (bar, pivot) in enumerate(zip(chart, pivots, strict=True)):
        stamp, price = bar["time"], bar["open"]
        assert stamp % DAY == 0
        if should_open:
            assert not held
            base = hour_map[stamp]
            near(price, float(base[0][1]))
            check_order(i, stamp, price, "buy", "strategy.long")
            matched_base.append(
                {
                    "kind": "entry",
                    "day": stamp,
                    "hour": stamp,
                    "broker_price": price,
                    "base_price": price,
                }
            )
            held, entry_time, entry_price = True, stamp, price
        if held:
            loss_ticks = Decimal(str(chart[i - 2]["close"])) / 2
            raw_trigger = Decimal(str(entry_price)) - loss_ticks * tick
            stop = float(
                (raw_trigger / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
            )
            if bar["low"] <= stop:
                exit_price = min(price, stop)
                base = hour_map[stamp]
                first_hit = next(hr for hr in base if float(hr[3]) <= stop)
                base_price = min(float(first_hit[1]), stop)
                check_order(i, stamp, exit_price, "exit", "strategy.exit")
                trade = next(trades)
                assert trade["id"] == "buy" and trade["qty"] == 1
                assert trade["entryTime"] == entry_time and trade["exitTime"] == stamp
                near(trade["entryPrice"], entry_price)
                near(trade["exitPrice"], exit_price)
                gross = exit_price - entry_price
                near(trade["profit"], gross)
                overlay = FEE * (entry_price + exit_price)
                equity += gross
                closed.append(
                    {
                        **trade,
                        "fee_sensitivity": overlay,
                        "after_fee_sensitivity": gross - overlay,
                    }
                )
                matched_base.append(
                    {
                        "kind": "stop",
                        "day": stamp,
                        "hour": first_hit[0],
                        "broker_price": exit_price,
                        "base_price": base_price,
                    }
                )
                held = False
        should_open = bool(
            pivot is not None and price < pivot < bar["close"] and not held
        )
        marked_equity = equity + (bar["close"] - entry_price if held else 0)
        near(broker["equity"][i]["equity"], marked_equity)
    assert next(orders, None) is None and next(trades, None) is None
    terminal = broker["position"][-1]
    assert terminal["size"] == int(held)
    assert set(hour_map) == {row["day"] for row in matched_base}
    return closed, matched_base, terminal


def run():
    raw_file = ROOT / "4703-probe.json"
    raw = json.loads(raw_file.read_bytes())
    runs = []
    for case in raw:
        market = case["market"]
        chart, clock = candles(market)
        assert clock == case["clock"]
        broker, pivots = verify_inputs(case, chart, clock)
        hours, references = hourly_for(market, chart)
        ledger, matches, terminal = audit_ledger(case, broker, pivots, chart, hours)
        outcome = {
            "market": market,
            "chart_start": chart[0]["time"],
            "chart_stop": clock,
            "chart_bars": len(chart),
            "daily_sha256": FEEDS[market],
            "trades": len(ledger),
            "orders": len(matches),
            "ending_position": terminal,
            "hourly_quotes": references,
            "execution_checks": matches,
            "ledger": ledger,
        }
        runs.append(outcome)
    verified = {"native_sha256": sha256(raw_file.read_bytes()), "runs": runs}
    (ROOT / "4703-verified.json").write_text(
        json.dumps(verified, indent=2) + "\n", encoding="utf8"
    )


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "4703-verify-error.txt").write_text(
            traceback.format_exc(), encoding="utf8"
        )
        raise
