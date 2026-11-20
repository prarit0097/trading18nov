"""Reconcile legacy Pine orders whose archived trailing calls omit the offset."""

import json
import math
import re
import sys
from collections import deque
from datetime import UTC, datetime
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

QUARTER = 900_000
CAPITAL = 1_000_000
STEP, FEE = Decimal(".001"), Decimal(".00075")
SPECS = {
    2345: (
        "2023-10-07",
        "2023-11-06",
        4,
        QUARTER,
        "60",
        "1h",
        1,
        "7a4ddf4f4161bf496b588ed5a123b77c3c38141f6fb082e67243a77c21768d63",
    ),
    4104: (
        "2023-02-22",
        "2024-02-28",
        24,
        4 * QUARTER,
        "D",
        "1d",
        3,
        "1a32aa779ea5f3144846bfcfa383c716b99eea7442aac7aa068ef464a25976cb",
    ),
    3047: (
        "2022-09-14",
        "2023-09-20",
        8,
        QUARTER,
        "120",
        "2h",
        1,
        "aed5576c23649999cd196395fe3f8c66d9ab524d75ae862719cb99188988c6b5",
    ),
}
FX = {
    (
        "2022-09-13",
        "2023-05-01",
    ): "124483a1a1d37605c2e02f3182464ae7407c3f5fdf78d0919318787c5bdd8d07",
    (
        "2023-05-01",
        "2023-11-06",
    ): "8b2d4d8188e5c92aab3947ca7dd39fe774a55a2d167f282ae6b90a3f71d33f34",
    (
        "2023-11-06",
        "2024-02-28",
    ): "e95df5720b22fc782ffd7dfd4f989c9035e418bf552e4441c86892362b468d60",
}
OBS = '\nplot(longCondition?1:0,"Buy gate")\nplot(shortCondition?1:0,"Sell gate")\n'


def sources(doc, digest):
    assert sha256(doc) == digest
    fence = chr(96) * 3
    (raw,) = re.findall(
        r"(?ms)^" + fence + r" pinescript[^\n]*\n(.*?)^" + fence,
        doc.read_text(encoding="utf-8"),
    )
    native, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", raw)
    assert (
        n == 1
        and native.count("strategy.entry(") == native.count("strategy.exit(") == 2
    )
    assert "trail_offset" not in native and "trail_price" not in native
    reduced, n = re.subn(
        r"(?m)^if \(exit(?:long|short)\)[ \t]*\n    strategy\.exit\([^\n]+\)\n",
        "",
        native,
    )
    reduced, k = re.subn(
        r"(?m)^    strategy\.exit\([^\n]*trail_points=TrailS\)[ \t]*\n", "", reduced
    )
    assert n + k == 2
    return native, reduced + OBS


def daily_rates(directory):
    rates, provenance = {}, []
    for (start, end), digest in FX.items():
        doc = directory / f"USDTUSD-{start}-{end}.json"
        assert sha256(doc) == digest
        endpoint = "https://api.exchange.coinbase.com/products/USDT-USD/candles?granularity=86400"
        url = f"{endpoint}&start={start}T00%3A00%3A00Z&end={end}T00%3A00%3A00Z"
        provenance.append({"sha256": digest, "url": url})
        for t, _, _, _, close, _ in json.loads(doc.read_bytes()):
            effective = t * 1000 + DAY
            value = Decimal(str(close))
            assert rates.setdefault(effective, value) == value and value > 0
    return rates, provenance


def sma(series, n):
    q = deque(maxlen=n)
    out = []
    for x in series:
        if x is not None:
            q.append(x)
        out.append(math.fsum(q) / n if len(q) == n else None)
    return out


def stochastic_gates(chart, ident):
    length, k_width, d_width = (54, 12, 3) if ident == 2345 else (11, 3, 3)
    raw = [None] * (length - 1)
    for i in range(length - 1, len(chart)):
        block = chart[i - length + 1 : i + 1]
        high = max(r[2] for r in block)
        low = min(r[3] for r in block)
        raw.append(100 * (chart[i][4] - low) / (high - low) if high > low else None)
    k = sma(raw, k_width)
    d = sma(k, d_width)
    mk = sma(raw, k_width * 3)
    md = sma(k, d_width * 3)
    result = []
    for i, (a, b, c, e) in enumerate(zip(k, d, mk, md, strict=True)):
        if i == 0 or any(
            x is None for x in (a, b, c, e, mk[i - 1], md[i - 1], k[i - 1])
        ):
            result.append((0, 0))
            continue
        buy = (
            mk[i - 1] <= 50 < c
            and a > 50
            and a > b
            and c > e
            and (ident == 2345 or a > k[i - 1])
        )
        sell = (
            md[i - 1] >= 50 > e
            and a < 50
            and a < b
            and c < e
            and (ident == 2345 or a < k[i - 1])
        )
        result.append((int(buy), int(sell)))
    return result


def magnet_gates(chart, market):
    scale = 10 if market == "BTCUSDT" else 100
    result = [(0, 0)]
    for i in range(1, len(chart)):
        scaled = chart[i - 1][4] * scale
        remainder = scaled % 500
        level = (scaled - remainder + (500 if remainder >= 250 else 0)) / scale
        around = chart[max(0, i - 9) : i + 1]
        distance = chart[i][4] - level
        result.append(
            (
                int(0 < distance <= 100 and min(x[3] for x in around) > level),
                int(-100 <= distance < 0 and max(x[2] for x in around) < level),
            )
        )
    return result


def close_lot(lot, stamp, opening, rate):
    side, qty, purchase, entry_price, entry_rate = lot
    gross = side * qty * (opening - entry_price) * rate
    fee = FEE * qty * (entry_price * entry_rate + opening * rate)
    return gross, {
        "dir": side,
        "qty": float(qty),
        "entryTime": purchase,
        "exitTime": stamp,
        "entryPrice": float(entry_price * rate),
        "exitPrice": float(opening * rate),
        "commission": float(fee),
        "profit": float(gross - fee),
    }


def broker(chart, children, span, rates, gates, cap, ids, actual):
    cash = Decimal(CAPITAL)
    active = []
    closed = []
    next_side = 0
    measured = iter(actual["orders"])
    lots = iter(actual["trades"])
    for i, bar in enumerate(chart):
        stamp = bar[0]
        opening = Decimal(str(bar[1]))
        closing = Decimal(str(bar[4]))
        rate = rates[stamp // DAY * DAY]
        side = active[0][0] if active else 0
        if next_side and (next_side != side or len(active) < cap):
            transfer = Decimal(0)
            if side and next_side != side:
                for prior in active:
                    gross, book = close_lot(prior, stamp, opening, rate)
                    native = next(lots)
                    assert (native["entryTime"], native["exitTime"], native["qty"]) == (
                        prior[2],
                        stamp,
                        prior[0] * float(prior[1]),
                    )
                    assert (native["entryPrice"], native["exitPrice"]) == (
                        float(prior[3]),
                        float(opening),
                    )
                    assert math.isclose(float(gross), native["profit"], abs_tol=1e-7)
                    cash += gross
                    closed.append(book)
                    transfer += prior[1]
                active = []
            marked = cash + sum(p[0] * p[1] * (opening - p[3]) * rate for p in active)
            qty = marked / (opening * rate) // STEP * STEP
            assert qty >= STEP
            order = next(measured)
            assert children[i * span][0:2] == bar[0:2] and children[i * span][5] > 0
            assert (order["id"], order["barIndex"], order["time"], order["price"]) == (
                ids[next_side],
                i,
                stamp,
                float(opening),
            )
            assert math.isclose(order["qty"], float(transfer + qty), abs_tol=1e-9)
            active.append((next_side, qty, stamp, opening, rate))
        floating = sum(p[0] * p[1] * (closing - p[3]) * rate for p in active)
        assert math.isclose(
            float(cash + floating),
            actual["equity"][i]["equity"],
            rel_tol=1e-12,
            abs_tol=1e-6,
        )
        buy, sell = gates[i]
        assert not (buy and sell)
        next_side = buy - sell
    assert next(measured, None) is None and next(lots, None) is None
    return closed, len(active)


def run(directory, hourly, quarter, runtime, out):
    assert sha256(runtime / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(runtime))
    import pine_compat

    fx, provenance = daily_rates(directory)
    rows, archives, scopes = [], [], []
    for ident, (start, end, span, step, frame, interval, cap, digest) in SPECS.items():
        native, reduced = sources(directory / f"{ident}.md", digest)
        lo, hi = map(date_ms, (start, end))
        days = range(lo, hi, DAY)
        months = sorted(
            {datetime.fromtimestamp(x / 1000, UTC).strftime("%Y-%m") for x in days}
        )
        fx_pairs = {
            "schemaVersion": 1,
            "pairs": [
                {
                    "from": "USDT",
                    "to": "USD",
                    "rates": [{"effectiveTime": x, "rate": float(fx[x])} for x in days],
                }
            ],
        }
        feed, tf = (hourly, "1h") if step == 4 * QUARTER else (quarter, "15m")
        decisions = []
        for market in ("BTCUSDT", "ETHUSDT"):
            files = verified_archives(feed, market, tf, months, archives)
            base = prices(files, lo, hi, step)
            chart = aggregate(base, span)
            bars = [dict(zip(FIELDS, x, strict=True)) for x in chart]
            request = {
                "$chart": {
                    "minMove": 1,
                    "priceScale": 10 if market == "BTCUSDT" else 100,
                    "quantityStep": ".001",
                    "minContract": ".001",
                    "pointValue": 1,
                    "currency": "USDT",
                },
                "$currencyRates": fx_pairs,
            }
            opts = {
                "chart_symbol": f"BINANCE:{market}",
                "chart_timeframe": frame,
                "request_bars": request,
            }
            baseline = pine_compat.run_script(native, bars, **opts)["strategy"]
            isolated = pine_compat.run_script(reduced, bars, **opts)
            actual = isolated["strategy"]
            for k in ("orders", "trades", "position", "equity"):
                assert baseline[k] == actual[k]
            assert not isolated["diagnostics"] and not actual["diagnostics"]
            known = {p["title"]: p["values"] for p in isolated["plots"] if "title" in p}
            gates = (
                magnet_gates(chart, market)
                if ident == 3047
                else stochastic_gates(chart, ident)
            )
            for i, (buy, sell) in enumerate(gates):
                assert (known["Buy gate"][i], known["Sell gate"][i]) == (buy, sell), (
                    ident,
                    market,
                    i,
                )
            ids = (
                {1: "LongMagnet", -1: "ShortMagnet"}
                if ident == 3047
                else {1: "Lungo", -1: "Corto"}
            )
            led, opened = broker(chart, base, span, fx, gates, cap, ids, actual)
            decisions.append(
                {
                    "id": ident,
                    "market": market,
                    "chart_bars": len(chart),
                    "ending_lots": opened,
                    "trades": led,
                    "no_offset_diagnostic_count": len(baseline["diagnostics"]),
                }
            )
        scopes.extend(decisions)
        for label, sample in (
            ("BTCUSDT", decisions[:1]),
            ("ETHUSDT", decisions[1:]),
            ("BTCUSDT + ETHUSDT", decisions),
        ):
            rows.append(
                {
                    "id": ident,
                    "group": "FMZ Pine v3 · Archived trailing activation has no offset",
                    "period": f"Saved window · {start} to {end} UTC exclusive",
                    "market": label,
                    "exit": "Opposite source entry, next observed open",
                    "archive_interval": interval,
                    "interval": interval,
                    "pine_source_version": "3",
                    "currency": "USD",
                    **ledger_metrics(
                        [t for c in sample for t in c["trades"]],
                        CAPITAL * len(sample),
                        sum(c["ending_lots"] for c in sample),
                    ),
                }
            )
    write(
        out,
        {
            "schema": "FMZ 2345/4104/3047 · Verified Pine v3 order state with incomplete trailing calls",
            "archive_inputs": list({r["url"]: r for r in archives}.values()),
            "fx_inputs": provenance,
            "source_sha256": {k: v[-1] for k, v in SPECS.items()},
            "engine_sha256": ENGINE_SHA,
            "notes": {
                "legacy": "TradingView's v5 migration notes state that legacy strategy.exit calls without a usable order type had no effect. Here each trail_points call lacks trail_offset. Exact archived runs and the no-op isolation agree over every order, position, realized lot and equity mark.",
                "market": "Official USD-M opening fills checked on each archived base interval. Prior completed Coinbase USDT/USD closes value cash and trades. Percent sizing follows the authored setting, including three possible lots for #4104. The test uses the broker's default starting 1,000,000 USD per market.",
                "fees": "Source has no explicit commission. The 0.075% per-side overlay uses each fill day's FX and leaves authored pre-overlay sizing intact. Funding, spread and liquidation are outside these scopes.",
            },
            "reference": "https://www.tradingview.com/pine-script-docs/v5/migration-guides/to-pine-version-5/",
            "coverage": [
                [
                    i,
                    "Tested · Legacy Pine v3 with inert incomplete trails",
                    "Saved BTC/ETH scopes. Exact legacy and isolation runs agree on all equity, positions and transactions. Independent decisions and USD sizing checked.",
                ]
                for i in SPECS
            ],
            "results": rows,
            "scopes": scopes,
        },
    )


if __name__ == "__main__":
    run(*map(Path, sys.argv[1:]))
