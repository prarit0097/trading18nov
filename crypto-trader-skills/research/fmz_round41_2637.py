"""Replay the archived SPY-driven FMZ strategy on BTC and ETH daily bars."""

import json
import math
import re
import sys
from bisect import bisect_right
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

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

SOURCE = "e45327cd1a96437a9af96aa1bb8dfc638e07d1d2bbfbb8924fc2931653e54f77"
BEGIN, END = map(date_ms, ("2023-10-13", "2023-11-12"))
HISTORY = BEGIN - 40 * DAY
FEE = Decimal("0.00075")
CAPITAL = 10_000
LOT = Decimal("0.001")
MONTHS = ("2023-09", "2023-10", "2023-11")
EQUITY_FEED = "https://query1.finance.yahoo.com/v8/finance/chart/SPY?period1=1690848000&period2=1702252800&interval=1d"
FUND_FEED = "https://www.ssga.com/library-content/products/fund-data/etfs/us/navhist-us-en-spy.xlsx"
SESSION_REFERENCE = "https://www.nyse.com/trade/hours-calendars"
MERGE_REFERENCE = "https://www.tradingview.com/pine-script-docs/v4/essential/context-switching-the-security-function"
OBSERVE = """
plot(ticker, title="SPY session close")
plot(curve, title="Coppock witness")
plot(longStopPrice, title="Trail witness")
"""


def source_program(document):
    assert sha256(document) == SOURCE
    fence = chr(96) * 3
    text = document.read_text(encoding="utf-8")
    (script,) = re.findall(
        r"(?ms)^" + fence + r" pinescript[^\n]*\n(.*?)^" + fence, text
    )
    script, count = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", script)
    assert count == 1 and 'security = input("SPY")' in script
    assert script.count('security(security, "D", close)') == 1
    return script.replace(
        'security = input("SPY")', 'spyTicker = input("SPY")'
    ).replace('security(security, "D", close)', 'security(spyTicker, "D", close)')


def fund_sessions(path):
    """Read the fund sponsor's public daily NAV dates and values."""
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with ZipFile(path) as book:
        strings = ElementTree.fromstring(book.read("xl/sharedStrings.xml"))
        sheet = ElementTree.fromstring(book.read("xl/worksheets/sheet1.xml"))
    names = ["".join(n.itertext()) for n in strings]
    sessions = {}
    for row in sheet.iter(namespace + "row"):
        a, b, *_ = [*row.findall(namespace + "c"), None, None]
        if a is None or b is None or a.get("t") != "s":
            continue
        t = names[int(a.findtext(namespace + "v"))]
        if re.fullmatch(r"\d{2}-[A-Za-z]{3}-\d{4}", t):
            dt = datetime.strptime(t, "%d-%b-%Y").replace(tzinfo=UTC)
            stamp = int(dt.timestamp()) * 1000
            assert stamp not in sessions
            sessions[stamp] = float(b.findtext(namespace + "v"))
    return sessions


def equity_sessions(feed, fund_book):
    [result] = json.loads(feed.read_bytes())["chart"]["result"]
    assert (
        result["meta"]["symbol"],
        result["meta"]["exchangeName"],
        result["meta"]["currency"],
        result["meta"]["exchangeTimezoneName"],
    ) == ("SPY", "PCX", "USD", "America/New_York")
    quotes = result["indicators"]["quote"][0]
    navs = fund_sessions(fund_book)
    first = date_ms("2023-09-01")
    dst_end = date_ms("2023-11-05")
    sessions = []
    for i, seconds in enumerate(result["timestamp"]):
        stamp = seconds * 1000
        day = stamp // DAY * DAY
        if not first <= day < END:
            continue
        opening, high, low, close = (round(quotes[k][i], 2) for k in FIELDS[1:5])
        assert low <= min(opening, close) <= max(opening, close) <= high
        assert stamp - day == (13.5 if day < dst_end else 14.5) * 3_600_000
        confirmed_at = stamp + 23_400_000
        sessions.append(
            (day, confirmed_at, opening, high, low, close, quotes["volume"][i])
        )
    assert len(sessions) == 50
    assert {x[0] for x in sessions} == {x for x in navs if first <= x < END}
    worst = max(abs(x[5] - navs[x[0]]) for x in sessions)
    assert worst < 0.30
    return sessions, worst


def signal_witness(closes):
    rates, curves = [], []
    for i, value in enumerate(closes):
        if i < 14:
            rates.append(None)
        else:
            rates.append(sum(100 * (value / closes[i - j] - 1) for j in (14, 11)))
        curves.append(
            None
            if i < 23
            else math.fsum(rates[j] * w for w, j in enumerate(range(i - 9, i + 1), 1))
            / 55
        )
    return curves


def ledger(chart, curves):
    orders, closed = [], []
    held = pending = None
    for bar, value in zip(chart, curves, strict=True):
        stamp, opening, *_ = bar
        price = Decimal(str(opening))
        if pending == "entry":
            qty = (Decimal(CAPITAL) / price).quantize(LOT, rounding=ROUND_DOWN)
            held = (stamp, price, qty)
            orders.append((stamp, opening, float(qty), "strategy.long"))
        elif pending == "exit":
            entered, entry, qty = held
            commission = (price + entry) * qty * FEE
            gross = (price - entry) * qty
            closed.append(
                {
                    "entryTime": entered,
                    "entryPrice": float(entry),
                    "exitTime": stamp,
                    "exitPrice": opening,
                    "qty": float(qty),
                    "dir": 1,
                    "gross": float(gross),
                    "commission": float(commission),
                    "profit": float(gross - commission),
                }
            )
            orders.append((stamp, opening, float(qty), "strategy.close"))
            held = None
        pending = None
        if stamp >= BEGIN and value is not None:
            if held is None and value > 0:
                pending = "entry"
            elif held is not None and value < 0:
                pending = "exit"
    terminal = None
    if held is not None:
        stamp, entry, qty = held
        mark = Decimal(str(chart[-1][4]))
        terminal = {
            "entryTime": stamp,
            "entryPrice": float(entry),
            "qty": float(qty),
            "mark": float(mark),
            "marked_unrealized": float((mark - entry) * qty),
            "entry_fee": float(entry * qty * FEE),
        }
    return orders, closed, terminal, pending


def check(engine, program, market, chart, sessions, warm):
    settlements = [x[1] for x in sessions]
    indices = [bisect_right(settlements, bar[0] + DAY) - 1 for bar in chart]
    assert indices[0] >= 0
    observed = [sessions[i] for i in indices]
    assert all(
        session[1] <= bar[0] + DAY for bar, session in zip(chart, observed, strict=True)
    )
    closes = [x[5] for x in observed]
    curves = signal_witness(closes)
    expected, closed, terminal, pending = ledger(chart, curves)
    if warm:
        program = program.replace("if (Bull)", f"if (Bull and time >= {BEGIN})")
        program = program.replace("if (Bear)", f"if (Bear and time >= {BEGIN})")
    bars = [dict(zip(FIELDS, x, strict=True)) for x in chart]
    sparse = [(x[0], *x[2:]) for x in sessions]
    dense = [(bar[0], *x[2:]) for bar, x in zip(chart, observed, strict=True)]
    reports = []
    for aux in (sparse, dense):
        frame = [dict(zip(FIELDS, x, strict=True)) for x in aux]
        requests = {f"SPY:{key}": frame for key in ("D", "1D", "1440")}
        requests["$chart"] = {
            "minMove": 1,
            "priceScale": 100 if market == "ETHUSDT" else 10,
            "minContract": ".001",
            "quantityStep": ".001",
            "pointValue": 1,
            "currency": "USDT",
        }
        receipt = engine.run_script(
            program + OBSERVE,
            bars,
            chart_timeframe="1D",
            chart_symbol=f"BINANCE:{market}",
            request_bars=requests,
        )
        strategy = receipt["strategy"]
        assert not receipt["diagnostics"] and not strategy["diagnostics"]
        plots = {x.get("title"): x.get("values") for x in receipt["plots"]}
        assert plots["SPY session close"] == closes
        for actual, witness in zip(plots["Coppock witness"], curves, strict=True):
            assert (
                actual is None
                if witness is None
                else math.isclose(actual, witness, abs_tol=1e-12)
            )
        assert all(x in (0, None) for x in plots["Trail witness"])
        native_orders = [
            (x["time"], x["price"], x["qty"], x["direction"])
            for x in strategy["orders"]
        ]
        assert native_orders == expected, (market, warm, native_orders, expected)
        for trade, native in zip(closed, strategy["trades"], strict=True):
            assert all(
                trade[k] == native[k]
                for k in ("entryTime", "entryPrice", "exitTime", "exitPrice", "qty")
            )
            assert math.isclose(trade["gross"], native["profit"], abs_tol=1e-9)
        assert strategy["position"][-1]["size"] == (terminal["qty"] if terminal else 0)
        reports.append(strategy)
    assert reports[0] == reports[1]
    return {
        "market": market,
        "prehistory_days": warm,
        "chart_days": len(chart),
        "signals": curves,
        "orders": expected,
        "closed": closed,
        "terminal": terminal,
        "pending_at_cutoff": pending,
    }


def main(document, feed, nav, hours, days, engine_root, output):
    assert sha256(engine_root / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(engine_root))
    import pine_compat

    sessions, max_nav_diff = equity_sessions(feed, nav)
    program = source_program(document)
    receipts, cases = [], []
    for market in ("BTCUSDT", "ETHUSDT"):
        mini = verified_archives(hours, market, "1h", MONTHS, receipts)
        daily = verified_archives(days, market, "1d", MONTHS, receipts)
        chart = aggregate(prices(mini, HISTORY, END, 3_600_000), 24)
        direct = prices(daily, HISTORY, END, DAY)
        assert all(a[:5] == b[:5] for a, b in zip(chart, direct, strict=True))
        for warm in (0, 40):
            bars = [b for b in chart if b[0] >= BEGIN - warm * DAY]
            cases.append(check(pine_compat, program, market, bars, sessions, warm))
    results = []
    for warm in (0, 40):
        common = {
            "id": 2637,
            "period": "2023-10-13 to 2023-11-12 UTC exclusive",
            "group": "FMZ Pine v4 · SPY Coppock · "
            + ("warm start" if warm else "cold start"),
            "currency": "USDT",
            "interval": "1d",
            "archive_interval": "1d",
            "pine_source_version": "4",
            "exit": "Authored negative curve market exit",
            "order_family": "Fixed cash-sized next-open market orders",
        }
        selected = [c for c in cases if c["prehistory_days"] == warm]
        for pair in [[selected[0]], [selected[1]], selected]:
            results.append(
                {
                    **common,
                    "market": " + ".join(c["market"] for c in pair),
                    **ledger_metrics(
                        [t for c in pair for t in c["closed"]],
                        CAPITAL * len(pair),
                        sum(bool(c["terminal"]) for c in pair),
                    ),
                }
            )
    write(
        output,
        {
            "schema": "FMZ #2637 verified SPY session merge and independent cash-sized ledger",
            "source_url": "https://www.fmz.com/strategy/431926",
            "source_sha256": SOURCE,
            "runtime_sha256": ENGINE_SHA,
            "equity_close": {
                "url": EQUITY_FEED,
                "sha256": sha256(feed),
                "sessions": sessions,
            },
            "sponsor_calendar_check": {
                "url": FUND_FEED,
                "sha256": sha256(nav),
                "matched_sessions": len(sessions),
                "max_nav_close_gap_usd": max_nav_diff,
            },
            "binance": receipts,
            "references": {
                "exchange_session": SESSION_REFERENCE,
                "pine_v4_merge": MERGE_REFERENCE,
            },
            "notes": {
                "compatibility": "Renamed the local SPY input variable shadowing security. Kept the source periods, arguments and orders. The warm control allows source orders only from the archived start.",
                "merge": "At each completed UTC crypto daily bar, SPY contributes its most recent confirmed 16:00 New York regular-session close, held between sessions. Sparse date-keyed and dense causally projected feeds give identical orders; providing equity-opening timestamps directly to this compatibility engine instead creates a one-crypto-bar lag. The sponsor daily NAV file independently confirms all session dates. NAV is a reference, while the replay uses the vendor's unadjusted close.",
                "cost": "Source cash sizing uses 10,000 per entry and a 0.001 quantity increment. The comparison applies a separate 0.075% fee per side to closed lots. No funding, observed execution cost, or leverage liquidation is modeled. The default 100% trail submits a zero stop and never touches positive market prices.",
            },
            "cases": cases,
            "results": results,
            "coverage": [
                [
                    2637,
                    "Tested · confirmed SPY session feed and independent Coppock ledger",
                    "Source SPY input, causal session-close gaps, cash sizing and next opens verified on BTC/ETH. Exact cold starts hold one open lot per market. The prehistory control closes one per market.",
                ]
            ],
        },
    )


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
