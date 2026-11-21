"""Verify the saved oscillator-candle benchmark and its causal fill chronology."""

import math
import re
import sys
from decimal import Decimal
from pathlib import Path

from research.fmz_round7_magnifier import (
    aggregate,
    date_ms,
    ledger_metrics,
    sha256,
    verified_archives,
    write,
)
from research.fmz_round18_5745 import DAY, ENGINE_SHA, FIELDS
from research.fmz_round26_977 import prices

SOURCE = "965248460d2385dee6a3ce0de9e2ee8a3adfa9c153f2409302fe77520288dbfe"
BEGIN, END = map(date_ms, ("2023-08-26", "2023-09-25"))
MONTHS = ("2023-08", "2023-09")
MINUTE = 60_000
CAPITAL = Decimal(1_000)
FEE = Decimal("0.0001")
LOT = Decimal("0.001")
PIVOT = "[pivotHigh, pivotLow] = f_getPivotHighLow(open, close, high, low, HTFMultiplier, resolution, PivotLength)"
OBSERVE = """
plot(oOpen, title="audit oscillator open")
plot(oHigh, title="audit oscillator high")
plot(oLow, title="audit oscillator low")
plot(oClose, title="audit oscillator close")
plot(barState, title="audit direction")
plot(buyStopDerived, title="audit lower stop")
plot(sellStopDerived, title="audit upper stop")
"""


def programs(document):
    assert sha256(document) == SOURCE
    fence = chr(96) * 3
    (script,) = re.findall(
        r"(?ms)^" + fence + r" pinescript[^\n]*\n(.*?)^" + fence,
        document.read_text(encoding="utf-8"),
    )
    script, count = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", script)
    assert count == 1 and "useHTFPivot = input(false)" in script
    assert script.count(PIVOT) == script.count("calc_on_order_fills = true") == 1
    # Preserve the constant highs and lows while satisfying the local engine's series type.
    script, count = re.subn(
        r"stoch\((open|high|low|close), longlength, shortlength, length\)",
        r"stoch(\1, longlength+0.0*close, shortlength+0.0*close, length)",
        script,
    )
    assert count == 4
    dead_pivot = script.replace(PIVOT, "pivotHigh = float(na)\npivotLow = float(na)")
    at_close = dead_pivot.replace(
        "calc_on_order_fills = true", "calc_on_order_fills = false"
    )
    return [x + OBSERVE for x in (script, dead_pivot, at_close)]


def annual_frames(folder, market, receipts):
    result = []
    for year, months, end_date in ((2022, 12, "2023-01-01"), (2023, 9, "2023-09-25")):
        files = verified_archives(
            folder,
            market,
            "1d",
            tuple(f"{year}-{i:02d}" for i in range(1, months + 1)),
            receipts,
        )
        candles = prices(files, date_ms(f"{year}-01-01"), date_ms(end_date), DAY)
        [bar] = aggregate(candles, len(candles))
        result.append(dict(zip(FIELDS, bar, strict=True)))
    return result


def indicator_witness(chart):
    names = (
        "oscillator open",
        "oscillator high",
        "oscillator low",
        "oscillator close",
        "direction",
        "lower stop",
        "upper stop",
    )
    output = {key: [] for key in names}
    prior_close = raw_lower = raw_upper = lower = upper = atr = None
    seed, direction = [], 0
    for i, (_, opening, high, low, close, _) in enumerate(chart):
        o, h, l, c = (
            100 * (p - 3) / (9 - 3) if i >= 2 else None
            for p in (opening, high, low, close)
        )
        if prior_close is not None:
            tr = max(h, prior_close) - min(l, prior_close)
            if atr is None:
                seed.append(tr)
                if len(seed) == 30:
                    atr = math.fsum(seed) / 30
            else:
                atr = (29 * atr + tr) / 30
        if atr is not None:
            if upper is not None and h > upper:
                direction = 1
            elif lower is not None and l < lower:
                direction = -1
            new_lower = c - atr * (4 if direction == 1 else 3)
            new_upper = c + atr * (4 if direction == -1 else 3)
            if direction == 1:
                new_lower, new_upper = (
                    max(new_lower, raw_lower),
                    max(new_upper, raw_upper),
                )
            elif direction == -1:
                new_lower, new_upper = (
                    min(new_lower, raw_lower),
                    min(new_upper, raw_upper),
                )
            raw_lower, raw_upper = new_lower, new_upper
            if lower is None or not lower < c < upper:
                lower, upper = raw_lower, raw_upper
        for key, value in zip(
            names, (o, h, l, c, direction, lower, upper), strict=True
        ):
            output[key].append(value)
        prior_close = c
    return output


def settlement(chart, directions, native):
    cash = CAPITAL
    position = None
    pending = 0
    orders, closed = [], []
    for i, ((stamp, opening, _, _, close, _), target, equity) in enumerate(
        zip(chart, directions, native["equity"], strict=True)
    ):
        opening, close = Decimal(str(opening)), Decimal(str(close))
        if pending and (position is None or position["side"] != pending):
            if position:
                qty, side, entry = (position[k] for k in ("qty", "side", "entry"))
                gross = (opening - entry) * side * qty
                fees = (entry + opening) * qty * FEE
                cash += opening * qty * (side - FEE)
                close_name = "Close entry(s) order " + position["name"]
                orders.append(
                    (close_name, i, stamp, "strategy.close", float(qty), float(opening))
                )
                closed.append(
                    {
                        "id": position["name"],
                        "dir": side,
                        "qty": float(qty),
                        "entryTime": position["time"],
                        "entryPrice": float(entry),
                        "exitTime": stamp,
                        "exitPrice": float(opening),
                        "commission": float(fees),
                        "profit": float(gross - fees),
                    }
                )
            qty = cash / (opening * (1 + FEE)) // LOT * LOT
            assert qty > 0
            name, direction = ("Buy", "long") if pending == 1 else ("Sell", "short")
            orders.append(
                (name, i, stamp, "strategy." + direction, float(qty), float(opening))
            )
            cash -= opening * qty * (pending + FEE)
            position = {
                "side": pending,
                "qty": qty,
                "entry": opening,
                "time": stamp,
                "name": name,
            }
        pending = target
        value = close * position["qty"] * position["side"] if position else Decimal(0)
        for name, expected in (
            ("cash", cash),
            ("marketValue", value),
            ("equity", cash + value),
        ):
            assert math.isclose(equity[name], float(expected), abs_tol=1e-8), (
                i,
                name,
                equity[name],
                expected,
            )
    keys = ("id", "barIndex", "time", "direction", "qty", "price")
    assert orders == [tuple(o[k] for k in keys) for o in native["orders"]]
    for a, b in zip(closed, native["trades"], strict=True):
        assert a["qty"] * a["dir"] == b["qty"]
        assert all(
            a[k] == b[k]
            for k in ("id", "entryTime", "entryPrice", "exitTime", "exitPrice")
        )
        assert math.isclose(a["profit"], b["profit"], abs_tol=1e-8)
    terminal = None
    if position:
        qty, side, entry = (position[k] for k in ("qty", "side", "entry"))
        terminal = {
            "qty": float(qty),
            "side": side,
            "entry": float(entry),
            "mark": float(close),
            "gross_unrealized": float((close - entry) * qty * side),
            "opening_fee": float(entry * qty * FEE),
        }
    return orders, closed, terminal


def case(engine, scripts, market, chart, annual):
    metadata = {
        "minMove": 1,
        "priceScale": 10 if market == "BTCUSDT" else 100,
        "pointValue": 1,
        "minContract": ".001",
        "quantityStep": ".001",
        "currency": "USDT",
    }
    symbol = f"BINANCE:{market}"
    frames = {"$chart": metadata, f"{symbol}:12M": annual}
    data = [dict(zip(FIELDS, a, strict=True)) for a in chart]
    witness = indicator_witness(chart)
    native = []
    for script in scripts:
        run = engine.run_script(
            script, data, chart_timeframe="60", chart_symbol=symbol, request_bars=frames
        )
        assert not run["strategy"]["diagnostics"]
        assert all(
            d["code"] == "W_LEGACY_SECURITY_LOOKAHEAD" for d in run["diagnostics"]
        )
        plots = {
            line["title"][6:]: line["values"]
            for line in run["plots"]
            if (line.get("title") or "").startswith("audit ")
        }
        for key, values in witness.items():
            for i, (a, b) in enumerate(zip(plots[key], values, strict=True)):
                assert (
                    a is None
                    if b is None
                    else a is not None
                    and math.isclose(a, b, rel_tol=1e-11, abs_tol=1e-9)
                ), (market, key, i, a, b)
        native.append(run["strategy"])
    assert native[0] == native[1] == native[2]
    orders, closed, terminal = settlement(chart, witness["direction"], native[0])
    return {
        "market": market,
        "orders": orders,
        "closed": closed,
        "terminal": terminal,
        "verified_chart_bars": len(chart),
        "signal_values": witness["direction"],
    }


def main(document, first_minutes, latter_minutes, quarters, annual, runner, output):
    assert sha256(runner / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(runner))
    import pine_compat

    scripts = programs(document)
    receipts, cases = [], []
    for market in ("BTCUSDT", "ETHUSDT"):
        finer = [
            *verified_archives(first_minutes, market, "1m", MONTHS[:1], receipts),
            *verified_archives(latter_minutes, market, "1m", MONTHS[1:], receipts),
        ]
        official = verified_archives(quarters, market, "15m", MONTHS, receipts)
        chart = aggregate(prices(official, BEGIN, END, 15 * MINUTE), 4)
        rebuild = aggregate(prices(finer, BEGIN, END, MINUTE), 60)
        assert all(a[:5] == b[:5] for a, b in zip(chart, rebuild, strict=True))
        cases.append(
            case(
                pine_compat,
                scripts,
                market,
                chart,
                annual_frames(annual, market, receipts),
            )
        )
    common = {
        "id": 5646,
        "group": "FMZ Pine v4 · archived oscillator candles",
        "period": "2023-08-26 to 2023-09-25 UTC exclusive",
        "currency": "USDT",
        "interval": "1h, verified 1m opening prints",
        "archive_interval": "1h",
        "pine_source_version": "4",
        "exit": "Authored opposite candle-state market close",
        "order_family": "Same open close then separate market entry",
    }
    results = []
    for selected in ([cases[0]], [cases[1]], cases):
        results.append(
            {
                **common,
                "market": " + ".join(c["market"] for c in selected),
                **ledger_metrics(
                    [t for c in selected for t in c["closed"]],
                    float(CAPITAL) * len(selected),
                    sum(c["terminal"] is not None for c in selected),
                ),
            }
        )
    write(
        output,
        {
            "schema": "FMZ #5646 verified oscillator recurrence, entry gates and causal market ledger",
            "source_url": "https://www.fmz.com/strategy/427922",
            "source_sha256": SOURCE,
            "runtime_sha256": ENGINE_SHA,
            "data_archives": receipts,
            "cases": cases,
            "results": results,
            "notes": {
                "oscillator": "FMZ's documented four-argument stoch accepts high and low series, positioned here as constant 9 and 3. Keeping those values preserves the archived behavior. The compatibility edit casts them to constant-valued series; it does not use an alternate oscillator.",
                "causality": "The archived annual pivot gate is disabled. Literal requests served with official daily aggregates match the disabled-branch witness. Turning off automatic fill callbacks leaves every historical order, closed trade, and equity record identical. All fills use the first minute of the next chart bar.",
                "cost": "The source commission 0.01% per side applies to all orders. No funding, real spread or tick-level priority is modeled. Metrics cover completed lots; cutoff position evidence is separate.",
            },
            "references": [
                "https://www.fmz.com/doc/9293#ta.stoch",
                "https://www.tradingview.com/pine-script-docs/concepts/strategies/",
            ],
            "coverage": [
                [
                    5646,
                    "Tested · verified oscillator recurrence and inactive annual pivot",
                    "Preserved the authored constant stochastic inputs, proved the disabled annual pivot and callback controls leave orders unchanged, and reconciled next opens, cash and fees for BTC/ETH.",
                ]
            ],
        },
    )


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
