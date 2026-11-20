"""Replay the effective archived EMA logic after eliminating legacy no-op exits."""

import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from replay_2864 import engine_options, load_case, near, pine_compat, sha256

CAPITAL = 50_000
COMMISSION = 0.00004


def migrate():
    raw = (ROOT / "source-1214.md").read_bytes()
    assert (
        sha256(raw)
        == "a6c50779e6b2fb7e3bd76b921268e96c436e6cb131ded08263f1c25c3e01e1c9"
    )
    (code,) = re.findall(r"(?m)^``` pinescript\n(.*?)^```", raw.decode(), re.DOTALL)
    code, removed = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", code)
    assert removed == 1
    legacy = code.replace("// @version=4", "//@version=4")
    substitutions = (
        ("// @version=4", "//@version=5", 1),
        ("ema(", "ta.ema(", 3),
        ("crossover(", "ta.crossover(", 1),
        ("crossunder(", "ta.crossunder(", 1),
        ("max(StopLoss,", "math.max(StopLoss,", 1),
        ("min(StopLoss,", "math.min(StopLoss,", 1),
    )
    for old, new, count in substitutions:
        assert code.count(old) == count, old
        code = code.replace(old, new)
    code, inputs = re.subn(
        r'\binput\(title=("[^"]+"), type=input\.integer,', r"input.int(title=\1,", code
    )
    assert inputs == 8
    untouched_exits = code
    code = without_noop_exits(code)
    assert code.count("StopLoss :=") == 4 and code.count("strategy.entry(") == 2
    return code, untouched_exits, legacy


def without_noop_exits(source):
    code, removed = re.subn(
        r'(?m)^    strategy\.exit\("(Long|Short) Stoploss", "\1"\)[ \t]*\n', "", source
    )
    assert removed == 4 and "strategy.exit(" not in code
    return code


def verify_rejected_exits(source, feed, options):
    try:
        pine_compat.run_script(source, feed, **options)
    except ValueError as error:
        messages = str(error).splitlines()
        assert len(messages) == 4
        assert all(
            line.startswith("E_CALL_ARITY:Error:")
            and "`strategy.exit` requires one of" in line
            for line in messages
        ), messages
        return messages
    raise AssertionError("Expected four invalid-empty-exit diagnostics.")


OBSERVER = """
plot(longCondition ? 1 : 0, title="Observed long")
plot(shortCondition ? 1 : 0, title="Observed short")
"""


def ema_signals(feed):
    prices = [bar["close"] for bar in feed]
    assert len(prices) >= 50
    tracks = []
    for length in (5, 20, 50):
        weights = 2 / (length + 1)
        series = [None] * (length - 1) + [math.fsum(prices[:length]) / length]
        for price in prices[length:]:
            series.append(price * weights + series[-1] * (1 - weights))
        tracks.append(series)
    emits = [0] * 49
    for i, price in enumerate(prices[49:], 49):
        calc = [series[i] for series in tracks]
        previous = [series[i - 1] for series in tracks]
        prev_close = prices[i - 1]
        up = (
            calc[0] > calc[1]
            and previous[0] <= previous[1]
            and price > calc[2]
            and min(calc[:2]) > calc[2]
            and price > prev_close + 0.00015
        )
        down = (
            calc[0] < calc[1]
            and previous[0] >= previous[1]
            and price < calc[2]
            and max(calc[:2]) < calc[2]
            and price < prev_close - 0.00015
        )
        assert not (up and down)
        emits.append(int(up) - int(down))
    return emits, tracks


def audit(base, observed, feed):
    assert not base["diagnostics"] and not base["strategy"]["diagnostics"]
    assert base["strategy"] == observed["strategy"] and not observed["diagnostics"]
    signals, tracks = ema_signals(feed)
    for plot, expected in zip(base["plots"], tracks, strict=True):
        for value, target in zip(plot["values"], expected, strict=True):
            near(value, target)
    long_signals, short_signals = [plot["values"] for plot in observed["plots"][-2:]]
    for i, (up, down, side) in enumerate(
        zip(long_signals, short_signals, signals, strict=True)
    ):
        assert up == int(side == 1) and down == int(side == -1), (
            i,
            up,
            down,
            side,
            feed[max(0, i - 1) : i + 1],
            [(p["title"], p["values"][max(0, i - 1) : i + 1]) for p in base["plots"]],
        )
    broker = base["strategy"]
    fills, trades = iter(broker["orders"]), iter(broker["trades"])
    side = pending = 0
    entry_time = entry = 0
    equity = CAPITAL
    ledger = []
    for i, (bar, signal) in enumerate(zip(feed, signals, strict=True)):
        if pending:
            order = next(fills)
            price, stamp = bar["open"], bar["time"]
            assert order["time"] == stamp and order["barIndex"] == i
            assert order["id"] == ("Long" if pending == 1 else "Short")
            assert order["qty"] == 1 + abs(side)
            near(order["price"], price)
            if side:
                trade = next(trades)
                assert trade["id"] == ("Long" if side == 1 else "Short")
                assert trade["entryTime"] == entry_time and trade["exitTime"] == stamp
                assert trade["qty"] == side
                near(trade["entryPrice"], entry)
                near(trade["exitPrice"], price)
                gross = side * (price - entry)
                fees = COMMISSION * (price + entry)
                near(trade["profit"], gross - fees)
                ledger.append({**trade, "gross": gross, "fees": fees})
                equity += gross - fees
            side, entry_time, entry = pending, stamp, price
        pending = signal if signal != side else 0
    assert next(fills, None) is None and next(trades, None) is None
    unsettled = None
    if side:
        unsettled = {
            "signed_quantity": side,
            "entryTime": entry_time,
            "entryPrice": entry,
        }
        equity += side * (feed[-1]["close"] - entry) - COMMISSION * entry
    near(broker["equity"][-1]["equity"], equity)
    return ledger, unsettled, signals


def run(probe):
    script, no_op_compare, legacy = migrate()
    manifest = json.loads((ROOT / "2864-inputs.json").read_bytes())
    cases = manifest["feeds"][:1] if probe else manifest["feeds"]
    engine = pine_compat.compile_script(script)
    observer = pine_compat.compile_script(script + OBSERVER)
    legacy_engine = pine_compat.compile_script(without_noop_exits(legacy))
    runs = []
    for ref in cases:
        feed = load_case(ref, 2880 if probe else None)
        options = engine_options(ref["market"])
        base = engine.run(feed, **options)
        tracked = observer.run(feed, **options)
        ledger, ending, signals = audit(base, tracked, feed)
        legacy_outcome = legacy_engine.run(feed, **options)
        assert not legacy_outcome["diagnostics"]
        assert legacy_outcome["strategy"] == base["strategy"]
        assert [p["values"] for p in legacy_outcome["plots"]] == [
            p["values"] for p in base["plots"]
        ]
        if probe:
            (ROOT / "1214-legacy-control.json").write_text(
                json.dumps(
                    {
                        "v4_errors": verify_rejected_exits(legacy, feed, options),
                        "v5_errors": verify_rejected_exits(
                            no_op_compare, feed, options
                        ),
                        "match": True,
                    },
                    indent=2,
                ),
                encoding="utf8",
            )
        runs.append(
            {
                **ref,
                "tested_bars": len(feed),
                "closed": len(ledger),
                "ending_position": ending,
                "orders": len(base["strategy"]["orders"]),
                "long_signals": signals.count(1),
                "short_signals": signals.count(-1),
                "legacy_v4_matches": True,
                "ledger": ledger,
            }
        )
        suffix = "probe" if probe else "replay-progress"
        (ROOT / f"1214-{suffix}.json").write_text(
            json.dumps(runs, indent=2), encoding="utf8"
        )
    if not probe:
        report = {
            "migrated_sha256": sha256(script.encode()),
            "inputs": manifest,
            "runs": runs,
        }
        (ROOT / "1214-replay.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf8"
        )


if __name__ == "__main__":
    try:
        run(sys.argv[1:] == ["probe"])
    except Exception:
        import traceback

        (ROOT / "1214-error.txt").write_text(traceback.format_exc(), encoding="utf8")
        raise
