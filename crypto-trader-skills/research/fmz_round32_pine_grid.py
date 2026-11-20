"""Reconcile the archived grid's per-entry-ID lifecycle and dollar reporting."""

from __future__ import annotations

import argparse
import re
from collections import Counter, deque
from math import floor
from pathlib import Path
from shutil import copy2
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import (
    FMZ_SHA256,
    aggregate,
    date_ms,
    sha256,
    verified_archives,
)
from research.fmz_round7_pine import EXECUTION, summarize
from research.fmz_round12_pine_authored import provider_bars
from research.fmz_round18_pine_qqe import executable_lines
from research.fmz_round19_pine_broker import equal
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH

IDENT = 1946
CAPITAL = 100
FEE = 0.00025
MARKETS = ("BTCUSDT", "ETHUSDT")
DAY = 86_400_000
HOUR = 3_600_000
NAME = "FMZ Pine · Prior-grid signals · Named-lot lifecycle"
LABEL = {"native": "FMZ native window", "next": "Next equal window"}
PRECISION = ("0.001", "0.000001")
FX_START, FX_END = map(date_ms, ("2023-12-31", "2024-03-02"))


def source_record(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (row,) = (r for r in read(baseline)["disposition"] if r["id"] == IDENT)
    assert row["status"].startswith("Pending")
    with ZipFile(archive) as source:
        ((_, record, document, digest),) = documents(source, {IDENT: row})
    (raw,) = re.findall(
        r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", document
    )
    config = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)", raw
        )
    )
    assert config == {
        "start": "2024-01-01 00:00:00",
        "end": "2024-01-31 00:00:00",
        "period": "2h",
        "basePeriod": "15m",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    active = "\n".join(executable_lines(raw))
    assert "//@version=4" in raw
    checks = (
        'pyramiding=3000, close_entries_rule="ANY", default_qty_type=strategy.cash, initial_capital=100.0, currency="USD"',
        "commission_value=0.025",
        'defval="Hi & Low"',
        "defval=250",
        "defval=0.10",
        "defval=30",
        "defval=100",
        "isAfterStartDate = true",
        "highest(close, _bl) * (1 + _bd)",
        "lowest(close, _bl)  * (1 - _bd)",
        "for i = 0 to (array.size(gridLineArr) - 1)",
        "close < array.get(gridLineArr, i) and not array.get(orderArr, i)",
        "close > array.get(gridLineArr, i) and i != 0",
        "array.set(orderArr, buyId, true)",
        "array.set(orderArr, sellId, false)",
        'strategy.entry(id=tostring(buyId), long=true, qty=(initial_balance/(i_gridQty-1))/close, comment="#"+tostring(buyId))',
        'strategy.close(id=tostring(sellId), comment="#"+tostring(sellId))',
        "upperBound  := f_getGridBounds(i_boundSrc, i_boundLookback, i_boundDev, true)",
        "tradingtime= (timenow - start_time)/(86400000*30)",
    )
    assert all(token in active for token in checks)
    assert active.count("timenow") == 1
    assert active.index("strategy.entry(") < active.index("upperBound  :=")
    assert len(re.findall(r"\bstrategy\.(entry|order|exit|close)\(", active)) == 2
    return record, digest, config, raw.encode()


def data(public):
    a, b = map(date_ms, ("2024-01-01", "2024-01-31"))
    end = 2 * b - a
    archives = []
    windows = {}
    for market in MARKETS:
        files = verified_archives(
            public, market, "1h", ("2024-01", "2024-02"), archives
        )
        feed = [r for p in files for r in provider_bars(p, HOUR) if a <= r[0] < end]
        assert [r[0] for r in feed] == list(range(a, end, HOUR))
        for period, lo, hi in (("native", a, b), ("next", b, end)):
            candles = aggregate([r for r in feed if lo <= r[0] < hi], 2)
            assert [r[0] for r in candles] == list(range(lo, hi, 2 * HOUR))
            windows.setdefault(period, {})[market] = [list(r) for r in candles]
    return archives, windows


def stage(archive, baseline, work, public):
    _, _, _, raw = source_record(archive, baseline)
    _, candles = data(public)
    (work / "r32-grid-source.pine").write_bytes(raw)
    write(work / "r32-grid-feeds.json", candles)
    copy2(
        Path(__file__).with_name("fmz_round32_pine_grid_probe.py"),
        work / "r32_grid_probe.py",
    )


def grid_model(candles, step):
    window = deque(maxlen=250)
    bounds = None
    flags = [False] * 30
    lots = {}
    pending_open = []
    pending_close = []
    diary = []
    marked = []
    expected_orders = []
    for i, (t, op, _, _, close, _) in enumerate(candles):
        for id in pending_close:
            if id in lots:
                e, x, quantity = lots.pop(id)
                expected_orders.append((f"Close entry(s) order {id}", i, quantity, op))
                diary.append((str(id), e, i, quantity, x, op))
        for id, size in pending_open:
            if size:
                assert id not in lots
                lots[id] = (i, op, size)
                expected_orders.append((str(id), i, size, op))
        pending_open, pending_close = [], []
        if bounds is not None:
            lower, upper = bounds
            spacing = (upper - lower) / 29
            for k in range(30):
                level = lower + spacing * k
                if close < level and not flags[k] and k < 29:
                    flags[k] = True
                    qty = floor(((100 / 29) / close) / step + 1e-9) * step
                    pending_open.append((k, qty))
                if k and close > level and flags[k - 1]:
                    flags[k - 1] = False
                    pending_close.append(k - 1)
        window.append(close)
        bounds = (min(window) * 0.9, max(window) * 1.1) if len(window) == 250 else None
        marked.append(
            (None, None, len(lots), sum(t[2] for t in lots.values()))
            if bounds is None
            else (bounds[0], bounds[1], len(lots), sum(t[2] for t in lots.values()))
        )
    return expected_orders, diary, marked


def cross_rates(directory, name):
    path = directory / f"r32-grid-{name}.json"
    raw = read(path)
    days = {}
    for t, a, b, c, d, v in raw:
        if name == "coinbase":
            t, o, h, low, close = t * 1000, c, b, a, d
        else:
            o, h, low, close = a, c, d, b
        assert 0 < low <= min(o, close) <= max(o, close) <= h and v > 0
        assert t not in days
        days[t] = close
    assert sorted(days) == list(range(FX_START, FX_END + DAY, DAY))
    proof = {
        "series": "USDT/USD",
        "data_response_sha256": sha256(path),
        "candles": len(raw),
        "endpoint": (directory / f"r32-grid-{name}-url.txt").read_text().strip(),
        "daily_close": {str(t): days[t] for t in sorted(days)},
    }
    return days, proof


def convert(ledger, rates):
    flows = []
    for t0, t1, qty, entry, exit in ledger:
        rate0 = rates[t0 // DAY * DAY - DAY]
        rate1 = rates[t1 // DAY * DAY - DAY]
        exposure = qty * (entry * rate0 + exit * rate1)
        flows.append(
            (t1, qty * (exit - entry) * rate1, exposure * FEE, exposure * EXECUTION)
        )
    return flows


def validate(candles, case):
    orders, ledger, marks = grid_model(candles, float(case["quantity_grid"]))
    actual = case["strategy"]
    assert not case["diagnostics"] and not actual["diagnostics"]
    observations = case["observations"]
    observed = zip(
        *(observations[key] for key in ("Lower", "Upper", "Live grid", "Position")),
        strict=True,
    )
    for index, (a, b) in enumerate(zip(marks, observed, strict=True)):
        assert all(equal(x, y) for x, y in zip(a, b, strict=True)), (index, a, b)
    assert observations["Top guard"] == observations["Upper"] or all(
        equal(x, y)
        for x, y in zip(observations["Top guard"], observations["Upper"], strict=True)
    )
    assert observations["First guard"] == observations["Lower"]
    expected = Counter((name, i, round(qty, 12), px) for name, i, qty, px in orders)
    got = Counter(
        (r["id"], r["barIndex"], round(r["qty"], 12), r["price"])
        for r in actual["orders"]
    )
    assert expected == got
    for r in actual["orders"]:
        assert r["time"] == candles[r["barIndex"]][0]
        assert r["direction"] == (
            "strategy.close" if r["id"].startswith("Close ") else "strategy.long"
        )
    flows = []
    for (tag, i, j, qty, o, c), r in zip(ledger, actual["trades"], strict=True):
        assert (r["id"], r["entryBarIndex"], r["exitBarIndex"]) == (tag, i, j)
        expected_trade = (qty, o, c, qty * (c - o) - qty * (o + c) * FEE)
        assert all(
            equal(a, b)
            for a, b in zip(
                expected_trade,
                (r["qty"], r["entryPrice"], r["exitPrice"], r["profit"]),
                strict=True,
            )
        )
        assert (r["entryTime"], r["exitTime"]) == (candles[i][0], candles[j][0])
        flows.append((candles[i][0], candles[j][0], qty, o, c))
    return (
        flows,
        marks[-1][2],
        {
            "chart_bars": len(marks),
            "orders": len(orders),
            "closed": len(flows),
            "quantity_grid": case["quantity_grid"],
            "terminal_lots": marks[-1][2],
            "terminal_units": marks[-1][3],
        },
    )


def report(archive, baseline, work, public, fx_folder, output):
    record, digest, settings, raw = source_record(archive, baseline)
    manifest, windows = data(public)
    pine = work / "r32-grid-source.pine"
    feed = work / "r32-grid-feeds.json"
    raw_receipt = work / "r32-grid-results.json"
    assert pine.read_bytes() == raw and read(feed) == windows
    assert (work / "r32_grid_probe.exit").read_text().strip() == "0"
    native = work / "priced-runtime/pine_compat/pine_compat.pyd"
    assert sha256(native) == NATIVE_BINARY_HASH
    isolation = read(work / "round3-isolation-python.json")
    assert all(
        isolation[k][0] == "PermissionError" for k in ("file_error", "network_error")
    )
    runner = Path(__file__).with_name("fmz_round32_pine_grid_probe.py")
    assert runner.read_bytes() == (work / "r32_grid_probe.py").read_bytes()
    primary, v1 = cross_rates(fx_folder, "coinbase")
    sensitivity, v2 = cross_rates(fx_folder, "bitfinex")
    assert max(abs(primary[t] - sensitivity[t]) for t in primary) < 0.01
    cases = read(raw_receipt)
    scope = {(r["period"], r["market"], r["quantity_grid"]): r for r in cases}
    assert len(scope) == len(cases) == 8
    detail = {
        "id": IDENT,
        "source": record["source"],
        "name": record["name"],
        "source_sha256": digest,
        "archived_pine_sha256": sha256(pine),
        "group": NAME,
        "interval": "2h",
        "archive_interval": "2h",
        "market_data": "Official Binance USD-M 1h archives aggregated to 2h",
        "quote_currency": "USD",
        "comparison_fee": FEE,
        "exit": "Close at the next open after the adjacent grid's upper crossing",
    }
    rows, stats = [], []
    for period, markets in windows.items():
        pooled = []
        net_open = 0
        for market, candles in markets.items():
            for precision in PRECISION:
                case = scope[period, market, precision]
                ledger, opened, note = validate(candles, case)
                cashflows = convert(ledger, primary)
                original = summarize(cashflows, opened, CAPITAL)
                side = summarize(convert(ledger, sensitivity), opened, CAPITAL)
                stats.append(
                    {
                        "id": IDENT,
                        "period": LABEL[period],
                        "market": market,
                        **note,
                        "coinbase_usd": original,
                        "bitfinex_usd_sensitivity": side,
                    }
                )
                if precision == PRECISION[0]:
                    rows.append(
                        {
                            **detail,
                            "period": LABEL[period],
                            "market": market,
                            **original,
                        }
                    )
                    net_open += opened
                    pooled.extend(cashflows)
        rows.append(
            {
                **detail,
                "period": LABEL[period],
                "market": "BTCUSDT + ETHUSDT",
                **summarize(pooled, net_open, 2 * CAPITAL),
            }
        )
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(baseline),
            "archive_sha256": FMZ_SHA256,
            "pine_compat_binary_sha256": NATIVE_BINARY_HASH,
            "isolation_probe": isolation,
            "provider_archives": manifest,
            "historical_fx": [v1, v2],
            "source_audit": {
                "settings": settings,
                "source_sha256": digest,
                "pine_sha256": sha256(pine),
            },
            "artifacts": {f.name: sha256(f) for f in (pine, feed, runner, raw_receipt)},
            "per_case_order_counts": stats,
            "method": [
                "The archived code updates bounds after generating orders, so each decision uses the preceding grid. It assigns individual entry IDs by grid index and later calls close with that specific ID. The exact legacy Pine source and independent Python reproduce both grid boundaries, every order, the full named-lot ledger and terminal holdings.",
                "The saved two-hour Binance Futures chart is rebuilt from official hourly trade bars. The archive's 30 active grid levels, 250-bar lookback, 10% band extrapolation and $100 starting allocation are retained. Price entry occurs at the next observed opening price, while explicitly coded quantity uses 100/29 divided by the signal close.",
                "Workbook rows use the prespecified 0.001-unit grid. Both BTC scenarios produce zero executable entry quantities on that grid. The six and nine ETH closes retain their actual named lots. The separate 0.000001-unit sensitivity is a hypothetical fractional broker and does not contribute to the workbook. This market-data replay applies the stated quantity model without exchange min-notional, funding or live margin validation.",
                "The broker run expresses the source execution in quote-neutral prices and validates the 0.025% authored commission per leg. The report converts realized price differences at the prior UTC day's Coinbase Exchange USDT/USD close effective at exit. Each commission and execution allowance is translated at its own fill day's prior close. The Bitfinex conversion is a distinct sensitivity using its same-dated spot instrument. The chart signal and nominal per-grid quantity do not depend on FX.",
                "Source timenow is only used in a display statistic and is supplied at the archived bar close. Unsettled grid lots are reported without forced settlement.",
            ],
            "references": [
                "https://github.com/binance/binance-public-data",
                "https://www.tradingview.com/pine-script-docs/v4/essential/strategies/",
                "https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles",
                "https://docs.bitfinex.com/reference/rest-public-candles",
            ],
            "coverage": [
                [
                    IDENT,
                    f"Tested · {NAME}",
                    "Original grid-order IDs, per-lot fills, market quantity model and USD cashflows verified. Primary BTC scope is zero-fill and ETH closes 15 lots.",
                ]
            ],
            "results": rows,
        },
    )
    print(
        f"Verified {IDENT}: {len(rows)} workbook rows, {sum(s['closed'] for s in stats if s['quantity_grid'] == PRECISION[0])} primary closures."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "finalize"))
    for arg in ("archive", "baseline", "work", "public", "fx", "output"):
        parser.add_argument(f"--{arg}", type=Path, required=True)
    a = parser.parse_args()
    args = (a.archive, a.baseline, a.work, a.public)
    if a.mode == "stage":
        stage(*args)
    else:
        report(*args, a.fx, a.output)


if __name__ == "__main__":
    main()
