"""Verify the archived EUR/USD Fibonacci gates on daily BTC and ETH."""

import csv
import gzip
import math
import re
import sys
from bisect import bisect_left
from datetime import datetime
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
from research.fmz_round18_5745 import DAY, ENGINE_SHA, FIELDS
from research.fmz_round21_1988 import rsi14
from research.fmz_round26_977 import prices

SOURCE = "d073afc8d4f0b9b7ef8ae2997135f3b38ebb423fb916372b924c387826111879"
BEGIN, END = map(date_ms, ("2023-01-10", "2024-01-16"))
MONTHS = tuple(f"2023-{i:02d}" for i in range(1, 13)) + ("2024-01",)
WEEKS = [(2023, i) for i in range(2, 54)] + [(2024, 2), (2024, 3)]
MINUTE = 60_000
FX_MINUTES = 5
FEE = 0.00075
CAPITAL = 1_000_000
ECB = "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?startPeriod=2023-07-03&endPeriod=2023-07-07&format=csvdata"
OBSERVE = """
plot(high_price, title="Selected high")
plot(low_price, title="Selected low")
plot(rsi, title="Derived RSI")
plot(longCondition ? 1 : 0, title="Long flag")
plot(shortCondition ? 1 : 0, title="Short flag")
"""


def program(document):
    assert sha256(document) == SOURCE
    fence = chr(96) * 3
    (body,) = re.findall(
        r"(?ms)^" + fence + r" pinescript[^\n]*\n(.*?)^" + fence,
        document.read_text(encoding="utf-8"),
    )
    body, count = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", body)
    assert count == 1 and body.count('request.security("FX:EURUSD", "5",') == 2
    return body + OBSERVE


def fx_candles(folder):
    """Build reported bid candles and capture the full bid/ask price envelope."""
    receipts, chart = [], {}
    prior_stamp = 0
    minimum, maximum = math.inf, 0
    for year, week in WEEKS:
        p = folder / f"{year}-{week}.csv.gz"
        count = 0
        with gzip.open(p, "rt", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                when = row["DateTime"]
                dt = datetime.fromisoformat(
                    f"{when[6:10]}-{when[:2]}-{when[3:5]}T{when[11:]}+00:00"
                )
                stamp = int(dt.timestamp()) * 1000
                assert stamp % MINUTE == 0 and stamp > prior_stamp
                prior_stamp = stamp
                values = [
                    float(row[side + part])
                    for side in ("Bid", "Ask")
                    for part in ("Open", "High", "Low", "Close")
                ]
                opening, high, low, close = values[:4]
                assert 0 < low <= min(opening, close) <= max(opening, close) <= high
                minimum, maximum = min(minimum, *values), max(maximum, *values)
                anchor = stamp // (FX_MINUTES * MINUTE) * (FX_MINUTES * MINUTE)
                if anchor not in chart:
                    chart[anchor] = [anchor, opening, high, low, close, 0]
                else:
                    old = chart[anchor]
                    old[2], old[3], old[4] = max(high, old[2]), min(low, old[3]), close
                count += 1
        assert (count == 0) if (year, week) == (2023, 27) else (count > 1000)
        receipts.append(
            {
                "url": f"https://candledata.fxcorporate.com/m1/EURUSD/{year}/{week}.csv.gz",
                "sha256": sha256(p),
                "minute_rows": count,
            }
        )
    return receipts, list(chart.values()), (minimum, maximum)


def gap_reference(path, envelope):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        values = {
            row["TIME_PERIOD"]: float(row["OBS_VALUE"])
            for row in csv.DictReader(handle)
        }
    assert set(values) == {f"2023-07-{day:02d}" for day in range(3, 8)}
    assert all(envelope[0] <= x <= envelope[1] for x in values.values())
    return {"url": ECB, "sha256": sha256(path), "reference_rates": values}


def independent(chart, fx):
    stamps = [x[0] for x in fx]
    indices = [bisect_left(stamps, t + DAY) - 1 for t, *_ in chart]
    assert indices[0] >= 0
    selected = [fx[i] for i in indices]
    assert all(
        x[0] + FX_MINUTES * MINUTE <= y[0] + DAY
        for x, y in zip(selected, chart, strict=True)
    )
    quote = [(x[2], x[3]) for x in selected]
    strengths = rsi14([x[4] for x in chart])
    buy = [False]
    sell = [False]
    for i, (prior, now) in enumerate(pairwise(strengths), 1):
        high, low = quote[i]
        fib = low + 0.618 * (high - low)
        buy.append(prior is not None and prior <= 30 < now and chart[i][4] > fib)
        sell.append(prior is not None and prior >= 70 > now and chart[i][4] < fib)
    assert not any(sell)
    return quote, strengths, buy, sell


def check(native, source, market, chart, fx):
    quote, strengths, buy, sell = independent(chart, fx)
    candles = [dict(zip(FIELDS, x, strict=True)) for x in chart]
    keys = {
        "FX:EURUSD:5": [dict(zip(FIELDS, x, strict=True)) for x in fx],
        "$chart": {
            "minMove": 1,
            "priceScale": 10 if market == "BTCUSDT" else 100,
            "minContract": ".001",
            "quantityStep": ".001",
            "pointValue": 1,
            "currency": "USDT",
        },
    }
    result = native.run_script(
        source,
        candles,
        chart_timeframe="1D",
        chart_symbol=f"BINANCE:{market}",
        request_bars=keys,
    )
    strategy = result["strategy"]
    assert not result["diagnostics"] and not strategy["diagnostics"]
    lines = {x.get("title"): x.get("values") for x in result["plots"]}
    assert (
        list(zip(lines["Selected high"], lines["Selected low"], strict=True)) == quote
    )
    assert lines["Long flag"] == buy and lines["Short flag"] == sell
    assert all(
        (b is None if a is None else math.isclose(a, b, abs_tol=1e-10))
        for a, b in zip(strengths, lines["Derived RSI"], strict=True)
    )
    assert not strategy["trades"]
    first = buy.index(True)
    stamp, price, *_ = chart[first + 1]
    [entry] = strategy["orders"]
    assert (entry["id"], entry["time"], entry["price"], entry["qty"]) == (
        "Buy",
        stamp,
        price,
        1,
    )
    assert strategy["position"][-1]["size"] == 1
    mark = chart[-1][4]
    return {
        "market": market,
        "base_days": len(chart),
        "rsi": strengths,
        "entry_signal_days": [b[0] for b, flag in zip(chart, buy, strict=True) if flag],
        "entry_time": stamp,
        "entry_price": price,
        "terminal_mark": mark,
        "terminal_unrealized_pnl": mark - price,
        "terminal_modeled_entry_fee": price * FEE,
    }


def main(document, fx_folder, binance, runtime, output):
    assert sha256(runtime / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(runtime))
    import pine_compat

    receipts, fx, envelope = fx_candles(fx_folder)
    ecb = gap_reference(fx_folder / "ecb-july.csv", envelope)
    source = program(document)
    markets, cases = [], []
    for market in ("BTCUSDT", "ETHUSDT"):
        days = verified_archives(binance, market, "1d", MONTHS, markets)
        halves = verified_archives(binance, market, "30m", MONTHS, markets)
        chart = prices(days, BEGIN, END, DAY)
        period = aggregate(prices(halves, BEGIN, END, 30 * MINUTE), 48)
        assert all(x[:5] == y[:5] for x, y in zip(chart, period, strict=True))
        assert min(x[3] for x in chart) > 2 * envelope[1]
        cases.append(check(pine_compat, source, market, chart, fx))
    info = {
        "id": 2833,
        "group": "FMZ Pine v5 · FXCM EUR/USD Fibonacci gate",
        "period": "2023-01-10 to 2024-01-16 UTC exclusive",
        "currency": "USDT",
        "interval": "1d with 5m FXCM",
        "archive_interval": "1d",
        "pine_source_version": "5",
        "exit": "Authored short reversal on RSI and FX threshold",
        "order_family": "Next-open market entry or reversal",
    }
    results = [
        {**info, "market": market, **ledger_metrics([], CAPITAL * count, count)}
        for market, count in (("BTCUSDT", 1), ("ETHUSDT", 1), ("BTCUSDT + ETHUSDT", 2))
    ]
    write(
        output,
        {
            "schema": "FMZ #2833 FXCM lower-timeframe gate proof",
            "source_sha256": SOURCE,
            "source_url": "https://www.fmz.com/strategy/439097",
            "engine_sha256": ENGINE_SHA,
            "fx_source": "https://github.com/fxcm/MarketData/tree/master/CandleData",
            "fx_symbol": "https://www.tradingview.com/symbols/EURUSD/?exchange=FX",
            "fx_receipts": receipts,
            "gap_check": ecb,
            "binance_receipts": markets,
            "fx_5m_bars": len(fx),
            "full_fx_bid_ask_range": envelope,
            "cases": cases,
            "results": results,
            "method": "The real FXCM bid feed selects the last available completed 5m bar under the source's default gaps-off request, carrying it through gaps. The public July 3–7, 2023 file has no observations. The independently published ECB daily reference rates for that week remain inside the observed FXCM bid/ask envelope. Even doubling the entire envelope leaves it below the cheapest crypto candle; the 0.618 retracement cannot change the order gates within that range. ECB is only a price-scale check and no replacement intraday bars are inserted. The authored short reversal never fires. The first valid RSI long crossing enters once on each market. No exit or cutoff liquidation is added. Realized P&L, fees and realized drawdown reflect zero closed lots. Open positions and modeled entry fees are recorded separately.",
            "coverage": [
                [
                    2833,
                    "Tested · verified FXCM input and no feasible short gate",
                    "Actual FXCM 5m prices and independent RSI gates match the archived daily replay. Both markets enter one long and never meet the authored short reversal. No completed-trade win rate is available.",
                ]
            ],
        },
    )


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
