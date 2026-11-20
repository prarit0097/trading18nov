"""Verify the saved #2425 dual-stop entry and unconditional close behavior."""

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
from research.fmz_round18_5745 import ENGINE_SHA, FIELDS
from research.fmz_round26_977 import prices

SOURCE = "550d07629e9f90240fafe4f3e32b044b089279c423c20671b2ff4ded6954aa4b"
BEGIN, END = map(date_ms, ("2024-01-26", "2024-02-15"))
MONTHS = ("2024-01", "2024-02")
STEP, FEE = Decimal(".001"), Decimal(".001")
CAPITAL = 100
MARKETS = ("BTCUSDT", "ETHUSDT")


def program(doc):
    assert sha256(doc) == SOURCE
    fence = chr(96) * 3
    text = doc.read_text(encoding="utf-8")
    assert "|v_input_9|false|Show label (drawdown)|" in text
    (body,) = re.findall(r"(?ms)^" + fence + r" pinescript[^\n]*\n(.*?)^" + fence, text)
    body, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", body)
    assert n == 1
    assert "if true\n    strategy.close_all()" in body
    assert body.count("strategy.entry(") == 2 and body.count("strategy.exit(") == 2
    adjusted, n = re.subn(r"\binput\(([^,]+), defval = ([^,]+),", r"input(\1,", body)
    assert n == 14
    assert 'showdd    = input(false, title = "Show label (drawdown)")' in adjusted
    return adjusted


def near(a, b):
    return math.isclose(a, float(b), rel_tol=1e-12, abs_tol=1e-8)


def reconcile(chart, minutes, native):
    cash = Decimal(CAPITAL)
    active = planned = exit_stop = long_stop = short_stop = order_qty = None
    orders = iter(native["orders"])
    trades = iter(native["trades"])
    settled = []
    stops_verified = 0
    for i, (stamp, opening, _, _, close, _) in enumerate(chart):
        before = active[1] if active else Decimal(0)
        if active:
            entered, q, ep, open_minute = active
            px = Decimal(str(opening))
            # The close-all market order at the next opening exits before the protective stop.
            assert (
                px > exit_stop
                and minutes[240 * i][:2] == (stamp, opening)
                and minutes[240 * i][5] > 0
            )
            lot = next(trades)
            gross = q * (px - ep)
            fees = q * (px + ep) * FEE
            assert (
                lot["entryBarIndex"],
                lot["exitBarIndex"],
                lot["entryPrice"],
                lot["exitPrice"],
            ) == (entered, i, float(ep), opening)
            assert (
                lot["exitTime"] == stamp
                and near(lot["qty"], q)
                and near(lot["profit"], gross - fees)
            )
            settled.append(
                {**lot, "entryTime": open_minute, "dir": 1, "commission": float(fees)}
            )
            cash += gross - q * px * FEE
            active = None
        children = minutes[240 * i : 240 * (i + 1)]
        assert short_stop is None or all(child[3] > short_stop for child in children)
        first = next(
            (r for r in children if long_stop is not None and r[2] >= long_stop), None
        )
        if first is not None:
            when, minute_open, _, _, _, volume = first
            assert volume > 0
            fill = Decimal(str(max(long_stop, minute_open)))
            last_close = Decimal(str(chart[i - 1][4]))
            size = cash / (last_close * (1 + FEE)) if order_qty is None else order_qty
            q = size // STEP * STEP
            event = next(orders)
            assert (event["id"], event["time"], event["barIndex"], event["price"]) == (
                "Long",
                stamp,
                i,
                float(fill),
            )
            assert near(event["qty"], q)
            cash -= q * fill * FEE
            active = i, q, fill, when
            long_stop = None
            stops_verified += 1
        qty = active[1] if active else Decimal(0)
        market_price = Decimal(str(close))
        equity = cash + (market_price - active[2]) * qty if active else cash
        assert near(native["equity"][i]["equity"], equity)
        if qty != before:
            planned = equity / market_price
        if active:
            fast = chart[i - 19 : i + 1]
            exit_stop = (
                Decimal(str(max(r[2] for r in fast)))
                + Decimal(str(min(r[3] for r in fast)))
            ) / 2
        elif i >= 49:
            slow = chart[i - 49 : i + 1]
            long_stop = max(r[2] for r in slow)
            short_stop = min(r[3] for r in slow)
            order_qty = planned
    assert next(orders, None) is None and next(trades, None) is None
    return settled, active is not None, stops_verified


def run(doc, data, runtime, out):
    assert sha256(runtime / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(runtime))
    import pine_compat

    source = program(doc)
    manifest, scopes = [], []
    for market in MARKETS:
        minutes = prices(
            verified_archives(data, market, "1m", MONTHS, manifest), BEGIN, END, 60_000
        )
        quarters = prices(
            verified_archives(data, market, "15m", MONTHS, manifest),
            BEGIN,
            END,
            900_000,
        )
        chart = aggregate(quarters, 16)
        assert [r[:5] for r in aggregate(minutes, 240)] == [r[:5] for r in chart]
        bars = [dict(zip(FIELDS, r, strict=True)) for r in chart]
        request = {
            "$chart": {
                "minMove": 1,
                "priceScale": 10 if market == "BTCUSDT" else 100,
                "quantityStep": ".001",
                "minContract": ".001",
                "pointValue": 1,
                "currency": "USDT",
            }
        }
        options = {
            "chart_symbol": f"BINANCE:{market}",
            "chart_timeframe": "240",
            "request_bars": request,
        }
        replay = pine_compat.run_script(source, bars, **options)
        native = replay["strategy"]
        assert not replay["diagnostics"]
        # 49 cold decisions each attempted two not-yet-defined Donchian prices.
        assert len(native["diagnostics"]) == 98 and {
            x["code"] for x in native["diagnostics"]
        } == {"E_STRATEGY_PRICE"}
        settled, ending, verified = reconcile(chart, minutes, native)
        assert len(settled) == (11 if market == "BTCUSDT" else 9) and ending == (
            market == "ETHUSDT"
        )
        scopes.append(
            {
                "market": market,
                "trades": settled,
                "ending_open": ending,
                "verified_entry_stops": verified,
                "cold_rejected_entry_calls": len(native["diagnostics"]),
            }
        )
    rows = []
    for market, cases in (
        (MARKETS[0], scopes[:1]),
        (MARKETS[1], scopes[1:]),
        ("BTCUSDT + ETHUSDT", scopes),
    ):
        rows.append(
            {
                "id": 2425,
                "group": "FMZ Pine v4 · Turtle stops and next-open close-all",
                "period": "Saved Jan–Feb 2024 · Binance USD-M",
                "market": market,
                "exit": "Unconditional source close-all at next open",
                "interval": "4h · 1m proof",
                "archive_interval": "4h",
                "currency": "USDT",
                "pine_source_version": "4",
                **ledger_metrics(
                    [t for c in cases for t in c["trades"]],
                    CAPITAL * len(cases),
                    sum(c["ending_open"] for c in cases),
                ),
            }
        )
    write(
        out,
        {
            "schema": "FMZ 2425 · Preserved Donchian entries and source close-all",
            "source_sha256": SOURCE,
            "runtime_sha256": ENGINE_SHA,
            "archives": manifest,
            "notes": {
                "source": "Remove duplicate defval arguments, retaining the serialized FMZ settings. For the display-only drawdown label, the saved false value resolves its conflicting named default. No risk parameter was added.",
                "fills": "The saved 4h BTC window and same-dates ETH replay use verified 15m bases independent of 1m path data. Each long stop is checked against its first touched minute. The other armed stop does not trigger. Unconditional source close-all exits on the next traded opening before the protective stop.",
                "sizing": "Independently observed fee-aware entry sizing uses the prior decision close until live position changes supply an explicit source quantity. Both markets start with 100 USDT. Source 0.1% per-side commissions and all marked equity reconcile. Stops are modeled prices, and historical resting order depth and funding are outside this comparison.",
                "warmup": "49 early bars attempt two undefined channel stops each. The native broker rejects them, matching the independent empty opening state.",
            },
            "coverage": [
                [
                    2425,
                    "Tested · Saved Donchian stops and unconditional close-all",
                    "Serialized defaults, 21 stop entries, 20 settled lots, one unsettled ETH position and every source-fee equity mark verified.",
                ]
            ],
            "scopes": scopes,
            "results": rows,
        },
    )


if __name__ == "__main__":
    run(*map(Path, sys.argv[1:]))
