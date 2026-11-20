"""Replay FMZ #3106 and verify its fixed BTC reference and cash accounting."""

import math
import re
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from research.fmz_round7_magnifier import ledger_metrics, read, sha256, write
from research.fmz_round18_5745 import DAY, ENGINE_SHA, FEEDS, FIELDS

SOURCE_SHA = "d32360b4aa583b259fad3a48df244275045c34b9a4ffe4f99e48566c0715fd1c"
START = int(datetime(2022, 10, 25, tzinfo=UTC).timestamp()) * 1000
END = int(datetime(2023, 10, 31, tzinfo=UTC).timestamp()) * 1000
CAPITAL = 1000
FEE = Decimal("0.001")
STEP = Decimal("0.001")
OBSERVE = """
plot(supportTicker,title="Support HLC3")
plot(supportLine,title="Support WMA")
plot(supportLongPrice,title="Support Long Anchor")
plot(supportShortPrice,title="Support Short Anchor")
plot(longCondition ? 1:0,title="Long gate")
plot(shortCondition ? 1:0,title="Short gate")
plot(takeprofitLongCondition or stoplossLongCondition ? 1:0,title="Long close gate")
plot(takeprofitShortCondition or stoplossShortCondition ? 1:0,title="Short close gate")
plot(strategy.position_size,title="Position")
"""


def program(path):
    assert sha256(path) == SOURCE_SHA
    (src,) = re.findall(r"(?ms)^```[^\n]*\n(.*?)^```", path.read_text(encoding="utf-8"))
    src, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", src)
    assert n == 1 and src.count("// MONTHLY TABLE //") == 1
    return src


def prices(chart):
    return [
        sum(Decimal(str(x[k])) for k in ("high", "low", "close")) / 3 for x in chart
    ]


def signals(chart, reference):
    wma = [None] * 199 + [
        sum(i * v for i, v in enumerate(reference[j - 199 : j + 1], 1)) / 20100
        for j in range(199, len(chart))
    ]
    records = []
    pending = 0
    holding = 0
    last_buy = last_sell = None
    cash = Decimal(CAPITAL)
    quantity = Decimal(0)
    entry_at = entry_price = None
    lots = []
    executions = []
    for i, bar in enumerate(chart):
        opening = Decimal(str(bar["open"]))
        closing = Decimal(str(bar["close"]))
        if pending != holding:
            cash_at_open = cash + (holding * quantity * opening)
            amount = (
                (cash_at_open / opening / (1 + FEE) // STEP) * STEP
                if pending
                else Decimal(0)
            )
            moved = abs(pending * amount - holding * quantity)
            if holding:
                gross = holding * quantity * (opening - entry_price)
                commission = FEE * quantity * (entry_price + opening)
                lots.append((holding, quantity, entry_at, i, gross, commission))
            cash += (
                opening * (holding * quantity - pending * amount)
                - FEE * moved * opening
            )
            holding, quantity = pending, amount
            entry_at, entry_price = i, opening
            executions.append((i, moved, opening))
        if holding <= 0:
            last_buy = closing
        if holding >= 0:
            last_sell = closing
        current = wma[i]
        trailing = [x for x in wma[max(i - 5, 0) : i] if x is not None]
        long = len(trailing) == 5 and current > max(trailing) and holding <= 0
        short = len(trailing) == 5 and current < min(trailing) and holding > 0
        long_close = holding > 0 and (
            reference[i] > last_buy * Decimal("1.2")
            or reference[i] < last_buy * Decimal("0.9")
        )
        short_close = holding < 0 and (
            reference[i] > last_sell * Decimal("1.15")
            or reference[i] < last_sell * Decimal("0.96")
        )
        if long:
            pending, last_buy = 1, reference[i]
        elif short:
            pending, last_sell = -1, reference[i]
        elif long_close or short_close:
            pending = 0
        records.append(
            (
                current,
                last_buy,
                last_sell,
                long,
                short,
                long_close,
                short_close,
                holding * quantity,
                cash + holding * quantity * closing,
            )
        )
    return records, executions, lots


def near(a, b):
    return math.isclose(a, float(b), rel_tol=1e-12, abs_tol=1e-9)


def replay(engine, src, market, chart, btc):
    options = {
        "chart_symbol": f"BINANCE:{market}",
        "chart_timeframe": "D",
        "execution_times": [END] * len(chart),
        "request_bars": {
            "BTC_USDT:swap:D": btc,
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
    core = src[: src.index("///////////////////\n// MONTHLY TABLE //")]
    result = engine.run_script(src, chart, **options)["strategy"]
    observed = engine.run_script(core + OBSERVE, chart, **options)
    assert observed["strategy"] == result
    plots = {p["title"]: p["values"] for p in observed["plots"]}
    reference = prices(btc)
    records, orders, lots = signals(chart, reference)
    for seen, expected in zip(plots["Support HLC3"], reference, strict=True):
        assert near(seen, expected)
    names = (
        "Support WMA",
        "Support Long Anchor",
        "Support Short Anchor",
        "Long gate",
        "Short gate",
        "Long close gate",
        "Short close gate",
        "Position",
    )
    for i, row in enumerate(records):
        for label, expected in zip(names, row[:-1], strict=True):
            seen = plots[label][i]
            assert seen is None if expected is None else near(seen, expected), (
                market,
                label,
                i,
                expected,
                seen,
            )
        assert near(result["equity"][i]["equity"], row[-1]), (market, i)
    for order, (i, moved, opening) in zip(result["orders"], orders, strict=True):
        assert (order["barIndex"], order["time"]) == (i, chart[i]["time"])
        assert near(order["qty"], moved) and near(order["price"], opening)
    verified = []
    for lot, (direction, quantity, entry, exit, gross, fee) in zip(
        result["trades"], lots, strict=True
    ):
        assert lot["id"] == ("Long" if direction > 0 else "Short")
        assert (lot["entryBarIndex"], lot["exitBarIndex"]) == (entry, exit)
        assert near(lot["qty"], direction * quantity) and near(
            lot["profit"], gross - fee
        )
        assert near(lot["entryPrice"], chart[entry]["open"]) and near(
            lot["exitPrice"], chart[exit]["open"]
        )
        verified.append(
            {**lot, "qty": float(quantity), "dir": direction, "commission": float(fee)}
        )
    return {
        "market": market,
        "bars": len(chart),
        "orders": result["orders"],
        "trades": verified,
        "ending_position": result["position"][-1],
        "ending_marked_equity": float(records[-1][-1]),
        "bars_with_wma": sum(x[0] is not None for x in records),
    }


def run(work, feeds, engine_root, output):
    assert sha256(engine_root / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(engine_root))
    import pine_compat as engine

    src = program(work / "source-3106.md")
    charts = {}
    for market, digest in FEEDS.items():
        path = feeds / f"5411-feed-{market}.json"
        assert sha256(path) == digest
        bars = [
            dict(zip(FIELDS, row, strict=True))
            for row in read(path)
            if START <= row[0] < END
        ]
        assert [b["time"] for b in bars] == list(range(START, END, DAY))
        charts[market] = bars
    cases = [
        replay(engine, src, m, chart, charts["BTCUSDT"]) for m, chart in charts.items()
    ]
    context = {
        "id": 3106,
        "group": "FMZ · Pine v5 · Verified fixed BTC daily reference",
        "exit": "WMA reversal or source HLC3 thresholds",
        "period": "Binance USD-M · 2022-10-25 to 2023-10-31 UTC exclusive",
        "archive_interval": "1d",
        "interval": "1d",
        "currency": "USDT",
    }
    results = [
        {
            **context,
            "market": c["market"],
            **ledger_metrics(
                c["trades"], CAPITAL, int(c["ending_position"]["size"] != 0)
            ),
        }
        for c in cases
    ]
    combined = [lot for c in cases for lot in c["trades"]]
    results.append(
        {
            **context,
            "market": "BTCUSDT + ETHUSDT",
            **ledger_metrics(
                combined,
                2 * CAPITAL,
                sum(int(c["ending_position"]["size"] != 0) for c in cases),
            ),
        }
    )
    write(
        output,
        {
            "schema": "FMZ 3106 exact daily Pine replay with fixed BTC perpetual reference",
            "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
            "source_sha256": SOURCE_SHA,
            "engine_sha256": ENGINE_SHA,
            "binance_daily_feeds_sha256": FEEDS,
            "notes": {
                "scope": "The saved BTC perpetual market and dates are used. ETH is a separate cross-asset run with the very same BTC perpetual HLC3 inputs, gated at equal-time UTC daily closes. The archived source remains untouched. A fixed report clock affects only the display table, whose removal was verified to leave every strategy output identical.",
                "orders": "Archived state transitions and thresholds, including short exits, are used verbatim. The archived one-hour base cannot change the modeled fills of the next-open market orders. The verifier checks the supplied daily open for each fill.",
                "sizing": "Archived 1000 USDT starting equity and 100% equity sizing, quantity grid 0.001, and 0.1% commission. The independent cash witness prices the target size using marked equity at the next open with commission headroom. All orders and daily equity balances reconcile.",
                "costs": "Source commission is charged on each fill. Gross uses the same quantities before subtracting commissions. Realized-only P&L and drawdown exclude unrealized positions and their commissions. Marked ending equity is separately available. Slippage and funding are outside this model.",
            },
            "coverage": [
                [
                    3106,
                    "Tested · Fixed BTC reference and source fees",
                    "Exact Pine v5 and pinned BTC daily perpetual HLC3 input, including the ETH comparison. Independent WMA, signed positions, order size, next-open fills, commission and daily marked equity reconcile.",
                ]
            ],
            "results": results,
            "scopes": cases,
        },
    )


if __name__ == "__main__":
    run(*map(Path, sys.argv[1:]))
