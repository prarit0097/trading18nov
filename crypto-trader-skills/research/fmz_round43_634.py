"""Compare the OCC source's delayed and repainting 3h projections."""

import math
import re
import sys
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

SOURCE = "86b328335671e8a4849404f51989b94fd385feb587f3080df4411e5f4892498b"
BEGIN, NEXT_DAY = map(date_ms, ("2022-04-15", "2022-05-15"))
HOUR = 3_600_000
CUTOFF = NEXT_DAY - 60_000
END = NEXT_DAY - HOUR
MONTHS = ("2022-04", "2022-05")
CAPITAL = 1_000_000
FEE = 0.00075
OBSERVE = """
plot(state_occ == "Long" ? 1 : 0, title="Audit Long")
plot(state_occ == "Short" ? 1 : 0, title="Audit Short")
plot(tdays, title="Audit elapsed hours")
"""


def sources(document):
    assert sha256(document) == SOURCE
    fence = chr(96) * 3
    (body,) = re.findall(
        r"(?ms)^" + fence + r" pinescript[^\n]*\n(.*?)^" + fence,
        document.read_text(encoding="utf-8"),
    )
    baseline, count = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", body)
    assert count == 1 and baseline.count("strategy.entry(") == 2
    declaration = "indicator(title='Strategy R5.1 fix'"
    default = "delayOffset = input.int(defval=0"
    assert baseline.count(declaration) == baseline.count(default) == 1
    saved = (
        baseline.replace(declaration, "strategy(title='Strategy R5.1 fix'") + OBSERVE
    )
    return saved, saved.replace(default, "delayOffset = input.int(defval=1")


def smma(values, delay):
    seed, output = [], []
    state = None
    for i in range(len(values)):
        if i >= delay:
            value = values[i - delay]
            if state is None:
                seed.append(value)
                if len(seed) == 8:
                    state = math.fsum(seed) / 8
            else:
                state = (state * 7 + value) / 8
        output.append(state)
    return output


def signals(three_hours, hourly, delay):
    opening = smma([p[1] for p in three_hours], delay)
    closing = smma([p[4] for p in three_hours], delay)
    lines = [(opening[i // 3], closing[i // 3]) for i in range(len(hourly))]
    elapsed = [(CUTOFF - r[0]) / HOUR for r in hourly]
    direction, prior = [], None
    for (o, c), t in zip(lines, elapsed, strict=True):
        delta = None if o is None else c - o
        if prior is None or delta is None or t > 10000:
            signal = 0
        elif prior <= 0 < delta:
            signal = 1
        elif prior >= 0 > delta:
            signal = -1
        else:
            signal = 0
        direction.append(signal)
        prior = delta
    return lines, elapsed, direction


def executions(hourly, direction, broker):
    holding = 0
    entry = stamp = None
    trades, fills = [], []
    cash = CAPITAL
    for i, (time, opening, _, _, close, _) in enumerate(hourly):
        if i and direction[i - 1] and direction[i - 1] != holding:
            new = direction[i - 1]
            if holding:
                cost = (entry + opening) * FEE
                gross = (opening - entry) * holding
                trades.append(
                    {
                        "entryTime": stamp,
                        "exitTime": time,
                        "dir": holding,
                        "qty": 1,
                        "entryPrice": entry,
                        "exitPrice": opening,
                        "commission": cost,
                        "profit": gross - cost,
                    }
                )
            name = "Long" if new == 1 else "Short"
            fills.append(
                (
                    f"Enter {name}",
                    i,
                    time,
                    f"strategy.{name.lower()}",
                    abs(new - holding),
                    opening,
                )
            )
            cash -= (new - holding) * opening
            holding, stamp, entry = new, time, opening
        balance = broker["equity"][i]
        assert balance["barIndex"] == i
        assert math.isclose(balance["cash"], cash, rel_tol=0, abs_tol=1e-7)
        assert math.isclose(
            balance["marketValue"], holding * close, rel_tol=0, abs_tol=1e-7
        )
    fields = ("id", "barIndex", "time", "direction", "qty", "price")
    assert fills == [tuple(x[k] for k in fields) for x in broker["orders"]]
    for a, b in zip(trades, broker["trades"], strict=True):
        assert a["dir"] == b["qty"]
        assert all(
            a[key] == b[key]
            for key in ("entryTime", "exitTime", "entryPrice", "exitPrice")
        )
        assert math.isclose(a["profit"] + a["commission"], b["profit"], abs_tol=1e-8)
    assert holding and broker["position"][-1]["size"] == holding
    return (
        fills,
        trades,
        {
            "side": holding,
            "qty": 1,
            "entry": entry,
            "mark": close,
            "unrealized_gross": holding * (close - entry),
            "modeled_opening_fee": entry * FEE,
        },
    )


def checked(engine, source, market, hourly, three_hours, delay):
    ticker = f"BINANCE:{market}"
    data = [dict(zip(FIELDS, a, strict=True)) for a in hourly]
    frames = {
        f"{ticker}:180": [dict(zip(FIELDS, c, strict=True)) for c in three_hours],
        "$chart": {
            "minMove": 1,
            "priceScale": 10 if market == "BTCUSDT" else 100,
            "minContract": ".001",
            "quantityStep": ".001",
            "pointValue": 1,
            "currency": "USDT",
        },
    }
    params = {"chart_timeframe": "60", "chart_symbol": ticker, "request_bars": frames}
    actual = engine.run_script(
        source, data, execution_times=[CUTOFF] * len(data), **params
    )
    fixed = engine.run_script(source.replace("timenow", str(CUTOFF)), data, **params)
    assert actual == fixed
    assert not actual["diagnostics"] and not actual["strategy"]["diagnostics"]
    lines, elapsed, direction = signals(three_hours, hourly, delay)
    plots = {x.get("title"): x.get("values") for x in actual["plots"]}
    for (a, b), (c, d) in zip(
        lines,
        zip(plots["Open Series"], plots["Close Series"], strict=True),
        strict=True,
    ):
        assert c is None if a is None else math.isclose(a, c, abs_tol=1e-9)
        assert d is None if b is None else math.isclose(b, d, abs_tol=1e-9)
    assert plots["Audit Long"] == [d == 1 for d in direction]
    assert plots["Audit Short"] == [d == -1 for d in direction]
    assert all(
        math.isclose(a, b)
        for a, b in zip(plots["Audit elapsed hours"], elapsed, strict=True)
    )
    return actual["strategy"], lines, direction


def check(engine, programs, market, quarter, hour, receipts):
    [q, h] = [
        verified_archives(folder, market, interval, MONTHS, receipts)
        for folder, interval in ((quarter, "15m"), (hour, "1h"))
    ]
    quarters = prices(q, BEGIN, END, HOUR // 4)
    hourly = prices(h, BEGIN, END, HOUR)
    assert all(
        a[:5] == b[:5] for a, b in zip(hourly, aggregate(quarters, 4), strict=True)
    )
    remainder = len(quarters) % 12
    assert remainder == 8
    three_hours = aggregate(quarters[:-remainder], 12) + aggregate(
        quarters[-remainder:], remainder
    )
    saved, saved_lines, saved_direction = checked(
        engine, programs[0], market, hourly, three_hours, 0
    )
    delayed, delayed_lines, delayed_direction = checked(
        engine, programs[1], market, hourly, three_hours, 1
    )
    assert delayed_lines[3:] == saved_lines[:-3]
    # Source uses lookahead for both. The delayed input only exposes the completed previous block.
    assert all(
        three_hours[i // 3 - 1][0] + 3 * HOUR <= bar[0]
        for i, bar in enumerate(hourly)
        if delayed_lines[i][0] is not None
    )
    differing = sum(
        a != b for a, b in zip(saved_direction, delayed_direction, strict=True)
    )
    assert differing and saved["orders"] != delayed["orders"]
    orders, closed, terminal = executions(hourly, delayed_direction, delayed)
    return {
        "market": market,
        "verified_complete_hourly_bars": len(hourly),
        "orders": orders,
        "trades": closed,
        "terminal": terminal,
        "changed_alert_bars_vs_saved_default": differing,
        "saved_diagnostic_entry_count": len(saved["orders"]),
        "first_confirmed_3h_value_stamp": next(
            hourly[i][0] for i, line in enumerate(delayed_lines) if line[0] is not None
        ),
    }


def main(document, quarter, hour, runtime, output):
    assert sha256(runtime / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(runtime))
    import pine_compat

    programs = sources(document)
    receipts = []
    cases = [
        check(pine_compat, programs, market, quarter, hour, receipts)
        for market in ("BTCUSDT", "ETHUSDT")
    ]
    common = {
        "id": 634,
        "group": "FMZ OCC · authored non-repainting 3h delay",
        "period": "2022-04-15 to 2022-05-14 23:59 UTC",
        "interval": "1h with previous confirmed 3h block",
        "archive_interval": "1h",
        "currency": "USDT",
        "pine_source_version": "5",
        "order_family": "Fixed-unit next-open entries and reversals",
        "exit": "Opposite smoothed opening and closing series crossover",
    }
    results = []
    for pair in ([cases[0]], [cases[1]], cases):
        results.append(
            {
                **common,
                "market": " + ".join(c["market"] for c in pair),
                **ledger_metrics(
                    [t for c in pair for t in c["trades"]],
                    CAPITAL * len(pair),
                    len(pair),
                ),
            }
        )
    write(
        output,
        {
            "schema": "FMZ #634 authored non-repainting input and verified cash ledger",
            "source_sha256": SOURCE,
            "runtime_sha256": ENGINE_SHA,
            "source_url": "https://www.fmz.com/strategy/363572",
            "market_receipts": receipts,
            "pine_reference": "https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/#lookahead",
            "cutoff": CUTOFF,
            "cases": cases,
            "results": results,
            "notes": "The archive starts with indicator() but submits strategy.entry calls. The compatibility change activates a strategy declaration and preserves the source orders. The author labels delayOffset as the non-repainting option. We verify that option at 1 and document the saved 0 as a future-informed diagnostic. Every plotted SMMA value, decision, order and cash state for the delayed configuration matches an independent calculation. The final hourly candle is still open at the archived 23:59 cutoff and is excluded. Source default exposure is one unit per market. The cost comparison applies 0.075% fee per side without modeling funding, spread or observed queue placement.",
            "coverage": [
                [
                    634,
                    "Tested · verified author delay option and causal 3h confirmation",
                    "Switches the authored delay to one previous completed 3h observation. BTC/ETH SMMA and next opens reconcile. The saved zero-delay results remain a future-price diagnostic.",
                ]
            ],
        },
    )


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
