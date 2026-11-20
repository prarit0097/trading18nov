"""Verify the published #1598 grid state and broker close-price settlement."""

import math
import re
import sys
from collections import defaultdict, deque
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
from research.fmz_round21_1988 import ema as sma_seeded_ema
from research.fmz_round26_977 import prices
from research.fmz_round31_dema_tsi import PINE_EMA, ema

SOURCE = "bda4b994489a289661e787e6742372df31abb966b83ed87e5da2fd9b4b11f512"
BEGIN, WARMUP, TAIL = map(date_ms, ("2023-02-19", "2023-01-23", "2024-02-01"))
END = TAIL + 320 * 60_000
ANCHOR, PERIOD = date_ms("2023-02-20"), 28 * DAY
CAPITAL = 10_000
LOT, FEE = Decimal(".001"), Decimal(".001")
MARKETS = ("BTCUSDT", "ETHUSDT")
MONTHS = (*(f"2023-{i:02d}" for i in range(1, 13)), "2024-01")


def model(bars, pivot, sma):
    balance = 500000.0
    quantity = position_cash = avg = 0.0
    oldbuy = oldsell = limitbuy = limitsell = final = None
    peak = 0.0
    ma_value = None
    nbuys = nsells = 0
    events = []
    prev_pp = None
    bar_lock = 0
    summaries = []

    def valid(a, b, fn):
        return a is not None and b is not None and fn(a, b)

    def down(width, pp):
        if final is None:
            return bars[0][1]
        if valid(oldsell, pp, lambda a, b: a <= b):
            if quantity > 0:
                return (oldbuy if oldbuy is not None else oldsell) - width
            return pp
        if oldbuy is not None:
            return oldbuy - width
        if oldsell is not None:
            return (
                pp
                if valid(oldsell - width, pp, lambda a, b: a > b)
                else oldsell - width
            )
        return None

    def up(width):
        if oldsell is not None:
            return oldsell + width
        return None if oldbuy is None else max(avg, oldbuy + width)

    def tri(n):
        return n * (n + 1) / 2

    for i, ((t, o, h, l, c, v), pp, ma) in enumerate(
        zip(bars, pivot, sma, strict=True)
    ):
        nbuys = nbuys or 0
        nsells = nsells or 0
        nb = 4 if valid(limitbuy, ma_value, lambda a, b: a >= b) else 5
        ns = 4 if valid(limitsell, ma_value, lambda a, b: a < b) else 20
        for _ in range(max(nb, ns)):
            width = peak * 0.75 / 5
            d, u = down(width, pp), up(width)
            buy = (
                d is not None
                and min(l, o) <= d
                and nbuys is not None
                and nbuys <= nb - 1
            )
            sell = (
                u is not None
                and max(h, o) >= u
                and nsells is not None
                and nsells <= ns - 1
            )
            cash = max(0, balance - quantity * avg)
            spend = (
                0.10 * cash
                if final is None
                else min(cash, cash / (nb - (nbuys or 0)))
                if (nb - (nbuys or 0))
                else cash
            )
            ded = tri(ns) - tri(nsells or 0)
            take = (
                min(quantity, quantity * ((nsells or 0) + 1) / ded) if ded else quantity
            )
            if (
                valid(pp, prev_pp, lambda p, q: p != q)
                and nbuys == 0
                and (nsells or 0) != 0
                and d is not None
            ):
                ma_value = ma
                limitbuy = d
            if buy and spend > 0:
                ma_value = ma
                oldbuy = min(o, d)
                oldsell = None
                final = oldbuy
                nbuys += 1
                nsells = None
                q = spend / oldbuy
                quantity += q
                position_cash += oldbuy * q
                avg = position_cash / quantity
                balance -= q * oldbuy * 0.001
                bar_lock = i
                peak = max(peak, oldbuy)
                width = peak * 0.75 / 5
                limitbuy = oldbuy - width if nbuys <= nb - 1 else None
                limitsell = up(width)
                events.append((i, 1, q, c, oldbuy))
            elif sell and take > 0 and bar_lock != i:
                ma_value = ma
                oldbuy = None
                oldsell = max(o, u)
                final = oldsell
                nbuys = None
                nsells += 1
                position_cash -= avg * take
                quantity -= take
                balance += (oldsell - avg) * take
                balance -= oldsell * take * 0.001
                bar_lock = i
                peak = oldsell
                width = peak * 0.75 / 5
                limitbuy = down(width, pp)
                limitsell = oldsell + width if nsells <= ns - 1 else None
                events.append((i, -1, take, c, oldsell))
        prev_pp = pp
        summaries.append((quantity, avg, balance))
    return events, summaries


def source(doc):
    assert sha256(doc) == SOURCE
    fence = chr(96) * 3
    (raw,) = re.findall(
        r"(?ms)^" + fence + r" pinescript[^\n]*\n(.*?)^" + fence,
        doc.read_text(encoding="utf-8"),
    )
    body, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", raw)
    assert n == 1
    assert body.count("strategy.initial_capital") == 6
    assert body.count("strategy.initial_capital = 50000") == 1
    refs = [
        line.strip() for line in body.splitlines() if "strategy.initial_capital" in line
    ]
    assert {line.split(":=")[0].strip() for line in refs[1:]} == {
        "RealizedPnL",
        "PRealizedPnL",
        "PURealizedPnL",
        "BuyAndHold",
        "PBuyAndHold",
    }
    body = body.replace(
        "strategy.initial_capital = 50000", "float displayCapital = 50000"
    ).replace("strategy.initial_capital", "displayCapital")
    assert body.count("timestamp('01 Jan 1970 00:00 +000')") == 1
    body = body.replace("timestamp('01 Jan 1970 00:00 +000')", "0")
    body += '\nplot(time("4W"),title="Four-week starts")\nplot(AvgPrice,title="Internal price")\nplot(PositionSize,title="Internal quantity")\nplot(Balance,title="Internal balance")\n'
    portable = body.replace(
        "//@version=5\n", "//@version=5\n" + PINE_EMA + "\n"
    ).replace("ta.ema(", "compat_ema(")
    return body, portable


def partition(rows):
    by_period = defaultdict(list)
    for row in rows:
        start = (row[0] - ANCHOR) // PERIOD * PERIOD + ANCHOR
        by_period[start].append(row)
    complete = {
        t: aggregate(group, 28)[0] for t, group in by_period.items() if len(group) == 28
    }
    assert all(x[0] == t for t, x in complete.items())
    return complete


def near(a, b):
    return math.isclose(a, float(b), rel_tol=1e-10, abs_tol=1e-8)


def broker(rows, events, actual):
    orders = iter(actual["orders"])
    trades = iter(actual["trades"])
    open_lots = deque()
    closed = []
    total_fees = Decimal(0)
    for i, direction, quantity, close, _ in events:
        native = next(orders)
        label = "Buy" if direction == 1 else "Close entry(s) order Buy"
        qty = Decimal(str(quantity)) // LOT * LOT
        px = Decimal(str(close))
        t = rows[i][0]
        known_close = rows[i][4]
        assert (native["id"], native["barIndex"], native["time"], native["price"]) == (
            label,
            i,
            t,
            known_close,
        )
        assert near(native["qty"], qty) and close == known_close
        realized_at = min(t + DAY, END)
        total_fees += qty * px * FEE
        if direction == 1:
            open_lots.append((i, qty, px, realized_at))
            continue
        remaining = qty
        while remaining:
            opened, size, first, entry_ts = open_lots.popleft()
            taken = min(remaining, size)
            measured = next(trades)
            gross = taken * (px - first)
            charge = taken * (px + first) * FEE
            assert (
                measured["entryBarIndex"],
                measured["exitBarIndex"],
                measured["entryPrice"],
                measured["exitPrice"],
            ) == (opened, i, float(first), float(px))
            assert near(measured["qty"], taken) and near(measured["profit"], gross)
            closed.append(
                {
                    "dir": 1,
                    "qty": float(taken),
                    "entryPrice": float(first),
                    "exitPrice": float(px),
                    "entryTime": entry_ts,
                    "exitTime": realized_at,
                    "commission": float(charge),
                    "profit": float(gross - charge),
                }
            )
            if taken < size:
                open_lots.appendleft((opened, size - taken, first, entry_ts))
            remaining -= taken
    assert next(orders, None) is None and next(trades, None) is None
    assert near(actual["position"][-1]["size"], sum(x[1] for x in open_lots))
    return closed, len(open_lots), float(total_fees)


def replay(engine, programs, market, complete, partial):
    visible = [r for r in complete if r[0] >= BEGIN] + partial
    buckets = partition(complete)

    def encode(dataset):
        return [dict(zip(FIELDS, row, strict=True)) for row in dataset]

    chart = encode(visible)
    symbol = f"BINANCE:{market}"
    options = {
        "chart_timeframe": "D",
        "chart_symbol": symbol,
        "request_bars": {
            symbol + ":4W": encode(list(buckets.values())),
            symbol + ":D": chart,
            "$chart": {
                "minMove": 1,
                "priceScale": 10 if market == "BTCUSDT" else 100,
                "quantityStep": ".001",
                "minContract": ".001",
                "pointValue": 1,
                "currency": "USDT",
            },
        },
    }
    pivot = []
    group_starts = []
    for bar in visible:
        current = (bar[0] - ANCHOR) // PERIOD * PERIOD + ANCHOR
        previous = buckets.get(current - PERIOD)
        pivot.append(math.fsum(previous[2:5]) / 3 if previous else None)
        group_starts.append(current)
    closes = [r[4] for r in visible]
    cases = []
    for code, baseline in zip(programs, (sma_seeded_ema, ema), strict=True):
        result = engine.run_script(
            code, chart, execution_times=[END] * len(chart), **options
        )
        actual = result["strategy"]
        assert not result["diagnostics"] and not actual["diagnostics"]
        charts = {p["title"]: p["values"] for p in result["plots"] if p.get("title")}
        assert charts["Four-week starts"] == group_starts
        for shown, want in zip(charts["PP"], pivot, strict=True):
            assert shown is None if want is None else near(shown, want)
        orders, trace = model(visible, pivot, [None] + baseline(closes, 100)[:-1])
        for i, (qty, price, balance) in enumerate(trace):
            assert near(charts["Internal quantity"][i], qty)
            assert near(charts["Internal price"][i], price)
            assert near(charts["Internal balance"][i], balance)
        cases.append(broker(visible, orders, actual))
    assert cases[0] == cases[1]
    settled, open_count, fees = cases[-1]
    return {
        "market": market,
        "decision_bars": len(visible),
        "tested_pivot_buckets": len(buckets),
        "trades": settled,
        "ending_open_lots": open_count,
        "all_order_fees": fees,
    }


def run(doc, hourly, minute, runtime, out):
    assert sha256(runtime / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(runtime))
    import pine_compat

    programs = source(doc)
    receipts, checks, results = [], [], []
    for market in MARKETS:
        sources = verified_archives(hourly, market, "1h", MONTHS, receipts)
        tail_inputs = verified_archives(minute, market, "1m", ("2024-02",), receipts)
        dated = aggregate(prices(sources, WARMUP, TAIL, 3_600_000), 24)
        truncated = aggregate(prices(tail_inputs, TAIL, END, 60_000), 320)
        checks.append(replay(pine_compat, programs, market, dated, truncated))
    assert [len(r["trades"]) for r in checks] == [5, 6]
    for market, books in (
        (MARKETS[0], checks[:1]),
        (MARKETS[1], checks[1:]),
        ("BTCUSDT + ETHUSDT", checks),
    ):
        stats = ledger_metrics(
            [t for x in books for t in x["trades"]],
            CAPITAL * len(books),
            sum(x["ending_open_lots"] for x in books),
        )
        mark = stats["gross"] - sum(x["all_order_fees"] for x in books)
        results.append(
            {
                "id": 1598,
                "group": "FMZ Pine v5 · Archived grid and close-price FIFO",
                "period": "Saved Feb 2023–Feb 2024 · Binance USD-M",
                "market": market,
                "exit": "Source grid reduction at confirmed bar close",
                "archive_interval": "1d",
                "interval": "1d · confirmed 4-week pivots",
                "pine_source_version": "5",
                "currency": "USDT",
                "realized_gross": stats["gross"],
                "realized_after_fees": mark,
                "realized_net": mark,
                **stats,
            }
        )
    write(
        out,
        {
            "schema": "FMZ 1598 · Source grid state and no-lookahead close execution",
            "source_sha256": SOURCE,
            "engine_sha256": ENGINE_SHA,
            "archives": receipts,
            "notes": {
                "source": "Preserve the source code's independent 500,000 USDT sizing balance and 10,000 USDT broker capital. Isolate the invalid 50,000 display assignment from broker and grid decisions. Normalize a malformed UTC epoch string to its unambiguous zero timestamp.",
                "cutoff": "The saved BTC daily scope and matched ETH use official hourly archives, plus 320 confirmed one-minute candles on February 1 to honor the 05:20 UTC cutoff. Four-week candles use the independently matched UTC Monday phase and supply only previous completed values.",
                "verification": "Independent simulation matches every internal balance, inventory and average price. Standard first-source EMA and runtime SMA startup produce the same broker events. Market reductions and entries use confirmed closes and independently reconcile lot sizes, FIFO and before-fee realized P&L.",
                "economics": "The displayed account uses 0.1% fees per fill under source commission. Internal fees affect source sizing, while broker P&L measures actual close-price fills. Closed P&L is distinct from total fee cash flow including open entries. No funding, market impact or real margin acceptance is modeled. The fixed source balance can size positions far above the broker starting capital.",
            },
            "coverage": [
                [
                    1598,
                    "Tested · Verified grid state and close-price FIFO",
                    "Saved dates and exact minute cutoff. Independently reconciled confirmed pivots, inventory, original sizing and all 11 closed FIFO fragments.",
                ]
            ],
            "scopes": checks,
            "results": results,
        },
    )


if __name__ == "__main__":
    run(*map(Path, sys.argv[1:]))
