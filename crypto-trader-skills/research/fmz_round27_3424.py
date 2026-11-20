"""Replay FMZ #3424 using timestamped NSE index closes and Binance futures."""

import csv
import math
import re
import sys
from bisect import bisect_right
from datetime import date
from pathlib import Path

from research.fmz_round7_magnifier import (
    date_ms,
    ledger_metrics,
    sha256,
    verified_archives,
    write,
)
from research.fmz_round18_5745 import ENGINE_SHA, FIELDS
from research.fmz_round26_977 import prices

ID = 3424
SOURCE_SHA = "685bce14abe595714d669e73c56964ae37e7a5a2ea9730681875fe42486d8fc1"
HOUR = 3_600_000
BEGIN, END = map(date_ms, ("2024-01-01", "2024-01-24"))
WARM = BEGIN - 48 * HOUR
MONTHS = ("2023-12", "2024-01")
JANUARY_SESSIONS = (1, 2, 3, 4, 5, 8, 9, 10, 11, 12, 15, 16, 17, 18, 19, 20, 23)
SESSIONS = (date(2023, 12, 29), *(date(2024, 1, d) for d in JANUARY_SESSIONS))
NSE = "https://archives.nseindia.com/content/indices"
FEE = 0.00075
CAPITAL = 1_000_000
PROBES = '\nplot(buySignal?1:0,title="Authored buy")\nplot(sellSignal?1:0,title="Authored sell")\n'


def index_values(directory):
    observations = []
    manifest = []
    for day in SESSIONS:
        filename = f"ind_close_all_{day:%d%m%Y}.csv"
        document = directory / f"{day}.csv"
        with document.open(newline="", encoding="utf-8-sig") as stream:
            (index,) = (
                r for r in csv.DictReader(stream) if r["Index Name"] == "Nifty 50"
            )
        assert index["Index Date"] == day.strftime("%d-%m-%Y")
        close = float(index["Closing Index Value"])
        assert (
            float(index["Low Index Value"]) <= close <= float(index["High Index Value"])
        )
        observations.append((date_ms(day.isoformat()), close))
        manifest.append(
            {
                "session": day.isoformat(),
                "url": f"{NSE}/{filename}",
                "sha256": sha256(document),
            }
        )
    return observations, manifest


def compile_source(document):
    assert sha256(document) == SOURCE_SHA
    fence = chr(96) * 3
    (archive,) = re.findall(
        r"(?ms)^" + fence + r"[^\n]*\n(.*?)^" + fence,
        document.read_text(encoding="utf-8"),
    )
    original, count = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", archive)
    assert count == 1
    source = original
    changes = (
        (
            'request.security(niftySymbol, "D", close)',
            'request.security(niftySymbol, "60", close)',
        ),
        ("when=buySignal", "when=buySignal and time >= timestamp(2024,1,1,0,0)"),
        ("when=sellSignal", "when=sellSignal and time >= timestamp(2024,1,1,0,0)"),
    )
    for old, new in changes:
        assert source.count(old) == 1
        source = source.replace(old, new)
    return source


def objects(rows):
    return [dict(zip(FIELDS, x, strict=True)) for x in rows]


def run_scope(engine, source, market, chart, children, observations, delay):
    available = [d + delay * HOUR for d, _ in observations]
    keys = [bisect_right(available, x["time"] + HOUR) - 1 for x in chart]
    assert min(keys) >= 0
    closes = [observations[i][1] for i in keys]
    projected = objects(
        (x["time"], c, c, c, c, 0) for x, c in zip(chart, closes, strict=True)
    )
    options = {
        "chart_symbol": f"BINANCE:{market}",
        "chart_timeframe": "60",
        "request_bars": {"NIFTY50:60": projected},
    }
    trace = engine.run_script(source + PROBES, chart, **options)
    strategy = trace["strategy"]
    assert not trace["diagnostics"] and not strategy["diagnostics"]
    assert strategy == engine.run_script(source, chart, **options)["strategy"]
    plots = {p["title"]: p["values"] for p in trace["plots"]}
    assert plots["Open Interest"] == closes
    oracle = [None] * 13 + [
        closes[i] - math.fsum(closes[i - 13 : i + 1]) / 14
        for i in range(13, len(chart))
    ]
    hold = queued = 0
    independent = []
    for i, (bar, delta) in enumerate(zip(chart, oracle, strict=True)):
        if queued != hold:
            stamp = bar["time"]
            opening = children[stamp]
            assert stamp >= BEGIN and opening[1] == bar["open"] and opening[5] > 0
            independent.append(
                (
                    "Buy" if queued == 1 else "Sell",
                    i,
                    stamp,
                    abs(queued - hold),
                    bar["open"],
                )
            )
            hold = queued
        seen = plots["Open Interest Change"][i]
        buy = int(delta is not None and bar["close"] < 15000 and delta > 1)
        sell = int(delta is not None and bar["close"] > 16000 and delta < -1)
        if delta is None:
            assert seen is None
            assert plots["Authored buy"][i] in (None, 0) and plots["Authored sell"][
                i
            ] in (None, 0)
        else:
            assert math.isclose(seen, delta, abs_tol=1e-8)
            assert (plots["Authored buy"][i], plots["Authored sell"][i]) == (buy, sell)
        if bar["time"] >= BEGIN and (buy or sell):
            queued = buy - sell
    assert [
        (x["id"], x["barIndex"], x["time"], x["qty"], x["price"])
        for x in strategy["orders"]
    ] == independent
    assert [
        (p["barIndex"], p["size"], p["avgPrice"]) for p in strategy["position"]
    ] == [(independent[0][1], hold, independent[0][4])]
    assert hold in (-1, 1) and len(independent) == 1 and not strategy["trades"]
    entry = independent[0][4]
    return {
        "market": market,
        "publication_hour_utc": delay,
        "ending_position": hold,
        "chart_bars": len(chart),
        "order": strategy["orders"][0],
        "entry_fee_overlay": entry * FEE,
        "terminal_unrealized_ex_funding": hold * (chart[-1]["close"] - entry),
    }


def run(document, directory, runtime, output):
    assert sha256(runtime / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(runtime))
    import pine_compat

    source = compile_source(document)
    observations, index_manifest = index_values(directory)
    archive_manifest = []
    cases = []
    for market in ("BTCUSDT", "ETHUSDT"):
        hours = verified_archives(directory, market, "1h", MONTHS, archive_manifest)
        quarters = verified_archives(directory, market, "15m", MONTHS, archive_manifest)
        chart = objects(prices(hours, WARM, END, HOUR))
        children = {r[0]: r for r in prices(quarters, WARM, END, HOUR // 4)}
        assert all(
            bar["close"] == children[bar["time"] + 3 * HOUR // 4][4] for bar in chart
        )
        cases.extend(
            run_scope(pine_compat, source, market, chart, children, observations, clock)
            for clock in (10, 11, 24)
        )
    selected = {
        scope["market"]: scope for scope in cases if scope["publication_hour_utc"] == 11
    }
    results = []
    for label, markets in (
        ("BTCUSDT", ("BTCUSDT",)),
        ("ETHUSDT", ("ETHUSDT",)),
        ("BTCUSDT + ETHUSDT", ("BTCUSDT", "ETHUSDT")),
    ):
        entry_fees = sum(selected[m]["entry_fee_overlay"] for m in markets)
        results.append(
            {
                "id": ID,
                "group": "FMZ Pine v5 · Confirmed Nifty 50 daily close",
                "period": "Binance USD-M · 2024-01-01 to 2024-01-24 UTC exclusive",
                "market": label,
                "exit": "Reverse only on opposite source signal",
                "archive_interval": "1h",
                "interval": "1h",
                "currency": "USDT",
                **ledger_metrics([], len(markets) * CAPITAL, len(markets)),
                "realized_gross": 0,
                "realized_after_fees": -entry_fees,
                "realized_net": -entry_fees,
            }
        )
    write(
        output,
        {
            "schema": "FMZ 3424 · Binance futures with confirmed NSE index dependency",
            "source_sha256": SOURCE_SHA,
            "engine_sha256": ENGINE_SHA,
            "index_receipts": index_manifest,
            "candle_archives": archive_manifest,
            "context": {
                "source": "The Pine code requests the daily NIFTY50 close and calculates the 14-hour SMA of the projected series. The comments call it open interest.",
                "timing": "The adapter carries each official close forward from 11:00 UTC on its NSE session date. This is a declared one-hour publication allowance after scheduled close. 10:00 UTC and next 00:00 UTC are sensitivity checks. Exact historical FMZ publication timing is unknown.",
                "calendar": "January 20 was a special session and January 22 a trading holiday. December 29 supplies the latest preceding close. Warm-up is read-only and ex-ante. No calculations use a later close before the modeled availability boundary.",
                "financials": "Exact-source size is one base unit per market. Source reversal is the only exit. Closed-trade P&L and realized-exit drawdown are flat. The separate realized fields show open-entry fees using a 0.075% overlay. Unrealized diagnostics use the last traded close without funding or liquidation assumptions.",
            },
            "references": {
                "pine": "https://www.tradingview.com/pine-script-docs/v5/concepts/other-timeframes-and-data/",
                "holiday_and_special_session": "https://nsearchives.nseindia.com/content/circulars/CMPT60343.pdf",
            },
            "coverage": [
                [
                    ID,
                    "Tested · Causal NSE close projection, positions open",
                    "Official Nifty 50 close feed plus archived Binance USD-M 1h and 15m. Three availability conventions agree that one BTC short and one ETH long remain unsettled. Win rates require closed trades.",
                ]
            ],
            "results": results,
            "scopes": cases,
        },
    )


if __name__ == "__main__":
    run(*map(Path, sys.argv[1:]))
