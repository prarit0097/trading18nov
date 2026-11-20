"""Verify FMZ #4054 multi-timeframe scope and the archived USD cash ledger."""

import bisect
import math
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from itertools import pairwise
from pathlib import Path

from research.fmz_round7_magnifier import (
    aggregate,
    date_ms,
    raw_ohlcv,
    read,
    sha256,
    verified_archives,
    write,
)
from research.fmz_round8_fx import prior_close_rates
from research.fmz_round18_5745 import DAY, ENGINE_SHA, FEEDS, FIELDS

SOURCE_SHA = "e5ed352d3330e580ce3057cfc4a5aa3be134189d70a587cc7898cc251b370037"
HOUR = 3_600_000
START, END = map(date_ms, ("2024-01-01", "2024-02-01"))
WARMUP = date_ms("2023-06-05")
FEE = 0.0001
CAPITAL = 100
FX_URL = "https://api.exchange.coinbase.com/products/USDT-USD/candles?granularity=86400&start=2023-12-31T00%3A00%3A00Z&end=2024-02-01T00%3A00%3A00Z"
OBS = """
plot(RSI_TF1,title="Weekly RSI")
plot(Stoch_TF1,title="Weekly Stochastic")
plot(RSI_TF2,title="Daily RSI")
plot(Stoch_TF2,title="Daily Stochastic")
plot(RSI_TF3,title="Four-hour RSI")
plot(Stoch_TF3,title="Four-hour Stochastic")
plot(RSI_TF4,title="Hourly RSI")
plot(Stoch_TF4,title="Hourly Stochastic")
plot(strategy.position_size,title="Position")
"""


def objects(rows):
    return [dict(zip(FIELDS, r, strict=True)) for r in rows]


def indicators(bars):
    gains = [max(b["close"] - a["close"], 0.0) for a, b in pairwise(bars)]
    losses = [max(a["close"] - b["close"], 0.0) for a, b in pairwise(bars)]
    up, down = math.fsum(gains[:14]) / 14, math.fsum(losses[:14]) / 14
    rsi = [None] * 14
    for i in range(14, len(bars)):
        if i > 14:
            up = (13 * up + gains[i - 1]) / 14
            down = (13 * down + losses[i - 1]) / 14
        rsi.append(100 - 100 / (1 + up / down) if down else 100.0)
    levels = [None] * 13
    for i, b in enumerate(bars[13:], 13):
        w = bars[i - 13 : i + 1]
        lo, hi = min(x["low"] for x in w), max(x["high"] for x in w)
        assert hi > lo
        levels.append(100 * (b["close"] - lo) / (hi - lo))
    stoch = [None] * 15 + [
        math.fsum(levels[i - 2 : i + 1]) / 3 for i in range(15, len(bars))
    ]
    return rsi, stoch


def aligned(chart, ref, timeframe):
    stamps = [b["time"] + timeframe for b in ref]
    indices = [bisect.bisect_right(stamps, b["time"] + HOUR) - 1 for b in chart]
    rsi, stoch = indicators(ref)
    return [(rsi[i], stoch[i]) if i >= 0 else (None, None) for i in indices]


def mean(values):
    if any(x is None for x in values):
        return None
    return float(
        Decimal(str(math.fsum(values) / 4)).quantize(
            Decimal(".01"), rounding=ROUND_HALF_UP
        )
    )


def oracle(chart, sources):
    reference = [
        aligned(chart, data, span)
        for data, span in zip(sources, (7 * DAY, DAY, 4 * HOUR, HOUR), strict=True)
    ]
    averages = [tuple(mean(group) for group in zip(*r)) for r in zip(*reference)]
    holdings = []
    events = []
    pending = side = 0
    entry = None
    for i, (bar, (rsi, stoch)) in enumerate(zip(chart, averages, strict=True)):
        if pending != side:
            events.append((i, side, pending, entry))
            side, entry = pending, (i, bar["open"]) if pending else None
        holdings.append(side)
        if rsi is None or stoch is None:
            continue
        if rsi <= 30 and stoch <= 30:
            pending = 1
        elif rsi >= 70 and stoch >= 70:
            pending = -1
        elif (
            side == 1
            and stoch >= 70
            and rsi >= 50
            and bar["close"] >= entry[1]
            or side == -1
            and stoch <= 30
            and rsi <= 50
            and bar["close"] <= entry[1]
        ):
            pending = 0
    return reference, averages, holdings, events


def near(a, b):
    return math.isclose(a, b, rel_tol=1e-11, abs_tol=1e-9)


def replay(engine, source, market, sources, fx):
    weekly, daily, four, chart = sources
    pair = f"BINANCE:{market}"
    options = {
        "chart_symbol": pair,
        "chart_timeframe": "60",
        "request_bars": {
            pair + ":W": weekly,
            pair + ":D": daily,
            pair + ":240": four,
            "$currencyRates": fx,
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
    original = engine.run_script(source, chart, **options)["strategy"]
    observed = engine.run_script(source + OBS, chart, **options)
    assert original == observed["strategy"] and not observed["diagnostics"]
    guarded = source.replace(
        'strategy.close("Buy_Long",when=(AVG_STOCH >=70 and AVG >=50 and close >=strategy.position_avg_price),comment="Long_OK")',
        'if AVG_STOCH >=70 and AVG >=50 and close >=strategy.position_avg_price\n    strategy.close("Buy_Long",comment="Long_OK")',
    ).replace(
        'strategy.close("Buy_Short",when=(AVG_STOCH <=30 and AVG <=50 and close <=strategy.position_avg_price),comment="Short_OK")',
        'if AVG_STOCH <=30 and AVG <=50 and close <=strategy.position_avg_price\n    strategy.close("Buy_Short",comment="Short_OK")',
    )
    assert (
        guarded != source
        and engine.run_script(guarded, chart, **options)["strategy"] == original
    )
    reference, averages, positions, expected = oracle(chart, sources)
    plots = {p["title"]: p["values"] for p in observed["plots"]}
    for label, series in zip(
        ("Weekly", "Daily", "Four-hour", "Hourly"), reference, strict=True
    ):
        for i, (rsi, stoch) in enumerate(series):
            for kind, value in (("RSI", rsi), ("Stochastic", stoch)):
                seen = plots[f"{label} {kind}"][i]
                assert seen is None if value is None else near(seen, value), (
                    label,
                    kind,
                    i,
                    value,
                    seen,
                )
    assert list(zip(plots["RSI"], plots["STOCH"], strict=True)) == averages
    assert plots["Position"] == positions
    rates = {item["effectiveTime"]: item["rate"] for item in fx["pairs"][0]["rates"]}
    lots = []
    for order, (i, prior, side, entry) in zip(
        original["orders"], expected, strict=True
    ):
        assert (
            order["barIndex"] == i
            and order["time"] == chart[i]["time"]
            and order["qty"] == 1
        )
        assert order["price"] == chart[i]["open"]
        if prior:
            j, ep = entry
            start_stamp = chart[j]["time"]
            end_stamp = chart[i]["time"]
            start_rate = rates[start_stamp // DAY * DAY]
            end_rate = rates[end_stamp // DAY * DAY]
            gross = prior * (chart[i]["open"] - ep) * end_rate
            commission = FEE * (ep * start_rate + chart[i]["open"] * end_rate)
            lot = original["trades"][len(lots)]
            assert (lot["entryBarIndex"], lot["exitBarIndex"], lot["qty"]) == (
                j,
                i,
                prior,
            )
            assert near(gross - commission, lot["profit"])
            lots.append({**lot, "gross_USD": gross, "commission_USD": commission})
    assert len(lots) == len(original["trades"])
    episode_by_exit = {item["exitBarIndex"]: item for item in lots}
    entries = {i: new for i, prior, new, _ in expected if new and not prior}
    settled = float(CAPITAL)
    inventory_price = 0.0
    entry_fee = 0.0
    curve = []
    for i, (bar, side) in enumerate(zip(chart, positions, strict=True)):
        rate = rates[bar["time"] // DAY * DAY]
        if i in entries:
            inventory_price = bar["open"]
            entry_fee = FEE * inventory_price * rate
        if i in episode_by_exit:
            settled += episode_by_exit[i]["profit"]
            inventory_price = 0.0
            entry_fee = 0.0
        marked = settled + side * (bar["close"] - inventory_price) * rate - entry_fee
        assert near(marked, original["equity"][i]["equity"]), (
            market,
            i,
            marked,
            original["equity"][i]["equity"],
        )
        curve.append(marked)
    peak = CAPITAL
    max_drawdown = 0.0
    for marked in curve:
        peak = max(peak, marked)
        max_drawdown = max(max_drawdown, peak - marked)
    margin_variant = source.replace(
        "initial_capital=100,",
        "initial_capital=100, margin_long=100, margin_short=100,",
    )
    assert margin_variant != source
    guarded_fills = engine.run_script(margin_variant, chart, **options)["strategy"]
    assert not guarded_fills["orders"] and all(
        e["code"] == "E_STRATEGY_MARGIN" for e in guarded_fills["diagnostics"]
    )
    return {
        "market": market,
        "fills": original["orders"],
        "realized": lots,
        "ending_position": positions[-1],
        "ending_equity_USD": original["equity"][-1]["equity"],
        "full_margin_control_rejections": len(guarded_fills["diagnostics"]),
        "indicator_bar_checks": len(chart),
        "marked_drawdown_USD": max_drawdown,
        "minimum_marked_equity_USD": min(curve),
    }


def totals(cases):
    ledger = [lot for c in cases for lot in c["realized"]]
    assert len(ledger) <= 1
    gross = math.fsum(lot["gross_USD"] for lot in ledger)
    fee = math.fsum(lot["commission_USD"] for lot in ledger)
    net = gross - fee
    return {
        "trades": len(ledger),
        "unsettled": sum(c["ending_position"] != 0 for c in cases),
        "gross_wins": int(gross > 0),
        "fee_wins": int(net > 0),
        "net_wins": int(net > 0),
        "gross": gross,
        "fees": fee,
        "after_fees": net,
        "execution": 0,
        "net": net,
        "gross_dd": max(0, -gross),
        "fee_dd": max(0, -net),
        "net_dd": max(0, -net),
        "net_dd_pct": max(0, -net) / (CAPITAL * len(cases)),
    }


def run(work, daily_path, archives, engine_root, output):
    assert sha256(engine_root / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(engine_root))
    import pine_compat as engine

    path = work / "source-4054.md"
    assert sha256(path) == SOURCE_SHA
    (src,) = re.findall(r"(?ms)^```[^\n]*\n(.*?)^```", path.read_text(encoding="utf-8"))
    src, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", src)
    assert n == 1
    fx_path = work / "4054-usdt-usd.json"
    fx = prior_close_rates(read(fx_path))
    fx["pairs"][0]["rates"] = [
        row for row in fx["pairs"][0]["rates"] if START <= row["effectiveTime"] < END
    ]
    assert [r["effectiveTime"] for r in fx["pairs"][0]["rates"]] == list(
        range(START, END, DAY)
    )
    cases, manifest = [], []
    for market, digest in FEEDS.items():
        (archive,) = verified_archives(archives, market, "15m", ("2024-01",), manifest)
        base = list(raw_ohlcv(archive, HOUR // 4))
        assert [r[0] for r in base] == list(range(START, END, HOUR // 4))
        full = daily_path / f"5411-feed-{market}.json"
        assert sha256(full) == digest
        rows = [r for r in read(full) if WARMUP <= r[0] < END]
        assert [r[0] for r in rows] == list(range(WARMUP, END, DAY))
        for actual, dated in zip(aggregate(base, 96), rows[-31:], strict=True):
            assert actual[:5] == tuple(dated[:5]) and near(actual[5], dated[5])
        sources = (
            objects(aggregate(rows[: len(rows) // 7 * 7], 7)),
            objects(rows),
            objects(aggregate(base, 16)),
            objects(aggregate(base, 4)),
        )
        cases.append(replay(engine, src, market, sources, fx))
    meta = {
        "id": 4054,
        "group": "FMZ · Hourly Pine v5 · Weekly/daily/4h/hourly oscillator join",
        "period": "Binance USD-M · 2024-01-01 to 2024-02-01 UTC exclusive",
        "exit": "Source profitable RSI/Stochastic exits",
        "archive_interval": "1h",
        "interval": "1h",
        "currency": "USD",
    }
    results = [{**meta, "market": c["market"], **totals([c])} for c in cases]
    results.append({**meta, "market": "BTCUSDT + ETHUSDT", **totals(cases)})
    write(
        output,
        {
            "schema": "FMZ 4054 · Independent four-frame join and USD portfolio ledger",
            "source_sha256": SOURCE_SHA,
            "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
            "engine_sha256": ENGINE_SHA,
            "daily_archive_sha256": FEEDS,
            "candle_archives": manifest,
            "usdt_usd": {"url": FX_URL, "sha256": sha256(fx_path)},
            "notes": {
                "scope": "Saved 2024-01-01 to 2024-01-31 23:59:59 hourly Binance chart. Weekly and daily indicators warm up from June 5, 2023. Hourly and four-hour histories start on January 1. Each evaluation uses data complete at the hourly chart close. Jan 2024 daily prices reconcile independently to the 15-minute archives.",
                "fills": "Original one-unit default, 100 USD initial equity, 0.01% commission and next-open market orders. The unchanged archive and explicit if form of the peripheral when guards produce identical ledgers. Realized gross uses exit-day FX from the prior Coinbase close and each fee uses its corresponding day's known rate.",
                "margin": "The saved Pine v5 clause omits margin parameters. This source-emulator test allows one-unit positions large relative to 100 USD. Replaying the same signals with 100% initial margin admits zero fills on both markets. This is historical execution-model evidence.",
                "drawdown": "Workbook drawdown uses settled USD equity. The single settled lot can produce zero realized drawdown even while a position experiences a large interim swing. The ETH short remains open. Ending marked equity, minimum marked equity and marked drawdown are independently reconciled and reported separately.",
            },
            "coverage": [
                [
                    4054,
                    "Tested · Four completed timeframes and original USD cash model",
                    "Pinned hourly source and four causal oscillator streams, including measured prior history. Every signal, position and fill matched the independent check. The no-margin source model closes one BTC lot; the separately guarded full-margin control places no orders.",
                ]
            ],
            "results": results,
            "scopes": cases,
        },
    )


if __name__ == "__main__":
    run(*map(Path, sys.argv[1:]))
