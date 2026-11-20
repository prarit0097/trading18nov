"""Reconcile #564 saved daily order gates and one-minute trailing exits."""

import json
import math
import re
import sys
from collections import deque
from decimal import Decimal
from itertools import pairwise
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
from research.fmz_round31_dema_tsi import PINE_EMA, ema

SOURCE = "d4bddc38a5fd57be481ff952000d61aa4764136f3f67b667c8c5b3bdb2f31502"
FX_SHA = "bd51343985c1e01c7918525fc59c2a907d6668ec271070deb0c07e21973ace4d"
FX_URL = "https://api.exchange.coinbase.com/products/USDT-USD/candles?granularity=86400&start=2022-09-10T00%3A00%3A00Z&end=2023-01-18T00%3A00%3A00Z"
BEGIN, END = map(date_ms, ("2022-09-11", "2023-01-18"))
MONTHS = ("2022-09", "2022-10", "2022-11", "2022-12", "2023-01")
CAPITAL = 1_000_000
FEE, LOT = Decimal(".0008"), Decimal(".001")
MARKETS = ("BTCUSDT", "ETHUSDT")
OBS = (
    "htfClose",
    "leadLine1",
    "leadLine2",
    "MFTsourceHTF",
    "volumeHTF",
    "macd",
    "signal",
    "mf",
    "rsi",
    "atr",
    "minATR",
    "UT?1:0",
    "entry_long?1:0",
    "exit_long?1:0",
    "longTPPrice",
    "longTakeProfitPrice",
    "longTrailingTakeProfitStepTicks",
)


def source(doc):
    assert sha256(doc) == SOURCE
    text = doc.read_text(encoding="utf-8")
    assert (
        "|v_input_18|8|Fixed SL (%)|" in text and "|v_input_25|false|Min ATR|" in text
    )
    fence = chr(96) * 3
    (archive,) = re.findall(
        r"(?ms)^" + fence + r" pinescript[^\n]*\n(.*?)^" + fence, text
    )
    body, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", archive)
    assert n == 1
    edits = (
        ('group="MACD", group="MACD",', 'group="MACD",'),
        (
            'step=0.1, defval=1, tooltip="Use 100 to turn off',
            'step=0.1, tooltip="Use 100 to turn off',
        ),
        (
            'step=0.001, defval=1, tooltip="Use 0 to turn off',
            'step=0.001, tooltip="Use 0 to turn off',
        ),
    )
    for a, b in edits:
        assert body.count(a) == 1
        body = body.replace(a, b)
    assert "long_trailing =1.3" in body and "useTP1 = false" in body
    assert (
        "enableTrailing = input(defval = true" in body
        and "commission_value=0.08" in body
    )
    code = body + "\n" + "\n".join(f'plot({x},title="{x}")' for x in OBS) + "\n"
    restored = code.replace("//@version=4\n", "//@version=4\n" + PINE_EMA + "\n")
    return code, re.sub(r"\bema\(", "compat_ema(", restored)


def fx(doc):
    assert sha256(doc) == FX_SHA
    rows = {
        t * 1000 + DAY: Decimal(str(close))
        for t, _, _, _, close, _ in json.loads(doc.read_bytes())
        if BEGIN - DAY <= t * 1000 < END - DAY
    }
    assert sorted(rows) == list(range(BEGIN, END, DAY))
    schema = {
        "schemaVersion": 1,
        "pairs": [
            {
                "from": "USDT",
                "to": "USD",
                "rates": [
                    {"effectiveTime": k, "rate": float(v)}
                    for k, v in sorted(rows.items())
                ],
            }
        ],
    }
    return rows, schema


def smooth(items, n, mode):
    if mode == "sma":
        q = deque(maxlen=n)
        out = []
        for value in items:
            q.append(value)
            out.append(math.fsum(q) / n if len(q) == n else None)
        return out
    init = []
    seed = None
    out = []
    for x in items:
        if x is not None:
            if seed is None:
                init.append(x)
                if len(init) == n:
                    seed = math.fsum(init) / n
            else:
                seed = (seed * (n - 1) + x) / n
        out.append(seed)
    return out


def check(plots, last, chart):
    closes = [x["close"] for x in last]
    positive, negative = [None], [None]
    tr = [None]
    atr = [None]
    for prev, now in pairwise(last):
        change = now["close"] - prev["close"]
        positive.append(max(0, change))
        negative.append(max(0, -change))
        tr.append(
            max(
                now["high"] - now["low"],
                abs(now["high"] - prev["close"]),
                abs(now["low"] - prev["close"]),
            )
        )
        value = tr[-1]
        atr.append(value if atr[-1] is None else atr[-1] + (value - atr[-1]) / 40)
    up = smooth(positive, 34, "rma")
    down = smooth(negative, 34, "rma")
    rsi = [
        None if a is None or b is None else 100 if b == 0 else 100 - 100 / (1 + a / b)
        for a, b in zip(up, down, strict=True)
    ]
    fast = ema(closes, 19)
    slow = smooth(closes, 19, "sma")
    macd = [a - b for a, b in zip(ema(closes, 7), ema(closes, 23), strict=True)]
    signal = ema(macd, 10)
    typical = [(x["high"] + x["low"] + x["close"]) / 3 for x in last]
    volume = [x["volume"] for x in last]
    ups, downs = [], []
    for i, (p, v) in enumerate(zip(typical, volume, strict=True)):
        before = typical[i - 1] if i else p
        ups.append(v * p if p > before or i == 0 else 0)
        downs.append(v * p if p < before or i == 0 else 0)
    money = [None] * 14
    for i in range(14, len(closes)):
        p = math.fsum(ups[i - 14 : i + 1])
        q = math.fsum(downs[i - 14 : i + 1])
        money.append(100 if q == 0 else 100 - 100 / (1 + p / q))
    expected = {
        "htfClose": closes,
        "leadLine1": fast,
        "leadLine2": slow,
        "MFTsourceHTF": typical,
        "volumeHTF": volume,
        "macd": macd,
        "signal": signal,
        "rsi": rsi,
        "atr": atr,
        "mf": money,
        "minATR": [0] * len(closes),
    }
    for name, array in expected.items():
        for i, (observed, want) in enumerate(zip(plots[name], array, strict=True)):
            assert (
                (observed is None)
                if want is None
                else math.isclose(observed, want, rel_tol=1e-11, abs_tol=1e-8)
            ), (name, i, want, observed)

    ready = []
    for i, bar in enumerate(chart):
        uptrend = slow[i] is not None and fast[i] > slow[i]
        cross = i > 0 and macd[i - 1] <= signal[i - 1] and macd[i] > signal[i]
        mf_cross = (
            i > 0
            and money[i - 1] is not None
            and money[i - 1] <= 12 < money[i]
            and uptrend
        )
        candidate = (
            (cross or mf_cross)
            and rsi[i] is not None
            and rsi[i] < 100
            and bar["close"] > 0
            and atr[i] > 0
        )
        assert plots["UT?1:0"][i] == int(uptrend)
        assert plots["entry_long?1:0"][i] == int(candidate)
        if candidate and uptrend:
            ready.append(i)
    return ready, atr


def ordered_stop(minutes, activation, distance, tick):
    top = None

    def walk(values, start):
        high = start
        for i, p in enumerate(values):
            if high is not None:
                stop = (high - distance) // tick * tick
                if p <= stop:
                    return high, p if i == 0 else stop
            if p >= activation:
                high = max(p, high or p)
        return high, None

    for t, o, h, low, c, volume in minutes:
        assert volume > 0
        paths = []
        for values in ((o, h, low, c), (o, low, h, c)):
            paths.append(walk((Decimal(str(x)) for x in values), top))
        assert paths[0] == paths[1], t
        top, fill = paths[0]
        if fill is not None:
            return t, fill, top
    raise AssertionError("The verified trailing control did not finish")


def replay(engine, programs, data, market, manifest, exchange, rates):
    files = verified_archives(data, market, "5m", MONTHS, manifest)
    units = prices(files, BEGIN, END, 300_000)
    objects = lambda rows: [dict(zip(FIELDS, x, strict=True)) for x in rows]
    chart = objects(aggregate(units, 288))
    last = objects(units[287::288])
    tick = Decimal(".1" if market == "BTCUSDT" else ".01")
    sym = f"BINANCE:{market}"
    settings = {
        "minMove": 1,
        "priceScale": int(1 / tick),
        "quantityStep": ".001",
        "minContract": ".001",
        "pointValue": 1,
        "currency": "USDT",
    }
    options = {
        "chart_symbol": sym,
        "chart_timeframe": "D",
        "request_bars": {
            sym + ":5": last,
            "$chart": settings,
            "$currencyRates": exchange,
        },
    }
    legacy, restored = [engine.run_script(p, chart, **options) for p in programs]
    assert not legacy["diagnostics"] and not restored["diagnostics"]
    raw = legacy["strategy"]
    actual = restored["strategy"]
    assert not raw["diagnostics"] and raw == actual
    full = {
        **options,
        "request_bars": {**options["request_bars"], sym + ":5": objects(units)},
    }
    reference = engine.run_script(programs[1], chart, **full)
    assert reference["plots"] == restored["plots"] and reference["strategy"] == actual
    plots = {p["title"]: p["values"] for p in restored["plots"] if p.get("title")}
    (i,), atr = check(plots, last, chart)
    (entry,) = actual["orders"]
    assert (
        entry["barIndex"] == i + 1
        and entry["direction"] == "strategy.long"
        and not actual["trades"]
    )
    start = entry["time"]
    op = Decimal(str(entry["price"]))
    e_rate = rates[start]
    qty = Decimal(CAPITAL) / (op * e_rate * (1 + FEE)) // LOT * LOT
    assert entry["qty"] == float(qty)
    anchor = Decimal(str(chart[i]["close"])) * Decimal("1.04")
    target = op * Decimal("1.04")
    fixed_stop = float(op * Decimal(".92"))
    source_high = chart[i]["high"]
    eligible = next(
        j for j in range(i + 1, len(chart)) if Decimal(str(chart[j]["close"])) > target
    )
    for j in range(i + 1, eligible + 1):
        threshold = source_high - 2 * atr[j]
        assert chart[j]["close"] >= max(fixed_stop, threshold)
        assert plots["exit_long?1:0"][j] == 0
        assert math.isclose(
            plots["longTakeProfitPrice"][j], float(anchor), abs_tol=1e-8
        )
    after = chart[eligible + 1]["time"]
    minute_source = verified_archives(data, market, "1m", ("2023-01",), manifest)
    minute = prices(minute_source, after, END, 60_000)
    assert minute[0][1] == chart[eligible + 1]["open"] and minute[0][5] > 0
    # The other trailing condition uses 1.3 times the signal bar high as a distance.
    assert float(op) + 1.3 * source_high > max(x[2] for x in minute)
    end, exit_price, peak = ordered_stop(minute, anchor, anchor * Decimal(".005"), tick)
    assert end < after + DAY
    exit_rate = rates[end // DAY * DAY]
    gross = qty * (exit_price - op) * exit_rate
    fees = qty * (op * e_rate + exit_price * exit_rate) * FEE
    return {
        "market": market,
        "qty": float(qty),
        "entry_timestamp": start,
        "exit_timestamp": end,
        "first_trailing_bar": after,
        "parent_bars": len(chart),
        "reference_bars": len(units),
        "trail_peak": float(peak),
        "fill_mark_usdt": float(exit_price),
        "trade": {
            "dir": 1,
            "qty": float(qty),
            "entryTime": start,
            "exitTime": end,
            "entryPrice": float(op * exit_rate),
            "exitPrice": float(exit_price * exit_rate),
            "commission": float(fees),
            "profit": float(gross - fees),
        },
    }


def run(doc, data, runtime, out):
    assert sha256(runtime / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(runtime))
    import pine_compat

    programs = source(doc)
    rates, fx_schema = fx(data / "USD-FX-2022-09-10-2023-01-18.json")
    archives = []
    books = [
        replay(pine_compat, programs, data, m, archives, fx_schema, rates)
        for m in MARKETS
    ]
    rows = []
    for m, s in (
        (MARKETS[0], books[:1]),
        (MARKETS[1], books[1:]),
        ("BTCUSDT + ETHUSDT", books),
    ):
        rows.append(
            {
                "id": 564,
                "group": "FMZ Pine v4 · Confirmed intrabar MACD and trailing replay",
                "period": "Saved Sep 2022–Jan 2023 · Binance USD-M",
                "market": m,
                "exit": "Source trailing activation followed by confirmed 1m stop",
                "archive_interval": "1d",
                "interval": "1d · 5m requests · 1m price path",
                "pine_source_version": "4",
                "currency": "USD",
                **ledger_metrics([x["trade"] for x in s], CAPITAL * len(s), 0),
            }
        )
    write(
        out,
        {
            "schema": "FMZ 564 · Saved 5m inputs and causal legacy trailing comparison",
            "source_sha256": SOURCE,
            "engine_sha256": ENGINE_SHA,
            "fx": {"url": FX_URL, "sha256": FX_SHA},
            "archives": archives,
            "references": {
                "trailing": "https://www.tradingview.com/pine-script-docs/v4/essential/strategies/",
                "merge": "https://www.tradingview.com/pine-script-docs/v5/concepts/other-timeframes-and-data/",
            },
            "notes": {
                "source": "Archived UI defaults resolve duplicated group, fixed stop (8%) and minimum ATR (0). The intra-day request's 5m values enter the saved daily chart only from the last completed intrabar. Full and last-only request realizations give identical engine traces.",
                "entry": "Confirmed chart decisions reconcile independently with MACD, volume MFI, trend EMA/SMA, RSI and True Range smoothing. Both EMA initializations give the same broker orders. Prior-day Coinbase FX converts source equity and the 0.08% commission.",
                "exit": "The raw interpreter leaves the orders open despite the archived profit gate. Independently reconstruct the scheduled trailing order from the source and first eligible next-bar tick. Two price-ordering bounds on each actual minute agree through the first stop and produce a valid tick-level price. The other trailing activation remains outside the archived price range.",
                "model": "Next-open entries and minute path stops are inferred historical fills. Source size is retained. Venue queue and actual fill size are outside the scope of this calculation.",
            },
            "coverage": [
                [
                    564,
                    "Tested · Verified daily entry and minute trail comparison",
                    "Saved 5m source projection, independent entry gates and USD fees. One BTC and one ETH close under a checked one-minute trailing path; raw interpreter limitations documented.",
                ]
            ],
            "scopes": books,
            "results": rows,
        },
    )


if __name__ == "__main__":
    run(*map(Path, sys.argv[1:]))
