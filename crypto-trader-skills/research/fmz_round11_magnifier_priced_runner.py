"""Source, feed, and ledger checks for the priced-stop experiment."""

import hashlib
import json
import math
import re
import sys
import traceback
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "priced-runtime"))
import pine_compat

fields = ("time", "open", "high", "low", "close", "volume")
lot_step = Decimal("0.001")
commission = Decimal("0.00075")
capital = Decimal(10_000)
day = 86_400_000


def objects(rows):
    return [dict(zip(fields, row, strict=True)) for row in rows]


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def balance_and_qty(orders, trades):
    balance = capital
    qty = Decimal(0)
    expected_closings = []
    starts = 0
    for order in orders:
        price = Decimal(str(order["price"]))
        amount = Decimal(str(order["qty"]))
        assert amount > 0 and price > 0
        if order["direction"] == "strategy.long":
            assert qty == 0 and order["id"] == "Entry"
            budget = Decimal(f"{balance * Decimal('0.1'):.9e}")
            expected = (budget / (price * (1 + commission))) // lot_step * lot_step
            assert expected == amount, (order, str(expected), str(balance))
            balance -= amount * price * (1 + commission)
            qty, entry = amount, price
            starts += 1
        else:
            assert (
                order["direction"] in {"strategy.exit", "strategy.close"}
                and amount == qty
            ), order
            balance += amount * price * (1 - commission)
            realized = amount * (price - entry - (entry + price) * commission)
            expected_closings.append((amount, entry, price, realized, order["time"]))
            qty = Decimal(0)
    assert len(expected_closings) == len(trades)
    for record, (amount, ep, xp, net, t) in zip(trades, expected_closings, strict=True):
        assert record["id"] == "Entry" and record["exitTime"] == t
        assert (record["qty"], record["entryPrice"], record["exitPrice"]) == tuple(
            map(float, (amount, ep, xp))
        )
        assert math.isclose(record["profit"], float(net), rel_tol=0, abs_tol=1e-8), (
            record
        )
    return starts, qty, balance


def verify_entries(report, chart, groups, strategy_day_high, scale):
    events = defaultdict(list)
    for row in report["orders"]:
        events[row["barIndex"]].append(row)
    threshold = None
    size = 0.0
    seen = 0
    for idx, (candle, lower, level) in enumerate(
        zip(chart, groups, strategy_day_high, strict=True)
    ):
        openings = [x for x in events[idx] if x["direction"] == "strategy.long"]
        expected = None
        if threshold is not None:
            assert size == 0
            for b in lower:
                if b["open"] >= threshold:
                    expected = b["open"]
                    break
                if b["high"] >= threshold:
                    expected = threshold
                    break
        if expected is not None:
            assert len(openings) == 1, (idx, threshold, expected, events[idx])
            assert math.isclose(
                openings[0]["price"],
                (math.floor(expected * scale + 0.5) + 1) / scale,
                rel_tol=0,
                abs_tol=1e-8,
            ), (idx, threshold, expected, openings[0])
            threshold = None
            seen += 1
        else:
            assert not openings, (idx, threshold, events[idx])
        for event in events[idx]:
            size = event["qty"] if event["direction"] == "strategy.long" else 0.0
        if not size and candle["close"] < level:
            raw = level + level / 100
            threshold = raw
    return seen


runs = []
for path in sorted(root.glob("priced-[0-9]*.json")):
    feed = path.read_bytes()
    p = json.loads(feed)
    if "id" not in p:
        continue
    ident, market = p["id"], p["symbol"]
    raw = (root / f"source-{ident}.pine").read_bytes()
    assert digest(raw) == p["archive_script_sha256"]
    code, removed = re.subn(r"(?m)^/\*backtest\r?\n[\s\S]*?^\*/\r?\n", "", raw.decode())
    assert removed == 1
    observer = (
        code
        + '\nplot(high_daily,title="Diagnostic requested day high")\nplot(closed,title="Diagnostic requested day close")\nplot(high_daily1,title="Diagnostic native day high")\n'
    )
    chart, daily = objects(p["chart"]), objects(p["daily"])
    groups = [objects(group) for group in p["groups"]]
    assert len(chart) == len(groups)
    assert all(
        c["open"] == g[0]["open"] and c["close"] == g[-1]["close"]
        for c, g in zip(chart, groups, strict=True)
    )
    scale = 10 if market == "BTCUSDT" else 100
    chart_symbol = "BINANCE:" + market
    host = {
        "$chart": {
            "currency": "USDT",
            "minMove": 1,
            "priceScale": scale,
            "quantityStep": "0.001",
            "minContract": "0.001",
            "pointValue": 1,
        },
        chart_symbol + ":D": daily,
        chart_symbol + ":1D": daily,
    }
    options = {
        "chart_symbol": chart_symbol,
        "chart_timeframe": p["chart_timeframe"],
        "request_bars": host,
        "magnifier_bars": {
            "schemaVersion": 1,
            "chartBars": [
                {"chartBarIndex": i, "bars": g} for i, g in enumerate(groups)
            ],
        },
    }
    note = {
        "id": ident,
        "market": market,
        "feed": path.name,
        "feed_sha256": digest(feed),
        "source_sha256": digest(raw),
        "start": p["start"],
        "end": p["end"],
        "chart_bars": len(chart),
        "lower_events": sum(map(len, groups)),
    }
    try:
        result = pine_compat.compile_script(code).run(chart, **options)
        assert result == pine_compat.run_script(code, chart, **options)
        report = result["strategy"]
        note["runtime_diagnostics"] = dict(
            Counter(o["code"] for o in result["diagnostics"])
        )
        note["broker_diagnostics"] = dict(
            Counter(o["code"] for o in report["diagnostics"])
        )
        assert not result["diagnostics"], note["runtime_diagnostics"]
        assert not report["diagnostics"], note["broker_diagnostics"]
        observed = pine_compat.run_script(observer, chart, **options)
        assert observed["strategy"] == report
        h, c, day_hi = [s["values"] for s in observed["plots"][-3:]]
        lookup = {x["time"]: x for x in daily}
        assert h[0] is None and c[0] is None
        for idx, cc in enumerate(chart):
            prior_time = cc["time"] // day * day - day
            ref = lookup[prior_time]
            if idx:
                assert (h[idx], c[idx]) == (ref["high"], ref["close"]), (
                    idx,
                    h[idx],
                    c[idx],
                    ref,
                )
            expected = 0 if cc["time"] < p["start"] + day else ref["high"]
            assert day_hi[idx] == expected, (idx, day_hi[idx], expected)
        note["aux_verified_chart_bars"] = len(chart) - 1
        assert report["trades"]
        opened, size, balance = balance_and_qty(report["orders"], report["trades"])
        assert math.isclose(
            float(balance), report["equity"][-1]["cash"], rel_tol=0, abs_tol=1e-7
        )
        assert float(size) == report["position"][-1]["size"]
        assert verify_entries(report, chart, groups, day_hi, scale) == opened
        note.update(
            qualified=True,
            opens=opened,
            closed=len(report["trades"]),
            ledger=report["trades"],
            orders=report["orders"],
            final_cash=str(balance),
            final_position=str(size),
        )
    except (ValueError, KeyError, TypeError, AssertionError):
        note["error"] = traceback.format_exc(limit=2)
    runs.append(note)
    (root / "priced-market-results.json").write_text(
        json.dumps(runs, indent=2) + "\n", encoding="utf8"
    )
assert len(runs) == 8
