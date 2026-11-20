"""Run exact archived #5411 Pine under its pinned UTC replay clock."""

import json
import math
import re
import sys
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from replay_2864 import engine_options, near, pine_compat, sha256

SOURCE = "2ad55037d1ca1b62514f9c577bd9bd00b9c6c0128c46da53e3e1639284792e9d"
DAY = 86_400_000
CAPITAL = 1_000_000
OBSERVE = """
plot(startTime, title="Confirmed historical cutoff")
plot(longCondition ? 1 : 0, title="Confirmed long condition")
plot(positionSize, title="Confirmed requested quantity")
"""


def source():
    raw = (ROOT / "source-5411.md").read_bytes()
    assert sha256(raw) == SOURCE
    (wrapper,) = re.findall(r"(?m)^``` pinescript\n(.*?)^```", raw.decode(), re.DOTALL)
    archived, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", wrapper)
    assert n == 1
    assert archived.count("timenow") == 3
    assert archived.count("input.int(30,") == 1
    assert archived.count("input.int(300,") == 1
    return archived


def bars(rows):
    keys = ("time", "open", "high", "low", "close", "volume")
    return [dict(zip(keys, row, strict=True)) for row in rows]


def daily_options(symbol):
    return {**engine_options(symbol), "chart_timeframe": "D"}


def clock_controls():
    one = bars([[0, 100, 100, 100, 100, 1]])
    script = """//@version=5
indicator("Clock controls")
plot(timenow)
plot(timestamp(year(timenow), month(timenow), dayofmonth(timenow) - 30, 0, 0))
"""
    dates = ["2024-12-09T08:00:00", "2024-03-01T09:30:00", "2025-01-05T08:00:00"]
    checked = []
    opts = daily_options("BTCUSDT")
    for date in dates:
        when = datetime.fromisoformat(date).replace(tzinfo=UTC)
        clock = int(when.timestamp()) * 1000
        cutoff = when.replace(hour=0, minute=0, second=0) - timedelta(days=30)
        expected = int(cutoff.timestamp()) * 1000
        outcome = pine_compat.run_script(script, one, execution_times=[clock], **opts)
        assert not outcome["diagnostics"]
        series = [p["values"] for p in outcome["plots"]]
        assert series == [[clock], [expected]], (when, series, expected)
        checked.append({"clock": clock, "cutoff": expected})
    try:
        outcome = pine_compat.run_script(script, one, **opts)
    except ValueError as error:
        missing = str(error)
    else:
        missing = repr(outcome["diagnostics"])
    assert "execution" in missing.lower() and (
        "timenow" in missing.lower() or "timestamp" in missing.lower()
    ), missing
    return {"valid_normalizations": checked, "missing_clock": missing}


def probe():
    clock_proof = clock_controls()
    inputs = json.loads((ROOT / "5411-inputs.json").read_bytes())
    code = source()
    cases = []
    for ref in inputs["history"]:
        raw = (ROOT / ref["file"]).read_bytes()
        assert sha256(raw) == ref["sha256"]
        chart = bars(json.loads(raw))
        execution = [inputs["clock"]] * len(chart)
        opts = daily_options(ref["symbol"])
        result = pine_compat.run_script(code, chart, execution_times=execution, **opts)
        observed = pine_compat.run_script(
            code + OBSERVE, chart, execution_times=execution, **opts
        )
        assert not result["diagnostics"] and not observed["diagnostics"]
        assert (
            observed["strategy"] == result["strategy"]
            and not result["strategy"]["diagnostics"]
        )
        assert observed["plots"][-3]["values"] == [inputs["gate"]] * len(chart)
        cases.append(
            {
                "market": ref["symbol"],
                "digest": sha256(raw),
                "bars": len(chart),
                "result": result,
                "observer": observed["plots"][-3:],
            }
        )
    output = {"inputs": inputs, "clock_controls": clock_proof, "cases": cases}
    (ROOT / "5411-probe.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf8"
    )


def tick_price(value, tick):
    units = (Decimal(str(value)) / Decimal(str(tick))).quantize(
        Decimal(1), rounding=ROUND_HALF_UP
    )
    return float(units * Decimal(str(tick)))


def ema(values, period):
    alpha = 2 / (1 + period)
    results = [None] * (period - 1) + [math.fsum(values[:period]) / period]
    for value in values[period:]:
        results.append(alpha * value + (1 - alpha) * results[-1])
    return results


def independent_empty(case, chart, gate):
    exact = case["result"]
    native = exact["strategy"]
    closes = [b["close"] for b in chart]
    ema30, ema300 = ema(closes, 30), ema(closes, 300)
    short_curve, long_curve = [plot["values"] for plot in exact["plots"]]
    cutoff, longs, sizes = [plot["values"] for plot in case["observer"]]
    assert not native["orders"] and not native["trades"]
    assert all(position["size"] == 0 for position in native["position"])
    assert all(e["cash"] == e["equity"] == CAPITAL for e in native["equity"])
    submissions = tested_limits = 0
    worst_clearance = None
    pending_limit = None
    tick = 0.1 if case["market"] == "BTCUSDT" else 0.01
    interactions = []
    for i, bar in enumerate(chart):
        near(short_curve[i], ema30[i])
        near(long_curve[i], ema300[i])
        if pending_limit is not None:
            upper_bound = max(pending_limit, tick_price(pending_limit, tick))
            clearance = bar["low"] - upper_bound
            assert clearance > 0, (case["market"], bar, pending_limit)
            worst_clearance = (
                clearance
                if worst_clearance is None
                else min(worst_clearance, clearance)
            )
            tested_limits += 1
            interactions.append([bar["time"], pending_limit, bar["low"], clearance])
        in_scope = bar["time"] >= gate
        active = in_scope and ema300[i] is not None and bar["close"] > ema300[i]
        assert cutoff[i] == gate and longs[i] == int(active)
        if ema30[i] is not None:
            near(sizes[i], CAPITAL * 0.10 / ema30[i])
        if active:
            pending_limit = ema30[i]
            submissions += 1
    return {
        "market": case["market"],
        "submitted_limits": submissions,
        "tested_next_day_limits": tested_limits,
        "minimum_untouched_clearance": worst_clearance,
        "unfilled_open_limit": pending_limit,
        "filled_orders": 0,
        "closed": 0,
        "interactions": interactions,
    }


def positive_controls(code, gate, clock):
    first = gate - 300 * DAY
    flat = [[first + i * DAY, 100, 101, 99, 100, 1] for i in range(300)]
    request = [gate, 130, 131, 129, 130, 1]
    entry = [gate + DAY, 104, 106, 99, 99.5, 1]
    gap_entry = [gate + DAY, 100, 106, 99, 99.5, 1]
    stop = [gate + 2 * DAY, 98, 115, 94, 100, 1]
    target = [gate + 2 * DAY, 111, 114, 94, 100, 1]
    avg = 100.0 + 30.0 * (2 / 31)
    updated = avg * (1 - 2 / 31) + 99.5 * (2 / 31)
    stop_fill = math.floor(updated * 0.95 * 10) / 10
    profit_fill = math.ceil(updated * 1.10 * 10) / 10
    amount = math.floor(CAPITAL * 0.10 / avg * 1000 + 1e-10) / 1000
    options = daily_options("BTCUSDT")
    summaries = {}
    for name, buy, exit_, entry_expected, exit_expected in (
        (
            "touch_then_stop",
            entry,
            stop,
            avg,
            stop_fill,
        ),
        (
            "touch_then_target",
            entry,
            target,
            avg,
            profit_fill,
        ),
        ("gap_then_stop", gap_entry, stop, 100, stop_fill),
    ):
        feed = bars([*flat, request, buy, exit_])
        result = pine_compat.run_script(
            code, feed, execution_times=[clock] * len(feed), **options
        )
        assert not result["diagnostics"] and not result["strategy"]["diagnostics"]
        (trade,) = result["strategy"]["trades"]
        assert len(result["strategy"]["orders"]) == 2
        near(trade["qty"], amount)
        near(trade["entryPrice"], entry_expected)
        near(trade["exitPrice"], exit_expected)
        near(trade["profit"], amount * (exit_expected - entry_expected))
        assert trade["entryTime"] == gate + DAY and trade["exitTime"] == gate + 2 * DAY
        summaries[name] = trade
    return summaries


def summarize():
    probe()
    raw = (ROOT / "5411-probe.json").read_bytes()
    reference = json.loads(raw)
    inputs = reference["inputs"]
    feeds = {row["symbol"]: row for row in inputs["history"]}
    runs = []
    for case in reference["cases"]:
        row = feeds[case["market"]]
        historical = bars(json.loads((ROOT / row["file"]).read_bytes()))
        runs.append(independent_empty(case, historical, inputs["gate"]))
    controls = positive_controls(source(), inputs["gate"], inputs["clock"])
    report = {
        "chart_run_sha256": sha256(raw),
        "input_data": inputs,
        "clock_controls": reference["clock_controls"],
        "positive_synthetic_controls": controls,
        "runs": runs,
    }
    (ROOT / "5411-verified.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf8"
    )


if __name__ == "__main__":
    try:
        summarize()
    except Exception:
        import traceback

        (ROOT / "5411-error.txt").write_text(traceback.format_exc(), encoding="utf8")
        raise
