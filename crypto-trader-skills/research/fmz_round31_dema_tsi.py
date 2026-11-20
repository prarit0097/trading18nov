"""Verify saved daily #226/#3526 orders from completed intrabars."""

import math
import re
import sys
from itertools import pairwise
from pathlib import Path

from research.fmz_round7_magnifier import (
    aggregate,
    date_ms,
    ledger_metrics,
    sha256,
    verified_archives,
    write,
)
from research.fmz_round18_5745 import ENGINE_SHA, FIELDS
from research.fmz_round26_977 import prices

HOUR, DAY = 3_600_000, 86_400_000
CAPITAL = 1000
SPECS = {
    226: (
        "2022-09-19",
        "2023-09-25",
        0.002,
        "1h",
        2,
        "120",
        "c0dcff4465e8a1d99c0930772c3a6b2ceb6003bcd744cd0162044c295796ca38",
    ),
    3526: (
        "2022-09-30",
        "2023-10-06",
        0.0015,
        "15m",
        1,
        "15",
        "df40f2dbcc0cb7e32b64b2212c81a9e8dda74613d5f4e1eacb416a5c815beae3",
    ),
}
PINE_EMA = """compat_ema(v, n) =>
    w = 2.0 / (n + 1)
    float e = na
    e := na(v) ? e[1] : na(e[1]) ? v : w * v + (1.0 - w) * e[1]
"""
SIGNALS = '\nplot(buy?1:0, "Entered long")\nplot(sell?1:0, "Entered short")\n'


def source_program(document, ident, digest):
    assert sha256(document) == digest
    fence = chr(96) * 3
    (source,) = re.findall(
        r"(?ms)^" + fence + r" pinescript[^\n]*\n(.*?)^" + fence,
        document.read_text(encoding="utf-8"),
    )
    body, count = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", source)
    assert count == 1 and "//@version=" not in body
    if ident == 226:
        for length in (32, 2):
            old = f"input(defval = {length},"
            assert body.count(old) == 1
            body = body.replace(old, f"input.int(defval = {length},")
        witness = '\nplot(demaSlow,"Active fast")\nplot(demaFast,"Active slow")\n'
    else:
        assert body.count('// strategy("True Strength Indicator') == 1
        body = body.replace(
            '// strategy("True Strength Indicator', 'strategy("True Strength Indicator'
        )
        assert body.count("yellow :") == 4
        body = body.replace("yellow :", "color.yellow :")
        assert body.count("stochserie") == 3
        body, n = re.subn(
            r"(?m)^stochserie\s*=\s*ta.stoch\(price,14,3,3\)[ \t]*\n", "", body
        )
        assert n == 1  # Remaining references are inside comments.
        witness = '\nplot(tsi_value,"Active fast")\nplot(tsi2,"Active slow")\nplot(price,"Intrabar close")\n'
    assert body.count("strategy.entry(") == 2
    return (
        "//@version=5\n"
        + PINE_EMA
        + body.replace("ta.ema(", "compat_ema(")
        + witness
        + SIGNALS
    )


def ema(values, n):
    weight = 2 / (n + 1)
    state = None
    result = []
    for value in values:
        if value is not None:
            state = value if state is None else weight * value + (1 - weight) * state
        result.append(state)
    return result


def dema(values, n, per_day):
    first = ema(values, n)
    double = ema(first, n)
    return [2 * first[i] - double[i] for i in range(per_day - 1, len(values), per_day)]


def indicators(ident, lower, chart):
    values = [r[4] for r in lower]
    per_day = len(values) // len(chart)
    final_values = values[per_day - 1 :: per_day]
    assert final_values == [r["close"] for r in chart]
    if ident == 226:
        return dema(values, 2, per_day), dema(values, 32, per_day)
    changes = [None, *(b - a for a, b in pairwise(final_values))]
    numerator = ema(ema(changes, 25), 13)
    denominator = ema(ema([abs(x) if x is not None else None for x in changes], 25), 13)
    tsi = [
        100 * x / y if y else None for x, y in zip(numerator, denominator, strict=True)
    ]
    return tsi, ema(tsi, 13)


def replay(engine, source, ident, market, base, base_step, group, request_frame, fee):
    span = DAY // base_step
    parent = aggregate(base, span)
    lower = aggregate(base, group)
    chart = [dict(zip(FIELDS, row, strict=True)) for row in parent]
    ltf = [dict(zip(FIELDS, row, strict=True)) for row in lower]
    symbol = f"BINANCE:{market}"
    req = {
        f"{symbol}:{request_frame}": ltf,
        "$chart": {
            "minMove": 1,
            "priceScale": 10 if market == "BTCUSDT" else 100,
            "quantityStep": ".001",
            "minContract": ".001",
            "pointValue": 1,
            "currency": "USDT",
        },
    }
    raw = engine.run_script(
        source, chart, chart_symbol=symbol, chart_timeframe="D", request_bars=req
    )
    strategy = raw["strategy"]
    assert not raw["diagnostics"] and not strategy["diagnostics"]
    plots = {p["title"]: p["values"] for p in raw["plots"] if p.get("title")}
    fast, slow = indicators(ident, lower, chart)
    if ident == 3526:
        assert plots["Intrabar close"] == [b["close"] for b in chart]
    for name, sequence in (("Active fast", fast), ("Active slow", slow)):
        for seen, expected in zip(plots[name], sequence, strict=True):
            assert (
                seen is None
                if expected is None
                else math.isclose(seen, expected, rel_tol=1e-11, abs_tol=1e-9)
            )

    orders, lots = iter(strategy["orders"]), iter(strategy["trades"])
    trades = []
    want = held = 0
    entry = None
    for i, (f, s) in enumerate(zip(fast, slow, strict=True)):
        if want != held:
            bar = chart[i]
            first = base[i * span]
            stamp, opening = bar["time"], bar["open"]
            assert (stamp, opening) == first[:2] and first[5] > 0
            if held:
                entered, entry_px = entry
                gross = held * (opening - entry_px)
                costs = fee * (entry_px + opening)
                actual = next(lots)
                assert (
                    actual["entryBarIndex"],
                    actual["exitBarIndex"],
                    actual["entryPrice"],
                    actual["exitPrice"],
                    actual["qty"],
                ) == (entered, i, entry_px, opening, held)
                assert math.isclose(actual["profit"], gross - costs, abs_tol=1e-8)
                trades.append({**actual, "dir": held, "qty": 1, "commission": costs})
            order = next(orders)
            assert (
                order["id"],
                order["barIndex"],
                order["time"],
                order["price"],
                order["qty"],
            ) == ("BUY" if want == 1 else "SELL", i, stamp, opening, abs(want - held))
            held, entry = want, (i, opening)
        p, q = (fast[i - 1], slow[i - 1]) if i else (None, None)
        buy = int(
            p is not None
            and q is not None
            and f is not None
            and s is not None
            and p <= q
            and f > s
        )
        sell = int(
            p is not None
            and q is not None
            and f is not None
            and s is not None
            and p >= q
            and f < s
        )
        assert (plots["Entered long"][i], plots["Entered short"][i]) == (buy, sell)
        if buy or sell:
            assert held != buy - sell
            want = buy - sell
    assert next(orders, None) is None and next(lots, None) is None
    assert strategy["position"][-1]["size"] == held
    return {
        "market": market,
        "chart_bars": len(chart),
        "lower_bars": len(lower),
        "trades": trades,
        "ending_side": held,
        "order_count": len(strategy["orders"]),
    }


def run(documents, hourly, quarter, runtime, output):
    assert sha256(runtime / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(runtime))
    import pine_compat

    rows, cases, archives = [], {}, []
    for ident, (start, end, fee, tf, group, frame, digest) in SPECS.items():
        source = source_program(documents / f"{ident}.md", ident, digest)
        months = [
            *(f"2022-{m:02}" for m in range(9, 13)),
            *(f"2023-{m:02}" for m in range(1, int(end[5:7]) + 1)),
        ]
        prices_dir, step = (hourly, HOUR) if tf == "1h" else (quarter, HOUR // 4)
        scopes = []
        for market in ("BTCUSDT", "ETHUSDT"):
            refs = verified_archives(prices_dir, market, tf, months, archives)
            base = prices(refs, date_ms(start), date_ms(end), step)
            scopes.append(
                replay(
                    pine_compat, source, ident, market, base, step, group, frame, fee
                )
            )
        cases[ident] = scopes
        for label, sample in (
            ("BTCUSDT", scopes[:1]),
            ("ETHUSDT", scopes[1:]),
            ("BTCUSDT + ETHUSDT", scopes),
        ):
            rows.append(
                {
                    "id": ident,
                    "group": "FMZ Pine · Confirmed final intrabar · DEMA/TSI next-open reversals",
                    "period": f"Saved window · {start} to {end} UTC exclusive",
                    "market": label,
                    "exit": "Authored DEMA/TSI signal reversal at next open",
                    "interval": "1d",
                    "archive_interval": "1d",
                    "currency": "USDT",
                    "pine_source_version": "Unspecified",
                    **ledger_metrics(
                        [t for c in sample for t in c["trades"]],
                        CAPITAL * len(sample),
                        sum(bool(c["ending_side"]) for c in sample),
                    ),
                }
            )
    write(
        output,
        {
            "schema": "FMZ 226 and 3526 · Published daily windows and causal lower input",
            "source_documents": {i: s[-1] for i, s in SPECS.items()},
            "engine_sha256": ENGINE_SHA,
            "candle_archives": list({x["url"]: x for x in archives}.values()),
            "scopes": cases,
            "results": rows,
            "references": {
                "request_merge": "https://www.tradingview.com/pine-script-docs/v5/concepts/other-timeframes-and-data/",
                "ema": "https://www.tradingview.com/pine-script-reference/v5/#fun_ta.ema",
            },
            "notes": {
                "repair": "Both archives use v5 namespaces without a version declaration, and #3526 comments the broker declaration. Replay supplies v5, restores that exact declaration, types #226 integer inputs, corrects a display color and removes #3526's invalid unused stochastic display variable.",
                "timing": "#226 computes double EMA inside the 2h context and selects its last completed value per daily chart bar. #3526 selects the last completed 15m close and then calculates TSI in daily context. An independent recurrence uses the first non-missing EMA source, with no engine-specific SMA startup.",
                "fills": "Order flips fill at the next observed official first base-candle opening price. Each market is funded independently with the declared 1,000 starting capital and explicit one-base-unit orders. Source charges 0.2% or 0.15% per fill. Results use historical zero-margin chart-broker behavior with no funding, quote spread or liquidation, and can exceed the model starting balance in losses.",
            },
            "coverage": [
                [
                    226,
                    "Tested · Completed two-hour DEMA projection",
                    "Saved BTC daily chart and matched ETH using independently verified two-hour DEMA series and next-open source-fee reversals.",
                ],
                [
                    3526,
                    "Tested · Completed 15m close and daily TSI",
                    "Restored the archived strategy header and verified last confirmed 15m close, daily TSI, next-open source-fee fills and realized lots on BTC/ETH.",
                ],
            ],
        },
    )


if __name__ == "__main__":
    run(*map(Path, sys.argv[1:]))
