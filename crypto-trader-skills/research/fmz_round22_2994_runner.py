"""Independently reconstruct the archived daily decision and fixed-cash ledger."""

import json
import math
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from replay_2994 import cases, sha256
from replay_2864 import near

ORDER_CASH = 10_000
QUANT = Decimal("0.001")
FEE = 0.025 / 100


def mean_stream(values, n, average):
    window = []
    prev = None
    result = []
    for value in values:
        if value is not None:
            window.append(value)
            if len(window) >= n:
                if average == "ema" and prev is not None:
                    a = 2 / (n + 1)
                    prev = value * a + prev * (1 - a)
                else:
                    prev = math.fsum(window[-n:]) / n
        result.append(prev)
    return result


def divergence(signal, chart, high_limit, low_limit):
    high_trail, low_trail = [], []
    high_record = low_record = None
    output = []
    for i in range(len(chart)):
        bear = bull = False
        if i >= 4:
            group = signal[i - 4 : i + 1]
            if None not in group:
                value = group[2]
                surrounding = (*group[:2], *group[3:])
                if value >= high_limit and value > max(surrounding):
                    price = chart[i - 2]["high"]
                    prior = high_trail[i - 2]
                    bear = prior is not None and price > prior[0] and value < prior[1]
                    high_record = (price, value)
                elif value <= low_limit and value < min(surrounding):
                    price = chart[i - 2]["low"]
                    prior = low_trail[i - 2]
                    bull = prior is not None and price < prior[0] and value > prior[1]
                    low_record = (price, value)
        high_trail.append(high_record)
        low_trail.append(low_record)
        output.append((bear, bull))
    return output


def source_logic(chart):
    prices = [(p["high"] + p["low"] + p["close"]) / 3 for p in chart]
    esa = mean_stream(prices, 9, "ema")
    deviations = [None if smoothed is None else abs(price - smoothed) for price, smoothed in zip(prices, esa, strict=True)]
    de = mean_stream(deviations, 9, "ema")
    normalized = [None if den is None or den == 0 else (p - m) / (0.015 * den) for p, m, den in zip(prices, esa, de, strict=True)]
    wt1 = mean_stream(normalized, 12, "ema")
    wt2 = mean_stream(wt1, 3, "sma")
    standard_div = divergence(wt2, chart, 45, -65)
    extra_div = divergence(wt2, chart, 15, -40)
    signals = []
    for i, (fast, slow) in enumerate(zip(wt1, wt2, strict=True)):
        ready = fast is not None and slow is not None
        prev_fast, prev_slow = (wt1[i - 1], wt2[i - 1]) if i else (None, None)
        buy, sell = (ready and slow < fast), (ready and slow > fast)
        crossed_up = buy and prev_fast is not None and prev_slow is not None and prev_fast <= prev_slow
        crossed_down = sell and prev_fast is not None and prev_slow is not None and prev_fast >= prev_slow
        bearish, bullish = [a or b for a, b in zip(standard_div[i], extra_div[i], strict=True)]
        end_buy = sell or (crossed_down and slow >= 53) or bearish
        end_sell = not sell or (crossed_up and slow <= -53) or bullish
        signals.append((int(buy), int(sell), int(end_buy), int(end_sell)))
    return wt1, wt2, signals


def size(price):
    return float((Decimal(ORDER_CASH) / Decimal(str(price))) // QUANT * QUANT)


def orders(chart, signals):
    """Queued next-open market orders, archived flat/default pyramiding and named closes."""
    position = None
    closed, events = [], []
    marked = []
    realized = 0
    opencost = 0

    def settle(i, bar, base, reason):
        nonlocal position, realized, opencost
        assert position
        ident, side, qty, index, first, entry = position
        pnl = side * qty * (base - entry)
        comm = FEE * qty * (entry + base)
        closed.append({
            "entryId": ident, "dir": side, "qty": qty, "entryPrice": entry,
            "exitPrice": base, "entryBar": index, "exitBar": i, "entryTime": first,
            "exitTime": bar["time"], "profit": pnl - comm, "commission": comm,
        })
        realized += pnl - comm
        events.append({"id": ident, "kind": reason, "bar": i, "price": base, "qty": qty})
        position = None
        opencost = 0

    queued = []
    for i, bar in enumerate(chart):
        open_ = bar["open"]
        if queued:
            for action, side, name in queued:
                if action == "close":
                    if position and position[1] == side:
                        settle(i, bar, open_, "explicit")
                elif not position or position[1] != side:
                    if position:
                        settle(i, bar, open_, "reverse")
                    count = size(open_)
                    position = (name, side, count, i, bar["time"], open_)
                    opencost = FEE * count * open_
                    events.append({"id": name, "kind": "entry", "bar": i, "price": open_, "qty": count})
        pnl = position[1] * position[2] * (bar["close"] - position[-1]) if position else 0
        marked.append(ORDER_CASH + realized + pnl - opencost)
        buy, sell, end_buy, end_sell = signals[i]
        queued = []
        if position and end_buy and position[1] == 1:
            queued.append(("close", 1, "long"))
        if position and end_sell and position[1] == -1:
            queued.append(("close", -1, "short"))
        if buy:
            queued.append(("enter", 1, "long"))
        if sell:
            queued.append(("enter", -1, "short"))
    return closed, position, events, marked


def run(piner_dir):
    raw_path = ROOT / "2994-replay.json"
    raw_bytes = raw_path.read_bytes()
    native = json.loads(raw_bytes)
    piner_path = piner_dir / "2994-piner.json"
    piner_data = json.loads(piner_path.read_bytes())
    compat_control_path = ROOT / "2994-cash-sizing.json"
    compat_control = json.loads(compat_control_path.read_bytes())
    compat_lots = compat_control["4"]["strategy"]["trades"]
    piner_lots = piner_data["fixture"]["closedTrades"]
    assert compat_control["4"] == compat_control["5"]
    assert [abs(row["qty"]) for row in compat_lots] == [100, 52.328]
    assert [row["qty"] for row in piner_lots] == [size(190.3), size(277.6)] == [52.548, 36.023]
    assert [(row["entryBar"], row["exitBar"]) for row in piner_lots] == [(1, 2), (2, 3)]
    for row in piner_lots:
        near(row["commission"], row["qty"] * FEE * (row["entryPrice"] + row["exitPrice"]))
    cases_tested = []
    for primary, alternate, (ref, chart, hour, _, _) in zip(native, piner_data["sample"], cases(), strict=True):
        assert primary["file"] == ref["file"] and alternate["market"] == ref["market"]
        assert alternate["dataSha256"] == ref["sha256"]
        native_book = primary["original"]["strategy"]
        assert native_book == primary["observed"]["strategy"] == primary["perturbed_visual_feeds"]["strategy"]
        for source in ("original", "observed", "perturbed_visual_feeds"):
            assert not primary[source]["strategy"]["diagnostics"]
            assert {d["code"] for d in primary[source]["diagnostics"]} == {"W_LEGACY_SECURITY_LOOKAHEAD"}
        observed = {plot["title"]: plot["values"] for plot in primary["observed"]["plots"] if (plot.get("title") or "").startswith("Observed")}
        wt1, wt2, source = source_logic(chart)
        for expected, name in ((wt1, "Observed WT1"), (wt2, "Observed WT2")):
            for a, b in zip(expected, observed[name], strict=True):
                near(a, b)
        names = ("Observed long", "Observed short", "Observed short-side close", "Observed long-side close")
        for i, (a, b) in enumerate(zip(source, zip(*(observed[n] for n in names), strict=True), strict=True)):
            assert a == b, (i, a, b)
        lots, open_, events, equity = orders(chart, source)
        matched = alternate["result"]
        for expected, actual in zip(lots, matched["closedTrades"], strict=True):
            for name, value in expected.items():
                if isinstance(value, float):
                    near(value, actual[name])
                else:
                    assert value == actual[name], (name, value, actual[name])
        for row in events:
            assert row["price"] == hour[row["bar"] * 24]["open"], row
        assert matched["initialCapital"] == ORDER_CASH and matched["barsProcessed"] == len(chart)
        for expected, real in zip(equity, matched["equityCurve"], strict=True):
            near(expected, real["equity"] if isinstance(real, dict) else real)
        native_arrivals = [r for r in native_book["orders"] if not r["direction"].startswith("strategy.close")]
        entries = [r for r in events if r["kind"] == "entry"]
        for wrong, correct in zip(native_arrivals, entries, strict=True):
            i = correct["bar"]
            assert (wrong["id"], wrong["barIndex"], wrong["price"]) == (correct["id"], i, correct["price"])
            near(wrong["qty"], size(chart[i - 1]["close"]))
        cases_tested.append({
            **ref,
            "start": chart[0]["time"], "end": chart[-1]["time"] + 86_400_000,
            "observed_flag_counts": {n: sum(observed[n]) for n in names},
            "closed": lots, "open": open_, "ending_marked_equity": equity[-1],
            "order_events": dict(Counter(row["kind"] for row in events)),
            "native_cash_quantities_differ": sum(a["qty"] != b["qty"] for a, b in zip(native_arrivals, entries, strict=True)),
            "adapter_sha256": alternate["sourceSha256"],
        })
    out = {
        "cases": cases_tested,
        "native_sha256": sha256(raw_bytes),
        "piner_sha256": sha256(piner_path.read_bytes()),
        "piner_engine_sha256": piner_data["engine"],
        "cash_control": {
            "native_sha256": sha256(compat_control_path.read_bytes()),
            "native": compat_lots,
            "fill_price": piner_lots,
        },
    }
    (ROOT / "2994-verified.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    try:
        run(Path(sys.argv[1]))
    except Exception:
        import traceback

        (ROOT / "2994-verify-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
