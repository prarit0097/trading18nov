"""Verify round-four compiler repairs against an independent v5 control."""

import argparse
from pathlib import Path

from research.delta_pinets_catalogue import read, write
from research.fmz_round3_compile_fixture import prepare as fixture_candles
from research.fmz_round3_compile_fixture import verify as verify_fixture
from research.fmz_round4_compile import prepare_source

LEGACY = """//@version=2
strategy("Fixture", process_orders_on_close=true)
weight(input) =>
    return = input + 7
    return
length = input(02, defval=2, title="Length", minval=1, maxval=10)
previous = nz(counter[1])
counter = previous + 1
average = weight(sma(close, length))
if counter == 5 and average > close
    strategy.entry("L", strategy.long, qty=2)
if counter == 7
    strategy.close("L")
"""
CONTROL = """//@version=5
strategy("Fixture", process_orders_on_close=true)
average = ta.sma(close, 2) + 7
if bar_index == 4 and average > close
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 6
    strategy.close("L")
"""
CHECKS = [
    "Function-local binding names preserve the returned average",
    "Equivalent duplicate numeric defaults preserve the archived setting",
    "Explicit recursive initialization preserves previous-bar evaluation",
]


RETRY_LEGACY = """//@version=4
strategy("Fixture", process_orders_on_close=true)
accumulate(change) =>
    accumulated = nz(accumulated[1]) + change
    accumulated
first = "forward"
second = "reverse"
choice = input(first, options=[first, second])
value = iff(bar_index % 2 == 0, ema(close, 3), ema(open, 4)) + 1
up = sum(volume * high, 2)
down = sum(volume * low, 2)
oscillator = rsi(up, down)
count = accumulate(1.0)
if count == 5 and choice == first and value == 104 and oscillator == 50
    strategy.entry("L", strategy.long, qty=2)
if count == 7
    strategy.close("L")
"""
RETRY_CONTROL = """//@version=5
strategy("Fixture", process_orders_on_close=true)
fast = ta.ema(close, 3)
slow = ta.ema(open, 4)
value = (bar_index % 2 == 0 ? fast : slow) + 1
if bar_index == 4 and value == 104
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 6
    strategy.close("L")
"""
RETRY_CHECKS = [
    "Eager EMA branches preserve evaluation on every chart bar",
    "Function-local recursive history preserves the count",
    "Literal string options preserve the default choice",
    "Legacy two-series RSI yields 50 for equal positive inputs",
]


def prepare(work, retry=False):
    fixture_candles(work)
    if retry:
        migrated, _, _, repairs = prepare_source(
            RETRY_LEGACY, local_types={"accumulate": {"accumulated": "float"}}
        )
        assert repairs["Archived eager iff argument evaluation"] == 1
        assert repairs["Audited function-local recursive state"] == 1
        assert repairs["Documented legacy float RSI overload"] == 1
        assert repairs["Legacy literal input normalized"] == 1
        control = RETRY_CONTROL
    else:
        migrated, _, _, repairs = prepare_source(LEGACY, state_types={"counter": "int"})
        assert repairs["Function-local v5 collision renamed"] == 2
        assert repairs["Legacy literal input normalized"] == 1
        assert repairs["Audited prior-bar recursive state"] == 1
        control = CONTROL
    candidates = read(work / "fixture-candidates.json")
    for candidate, code in zip(candidates, (migrated, control), strict=True):
        candidate["code"] = code
    write(work / "fixture-candidates.json", candidates)


def verify(work, destination, retry=False):
    verify_fixture(work, destination)
    report = read(destination)
    report["checks"] = RETRY_CHECKS if retry else CHECKS
    write(destination, report)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("work", type=Path)
    cli.add_argument("--verify-to", type=Path)
    cli.add_argument("--retry", action="store_true")
    args = cli.parse_args()
    if args.verify_to:
        verify(args.work, args.verify_to, args.retry)
    else:
        prepare(args.work, args.retry)
