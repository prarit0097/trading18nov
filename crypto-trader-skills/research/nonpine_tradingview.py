"""Prepare the official Help Center Pine scripts and documented chart-rule variants."""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urljoin
from urllib.request import urlopen
from zipfile import ZipFile

from bs4 import BeautifulSoup

FOLDER = "https://www.tradingview.com/support/folders/43000587406/"
WINDOWS = {
    "Reference": ("2026-09-23", "2026-10-21"),
    "Later": ("2026-10-21", "2026-11-04"),
}
INTERVAL = 900000
KEYS = (
    "barupdn",
    "bollinger-bands-strategy/",
    "bollinger-bands-strategy-directed",
    "channel-breakout",
    "consecutive-up-down",
    "greedy",
    "inside-bar",
    "keltner-channels",
    "macd",
    "momentum",
    "outside-bar",
    "parabolic-sar",
    "pivot-extension",
    "pivot-reversal",
    "price-channel",
    "rsi",
    "stochastic-slow",
    "supertrend",
    "technical-ratings",
    "volty-expan-close",
)
VARIANTS = {
    6041: (
        "[mid, upper, lower] = ta.kc(close, 20, 2.0, true)",
        "ta.crossover(close, upper)",
        "ta.crossunder(close, lower)",
        "20 bars, multiplier 2.0, EMA and True Range",
    ),
    6042: (
        "[line, signal, hist] = ta.macd(close, 12, 26, 9)",
        "ta.crossover(hist, 0)",
        "ta.crossunder(hist, 0)",
        "12/26/9 MACD histogram zero crosses",
    ),
    6043: (
        "change = close - close[12]",
        "change > 0 and change > change[1]",
        "change < 0 and change < change[1]",
        "12-bar momentum and one-bar acceleration",
    ),
    6044: (
        "outside = high > high[1] and low < low[1]",
        "outside and close > open",
        "outside and close < open",
        "Strict outside range and bar color",
    ),
    6045: (
        "sar = ta.sar(0.02, 0.02, 0.2)",
        "ta.crossover(close, sar)",
        "ta.crossunder(close, sar)",
        "0.02 start and step, 0.2 cap, close crossing",
    ),
    6046: (
        "top = not na(ta.pivothigh(high, 4, 2))\nbottom = not na(ta.pivotlow(low, 4, 2))",
        "bottom and not top",
        "top and not bottom",
        "4 left and 2 right bars, confirmed pivots, skip conflicting signals",
    ),
    6048: (
        "top = high == ta.highest(high, 20)[1]\nbottom = low == ta.lowest(low, 20)[1]",
        "top and not bottom",
        "bottom and not top",
        "20-bar prior channel, equality trigger, skip conflicting signals",
    ),
    6049: (
        "rsi = ta.rsi(close, 14)",
        "ta.crossover(rsi, 30)",
        "ta.crossunder(rsi, 70)",
        "14-bar RSI, levels 30 and 70",
    ),
    6051: (
        "[level, direction] = ta.supertrend(3, 10)",
        "ta.crossunder(direction, 0)",
        "ta.crossover(direction, 0)",
        "10-bar ATR, factor 3, direction changes",
    ),
    6053: (
        "width = ta.sma(ta.tr(true), 5) * 0.75",
        "close > close[1] + width[1]",
        "close < close[1] - width[1]",
        "5-bar simple average of True Range, factor 0.75, confirmed close breakout",
    ),
}


def page(url):
    with urlopen(url, timeout=30) as response:
        return BeautifulSoup(response.read(), "html.parser")


def source_blocks(url):
    source = page(url)
    blocks = list(
        dict.fromkeys(
            e.get_text()
            for e in source.select("pre, code")
            if "strategy(" in e.get_text()
        )
    )
    prose = source.find("h1").parent.get_text("\n", strip=True)
    return url, blocks, prose


def source_cases(work):
    catalogue = Path(__file__).with_name("public-strategy-catalogue.csv")
    with catalogue.open(encoding="utf-8-sig") as stream:
        entries = list(csv.DictReader(stream))
    links = list(
        dict.fromkeys(
            urljoin(FOLDER, a["href"])
            for a in page(FOLDER).select('a[href^="/support/solutions/"]')
        )
    )
    assert len(links) == len(KEYS)
    with ThreadPoolExecutor(10) as pool:
        pages = list(pool.map(source_blocks, links))
    candidates, reasons, models = [], [], {}
    for ident, key in enumerate(KEYS, 6034):
        [(url, blocks, prose)] = [(u, b, p) for u, b, p in pages if ("-" + key) in u]
        name = entries[ident - 1]["name"]
        methodology = None
        if blocks:
            [raw] = blocks
            code = (
                "\n".join(
                    "  " + line
                    if line.startswith("  ") and not line.startswith("    ")
                    else line
                    for line in raw.splitlines()
                )
                + "\n"
            )
            if ident == 6036:
                code = (
                    "\n".join(
                        line
                        for line in code.splitlines()
                        if "strategy.risk.allow_entry_in" not in line
                    )
                    + "\n"
                )
                methodology = (
                    "Default direction is both sides, equivalent risk no-op omitted"
                )
            if ident == 6039:
                code = code.replace("false),\n", "false)\n")
                methodology = "Removed trailing comma from published assignment"
        elif ident in VARIANTS:
            raw = prose
            indicators, up, down, settings = VARIANTS[ident]
            code = (
                f'//@version=5\nstrategy("{name}", overlay=true)\n{indicators}\n'
                f'if {up}\n    strategy.entry("Long", strategy.long)\n'
                f'if {down}\n    strategy.entry("Short", strategy.short)\n'
            )
            methodology = f"Documented-rule reconstruction. {settings}. Reversals fill on the next open."
        else:
            reasons.append(
                [
                    ident,
                    "TradingView source pending",
                    "Official Help Center description leaves the exact signals, execution rules or indicator configuration unspecified",
                    url,
                ]
            )
            continue
        candidates.append(
            dict(
                id=ident,
                name=name,
                source=url,
                code=code,
                hash=hashlib.sha256(raw.encode()).hexdigest(),
                archived="Chart timeframe",
            )
        )
        if methodology:
            models[str(ident)] = methodology
    assert len(candidates) + len(reasons) == len(KEYS)
    (work / "tv-candidates.json").write_text(json.dumps(candidates), encoding="utf-8")
    (work / "tv-pending.json").write_text(json.dumps(reasons), encoding="utf-8")
    (work / "tv-methods.json").write_text(json.dumps(models), encoding="utf-8")


def candles(work):
    windows = {label: {} for label in WINDOWS}
    for coin in ("BTC", "ETH"):
        groups = defaultdict(list)
        for path in sorted(
            (work / "binance").glob(f"klines-futures-{coin}USDT-1m-*.zip")
        ):
            if "-08." in path.name:
                continue
            with (
                ZipFile(path) as archive,
                archive.open(archive.namelist()[0]) as stream,
            ):
                for row in csv.reader(line.decode() for line in stream):
                    if not row[0].isdigit():
                        continue
                    time = int(row[0])
                    groups[time // INTERVAL * INTERVAL].append(
                        (time, *map(float, row[1:6]))
                    )
        for label, dates in WINDOWS.items():
            ist = timezone(timedelta(hours=5, minutes=30))
            start, stop = (
                int(datetime.fromisoformat(d).replace(tzinfo=ist).timestamp() * 1000)
                for d in dates
            )
            bars = []
            for time in range(start, stop, INTERVAL):
                sample = sorted(groups[time])
                assert len(sample) == 15 and all(
                    x[0] == time + j * 60000 for j, x in enumerate(sample)
                ), (coin, time)
                bars.append(
                    dict(
                        openTime=time,
                        closeTime=time + INTERVAL,
                        open=sample[0][1],
                        high=max(x[2] for x in sample),
                        low=min(x[3] for x in sample),
                        close=sample[-1][4],
                        volume=sum(x[5] for x in sample),
                    )
                )
            windows[label][coin + "USD"] = [bars]
    (work / "tv-candles.json").write_text(
        json.dumps(windows, separators=(",", ":")), encoding="utf-8"
    )


if __name__ == "__main__":
    root = Path(sys.argv[1])
    source_cases(root)
    candles(root)
