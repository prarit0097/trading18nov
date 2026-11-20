"""Independently settle #1216 DEMA signals and five-minute bracket ordering."""

import json
import math
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from probe_1216 import (
    CAPITAL,
    MINUTE,
    engine_options,
    load_cases,
    near,
    objects,
    pine_compat,
    sha256,
    source_versions,
)

FEE = 0.00075
OBSERVE = """
plot(longCondition ? 1 : 0, title="Verified London long")
plot(shortCondition ? 1 : 0, title="Verified London short")
plot(longCondition2 ? 1 : 0, title="Verified New York long")
plot(shortCondition2 ? 1 : 0, title="Verified New York short")
"""


def ema(values, period):
    count = 0
    seed = []
    last = None
    out = []
    alpha = 2 / (period + 1)
    for price in values:
        if price is None:
            out.append(None)
            continue
        if last is None:
            seed.append(price)
            count += 1
            if count == period:
                last = math.fsum(seed) / period
        else:
            last = alpha * price + (1 - alpha) * last
        out.append(last)
    return out


def dema(prices, period):
    first = ema(prices, period)
    second = ema(first, period)
    return [
        None if b is None else 2 * a - b for a, b in zip(first, second, strict=True)
    ]


def signal_data(chart):
    closes = [bar["close"] for bar in chart]
    curves = [dema(closes, period) for period in (25, 50, 100)]
    expected = []
    for i, bar in enumerate(chart):
        date = datetime.fromtimestamp(bar["time"] / 1000, UTC)
        london = date.weekday() < 5 and 3 <= date.hour < 11
        ny = date.weekday() < 5 and 8 <= date.hour < 16
        fast, medium, slow = [track[i] for track in curves]
        before = [track[i - 1] for track in curves] if i else [None] * 3
        and_ready = None not in (fast, medium, slow, *before)
        go_long = (
            and_ready and fast > max(medium, slow) and before[0] <= min(before[1:])
        )
        go_short = (
            and_ready and fast < min(medium, slow) and before[0] >= max(before[1:])
        )
        assert not (go_long and go_short)
        expected.append(
            [
                int(go_long and london),
                int(go_short and london),
                int(go_long and ny),
                int(go_short and ny),
            ]
        )
    return curves, expected


def verify_signals(report, chart):
    curves, expected = signal_data(chart)
    plots = [p["values"] for p in report["plots"]]
    assert len(plots) == 7
    for actual, calculated in zip(plots[:3], curves, strict=True):
        for a, b in zip(actual, calculated, strict=True):
            near(a, b)
    assert list(map(list, zip(*plots[3:], strict=True))) == expected
    return [int(bool(a or c)) - int(bool(b or d)) for a, b, c, d in expected]


def first_touch(children, side, entry, tick):
    base = Decimal(str(entry))
    target = float(base + side * 50 * tick)
    stop = float(base - side * 100 * tick)
    for candle in children:
        open_, high, low, close = [candle[k] for k in ("open", "high", "low", "close")]
        assert not (side * (open_ - target) >= 0 or side * (open_ - stop) <= 0), (
            candle,
            entry,
            target,
            stop,
        )
        high_first = high - open_ < open_ - low
        extreme_1, extreme_2 = (high, low) if high_first else (low, high)
        for price in (extreme_1, extreme_2, close):
            if side * (price - target) >= 0:
                return target, "target", candle["time"]
            if side * (price - stop) <= 0:
                return stop, "stop", candle["time"]
    raise AssertionError("Selected case has no complete bracket touch in its entry bar")


def model_ledger(book, chart, lower, signals, market):
    orders, trades = iter(book["orders"]), iter(book["trades"])
    ledger = []
    equity = CAPITAL
    tick = Decimal("0.1" if market == "BTCUSDT" else "0.01")
    for i, (bar, children) in enumerate(zip(chart, lower, strict=True)):
        side = signals[i - 1] if i else 0
        if side:
            price = bar["open"]
            near(price, children[0]["open"])
            entry = next(orders)
            exit_ = next(orders)
            trade = next(trades)
            entry_id = "long" if side == 1 else "short"
            expected_price, reason, base_time = first_touch(children, side, price, tick)
            assert entry["id"] == trade["id"] == entry_id and exit_["id"] == "tp/sl"
            assert (
                entry["direction"] == f"strategy.{entry_id}"
                and exit_["direction"] == "strategy.exit"
            )
            assert (
                entry["qty"] == exit_["qty"] == abs(trade["qty"]) == 1
                and trade["qty"] == side
            )
            assert (
                entry["barIndex"]
                == exit_["barIndex"]
                == trade["entryBarIndex"]
                == trade["exitBarIndex"]
                == i
            )
            assert (
                entry["time"]
                == exit_["time"]
                == trade["entryTime"]
                == trade["exitTime"]
                == bar["time"]
            )
            near(entry["price"], price)
            near(trade["entryPrice"], price)
            near(exit_["price"], expected_price)
            near(trade["exitPrice"], expected_price)
            gross = side * (expected_price - price)
            near(trade["profit"], gross)
            equity += gross
            fee = FEE * (price + expected_price)
            ledger.append(
                {
                    **trade,
                    "reason": reason,
                    "first_base_time": base_time,
                    "fee_sensitivity": fee,
                    "after_fee_sensitivity": gross - fee,
                }
            )
        near(book["equity"][i]["equity"], equity)
    assert next(orders, None) is None and next(trades, None) is None
    assert not book["position"] or book["position"][-1]["size"] == 0
    return ledger


def fixture():
    snippet = """//@version=5
strategy("Archived bracket control", use_bar_magnifier=MODE)
if bar_index==0
    strategy.entry("short",strategy.short)
    strategy.exit("tp/sl","short",profit=50,loss=100)
"""
    chart = objects([[0, 100, 100, 100, 100, 3], [15 * MINUTE, 100, 112, 89, 100, 3]])
    opening = objects([[m * MINUTE, 100, 100, 100, 100, 1] for m in (0, 5, 10)])
    higher_first = objects(
        [
            [15 * MINUTE, 100, 112, 99, 106, 1],
            [20 * MINUTE, 106, 107, 89, 100, 1],
            [25 * MINUTE, 100, 100, 100, 100, 1],
        ]
    )
    lower_first = objects(
        [
            [15 * MINUTE, 100, 101, 89, 94, 1],
            [20 * MINUTE, 94, 112, 89, 100, 1],
            [25 * MINUTE, 100, 100, 100, 100, 1],
        ]
    )
    options = {**engine_options("BTCUSDT"), "chart_timeframe": "15"}
    coarse = pine_compat.run_script(snippet.replace("MODE", "false"), chart, **options)
    assert not coarse["diagnostics"]
    assert coarse["strategy"]["trades"][0]["exitPrice"] == 95
    verify = {"coarse_exit": 95}
    for name, children, expected in (
        ("five_minute_high_first", higher_first, 110),
        ("five_minute_low_first", lower_first, 95),
    ):
        groups = [
            {"chartBarIndex": 0, "bars": opening},
            {"chartBarIndex": 1, "bars": children},
        ]
        check = pine_compat.run_script(
            snippet.replace("MODE", "true"),
            chart,
            **options,
            magnifier_bars={"schemaVersion": 1, "chartBars": groups},
        )
        assert not check["diagnostics"] and not check["strategy"]["diagnostics"]
        assert check["strategy"]["trades"][0]["exitPrice"] == expected
        verify[name] = expected
    return verify


def run():
    ref_path = ROOT / "1216-probe.json"
    ref = json.loads(ref_path.read_bytes())
    _, _, _, based = source_versions()
    observed_engine = pine_compat.compile_script(based + OBSERVE)
    outcomes = []
    for item, (data, start, stop, chart, groups) in zip(
        ref["cases"], load_cases(), strict=True
    ):
        market = data["market"]
        assert item["file"] == data["file"]
        assert not any(item["warnings"]) and not item["base"]["diagnostics"]
        assert item["old"] == item["modern"] and not item["old"]["diagnostics"]
        options = {**engine_options(market), "chart_timeframe": "15"}
        verified = observed_engine.run(
            chart, **options, magnifier_bars={"schemaVersion": 1, "chartBars": groups}
        )
        assert not verified["diagnostics"] and verified["strategy"] == item["base"]
        signals = verify_signals(verified, chart)
        precise = model_ledger(
            item["base"], chart, [g["bars"] for g in groups], signals, market
        )
        coarse = model_ledger(
            item["old"], chart, [[row] for row in chart], signals, market
        )
        assert len(precise) == len(coarse)
        switches = []
        for actual, control in zip(precise, coarse, strict=True):
            for key in ("id", "entryTime", "entryPrice", "qty"):
                assert actual[key] == control[key]
            if actual["exitPrice"] != control["exitPrice"]:
                switches.append(
                    {
                        "entry_time": actual["entryTime"],
                        "base_exit": actual["exitPrice"],
                        "chart_exit": control["exitPrice"],
                        "base_reason": actual["reason"],
                        "chart_reason": control["reason"],
                    }
                )
        if not outcomes:
            broken = observed_engine.run(
                chart,
                **options,
                magnifier_bars={"schemaVersion": 1, "chartBars": groups[:-1]},
            )
            assert [warning["code"] for warning in broken["diagnostics"]] == [
                "W_MAGNIFIER_FALLBACK"
            ]
        outcomes.append(
            {
                **data,
                "start": start,
                "end": stop,
                "signal_count": sum(side != 0 for side in signals),
                "closed": len(precise),
                "chart_base_differences": switches,
                "base_ledger": precise,
                "chart_ledger": coarse,
            }
        )
    result = {
        "raw_probe_sha256": sha256(ref_path.read_bytes()),
        "synthetic_ordering": fixture(),
        "missing_group_warning": "W_MAGNIFIER_FALLBACK",
        "cases": outcomes,
    }
    (ROOT / "1216-verified.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf8"
    )


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "1216-verify-error.txt").write_text(
            traceback.format_exc(), encoding="utf8"
        )
        raise
