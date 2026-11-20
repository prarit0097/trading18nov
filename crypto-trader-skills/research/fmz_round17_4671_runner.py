"""Probe the recoverable authored portions of FMZ catalogue entry #4671."""

import json
import math
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from control_3604_base import LOWER_HASHES
from probe_3604 import INPUTS, near, options_for, pine_compat, sha256

SOURCE_SHA = "bc4aa004c953721da57d29dbfafe1f192606a50efae5ee70e4e890d5d84c3013"
HOUR = 3_600_000
DAY = 86_400_000
CAPITAL = 50_000
FEE = 0.00075
HEADER_FEE = 0.00008
OBSERVE = """
plot(longC ? 1 : 0, title="Verified long signal")
plot(shortC ? 1 : 0, title="Verified short signal")
plot(not (timeinrange(timeframe.period, "0300-0945")) ? 1 : 0, title="Verified session exit")
plot(size, title="Archived informational size")
"""


def versions():
    raw = (ROOT / "wallet-4671.md").read_bytes()
    assert sha256(raw) == SOURCE_SHA
    (code,) = re.findall(r"(?m)^``` pinescript\n(.*?)^```", raw.decode(), re.DOTALL)
    code, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", code)
    assert n == 1
    declared = 'strategy(title="2 ma breakout", shorttitle="2 ma breakout", initial_capital=50000, overlay=true)'
    choose_comment = 'strategy(title="2 ma breakout",shorttitle="2 ma breakout", initial_capital=10000,overlay=true, commission_type = strategy.commission.cash_per_contract, commission_value = 0.00008 )'
    assert code.count("// " + choose_comment) == 1
    repaired, n = re.subn(r"(?m)^strategy\.initial_capital = 50000[ \t]*\n", "", code)
    assert n == 1
    assert repaired.count("strategy.initial_capital") == 1
    one = repaired.replace("//@version=4\n", "//@version=4\n" + declared + "\n")
    two = repaired.replace("// " + choose_comment, choose_comment)
    return code, one, two


def session_control():
    base = int(datetime(2026, 8, 1, tzinfo=UTC).timestamp()) * 1000
    chart = [
        {
            "time": base + i * HOUR,
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1.0,
        }
        for i in range(4 * 24)
    ]
    script = """//@version=4
study("Session behavior")
t = time(timeframe.period, "0300-0945")
cond = time(timeframe.period, "0300-0945") != 0
notcond = not cond
plot(t, title="Timestamp")
plot(cond ? 1 : 0, title="In session")
plot(notcond ? 1 : 0, title="Outside condition")
plot(na(cond) ? 1 : 0, title="Condition NA")
plot(na(notcond) ? 1 : 0, title="Outside condition NA")
"""
    result = pine_compat.run_script(script, chart, **options_for("BTCUSDT"))
    assert not result["diagnostics"]
    series = [plot["values"] for plot in result["plots"]]
    for i, row in enumerate(chart):
        instant = datetime.fromtimestamp(row["time"] / 1000, UTC)
        active = instant.weekday() < 5 and 3 <= instant.hour <= 9
        expected = [
            row["time"] if active else None,
            int(active),
            int(not active),
            int(not active),
            0,
        ]
        assert [curve[i] for curve in series] == expected
    return {"start": base, "plots": result["plots"]}


def probe():
    from probe_3604 import load_feed

    filename, checksum = next(iter(INPUTS.items()))
    market, _, _, chart = load_feed(filename, checksum)
    output = {"session_control": session_control()}
    for label, source in zip(
        ("archive", "relocated", "commented"), versions(), strict=True
    ):
        try:
            output[label] = pine_compat.run_script(source, chart, **options_for(market))
        except ValueError as failure:
            output[label] = {"exception": str(failure).splitlines()}
    (ROOT / "4671-probe.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf8"
    )


def chart_series(chart):
    closes = [bar["close"] for bar in chart]
    averages = [None, *[(closes[i - 1] + closes[i]) / 2 for i in range(1, len(chart))]]
    alpha = 2 / 201
    slow = [None] * 199 + [math.fsum(closes[:200]) / 200]
    for close in closes[200:]:
        slow.append(alpha * close + (1 - alpha) * slow[-1])
    signals, outside = [], []
    for i, bar in enumerate(chart):
        date = datetime.fromtimestamp(bar["time"] / 1000, UTC)
        weekday = date.weekday() < 5
        outside.append(not (weekday and 3 <= date.hour <= 9))
        if not (weekday and date.hour == 3 and slow[i] is not None):
            signals.append(0)
            continue
        previous = chart[i - 1]
        fast, last_fast = averages[i], averages[i - 1]
        crossup = any(
            previous[key] <= last_fast and bar[key] > fast for key in ("close", "high")
        )
        crossdown = any(
            previous[key] >= last_fast and bar[key] < fast for key in ("close", "low")
        )
        long = previous["close"] > slow[i] and crossup
        short = previous["close"] < slow[i] and crossdown
        assert not (long and short)
        signals.append(int(long) - int(short))
    return averages, slow, signals, outside


def to_bars(rows):
    keys = ("time", "open", "high", "low", "close", "volume")
    return [dict(zip(keys, row, strict=True)) for row in rows]


def study_inputs():
    author_path = ROOT / "4671-author-data.json"
    authored = json.loads(author_path.read_bytes())
    cases = [dict(item, sample="FMZ archived dates") for item in authored["feeds"]]
    cases.extend(
        {"file": name, "sha256": sha, "sample": "Comparison window"}
        for name, sha in INPUTS.items()
    )
    for ref in cases:
        raw = (ROOT / ref["file"]).read_bytes()
        assert sha256(raw) == ref["sha256"]
        source = json.loads(raw)
        market, start, stop = source["symbol"], source["from"], source["to"]
        chart = to_bars(source["chart"])
        assert [bar["time"] for bar in chart] == list(range(start, stop, HOUR))
        if ref["sample"] == "FMZ archived dates":
            base = to_bars(source["intrabar"])
            base_digest = ref["sha256"]
        else:
            first = ref["file"].removeprefix(f"feed-{market}-60-10-")
            base_name = f"native-base-{market}-{first}"
            base_raw = (ROOT / base_name).read_bytes()
            base_digest = sha256(base_raw)
            assert base_digest == LOWER_HASHES[base_name]
            base = to_bars(json.loads(base_raw))
        assert [bar["time"] for bar in base] == list(range(start, stop, HOUR // 4))
        for i, hour in enumerate(chart):
            block = base[i * 4 : i * 4 + 4]
            assert (
                block[0]["open"] == hour["open"] and block[-1]["close"] == hour["close"]
            )
            assert max(b["high"] for b in block) == hour["high"]
            assert min(b["low"] for b in block) == hour["low"]
            near(math.fsum(b["volume"] for b in block), hour["volume"])
        yield ref, market, start, stop, chart, base, base_digest


def verify_signals(actual, observed, chart):
    fast, slow, signals, outside = chart_series(chart)
    for values, curve in zip(actual["plots"], (fast, slow), strict=True):
        for native, target in zip(values["values"], curve, strict=True):
            near(native, target)
    longs, shorts, close_signal, displayed_size = [
        p["values"] for p in observed["plots"][-4:]
    ]
    for i, (signal, off) in enumerate(zip(signals, outside, strict=True)):
        assert (longs[i], shorts[i], close_signal[i]) == (
            int(signal == 1),
            int(signal == -1),
            int(off),
        ), (i, chart[i], signal, longs[i], shorts[i], off, close_signal[i])
    return signals, outside, displayed_size


def id_for(side):
    assert side in (-1, 1)
    return "long" if side == 1 else "short"


def audit(actual, observed, chart, base, market):
    assert not actual["diagnostics"] and not actual["strategy"]["diagnostics"]
    assert not observed["diagnostics"] and actual["strategy"] == observed["strategy"]
    signals, outside, displayed_size = verify_signals(actual, observed, chart)
    report = actual["strategy"]
    orders, trades = iter(report["orders"]), iter(report["trades"])
    pending_signal = side = 0
    session_exit = False
    entry_time = entry_price = 0
    tick = 0.1 if market == "BTCUSDT" else 0.01
    equity = CAPITAL
    closed = []

    def match_order(i, bar, ident, direction, price):
        order = next(orders)
        assert order["id"] == ident and order["direction"] == direction, (
            i,
            order,
            ident,
            direction,
        )
        assert (
            order["barIndex"] == i
            and order["time"] == bar["time"]
            and order["qty"] == 1
        )
        near(order["price"], price)

    def settle(bar, price, reason):
        nonlocal side, equity
        trade = next(trades)
        assert trade["id"] == id_for(side) and trade["qty"] == side
        assert trade["entryTime"] == entry_time and trade["exitTime"] == bar["time"]
        near(trade["entryPrice"], entry_price)
        near(trade["exitPrice"], price)
        gross = side * (price - entry_price)
        near(trade["profit"], gross)
        fee_sensitive = FEE * (entry_price + price)
        closed.append(
            {
                **trade,
                "reason": reason,
                "fee_sensitivity": fee_sensitive,
                "after_fee_sensitivity": gross - fee_sensitive,
            }
        )
        equity += gross
        side = 0

    stop_controls = []
    for i, (bar, signal, outside_now) in enumerate(
        zip(chart, signals, outside, strict=True)
    ):
        if session_exit and side:
            match_order(
                i,
                bar,
                f"Close entry(s) order {id_for(side)}",
                "strategy.close",
                bar["open"],
            )
            near(bar["open"], base[i * 4]["open"])
            settle(bar, bar["open"], "session_market")
        if pending_signal:
            assert not side
            entry_id = id_for(pending_signal)
            match_order(i, bar, entry_id, f"strategy.{entry_id}", bar["open"])
            side, entry_time, entry_price = pending_signal, bar["time"], bar["open"]
            near(entry_price, base[i * 4]["open"])
        if side:
            stop = (round(entry_price / tick) - side * 66) * tick
            hit = bar["low"] <= stop if side == 1 else bar["high"] >= stop
            if hit:
                slug = "low" if side == 1 else "high"
                block = base[i * 4 : i * 4 + 4]
                hit_bar = next(b for b in block if side * (b[slug] - stop) <= 1e-8)
                at_hour_open = side * (bar["open"] - stop) <= 0
                at_base_open = side * (hit_bar["open"] - stop) <= 0
                hourly_price = bar["open"] if at_hour_open else stop
                price_15m = hit_bar["open"] if at_base_open else stop
                match_order(i, bar, f"x_{id_for(side)}", "strategy.exit", hourly_price)
                stop_controls.append(
                    {
                        "time": bar["time"],
                        "first_base_bar": hit_bar["time"],
                        "trigger": stop,
                        "native_price": hourly_price,
                        "base_open_model_price": price_15m,
                    }
                )
                settle(bar, hourly_price, "stop")
        near(displayed_size[i], max(1, math.floor(equity * 0.01 / 66 * 100)))
        pending_signal = signal
        session_exit = outside_now
    assert next(orders, None) is None and next(trades, None) is None
    final = report["position"][-1] if report["position"] else {"size": 0}
    near(final["size"], side)
    near(
        report["equity"][-1]["equity"],
        equity + side * (chart[-1]["close"] - entry_price),
    )
    return closed, stop_controls, final


def replay():
    original, relocated, commented = versions()
    try:
        pine_compat.compile_script(original)
    except ValueError as rejection:
        errors = str(rejection).splitlines()
        assert len(errors) == 2 and [r.split(":")[0] for r in errors] == [
            "E_PARSE_EXPR",
            "E_LEGACY_INDICATOR_DECLARATION",
        ]
    else:
        raise AssertionError(
            "Archive must fail on the missing declaration and dotted assignment."
        )
    proof = session_control()
    obs = pine_compat.compile_script(relocated + OBSERVE)
    main = pine_compat.compile_script(relocated)
    sensitivity = pine_compat.compile_script(commented)
    results = []
    for ref, market, start, stop, chart, base, base_digest in study_inputs():
        opts = options_for(market)
        actual, observed, minor_fee = [
            p.run(chart, **opts) for p in (main, obs, sensitivity)
        ]
        assert not minor_fee["diagnostics"] and not minor_fee["strategy"]["diagnostics"]
        assert minor_fee["strategy"]["equity"][0]["equity"] == 10_000
        assert actual["strategy"]["equity"][0]["equity"] == CAPITAL
        expect, alternate = actual["strategy"], minor_fee["strategy"]
        assert (
            expect["orders"] == alternate["orders"]
            and expect["position"] == alternate["position"]
        )
        assert actual["plots"] == minor_fee["plots"]
        for uncharged, charged in zip(
            expect["trades"], alternate["trades"], strict=True
        ):
            assert {k: v for k, v in uncharged.items() if k != "profit"} == {
                k: v for k, v in charged.items() if k != "profit"
            }
            near(charged["profit"], uncharged["profit"] - 2 * HEADER_FEE)
        closed, controls, final = audit(actual, observed, chart, base, market)
        results.append(
            {
                **ref,
                "market": market,
                "start": start,
                "stop": stop,
                "chart_bars": len(chart),
                "base_bars": len(base),
                "base_sha": base_digest,
                "native_orders": len(expect["orders"]),
                "closed": len(closed),
                "ending_position": final,
                "base_stop_controls": controls,
                "ledger": closed,
            }
        )
    final = {"raw_compile_errors": errors, "session_control": proof, "runs": results}
    (ROOT / "4671-replay.json").write_text(
        json.dumps(final, indent=2) + "\n", encoding="utf8"
    )


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["probe"]:
            probe()
        else:
            replay()
    except Exception:
        import traceback

        (ROOT / "4671-error.txt").write_text(traceback.format_exc(), encoding="utf8")
        raise
