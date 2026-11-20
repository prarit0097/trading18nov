"""Replay fixed and floating funding from public Boros books and settlements."""

import argparse
import csv
import hashlib
import io
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.nonpine_round4_metrics import metrics

MONTH = "2026-08"
MARKETS = {
    "BTC": (0.01, "170-BINANCE-BTCUSDT-28AUG2026", "130-BINANCE-BTCUSDT-25SEP2026"),
    "ETH": (0.1, "168-BINANCE-ETHUSDT-28AUG2026", "101-BINANCE-ETHUSDT-25SEP2026"),
}
IDS = {
    6152: "Prior floating APR versus fixed quote",
    6153: "Short YU plus perpetual funding receivable",
    6154: "Long lower implied APR, short higher implied APR",
}
HOUR = 3600
DAY = 24 * HOUR
INTERVAL = 8 * HOUR
YEAR = 365 * DAY
TAKER_FEE = 0.0005
SETTLEMENT_FEE = 0.002
ENTRANCE_FEE = {"BTC": 0.000008, "ETH": 0.00027}
GAS_PER_ORDER = 0.25
EDGE = 0.005


def rate(tick):
    return math.copysign(math.expm1(abs(tick) * 2 * math.log(1.00005)), tick)


def top(book, side, quantity):
    levels = book["short" if side > 0 else "long"]
    if levels and int(levels[0]["sz"]) >= round(quantity * 10**18):
        return rate(levels[0]["t"])
    return None


def roundtrip(side, size, maturity, opened, closed, opening, closing, funding):
    duration_open = maturity - opened // INTERVAL * INTERVAL
    duration_close = maturity - closed // INTERVAL * INTERVAL
    assert 0 < duration_close < duration_open
    assert duration_open - duration_close == len(funding) * INTERVAL
    fixed = closing * duration_close - opening * duration_open
    floating = math.fsum(funding) * INTERVAL
    gross = side * size * (fixed + floating) / YEAR
    fees = (
        size
        * (
            TAKER_FEE * (duration_open + duration_close)
            + SETTLEMENT_FEE * (duration_open - duration_close)
        )
        / YEAR
    )
    return gross, fees


def zipped(path, url, evidence, decode):
    raw = path.read_bytes()
    evidence[url] = hashlib.sha256(raw).hexdigest()
    with ZipFile(io.BytesIO(raw)) as archive:
        [member] = archive.namelist()
        with archive.open(member) as stream, io.TextIOWrapper(stream) as lines:
            return list(decode(lines))


def boros_series(directory, market, evidence):
    def rows(kind, subfolder=""):
        relative = f"{kind}/{market}/{subfolder}{MONTH}.ndjson.zip"
        return zipped(
            directory / relative,
            f"https://historical-data.boros.finance/{relative}",
            evidence,
            lambda lines: map(json.loads, lines),
        )

    books = {b["blockTimestamp"]: b for b in rows("order-book", "raw/")}
    quotes = {b["timestamp"]: b for b in rows("market-data")}
    assert books.keys() == quotes.keys()
    for time, book in books.items():
        q = quotes[time]
        assert book["blockNumber"] == q["blockNumber"]
        for field, name in (("short", "bestAsk"), ("long", "bestBid")):
            if book[field]:
                assert math.isclose(rate(book[field][0]["t"]), q[name], abs_tol=1e-11)
            else:
                assert q[name] is None
    settlements = {}
    for event in rows("settlement"):
        at = event["timestamp"]
        boundary = at // INTERVAL * INTERVAL
        assert 0 <= at - boundary < 300 and boundary not in settlements
        settlements[boundary] = event
    expiry = datetime.strptime(market.split("-")[-1], "%d%b%Y").replace(tzinfo=UTC)
    return market, int(expiry.timestamp()), books, settlements


def binance_series(source, coin, evidence):
    symbol = coin + "USDT"
    market = "https://data.binance.vision/data"
    spot_path = f"spot/monthly/klines/{symbol}/1m/{symbol}-1m-{MONTH}.zip"
    futures_path = (
        f"futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{MONTH}.zip"
    )
    klines = zipped(
        source / f"klines-spot-{symbol}-1m-{MONTH}.zip",
        f"{market}/{spot_path}",
        evidence,
        csv.reader,
    )
    archive = zipped(
        source / f"fundingRate-futures-{symbol}-{MONTH}.zip",
        f"{market}/{futures_path}",
        evidence,
        csv.DictReader,
    )
    spot = {(int(row[6]) + 1) // 1_000_000: float(row[4]) for row in klines}
    funding = {}
    for row in archive:
        ts = int(row["calc_time"]) // 1000
        boundary = ts // INTERVAL * INTERVAL
        assert 0 <= ts - boundary < 300 and boundary not in funding
        assert row["funding_interval_hours"] == "8"
        funding[boundary] = float(row["last_funding_rate"])
    return spot, funding


def proposals(fixed, front, back):
    bid, ask = front
    future_bid, future_ask = back
    if bid is not None:
        yield 6153, (-1,)
    if ask is not None and fixed >= ask + EDGE:
        yield 6152, (1,)
    elif bid is not None and fixed <= bid - EDGE:
        yield 6152, (-1,)
    if ask is not None and future_bid is not None and ask + EDGE <= future_bid:
        yield 6154, (1, -1)
    elif bid is not None and future_ask is not None and future_ask + EDGE <= bid:
        yield 6154, (-1, 1)


def replay(coin, size, series, spot, binance_funding):
    first = int(datetime(2026, 8, 1, tzinfo=UTC).timestamp())
    results = {ident: [] for ident in IDS}
    unresolved = dict.fromkeys(IDS, 0)
    paid = {ident: set() for ident in IDS}
    observed = 0
    for day in range(first, series[0][1], DAY):
        opened, closed = day + HOUR, day + 23 * HOUR
        front = series[0]
        latest = front[3].get(day)
        if latest is None or latest["timestamp"] >= opened:
            continue
        if any(opened not in books for _, _, books, _ in series):
            continue
        observed += 1
        quotes = [
            tuple(top(books[opened], side, size) for side in (-1, 1))
            for _, _, books, _ in series
        ]
        for ident, sides in proposals(latest["settlementApr"], *quotes):
            legs = []
            boundaries = [day + INTERVAL, day + 2 * INTERVAL]
            for side, (market, expiry, books, settlements) in zip(sides, series):
                if closed not in books or not all(
                    t in settlements and settlements[t]["timestamp"] < closed
                    for t in boundaries
                ):
                    break
                opening = top(books[opened], side, size)
                closing = top(books[closed], -side, size)
                if closing is None:
                    break
                rates = [settlements[t]["settlementApr"] for t in boundaries]
                gross, fees = roundtrip(
                    side, size, expiry, opened, closed, opening, closing, rates
                )
                if market not in paid[ident]:
                    fees += ENTRANCE_FEE[coin]
                legs.append((market, side, opening, closing, gross, fees, rates))
            if (
                len(legs) != len(sides)
                or opened not in spot
                or (ident == 6153 and any(t not in binance_funding for t in boundaries))
            ):
                unresolved[ident] += 1
                continue
            paid[ident].update(x[0] for x in legs)
            hedge = (
                size * math.fsum(binance_funding[t] for t in boundaries)
                if ident == 6153
                else 0
            )
            usd = spot[opened]
            results[ident].append(
                {
                    "opened": opened,
                    "closed": closed,
                    "legs": legs,
                    "unit_price_usdt": usd,
                    "funding_receivable_coin": hedge,
                    "gross": (math.fsum(x[4] for x in legs) + hedge) * usd,
                    "fees": math.fsum(x[5] for x in legs) * usd,
                    "execution": len(legs) * 2 * GAS_PER_ORDER,
                }
            )
    assert observed >= 25, (coin, observed)
    return results, unresolved, observed


def run(directory, binance, baseline, report):
    catalogue = {row["id"]: row for row in read(baseline)["disposition"]}
    inputs, ledger, results, coverage, windows = {}, {}, [], [], {}
    for coin, (size, *markets) in MARKETS.items():
        series = [boros_series(directory, market, inputs) for market in markets]
        spot, funding = binance_series(binance, coin, inputs)
        measured, unresolved, count = replay(coin, size, series, spot, funding)
        windows[coin] = count
        for ident, variant in IDS.items():
            ledger[f"{coin}/{ident}"] = measured[ident]
            trades = [
                (x["closed"], x["gross"], x["fees"], x["execution"])
                for x in measured[ident]
            ]
            results.append(
                {
                    "id": ident,
                    "period": "2026 Aug 1–27",
                    "group": "Boros · funding replay variant",
                    "exit": "23:00 UTC opposite order-book side",
                    "market": coin + " YU (USDT)",
                    "currency": "USDT",
                    "interval": "1h",
                    "archive_interval": "Boros raw order book",
                    "order_family": variant,
                    **metrics(trades, unresolved[ident]),
                }
            )
    for ident, variant in IDS.items():
        assert not catalogue[ident]["status"].startswith("Tested")
        assert sum(row["trades"] for row in results if row["id"] == ident) > 0
        coverage.append(
            [
                ident,
                "Tested · Boros funding replay variant",
                (
                    f"{variant}. BTC and ETH historical Boros top-level depth and actual settlement APRs. "
                    "Independent daily trials, representative fees, entry FX and realized-close drawdown. "
                    "For receivables, separately archived Binance funding and an existing perpetual hedge."
                ),
            ]
        )
    write(
        report,
        {
            "coverage": coverage,
            "results": results,
            "source_hashes": inputs,
            "eligible_opening_snapshots": windows,
            "ledger": ledger,
            "settings": {
                "size": {k: v[0] for k, v in MARKETS.items()},
                "rate_edge": EDGE,
                "taker_fee_annual": TAKER_FEE,
                "settlement_fee_annual": SETTLEMENT_FEE,
                "entrance_coin": ENTRANCE_FEE,
                "gas_usdt_per_order": GAS_PER_ORDER,
            },
        },
    )
    print(
        [
            (row["id"], row["market"], row["trades"], round(row["net"], 6))
            for row in results
        ]
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("directory", "binance", "baseline", "report"):
        parser.add_argument(arg, type=Path)
    run(**vars(parser.parse_args()))
