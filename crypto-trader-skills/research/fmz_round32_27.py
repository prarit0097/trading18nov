"""Backtest #27 with archived 3h CCI decisions and historical trade flow."""

import csv
import gzip
import hashlib
import io
import json
import math
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile

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

SOURCE = "6fa3e5d075915c22b5cdf3aa41652c1d0cfd36b6aab2b9c985bfec8b4f56f1f0"
ROOT = "https://data.binance.vision/data/futures/um/daily/aggTrades"
QUARTER, BAR = 900_000, 10_800_000
BEGIN, END = map(date_ms, ("2023-09-12", "2023-10-12"))
MAX_TAPE_MS = 120_000
STEP, FEE = Decimal(".001"), Decimal(".00075")
CAPITAL = 1_000_000
PARTICIPATION = (Decimal(".10"), Decimal(".25"))
MARKETS = ("BTCUSDT", "ETHUSDT")


def program(document):
    assert sha256(document) == SOURCE
    fence = chr(96) * 3
    (raw,) = re.findall(
        r"(?ms)^" + fence + r" pinescript[^\n]*\n(.*?)^" + fence,
        document.read_text(encoding="utf-8"),
    )
    code, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", raw)
    assert n == 1 and "//@version=4" in code
    prefix, unused, orders = re.split(
        r"(?m)(?=^resCustom =|^if \(not na\(vcci\)\))", code
    )
    assert "request.security" in unused and "nAMA" in unused
    assert set(re.findall(r"\b(?:ucci|dcci|vcci|overSold|overBought)\b", orders)) == {
        "ucci",
        "dcci",
        "vcci",
        "overSold",
        "overBought",
    }
    for variable in (
        "resCustom",
        "Length",
        "xPrice",
        "xvnoise",
        "nfastend",
        "nslowend",
        "nsignal",
        "nnoise",
        "nefratio",
        "nsmooth",
        "nAMA",
        "basis1",
        "slope",
    ):
        assert not re.search(rf"\b{variable}\b", orders)
    assert orders.count("profit = 0.01, loss = 0.005") == 2
    return (
        prefix
        + orders
        + '\nplot(ucci,"High CCI")\nplot(dcci,"Low CCI")\nplot(vcci,"OHLC4 CCI")\n'
    )


def cci(series):
    out = [None] * 10
    for i in range(10, len(series)):
        items = series[i - 10 : i + 1]
        mean = math.fsum(items) / 11
        deviation = math.fsum(abs(x - mean) for x in items) / 11
        out.append((series[i] - mean) / (0.015 * deviation) if deviation else None)
    return out


def entries(engine, code, directory, market, manifest):
    paths = verified_archives(
        directory, market, "15m", ("2023-09", "2023-10"), manifest
    )
    base = prices(paths, BEGIN, END, QUARTER)
    chart = [dict(zip(FIELDS, row, strict=True)) for row in aggregate(base, 12)]
    tick = Decimal(".1" if market == "BTCUSDT" else ".01")
    meta = {
        "minMove": 1,
        "priceScale": int(1 / tick),
        "quantityStep": ".001",
        "minContract": ".001",
        "pointValue": 1,
        "currency": "USDT",
    }
    raw = engine.run_script(
        code,
        chart,
        chart_symbol=f"BINANCE:{market}",
        chart_timeframe="180",
        request_bars={"$chart": meta},
    )
    assert not raw["diagnostics"] and not raw["strategy"]["diagnostics"]
    high = cci([r["high"] for r in chart])
    low = cci([r["low"] for r in chart])
    middle = cci(
        [math.fsum(r[k] for k in ("open", "high", "low", "close")) / 4 for r in chart]
    )
    for label, corresponding in (
        ("High CCI", high),
        ("Low CCI", low),
        ("OHLC4 CCI", middle),
    ):
        (shown,) = [p["values"] for p in raw["plots"] if p.get("title") == label]
        for actual, expected in zip(shown, corresponding, strict=True):
            assert (
                actual is None
                if expected is None
                else math.isclose(actual, expected, rel_tol=1e-11, abs_tol=1e-8)
            )
    selected = []
    for i in range(11, len(chart) - 1):
        if middle[i] is None:
            continue
        long = low[i - 1] <= -150 < low[i]
        short = high[i - 1] >= 150 > high[i]
        assert not (long and short)
        if long or short:
            fill = chart[i + 1]
            assert base[(i + 1) * 12][1] == fill["open"] and base[(i + 1) * 12][5] > 0
            selected.append((fill["time"], fill["open"], 1 if long else -1))
    book = raw["strategy"]
    opens = [
        (o["time"], o["price"], 1 if o["id"] == "CCILE" else -1)
        for o in book["orders"]
        if o["id"] in ("CCILE", "CCISE")
    ]
    assert selected == opens and len(book["trades"]) == len(opens) == 21
    assert all(
        t["entryTime"] == t["exitTime"] and abs(t["qty"]) == 1 for t in book["trades"]
    )
    return selected, len(chart)


def read_public(url):
    with urlopen(url, timeout=30) as response:
        return response.read()


def collect_one(job):
    market, day, stamps = job
    name = f"{market}-aggTrades-{day}.zip"
    url = f"{ROOT}/{market}/{name}"
    archive = read_public(url)
    digest = hashlib.sha256(archive).hexdigest()
    assert read_public(url + ".CHECKSUM").decode().split() == [digest, name]
    captures = {x: [] for x in stamps}
    with ZipFile(io.BytesIO(archive)) as z, z.open(z.namelist()[0]) as handle:
        for row in csv.reader(io.TextIOWrapper(handle, encoding="utf-8")):
            if not row[0].isdigit():
                continue
            t = int(row[5])
            for x in stamps:
                if x <= t < x + MAX_TAPE_MS:
                    captures[x].append([int(row[0]), row[1], row[2], t])
            if t >= max(stamps) + MAX_TAPE_MS:
                break
    return {
        "market": market,
        "day": day,
        "url": url,
        "sha256": digest,
        "captures": captures,
    }


def collect(tape_path, schedule):
    days = defaultdict(list)
    for market, orders in schedule.items():
        for stamp, _, _ in orders:
            day = datetime.fromtimestamp(stamp / 1000, UTC).date().isoformat()
            days[market, day].append(stamp)
    with ThreadPoolExecutor(max_workers=3) as pool:
        captured = list(
            pool.map(collect_one, ((m, d, ts) for (m, d), ts in days.items()))
        )
    if tape_path.suffix == ".gz":
        tape_path.write_bytes(
            gzip.compress(json.dumps(captured, separators=(",", ":")).encode(), mtime=0)
        )
    else:
        write(tape_path, captured)


def trade(rows, opening, side, tick, share):
    assert Decimal(str(opening)) == Decimal(rows[0][1])
    entry_cash = exit_cash = entered = exited = Decimal(0)
    entry_at = stop = target = None
    stop_active = False
    round_mode = ROUND_CEILING if side == 1 else ROUND_FLOOR
    prev = (rows[0][3], rows[0][0] - 1)
    for ident, px, qty, t in rows:
        assert (t, ident) > prev
        prev = t, ident
        price = Decimal(px)
        supplied = (Decimal(qty) * share // STEP) * STEP
        if entered < 1:
            got = min(1 - entered, supplied)
            entered += got
            entry_cash += got * price
            if entered == 1:
                entry_at = t
                target = (entry_cash / tick + side).to_integral_value(
                    rounding=round_mode
                ) * tick
                stop = (entry_cash / tick - side).to_integral_value(
                    rounding=round_mode
                ) * tick
                assert side * stop < side * entry_cash < side * target
            continue
        stop_active |= side * price <= side * stop
        if stop_active or side * price > side * target:
            got = min(1 - exited, supplied)
            exited += got
            exit_cash += got * (price if stop_active else target)
        if exited == 1:
            cost = (entry_cash + exit_cash) * FEE
            net = side * (exit_cash - entry_cash) - cost
            return {
                "dir": side,
                "qty": 1,
                "entryTime": entry_at,
                "exitTime": t,
                "entryPrice": float(entry_cash),
                "exitPrice": float(exit_cash),
                "commission": float(cost),
                "profit": float(net),
            }
    raise AssertionError("Incomplete scenario in available trade tape")


def run(document, data, runtime, tape_path, out):
    assert sha256(runtime / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(runtime))
    import pine_compat

    code = program(document)
    bars, schedule, chart_counts = [], {}, {}
    for market in MARKETS:
        schedule[market], chart_counts[market] = entries(
            pine_compat, code, data, market, bars
        )
    if not tape_path.exists():
        collect(tape_path, schedule)
    payload = tape_path.read_bytes()
    if tape_path.suffix == ".gz":
        payload = gzip.decompress(payload)
    receipts = json.loads(payload)
    assert len(receipts) == 31
    tapes = {
        (a["market"], int(t)): r for a in receipts for t, r in a["captures"].items()
    }
    assert set(tapes) == {(m, t) for m in MARKETS for t, _, _ in schedule[m]}
    output, details = [], []
    for limit in PARTICIPATION:
        by_market = {}
        for market in MARKETS:
            tick = Decimal(".1" if market == "BTCUSDT" else ".01")
            assert all(len(tapes[market, t]) >= 2 for t, _, _ in schedule[market])
            books = []
            delays = []
            for stamp, opening, side in schedule[market]:
                settled = trade(tapes[market, stamp], opening, side, tick, limit)
                delay = settled["exitTime"] - stamp
                assert 0 <= delay < MAX_TAPE_MS < BAR
                delays.append(delay)
                books.append(settled)
            by_market[market] = books
            details.append(
                {
                    "market": market,
                    "volume_share": float(limit),
                    "max_seconds_to_close": max(delays) / 1000,
                    "long_entries": sum(x["dir"] == 1 for x in books),
                    "position_closed_before_next_signal": True,
                }
            )
        for label, subset in (
            (MARKETS[0], MARKETS[:1]),
            (MARKETS[1], MARKETS[1:]),
            ("BTCUSDT + ETHUSDT", MARKETS),
        ):
            output.append(
                {
                    "id": 27,
                    "group": "FMZ Pine v4 · CCI and trade-print participation",
                    "period": f"{limit:.0%} print share · Saved Sep–Oct 2023",
                    "market": label,
                    "exit": "One-tick bracket using chronological prints",
                    "archive_interval": "3h",
                    "interval": "3h · trade tape",
                    "pine_source_version": "4",
                    "currency": "USDT",
                    **ledger_metrics(
                        [t for m in subset for t in by_market[m]],
                        CAPITAL * len(subset),
                        0,
                    ),
                }
            )
    write(
        out,
        {
            "schema": "FMZ 27 · Source CCI orders with timestamped trade participation model",
            "source_sha256": SOURCE,
            "engine_sha256": ENGINE_SHA,
            "chart_counts": chart_counts,
            "candle_archives": bars,
            "binance_trade_archives": [
                {k: v for k, v in x.items() if k != "captures"} for x in receipts
            ],
            "notes": {
                "source": "The saved chart is three hours despite the source title. Removing the unused 15m adaptive average leaves every variable used by orders intact. CCI signals and the next observed open reconcile independently. Published fractional target and stop tick distances each imply one exchange tick in the compatibility broker.",
                "execution": "The same signals start each one-unit order on the first observed new-bar print. Each execution consumes at most the modeled percentage of each chronological aggregate-trade print, rounded down to the minimum lot. After entry completes, tick-grid protective stops trigger the exit market flow. Resting targets use strict trade-through and fill at their displayed limit. No historical resting queue or market impact is inferred.",
                "fees": "A 0.075% per-side overlay includes build-up and exit VWAP. Both scenarios close all 42 positions before the next three-hour decision. Drawdown uses realized closes. The alternate print participation is a sensitivity on the same archived tape.",
                "attribution": "Binance Vision public USD-M historical candle and aggregate-trade archive. The underlying data is available from its provider and is kept in private replay scratch.",
            },
            "references": {
                "dataset": "https://github.com/binance/binance-public-data",
                "license": "https://github.com/binance/binance-public-data/blob/master/TERMS_AND_CONDITIONS.md",
            },
            "coverage": [
                [
                    27,
                    "Tested · Saved 3h CCI and historical trade chronology",
                    "Independent CCI and exact archived signal timing. All 42 modeled BTC/ETH positions close under two disclosed trade-flow participation assumptions.",
                ]
            ],
            "scopes": details,
            "results": output,
        },
    )


if __name__ == "__main__":
    run(*map(Path, sys.argv[1:]))
