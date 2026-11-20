"""Verify #1988 on two explicit positive historical reference feeds."""

import math
import re
import sys
from itertools import pairwise
from pathlib import Path

from research.fmz_round7_magnifier import date_ms, ledger_metrics, read, sha256, write
from research.fmz_round18_5745 import DAY, ENGINE_SHA, FEEDS, FIELDS

SOURCE_SHA = "5ff8de577434eb90c959207df62cbaf478bf563431f4098babe00a78bd0e3aad"
START, END = map(date_ms, ("2019-12-24", "2024-12-03"))
CAPITAL, FEE = 1_000_000, 0.00075
OBSERVE = """
plot(rs,title="Relative strength")
plot(longCondition?1:0,title="Base entry")
plot(reEntryCondition?1:0,title="Repeat entry")
plot(reEntryAfterSL?1:0,title="After stop")
plot(exitCondition?1:0,title="Exit gate")
plot(strategy.position_size,title="Position")
"""


def ema(values, n):
    out = [None] * (n - 1) + [math.fsum(values[:n]) / n]
    weight = 2 / (n + 1)
    for value in values[n:]:
        out.append(out[-1] + weight * (value - out[-1]))
    return out


def rsi14(close):
    changes = [b - a for a, b in pairwise(close)]
    up = math.fsum(max(c, 0) for c in changes[:14]) / 14
    down = math.fsum(max(-c, 0) for c in changes[:14]) / 14
    result = [None] * 14
    for i in range(14, len(close)):
        if i > 14:
            up = (13 * up + max(changes[i - 1], 0)) / 14
            down = (13 * down + max(-changes[i - 1], 0)) / 14
        result.append(100 - 100 / (1 + up / down) if down else 100)
    return result


def independent(chart):
    close = [b["close"] for b in chart]
    assert all(0 < b["close"] <= b["high"] for b in chart)
    fast, slow = (ema(close, n) for n in (13, 21))
    strength = rsi14(close)
    signals, repeat, exits = [], [], []
    lots, states, orders = [], [], []
    target = held = 0
    entry_index = None
    for i, (c, f, s, r) in enumerate(zip(close, fast, slow, strength, strict=True)):
        if target != held:
            if held:
                lots.append((entry_index, i))
            held = target
            entry_index = i if held else None
            orders.append((i, held))
        states.append(held)
        prev_close_cross = i >= 13 and close[i - 1] <= fast[i - 1]
        prev_ema_cross = i >= 21 and fast[i - 1] <= slow[i - 1]
        enter = (prev_ema_cross and f > s) or (
            i >= 54 and c > f and r is not None and r > 60
        )
        reenter = i >= 54 and c > f and prev_close_cross and f > s
        exit = (s is not None and c < s) or (r is not None and r < 50)
        signals.append(int(enter))
        repeat.append(int(reenter))
        exits.append(int(exit))
        if held:
            target = int(not exit)
        else:
            target = int(enter or reenter)
    return (
        {
            "Base entry": signals,
            "Repeat entry": repeat,
            "After stop": [0] * len(chart),
            "Exit gate": exits,
            "Position": states,
        },
        lots,
        orders,
        held,
    )


def replay(engine, source, market, chart, references):
    options = {
        "chart_symbol": f"BINANCE:{market}",
        "chart_timeframe": "D",
        "request_bars": {
            "$chart": {
                "minMove": 1,
                "priceScale": 100,
                "pointValue": 1,
                "quantityStep": "0.001",
                "minContract": "0.001",
                "currency": "USDT",
            }
        },
    }
    expected, lots, orders, pending = independent(chart)
    all_results = []
    for input_market, bars in references.items():
        assert [b["time"] for b in chart] == [b["time"] for b in bars]
        assert all(b["close"] > 0 for b in bars)
        opts = {**options, "request_bars": {**options["request_bars"], "swap:D": bars}}
        plain = engine.run_script(source, chart, **opts)["strategy"]
        tracked = engine.run_script(source + OBSERVE, chart, **opts)
        assert plain == tracked["strategy"] and not tracked["diagnostics"]
        plots = {p["title"]: p["values"] for p in tracked["plots"] if p["title"]}
        target = ema(
            [a["close"] / b["close"] for a, b in zip(chart, bars, strict=True)], 55
        )
        for actual, check in zip(plots["Relative strength"], target, strict=True):
            assert (
                actual is None
                if check is None
                else actual > 0
                and math.isclose(actual, check, rel_tol=1e-12, abs_tol=1e-12)
            )
        for title, expect in expected.items():
            assert plots[title] == expect, (market, input_market, title)
        all_results.append(plain)
    a, b = all_results
    assert a == b
    for o, (i, held) in zip(a["orders"], orders, strict=True):
        assert (o["barIndex"], o["price"], o["qty"]) == (i, chart[i]["open"], 1)
        assert o["direction"] == ("strategy.long" if held else "strategy.close")
    settled = []
    for trade, (entry, exit) in zip(a["trades"], lots, strict=True):
        assert (trade["entryBarIndex"], trade["exitBarIndex"], trade["qty"]) == (
            entry,
            exit,
            1,
        )
        ep, xp = chart[entry]["open"], chart[exit]["open"]
        assert (trade["entryPrice"], trade["exitPrice"]) == (ep, xp)
        assert math.isclose(trade["profit"], xp - ep, abs_tol=1e-8)
        fee = FEE * (xp + ep)
        settled.append({**trade, "dir": 1, "commission": fee, "profit": xp - ep - fee})
    return {
        "market": market,
        "bars": len(chart),
        "settled": settled,
        "position": a["position"][-1],
        "unsettled": pending,
        "fills": a["orders"],
    }


def run(source_path, feeds, engine_root, output):
    assert sha256(engine_root / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(engine_root))
    import pine_compat as engine

    assert sha256(source_path) == SOURCE_SHA
    (src,) = re.findall(
        r"(?ms)^```[^\n]*\n(.*?)^```", source_path.read_text(encoding="utf-8")
    )
    src, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", src)
    assert n == 1
    references = {}
    for market, digest in FEEDS.items():
        path = feeds / f"5411-feed-{market}.json"
        assert sha256(path) == digest
        bars = [
            dict(zip(FIELDS, row, strict=True))
            for row in read(path)
            if START <= row[0] < END
        ]
        assert [b["time"] for b in bars] == list(range(START, END, DAY))
        references[market] = bars
    cases = [
        replay(engine, src, market, chart, references)
        for market, chart in references.items()
    ]
    meta = {
        "id": 1988,
        "group": "FMZ · Pine v5 · Reference sign invariance",
        "exit": "EMA21, RSI and reference sign gates",
        "period": "Binance USD-M · 2019-12-24 to 2024-12-03 UTC exclusive",
        "archive_interval": "1d",
        "interval": "1d",
        "currency": "USDT",
    }
    results = [
        {
            **meta,
            "market": c["market"],
            **ledger_metrics(c["settled"], CAPITAL, c["unsettled"]),
        }
        for c in cases
    ]
    pool = [lot for c in cases for lot in c["settled"]]
    results.append(
        {
            **meta,
            "market": "BTCUSDT + ETHUSDT",
            **ledger_metrics(pool, 2 * CAPITAL, sum(c["unsettled"] for c in cases)),
        }
    )
    write(
        output,
        {
            "schema": "FMZ 1988 · Positive-reference order invariance",
            "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
            "source_sha256": SOURCE_SHA,
            "engine_sha256": ENGINE_SHA,
            "daily_sha256": FEEDS,
            "notes": {
                "input": "The archive's active input is a bare swap alias and its NIFTY request is commented out. Two separate fully observed BTC and ETH daily perpetual references are bound to swap. This is a controlled input comparison. Neither is asserted to be the archival symbol.",
                "equivalence": "After the shared 55-bar warmup, an EMA of finite positive close/reference values is strictly positive. Only its sign enters these order rules. Two native runs with distinct source data give identical complete outputs, and an independent reconstruction matches every entry and exit gate. The active high crossover is unreachable with valid OHLC because its lookback includes the current high.",
                "broker": "One base unit, historical cents grid, next-open market orders and an initial 1,000,000 USDT per independent market. Drawdown uses settled P&L. Gross uses the source's zero commission; the after-fees sensitivity applies 0.075% per fill. No liquidity, funding or additional execution model.",
            },
            "coverage": [
                [
                    1988,
                    "Tested · Daily positive reference comparison and sign proof",
                    "Both BTC and ETH perpetual references preserve the complete daily order ledger because the finite positive ratio's sign is invariant. Source order gates and fills match independent EMA, RSI and OHLC checks. The archived swap alias stays unidentified.",
                ]
            ],
            "results": results,
            "scopes": cases,
        },
    )


if __name__ == "__main__":
    run(*map(Path, sys.argv[1:]))
