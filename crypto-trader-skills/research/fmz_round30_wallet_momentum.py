"""Verify active legacy momentum orders separately from the archived display code."""

import json
import math
import re
import sys
from collections import deque
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
from research.fmz_round18_5745 import ENGINE_SHA, FIELDS
from research.fmz_round26_977 import prices

DAY, MINUTE = 86_400_000, 60_000
CAPITAL = 662
STEP, FEE = Decimal(".001"), Decimal(".00075")
FX_ROOT = (
    "https://api.exchange.coinbase.com/products/USDT-USD/candles?granularity=86400"
)
SOURCES = {
    2521: "bc1df3940fc82cce2a44f7551f3e427503534d71231b6db7d34107585db9a61e",
    4648: "2919f38cd85ee35c7992262c77188b82aca0eabce83a02446b753e89b643dd7f",
}
FX_FILES = {
    2521: (
        "USDTUSD-2023-10-12.json",
        "2023-10-04",
        "2023-12-10",
        "afbe21de3e75daf76033514035569fc77f4958a11c4afe83c6aa7ccd04a2e807",
    ),
    4648: (
        "USDTUSD-2023-02-11.json",
        "2023-02-28",
        "2023-11-04",
        "c15c93f9a9f607444fd95aec22988e5ac589caf5206cdb2d9a47bcc00fadfbfd",
    ),
}


def programs(engine, document, ident):
    assert sha256(document) == SOURCES[ident]
    fence = chr(96) * 3
    (archived,) = re.findall(
        r"(?ms)^" + fence + r"[^\n]*\n(.*?)^" + fence,
        document.read_text(encoding="utf-8"),
    )
    body, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", archived)
    assert n == 1
    active, report = body.split("strategy.initial_capital = 50000")
    report_code = [
        line.strip()
        for line in report.splitlines()
        if line.strip() and not line.lstrip().startswith("//")
    ]
    assert (
        len(report_code) == 2
        and report_code[0].startswith("plot(strategy.equity-")
        and report_code[1] == "hline(0)"
    )
    assert (
        active.count("strategy.entry(") == 2 and active.count("strategy.cancel(") == 2
    )
    assert 'default_qty_value = 100,currency="USD",initial_capital=662' in active
    assert active.count("sum = 0\n") == 1
    try:
        engine.compile_script(active)
    except ValueError as error:
        assert "E_ASSIGN_TYPE" in str(error) and "assign series float to " in str(error)
    else:
        raise AssertionError("Expected scalar accumulator type check")
    return (
        active.replace("sum = 0\n", "sum = 0.0\n")
        + '\nplot(sum,title="Momentum sum")\n'
    )


def fx_data(directory, ident, lo, hi):
    name, start, end, digest = FX_FILES[ident]
    doc = directory / name
    assert sha256(doc) == digest
    values = {
        t * 1000 + DAY: Decimal(str(close))
        for t, _, _, _, close, _ in json.loads(doc.read_bytes())
        if lo - DAY <= t * 1000 < hi - DAY
    }
    assert sorted(values) == list(range(lo, hi, DAY))
    url = f"{FX_ROOT}&start={start}T00%3A00%3A00Z&end={end}T00%3A00%3A00Z"
    return values, {"url": url, "sha256": digest}


def decimal_price(value):
    return Decimal(str(value))


def observe(engine, source, chart, rates, market, frame):
    pairs = [
        {
            "from": "USDT",
            "to": "USD",
            "rates": [
                {"effectiveTime": t, "rate": float(rate)}
                for t, rate in sorted(rates.items())
            ],
        }
    ]
    meta = {
        "minMove": 1,
        "priceScale": 10 if market == "BTCUSDT" else 100,
        "quantityStep": ".001",
        "minContract": ".001",
        "pointValue": 1,
        "currency": "USDT",
    }
    observed = engine.run_script(
        source,
        chart,
        chart_symbol=f"BINANCE:{market}",
        chart_timeframe=frame,
        request_bars={
            "$chart": meta,
            "$currencyRates": {"schemaVersion": 1, "pairs": pairs},
        },
    )
    assert not observed["diagnostics"] and not observed["strategy"]["diagnostics"]
    return next(
        plot["values"]
        for plot in observed["plots"]
        if plot.get("title") == "Momentum sum"
    ), observed["strategy"]


def broker(chart, children, span, rates, active_from, ids, watched, measured):
    balance = Decimal(CAPITAL)
    current = desired = None
    history, drift = deque(maxlen=170), deque(maxlen=19)
    fills, lots = iter(measured["orders"]), iter(measured["trades"])
    closed = []
    for i, bar in enumerate(chart):
        stamp = bar["time"]
        opening, close = map(decimal_price, (bar["open"], bar["close"]))
        rate = rates[stamp // DAY * DAY]
        if desired and (current is None or current[0] != desired):
            transfer = Decimal(0)
            if current is not None:
                side, qty, entry, entry_rate, j = current
                gain = (opening - entry) * qty * side * rate
                balance += gain
                native = next(lots)
                assert (native["entryBarIndex"], native["exitBarIndex"]) == (j, i)
                assert (native["entryPrice"], native["exitPrice"], native["qty"]) == (
                    float(entry),
                    float(opening),
                    float(qty) * side,
                )
                assert math.isclose(float(gain), native["profit"], abs_tol=1e-7)
                assessed_fee = (entry * entry_rate + opening * rate) * qty * FEE
                closed.append(
                    {
                        "entryTime": chart[j]["time"],
                        "exitTime": stamp,
                        "dir": side,
                        "qty": float(qty),
                        "entryPrice": float(entry * rate),
                        "exitPrice": float(opening * rate),
                        "commission": float(assessed_fee),
                        "profit": float(gain - assessed_fee),
                    }
                )
                transfer = qty
            qty = balance / (opening * rate) // STEP * STEP
            assert (
                qty >= STEP
                and children[i * span][5] > 0
                and children[i * span][1] == bar["open"]
            )
            trade = next(fills)
            assert (trade["id"], trade["barIndex"], trade["time"], trade["price"]) == (
                ids[desired],
                i,
                stamp,
                float(opening),
            )
            assert math.isclose(trade["qty"], float(transfer + qty), abs_tol=1e-10)
            current = desired, qty, opening, rate, i
        history.append(bar["close"])
        if len(history) == 170:
            drift.append(bar["close"] - math.fsum(history) / 170)
        score = math.fsum(drift) if len(drift) == 19 else None
        known = watched[i]
        assert (
            (known is None)
            if score is None
            else math.isclose(score, known, abs_tol=1e-7)
        )
        desired = (
            (1 if score > 0 else -1 if score < 0 else 0)
            if score is not None and stamp >= active_from
            else None
        )
        floating = (
            (close - current[2]) * current[1] * current[0] * rate
            if current
            else Decimal(0)
        )
        assert math.isclose(
            float(balance + floating), measured["equity"][i]["equity"], abs_tol=1e-6
        )
    assert next(fills, None) is None and next(lots, None) is None
    return closed, current is not None


def portfolio_rows(ident, scopes, period, interval):
    if ident == 2521:
        assert tuple(len(x["trades"]) for x in scopes) == (98, 96)
    for market, books in (
        ("BTCUSDT", scopes[:1]),
        ("ETHUSDT", scopes[1:]),
        ("BTCUSDT + ETHUSDT", scopes),
    ):
        yield {
            "id": ident,
            "group": "FMZ Pine v2 · USD momentum-integrator reversals",
            "period": period,
            "market": market,
            "exit": "Opposite closed-bar momentum sum, next open",
            "archive_interval": interval,
            "interval": interval,
            "pine_source_version": "2",
            "currency": "USD",
            **ledger_metrics(
                [t for b in books for t in b["trades"]],
                CAPITAL * len(books),
                sum(b["ending_open"] for b in books),
            ),
        }


def run(scratch, minute_dir, hourly_dir, runtime, output):
    assert sha256(runtime / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(runtime))
    import pine_compat

    answers, witness, archives, receipts = [], [], [], {}
    for ident in (2521, 4648):
        source = programs(pine_compat, scratch / f"{ident}.md", ident)
        configs = (
            [
                (
                    "2023-12-03",
                    "2023-12-03",
                    "2023-12-10",
                    "1m",
                    "1",
                    minute_dir,
                    ("2023-12",),
                    MINUTE,
                    1,
                )
            ]
            if ident == 2521
            else [
                (
                    "2023-10-06",
                    "2023-10-06",
                    "2023-11-05",
                    "1d",
                    "D",
                    hourly_dir,
                    ("2023-10", "2023-11"),
                    60 * MINUTE,
                    24,
                ),
                (
                    "2023-03-01",
                    "2023-10-06",
                    "2023-11-05",
                    "1d",
                    "D",
                    hourly_dir,
                    tuple(f"2023-{m:02}" for m in range(3, 12)),
                    60 * MINUTE,
                    24,
                ),
            ]
        )
        ids = (
            {1: "BBandLE", -1: "BBandSE"} if ident == 2521 else {1: "Long", -1: "Short"}
        )
        for lo, start, hi, interval, frame, directory, months, step, span in configs:
            rates, receipts[ident] = fx_data(scratch, ident, date_ms(lo), date_ms(hi))
            context = source
            if lo != start:
                context = source.replace(
                    "if sum>0", "if sum>0 and time >= timestamp(2023,10,6,0,0)"
                ).replace("if sum<0", "if sum<0 and time >= timestamp(2023,10,6,0,0)")
                assert context.count("time >= timestamp") == 2
            cases = []
            for market in ("BTCUSDT", "ETHUSDT"):
                paths = verified_archives(
                    directory, market, "1m" if span == 1 else "1h", months, archives
                )
                base = prices(paths, date_ms(lo), date_ms(hi), step)
                chart = [
                    dict(zip(FIELDS, bar, strict=True)) for bar in aggregate(base, span)
                ]
                scores, result = observe(
                    pine_compat, context, chart, rates, market, frame
                )
                trades, held = broker(
                    chart, base, span, rates, date_ms(start), ids, scores, result
                )
                cases.append(
                    {
                        "id": ident,
                        "market": market,
                        "warmup_start": lo,
                        "first_eligible": start,
                        "end": hi,
                        "candles": len(chart),
                        "trades": trades,
                        "ending_open": held,
                    }
                )
            if ident == 4648 and lo == start:
                assert all(not r["trades"] and not r["ending_open"] for r in cases)
            label = "Warm-up sensitivity" if lo != start else "Saved window"
            period = f"{label} · Binance USD-M · {start} to {hi} UTC exclusive"
            answers.extend(portfolio_rows(ident, cases, period, interval))
            witness.extend(cases)
    write(
        output,
        {
            "schema": "FMZ 2521 and 4648 · Legacy momentum sums in the saved market windows",
            "source_documents": SOURCES,
            "engine_sha256": ENGINE_SHA,
            "currency_inputs": receipts,
            "candle_archives": list({a["url"]: a for a in archives}.values()),
            "notes": {
                "source": "Both sources declare USD 662 and 100% equity sizing. The conflicting USD 50,000 assignment occurs after the order logic and feeds a display-only equity plot. The replay isolates the display tail and initializes the accumulator with floating zero to preserve the rolling sum of prices.",
                "warmup": "Native #4648 saved length is 30 daily bars. The first usable score needs 188 price bars. The second #4648 run uses March 1 onward as read-only warm-up and permits orders from the saved October 6 start. Both modes retain the original cutoff.",
                "fills": "Next open of the official first base candle. The independent oracle matches native decision values, reversal quantities, every gross close and candle mark. Previous completed Coinbase daily close converts USDT to USD.",
                "costs": "Source commission is unspecified. A 0.075% per-side overlay values fees at each fill day's causal rate. Sizing follows the original replay before the overlay. Funding, spread and margin are outside this model.",
            },
            "coverage": [
                [
                    2521,
                    "Tested · Legacy momentum sum and causal USD sizing",
                    "Saved one-minute BTC and matched ETH with 194 independently verified closed lots. The display suffix is isolated and active sizing retains the authored USD 662.",
                ],
                [
                    4648,
                    "Tested · Saved daily window and warm-up sensitivity",
                    "The 30-bar archived window is too short for the authored 188-bar lookback. An additional verified read-only warm-up uses the same market dates and order rules.",
                ],
            ],
            "results": answers,
            "scopes": witness,
        },
    )


if __name__ == "__main__":
    run(*map(Path, sys.argv[1:]))
