"""Verify risk-sized quantities in #5114's archived BTC and ETH window."""

import json
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

BEGIN = date_ms("2023-10-26")
END = date_ms("2023-10-28") + 3 * 3_600_000
SOURCE = "15d9d120b51ab7039426bfb500c6147b69a022b30c9692aede4dc7c550f1c2e2"
FX_SOURCE = "https://api.exchange.coinbase.com/products/USDT-USD/candles?start=2023-10-23T00:00:00Z&end=2023-10-29T00:00:00Z&granularity=86400"
OBSERVE = """
plot(depositExchangeRate, title="audit conversion")
plot(entryBand_high, title="audit prior upper band")
plot(entryBand_low, title="audit prior lower band")
plot(rangeBreakDetected_long ? 1 : 0, title="audit long flags")
plot(rangeBreakDetected_short ? 1 : 0, title="audit short flags")
plot(entryQty, title="audit submitted quantity")
"""


def program(document):
    assert sha256(document) == SOURCE
    fence = chr(96) * 3
    (body,) = re.findall(
        r"(?ms)^" + fence + r" pinescript[^\n]*\n(.*?)^" + fence,
        document.read_text(encoding="utf-8"),
    )
    body, count = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", body)
    assert count == 1 and body.count("_result := na") == 1
    assert "initial_capital=0" in body
    # The typed missing string preserves the inactive USD/USD branch.
    return body.replace("_result := na", "_result := string(na)") + OBSERVE


def conversion(path):
    rate = []
    for stamp, low, high, opening, close, volume in sorted(
        json.loads(path.read_bytes())
    ):
        assert low <= min(opening, close) <= max(opening, close) <= high and volume > 0
        rate.append([stamp * 1000 + DAY, close])
    assert [r[0] for r in rate] == list(
        range(date_ms("2023-10-24"), date_ms("2023-10-31"), DAY)
    )
    return {"schemaVersion": 1, "pairs": [{"from": "USDT", "to": "USD", "rates": rate}]}


def verify(engine, source, market, chart, rates):
    candles = [dict(zip(FIELDS, row, strict=True)) for row in chart]
    settings = {
        "$chart": {
            "minMove": 1,
            "priceScale": 10 if market.startswith("BTC") else 100,
            "minContract": ".001",
            "quantityStep": ".001",
            "pointValue": 1,
            "currency": "USDT",
        },
        "$currencyRates": rates,
    }
    # Explicitly naming the chart symbol checks the semantics of the empty-string lookup.
    current = source.replace(
        "security(depositExchangeSymbolId, timeframe.period, hl2)",
        "security(syminfo.tickerid, timeframe.period, hl2)",
    )
    assert current != source
    results = [
        engine.run_script(
            s,
            candles,
            chart_timeframe="10",
            chart_symbol=f"BINANCE:{market}",
            request_bars=settings,
        )
        for s in (source, current)
    ]
    assert results[0] == results[1]
    result = results[0]
    report = result["strategy"]
    assert not result["diagnostics"] and not report["diagnostics"]
    assert (
        not report["orders"]
        and not report["trades"]
        and report["equity"][-1]["equity"] == 0
    )
    plots = {
        p["title"][6:]: p["values"]
        for p in result["plots"]
        if (p.get("title") or "").startswith("audit ")
    }
    candidates = []
    for i, (stamp, _, high, low, close, _) in enumerate(chart):
        rate = (Decimal(str(high)) + Decimal(str(low))) / 2
        assert math.isclose(float(rate), plots["conversion"][i], abs_tol=1e-10)
        assert plots["submitted quantity"][i] == 0
        if i < 99:
            assert plots["prior upper band"][i] is plots["prior lower band"][i] is None
            assert not plots["long flags"][i] and not plots["short flags"][i]
            continue
        history = [p for bar in chart[i - 99 : i - 2] for p in (bar[1], bar[4])]
        lo, hi = min(history), max(history)
        assert (plots["prior lower band"][i], plots["prior upper band"][i]) == (lo, hi)
        buy, sell = close > hi, close < lo
        assert (plots["long flags"][i], plots["short flags"][i]) == (buy, sell)
        if buy or sell:
            midpoint = (Decimal(str(lo)) + Decimal(str(hi))) / 2
            distance = abs(Decimal(str(close)) - midpoint)
            unfloored = Decimal(100) / (rate * distance)
            assert 0 < unfloored < 1
            candidates.append(
                {
                    "chart_open": stamp,
                    "side": "buy" if buy else "sell",
                    "stop_distance": str(distance),
                    "unfloored_quantity": str(unfloored),
                }
            )
    assert candidates
    return {
        "market": market,
        "chart_bars": len(chart),
        "zero_quantity_signals": candidates,
        "max_unfloored_quantity": max(
            float(t["unfloored_quantity"]) for t in candidates
        ),
    }


def main(document, minute, five_minute, fx, runtime, output):
    assert sha256(runtime / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(runtime))
    import pine_compat

    receipts, cases = [], []
    for market in ("BTCUSDT", "ETHUSDT"):
        minute_files = verified_archives(minute, market, "1m", ("2023-10",), receipts)
        five_files = verified_archives(
            five_minute, market, "5m", ("2023-10",), receipts
        )
        chart = aggregate(prices(minute_files, BEGIN, END, 60_000), 10)
        wrapped = aggregate(prices(five_files, BEGIN, END, 300_000), 2)
        assert all(a[:5] == b[:5] for a, b in zip(chart, wrapped, strict=True))
        cases.append(
            verify(pine_compat, program(document), market, chart, conversion(fx))
        )
    info = {
        "id": 5114,
        "group": "FMZ Pine v4 · archived zero order sizes",
        "period": "2023-10-26 to 2023-10-28 03:00 UTC exclusive",
        "currency": "USD",
        "interval": "10m from 1m",
        "archive_interval": "10m",
        "pine_source_version": "4",
        "order_family": "Price breakout stop and midpoint protective stop",
        "exit": "No admitted entries at the archived sizing",
    }
    write(
        output,
        {
            "schema": "FMZ #5114 source-derived zero quantities and archived window",
            "source_sha256": SOURCE,
            "runtime_sha256": ENGINE_SHA,
            "source_url": "https://www.fmz.com/strategy/430975",
            "crypto_receipts": receipts,
            "broker_currency_feed": {"url": FX_SOURCE, "sha256": sha256(fx)},
            "market_symbol_reference": "https://www.tradingview.com/pine-script-docs/concepts/inputs/",
            "notes": "The archived USD strategy uses a USDT-quoted chart, absent from its conversion map. In Pine an empty security symbol resolves to the current chart, so the source obtains the chart's hl2 as its apparent currency rate. The explicit-symbol control exactly matches. Coinbase prior-day USDT/USD close is passed only to the broker's accounting, never into the author's sizing call. The independent 100-bar opening/closing price bands reproduce every breakout and prove every risk quantity floors to zero. No valid orders or realized trades occur, with the source's zero starting equity. There is no meaningful sample win rate or drawdown percentage.",
            "cases": cases,
            "results": [
                {**info, "market": m, **ledger_metrics([], 0, 0)}
                for m in ("BTCUSDT", "ETHUSDT", "BTCUSDT + ETHUSDT")
            ],
            "coverage": [
                [
                    5114,
                    "Tested · archived risk sizing yields zero quantities",
                    "Independently verified actual breakout windows and the source's empty-symbol current-chart rate on BTC and ETH. Every archived quantity floors to zero. No positions are opened or closed.",
                ]
            ],
        },
    )


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
