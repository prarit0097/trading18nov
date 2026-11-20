"""Run the archive's hourly Keltner decision sequence on closed Binance spot bars."""

import argparse
import json
from collections import defaultdict
from itertools import pairwise
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import talib

from research.delta_pinets_catalogue import read, write
from research.delta_strategy_replay import EQUITY, EXECUTION, FEE, stamp, summarize
from research.fmz_native_round3 import KEYS, WINDOWS
from research.fmz_native_round5 import assert_source
from research.fmz_native_round6_audit import BASE, ROOT, digest

IDENT = 472
HOUR = 3_600_000
NOTES = (
    "Archived 80-hour Keltner channel, volume gate, 600 USDT buys and branching stop/hold rules. "
    "Evaluate the last completed hour. Execute at the next traded hourly open on Binance spot."
)


def action(close, ema, old_close, last, base_amount, cash, long):
    if cash >= 600 and base_amount < 0.001 and long:
        return "buy"
    if base_amount > 0.001:
        if close <= last * 0.94 or (close >= last * 1.1 and close <= old_close * 0.9):
            return "sell"
        if close < ema:
            return "stop" if close > last * 1.1 else "sell"
    return "wait"


def hourly(raw, step):
    groups = defaultdict(list)
    for row in raw:
        groups[row[0] // HOUR * HOUR].append(row)
    result = []
    for key, group in groups.items():
        if len(group) == HOUR // step:
            assert [x[0] for x in group] == list(range(key, key + HOUR, step))
            result.append(
                (
                    key,
                    group[0][1],
                    max(r[2] for r in group),
                    min(r[3] for r in group),
                    group[-1][4],
                    sum(r[5] for r in group),
                    group[0][5],
                )
            )
    assert result and all(y[0] - x[0] == HOUR for x, y in pairwise(result))
    return result


def replay(data, feed):
    step = feed["base_seconds"] * 1000
    assert step == 300_000
    bars = hourly(data["data"], step)
    detail = data["detail"]
    scale = 10 ** detail["quotePrecision"]
    quantity_scale = 10 ** detail["basePrecision"]
    high, low, close = (np.array([r[i] / scale for r in bars]) for i in (2, 3, 4))
    average = talib.EMA(close, timeperiod=80)
    upper = average + 3 * talib.EMA(talib.TRANGE(high, low, close), timeperiod=80)
    begin, end = (stamp(feed[key]) * 1000 for key in ("start", "end"))
    cash, quantity, price_in, last = EQUITY, 0.0, 0.0, 0.0
    trades, orders = [], []
    stopped = None
    for i in range(80, len(bars) - 1):
        at, opening, *_, opening_liquidity = bars[i + 1]
        if not begin <= at < end:
            continue
        assert np.isfinite(upper[i])
        volumes = [bars[j][5] for j in (i, i - 1, i - 3, i - 4)]
        long = close[i] > upper[i] and volumes[0] + volumes[1] > 1.5 * (
            volumes[2] + volumes[3]
        )
        choice = action(close[i], average[i], close[i - 23], last, quantity, cash, long)
        if choice == "stop":
            stopped = at
            break
        if not opening_liquidity or choice == "wait":
            continue
        price = opening / scale
        if choice == "buy":
            size = int(600 / (price * (1 + FEE)) * quantity_scale) / quantity_scale
            if size < detail["minQty"] or size * price < detail["minNotional"]:
                continue
            assert quantity == 0 and size > 0.001
            price_in, last, quantity = price, float(close[i] + 10), size
            cash -= price * size * (1 + FEE)
            orders.append((at, "buy", size, price))
        else:
            if quantity * price < detail["minNotional"]:
                continue
            gross = quantity * (price - price_in)
            turnover = quantity * (price + price_in)
            after = gross - turnover * FEE
            trades.append((at, gross, after, after - turnover * EXECUTION))
            cash += quantity * price * (1 - FEE)
            orders.append((at, "sell", quantity, price))
            quantity = 0.0
    open_count = int(quantity > 0)
    assert len(orders) == 2 * len(trades) + open_count
    assert (
        abs(cash + quantity * price_in * (1 + FEE) - EQUITY - sum(x[2] for x in trades))
        < 1e-8
    )
    return (
        trades,
        open_count,
        {
            "orders": orders,
            "cash": cash,
            "quantity": quantity,
            "stopped_holding": stopped,
        },
    )


def run(archive, offline, output):
    source = next(r for r in read(BASE)["disposition"] if r["id"] == IDENT)
    audit = next(
        r
        for r in read(ROOT / "fmz-native-round6-audit.json")["source_evidence"]
        if r["id"] == IDENT
    )
    results, snapshots, fills = [], [], {}
    with ZipFile(archive) as pinned:
        for job in read(offline / "round5-native-python-jobs.json"):
            if job["item"]["id"] != IDENT:
                continue
            assert_source(job, pinned, {**source, **audit})
            feed = job["feed"]
            raw = (offline / feed["file"]).read_bytes()
            assert digest(raw) == feed["sha256"]
            orders, open_count, receipt = replay(json.loads(raw), feed)
            fills[feed["coin"], feed["start"]] = orders, open_count
            snapshots.append(
                {**receipt, "feed": feed, "document_sha256": audit["document_sha256"]}
            )
    assert fills.keys() == KEYS and any(a or b for a, b in fills.values())
    for start, (_, window) in WINDOWS.items():
        btc, b = fills["BTC", start]
        eth, e = fills["ETH", start]
        for market, outcomes, open_ in (
            ("BTCUSDT", btc, b),
            ("ETHUSDT", eth, e),
            ("BTCUSDT + ETHUSDT", btc + eth, b + e),
        ):
            result = summarize(
                (
                    "FMZ Python · closed-bar Keltner",
                    source["name"],
                    market + " spot",
                    "Archived Keltner order rule",
                ),
                window,
                outcomes,
                open_,
            )
            result.update(
                id=IDENT,
                interval="1h",
                archive_interval="1h",
                quote_currency="USDT",
                source=source["source"],
            )
            results.append(result)
    label = "Tested · FMZ Python closed-bar variant" + (
        "" if any(a for a, _ in fills.values()) else ", no closes"
    )
    write(
        output,
        {
            "baseline": "91ad53db",
            "coverage": [[IDENT, label, NOTES]],
            "talib_version": talib.__version__,
            "results": results,
            "snapshots": snapshots,
        },
    )
    print(IDENT, len(results), "result rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("archive", "offline", "output"):
        parser.add_argument(field, type=Path)
    run(**vars(parser.parse_args()))
