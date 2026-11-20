"""Verify archived FMZ #5745 with explicit official Cboe VIX input."""

import csv
import math
import re
import sys
from bisect import bisect_right
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from research.fmz_round7_magnifier import ledger_metrics, read, sha256, write

REVISION = "7853bb2bf262c4567ac238d3552d97f0e50cb801"
SOURCE_SHA = "8cce821d5f03ce614830b8b398cd0b60b17b234fcc6345836b8ba9eeac8aa430"
VIX_SHA = "0d9c033a1ee06d41832ef98ce17d84910c8c386d890daca5cb24bbf9cd4af8d5"
ENGINE_SHA = "6c4ad673c8a78e3d31d40ae66908d86423c209fc92d52930c0c6f55853fafcda"
FEEDS = {
    "BTCUSDT": "a7acbcdedcbdc3da6d72bfd9a6f3a8fbfebaffaf47b264778b4dae4b44bb1640",
    "ETHUSDT": "b9affb20b5e749f7b27232edb0d256b69c89e2c4e6f9f52911f1c438f36b9c65",
}
START = int(datetime(2019, 12, 24, tzinfo=UTC).timestamp()) * 1000
END = int(datetime(2024, 12, 9, tzinfo=UTC).timestamp()) * 1000
DAY = 86_400_000
CAPITAL = 1_000_000
FEE = 0.00075
FIELDS = ("time", "open", "high", "low", "close", "volume")
RELAY = 'input("swap", "VIX Symbol")'
CBOE = 'input("CBOE:VIX", "VIX Symbol")'
OBSERVE = """
plot(vixClose, title="Cboe close")
plot(vixHigh, title="Cboe high")
plot(vixLow, title="Cboe low")
plot(vixMA, title="VIX SMA")
plot(vixMA_yesterday, title="Prior VIX SMA")
plot(buySignal ? 1 : 0, title="Buy signal")
plot(sellSignal ? 1 : 0, title="Sell signal")
plot(buyExit ? 1 : 0, title="Buy exit")
plot(sellExit ? 1 : 0, title="Sell exit")
plot(strategy.position_size, title="Position")
"""


def archive(path):
    assert sha256(path) == SOURCE_SHA
    (src,) = re.findall(r"(?ms)^```[^\n]*\n(.*?)^```", path.read_text(encoding="utf-8"))
    src, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", src)
    assert n == 1 and src.count(RELAY) == 1
    return src


def vix_sessions(path):
    assert sha256(path) == VIX_SHA
    result = {}
    with path.open(encoding="ascii", newline="") as f:
        for row in csv.DictReader(f):
            dt = datetime.strptime(row["DATE"], "%m/%d/%Y").replace(tzinfo=UTC)
            time = int(dt.timestamp()) * 1000
            if START - 30 * DAY <= time < END:
                values = tuple(
                    Decimal(row[k]) for k in ("OPEN", "HIGH", "LOW", "CLOSE")
                )
                o, h, l, c = values
                assert dt.weekday() < 5 and l <= min(o, c) <= max(o, c) <= h
                assert time not in result
                result[time] = values
    assert list(result) == sorted(result)
    return result


def release_series(sessions, chart, delay_days):
    release = [intro + delay_days * DAY for intro in sessions]
    last_quote = [bisect_right(release, day["time"]) - 1 for day in chart]
    actual = list(sessions.items())
    assert min(last_quote) >= 0
    selected = [actual[i] for i in last_quote]
    for source, market in zip(selected, chart, strict=True):
        assert 0 <= market["time"] - source[0] - delay_days * DAY <= 4 * DAY
    quotes = [
        dict(zip(FIELDS, (day["time"], *map(float, source[1]), 0), strict=True))
        for day, source in zip(chart, selected, strict=True)
    ]
    return quotes, selected


def oracle(chart, selected):
    strategy_states = []
    averages = []
    gates = []
    ledger = []
    holding = None
    target = None
    closes = [item[1][3] for item in selected]
    for bar, (market, (_, (_, high, low, close))) in enumerate(
        zip(chart, selected, strict=True)
    ):
        # Orders from a prior close fill before this day's VIX gates are evaluated.
        if bar and target != (holding[0] if holding else None):
            if holding:
                side, entry = holding
                ledger.append((side, entry, bar))
            holding = (target, bar) if target else None
        side = holding[0] if holding else None
        strategy_states.append({None: 0, "Buy": 1, "Sell": -1}[side])
        mean = sum(closes[bar - 9 : bar + 1]) / 10 if bar >= 9 else None
        previous = averages[-1] if averages else None
        averages.append(mean)
        buy = mean is not None and low > mean and close > mean * Decimal("1.1")
        sell = mean is not None and high < mean and close < mean * Decimal("0.9")
        buy_exit = previous is not None and low < previous
        sell_exit = previous is not None and high > previous
        gates.append((buy, sell, buy_exit, sell_exit))
        assert not (buy and sell)
        requested = "Buy" if buy else "Sell" if sell else None
        existing_exit = (side == "Buy" and buy_exit) or (side == "Sell" and sell_exit)
        if requested is not None and requested != side:
            target = requested
        else:
            target = None if existing_exit else side
    return averages, gates, strategy_states, ledger, holding


def replay(engine, src, chart, sessions, market, delay_days):
    quotes, selected = release_series(sessions, chart, delay_days)
    averages, gates, states, ledger, holding = oracle(chart, selected)
    opt = {
        "chart_symbol": f"BINANCE:{market}",
        "chart_timeframe": "D",
        "request_bars": {
            "CBOE:VIX:D": quotes,
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
    untouched = engine.run_script(src, chart, **opt)["strategy"]
    tracked = engine.run_script(src + OBSERVE, chart, **opt)
    assert untouched == tracked["strategy"]
    plots = {p["title"]: p["values"] for p in tracked["plots"]}
    for title, key in (
        ("Cboe close", "close"),
        ("Cboe high", "high"),
        ("Cboe low", "low"),
    ):
        assert plots[title] == [q[key] for q in quotes]
    for key, expected in (
        ("VIX SMA", averages),
        ("Prior VIX SMA", [None, *averages[:-1]]),
    ):
        for seen, value in zip(plots[key], expected, strict=True):
            assert (
                seen is None
                if value is None
                else math.isclose(seen, float(value), abs_tol=1e-10)
            )
    for title, flags in zip(
        ("Buy signal", "Sell signal", "Buy exit", "Sell exit"), zip(*gates), strict=True
    ):
        assert plots[title] == [int(x) for x in flags], title
    assert plots["Position"] == states
    lots = []
    for (side, entry, exit), trade in zip(ledger, untouched["trades"], strict=True):
        eb, xb = chart[entry], chart[exit]
        direction = 1 if side == "Buy" else -1
        assert (trade["id"], trade["qty"]) == (side, direction)
        assert (trade["entryBarIndex"], trade["exitBarIndex"]) == (entry, exit)
        assert (trade["entryTime"], trade["exitTime"]) == (eb["time"], xb["time"])
        assert (trade["entryPrice"], trade["exitPrice"]) == (eb["open"], xb["open"]), (
            market,
            trade,
            eb["open"],
            xb["open"],
        )
        gross = direction * (xb["open"] - eb["open"])
        assert math.isclose(gross, trade["profit"], abs_tol=1e-8)
        cost = FEE * (eb["open"] + xb["open"])
        lots.append(
            {
                **trade,
                "qty": 1,
                "dir": direction,
                "commission": cost,
                "profit": gross - cost,
            }
        )
    assert len(untouched["orders"]) == 2 * len(lots) + bool(holding)
    for order in untouched["orders"]:
        b = chart[order["barIndex"]]
        assert (order["time"], order["price"], order["qty"]) == (
            b["time"],
            b["open"],
            1,
        )
    summary = {
        "market": market,
        "daily_bars": len(chart),
        "lookahead_delayed_days": delay_days,
        "unique_source_sessions": len({x[0] for x in selected}),
        "first_source_utc_day": selected[0][0],
        "last_source_utc_day": selected[-1][0],
        "gates_buy_sell_buy_exit_sell_exit": list(map(sum, zip(*gates))),
        "fills": untouched["orders"],
        "unsettled": bool(holding),
        "ending_holding": holding,
        "closed_lots": lots,
    }
    return summary


def run(work, feeds, engine_root, output):
    assert sha256(engine_root / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(engine_root))
    import pine_compat as engine

    original = archive(work / "source-5745.md")
    variant = original.replace(RELAY, CBOE)
    sessions = vix_sessions(work / "vix.csv")
    summaries = []
    for market, digest in FEEDS.items():
        path = feeds / f"5411-feed-{market}.json"
        assert sha256(path) == digest
        chart = [dict(zip(FIELDS, row, strict=True)) for row in read(path)]
        assert [b["time"] for b in chart] == list(range(START, END, DAY))
        # The literal archive requires an unresolved symbol. Independently verify
        # that substituting the documented chart series does not happen implicitly.
        try:
            engine.run_script(
                original,
                chart[:3],
                chart_symbol=f"BINANCE:{market}",
                chart_timeframe="D",
            )
        except ValueError as error:
            assert "missing request data for symbol `swap` timeframe `D`" in str(error)
        else:
            raise AssertionError("Archived symbol resolved without a source")
        summaries.append(replay(engine, variant, chart, sessions, market, 1))
    context = {
        "id": 5745,
        "group": "FMZ · Pine v5 · Explicit official Cboe VIX input",
        "exit": "Prior VIX SMA thresholds or market reversal",
        "period": "Binance USD-M · 2019-12-24 to 2024-12-09 UTC exclusive",
        "archive_interval": "1d",
        "interval": "1d",
        "currency": "USDT",
    }
    outcomes = []
    combined = []
    for case in summaries:
        lots = case["closed_lots"]
        outcomes.append(
            {
                **context,
                "market": case["market"],
                **ledger_metrics(lots, CAPITAL, int(case["unsettled"])),
            }
        )
        combined.extend(lots)
    outcomes.append(
        {
            **context,
            "market": "BTCUSDT + ETHUSDT",
            **ledger_metrics(
                combined, 2 * CAPITAL, sum(int(x["unsettled"]) for x in summaries)
            ),
        }
    )
    write(
        output,
        {
            "schema": "FMZ 5745 · Explicit public VIX input and independent order replay",
            "source_revision": REVISION,
            "source_sha256": SOURCE_SHA,
            "cboe_history": {
                "sha256": VIX_SHA,
                "url": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
            },
            "binance_daily_feeds_sha256": FEEDS,
            "engine_sha256": ENGINE_SHA,
            "notes": {
                "source_input": "Archive default swap does not resolve in local Pine. The source exposes VIX Symbol as a configurable input, and CBOE:VIX is chosen for this research variant. All other settings and order conditions stay literal.",
                "join": "Every UTC crypto day uses the latest Cboe OHLC whose session label precedes the chart's UTC date. The one-day release delay excludes incomplete same-date Cboe data. The last released value carries forward over weekends and holidays. Pine computes its 10-sample averages on the resulting chart-day sequence.",
                "venue": "Native BTC chart plus independent ETH comparison at the saved daily cadence. 2019-12-23 08:00 to 2024-12-09 08:00 is interpreted in UTC, retaining 1,812 full chart bars within the saved window.",
                "fills_and_costs": "Next daily open at the supplied historical cents precision. Quantity one base unit and default broker capital 1,000,000 USDT per independent market. Zero source fee for gross and 0.075% per-side fee overlay. Drawdown on settled equity. Funding and slippage are excluded from this research variant.",
                "verification": "Uninstrumented and instrumented Pine orders and strategy output agree. An independent Decimal oracle verifies the joined values, both moving averages, all four conditions, position transitions, fill times and prices, and lot P&L.",
            },
            "coverage": [
                [
                    5745,
                    "Tested · Explicit official Cboe VIX input",
                    "Archived rule logic replayed with the author-configurable VIX Symbol set to official Cboe VIX. Strict lagged input join, Pine traces and independent order witness agree on both markets. Archived bare swap alias remains unidentified.",
                ]
            ],
            "results": outcomes,
            "scopes": summaries,
        },
    )


if __name__ == "__main__":
    run(*map(Path, sys.argv[1:]))
