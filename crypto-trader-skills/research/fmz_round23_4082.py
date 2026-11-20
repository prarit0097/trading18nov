"""Verify #4082 on a preselected month of five complete crypto timeframes."""

import bisect
import math
import re
import sys
from pathlib import Path
from statistics import fmean

from research.fmz_round7_magnifier import (
    aggregate,
    date_ms,
    ledger_metrics,
    raw_ohlcv,
    sha256,
    verified_archives,
    write,
)
from research.fmz_round18_5745 import ENGINE_SHA, FIELDS
from research.fmz_round21_1988 import ema, rsi14

SOURCE_SHA = "3b5aa850c0233c9212a2d1f2de612921fd08f9103e45dc77ce7bbe0b8d4587f3"
CAPITAL = 1_000_000
FEE = 0.00075
MIN = 60_000
RANGES = (1, 5, 15, 60, 240)
OBSERVE = """
plot(trend1m,title="1m")
plot(trend5m,title="5m")
plot(trend15m,title="15m")
plot(trend1h,title="1h")
plot(trend4h,title="4h")
plot(longEntry?1:0,title="Long gate")
plot(shortEntry?1:0,title="Short gate")
"""


def objects(rows):
    return [dict(zip(FIELDS, r, strict=True)) for r in rows]


def trend(chart, bins, minutes):
    close = [r["close"] for r in bins]
    fast, slow = (ema(close, n) for n in (9, 21))
    rsi = rsi14(close)
    levels = []
    for c, f, s, r in zip(close, fast, slow, rsi, strict=True):
        side = 0
        if f is not None and s is not None and r is not None:
            if f > s and r > 50 and c > f:
                side = 1
            elif f < s and r < 50 and c < f:
                side = -1
        levels.append(side)
    released = [b["time"] + minutes * MIN for b in bins]
    result = []
    for bar in chart:
        i = bisect.bisect_right(released, bar["time"] + 60 * MIN) - 1
        result.append(levels[i] if i >= 0 else 0)
    return result


def signals(chart, trends):
    close = [b["close"] for b in chart]
    rsi = rsi14(close)
    buy, sell = [0] * 19, [0] * 19
    for i in range(19, len(chart)):
        prior, current = chart[i - 1 : i + 1]
        current_open, current_close = current["open"], current["close"]
        old_open, old_close = prior["open"], prior["close"]
        recent = chart[i - 19 : i + 1]
        area = chart[i - 13 : i + 1]
        width = max(b["high"] for b in area) - min(b["low"] for b in area)
        cmi = 100 * abs(close[i] - close[i - 14]) / width
        vwma = math.fsum(b["close"] * b["volume"] for b in recent) / math.fsum(
            b["volume"] for b in recent
        )
        vol = current["volume"] > 2 * fmean(b["volume"] for b in recent)
        bullish = (
            old_open > old_close
            and current_close > current_open
            and current_open < old_close
            and current_close > old_open
        )
        bearish = (
            old_open < old_close
            and current_close < current_open
            and current_open > old_close
            and current_close < old_open
        )
        buy.append(
            int(
                all(t[i] == 1 for t in trends)
                and bullish
                and vol
                and rsi[i] > 55
                and cmi > 30
                and current_close > vwma
            )
        )
        sell.append(
            int(
                all(t[i] == -1 for t in trends)
                and bearish
                and vol
                and rsi[i] < 45
                and cmi > 30
                and current_close < vwma
            )
        )
    return buy, sell


def replay(engine, source, exchange, raw):
    bins = {n: objects(aggregate(raw, n)) for n in RANGES if n != 1}
    bins[1] = objects(raw)
    chart = bins[60]
    symbol = f"BINANCE:{exchange}"
    options = {
        "chart_symbol": symbol,
        "chart_timeframe": "60",
        "request_bars": {
            **{f"{symbol}:{n}": bins[n] for n in RANGES if n != 60},
            "$chart": {
                "minMove": 1,
                "priceScale": 100,
                "pointValue": 1,
                "quantityStep": "0.001",
                "minContract": "0.001",
                "currency": "USDT",
            },
        },
    }
    broker = engine.run_script(source, chart, **options)["strategy"]
    out = engine.run_script(source + OBSERVE, chart, **options)
    assert (
        broker == out["strategy"]
        and not out["diagnostics"]
        and not broker["diagnostics"]
    )
    plots = {p["title"]: p["values"] for p in out["plots"]}
    trends = [trend(chart, bins[n], n) for n in RANGES]
    for label, series in zip(("1m", "5m", "15m", "1h", "4h"), trends, strict=True):
        assert plots[label] == series, (
            exchange,
            label,
            [
                i
                for i, (a, b) in enumerate(zip(plots[label], series, strict=True))
                if a != b
            ][:15],
        )
    up, down = signals(chart, trends)
    assert (plots["Long gate"], plots["Short gate"]) == (up, down)
    triggered = [(i, 1 if up[i] else -1) for i in range(len(chart)) if up[i] or down[i]]
    record = {
        "market": exchange,
        "chart_bars": len(chart),
        "trends_checked": len(chart) * len(RANGES),
        "closed": [],
        "fills": broker["orders"],
        "ending_position": 0,
    }
    if not triggered:
        assert not broker["orders"] and not broker["trades"]
        return record
    ((i, side),) = triggered
    assert side == 1
    parent = chart[i]
    width = parent["high"] - parent["low"]
    target = round(parent["close"] + 2 * width, 2)
    stop = round(parent["close"] - width, 2)
    first = None
    for row in bins[1][(i + 1) * 60 :]:
        if row["low"] <= stop or row["high"] >= target:
            assert row["high"] >= target and row["low"] > stop
            first = row
            break
    assert first is not None
    entry, exit = broker["orders"]
    (lot,) = broker["trades"]
    px = chart[i + 1]["open"]
    quantity = math.floor(CAPITAL * 0.1 / px * 1000) / 1000
    assert (
        entry["barIndex"] == i + 1 and entry["price"] == px and entry["qty"] == quantity
    )
    assert (
        exit["time"] == first["time"] // (60 * MIN) * (60 * MIN)
        and exit["price"] == max(first["open"], target)
        and exit["qty"] == quantity
    )
    assert (
        lot["entryPrice"] == px
        and lot["exitPrice"] == exit["price"]
        and lot["qty"] == quantity
    )
    gross = quantity * (exit["price"] - px)
    assert math.isclose(gross, lot["profit"], abs_tol=1e-8)
    fee = quantity * FEE * (px + exit["price"])
    record["closed"].append({**lot, "dir": 1, "commission": fee, "profit": gross - fee})
    record["minute_execution_witness"] = {
        "source_signal": parent["time"],
        "target": target,
        "stop": stop,
        "first_touch": first,
    }
    return record


def run(source_path, archives, engine_root, output):
    assert sha256(source_path) == SOURCE_SHA
    assert sha256(engine_root / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(engine_root))
    import pine_compat as engine

    (source,) = re.findall(
        r"(?ms)^```[^\n]*\n(.*?)^```", source_path.read_text(encoding="utf-8")
    )
    source, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", source)
    assert n == 1
    start, end = map(date_ms, ("2024-05-01", "2024-06-01"))
    manifest = []
    cases = []
    for market in ("BTCUSDT", "ETHUSDT"):
        (archive,) = verified_archives(archives, market, "1m", ("2024-05",), manifest)
        raw = list(raw_ohlcv(archive, MIN))
        assert [r[0] for r in raw] == list(range(start, end, MIN))
        assert all(row[5] > 0 for row in raw)
        cases.append(replay(engine, source, market, raw))
    meta = {
        "id": 4082,
        "group": "FMZ · Pine v5 · Five complete hourly reference streams",
        "period": "Binance USD-M · 2024-05-01 to 2024-06-01 UTC exclusive",
        "interval": "1h",
        "archive_interval": "1h",
        "currency": "USDT",
        "exit": "Source signal-bar range stop and target",
    }
    results = [
        {**meta, "market": c["market"], **ledger_metrics(c["closed"], CAPITAL, 0)}
        for c in cases
    ]
    results.append(
        {
            **meta,
            "market": "BTCUSDT + ETHUSDT",
            **ledger_metrics(
                [lot for case in cases for lot in case["closed"]], 2 * CAPITAL, 0
            ),
        }
    )
    write(
        output,
        {
            "schema": "FMZ 4082 · Five timeframe validation on complete Binance minute candles",
            "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
            "source_sha256": SOURCE_SHA,
            "engine_sha256": ENGINE_SHA,
            "candle_archives": manifest,
            "notes": {
                "window": "May 2024 was preselected as a full calendar month within the saved wider April 2024–April 2025 Binance hourly scope. The untouched source uses the chart's own symbol in all five requests. Both replays start from flat on May 1.",
                "lookahead": "Completed 1m, 5m, 15m, 1h and 4h bars are independently aggregated from the verified Binance USD-M minute archives. The indicator reconstruction selects only observations completed by each evaluation close, including the last available lower-timeframe sample. All five directional curves and source gates agree with the native Pine trace.",
                "execution": "The native model enters at the next hourly open and uses 10% of 1,000,000 USDT starting equity. The single BTC bracket reaches its target on positive-volume one-minute evidence. ETH never opens. The model uses the source's zero commission for gross and a 0.075% per-side overlay with unchanged fills. Funding and extra price impact are outside the measured model.",
            },
            "coverage": [
                [
                    4082,
                    "Tested · Five timeframes and verified intrabar target",
                    "Untouched Pine v5 in a preselected complete month within the archived hourly dates. Five completed-timeframe trend curves, both active gates and the single minute-confirmed bracket exit agree with independent evidence.",
                ]
            ],
            "results": results,
            "scopes": cases,
        },
    )


if __name__ == "__main__":
    run(*map(Path, sys.argv[1:]))
