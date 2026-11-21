"""Prepare and cross-audit the archived #3664 multi-timeframe inputs."""

import json
from collections import Counter, defaultdict
from hashlib import sha256
from itertools import pairwise
from math import isclose
from urllib.parse import urlencode

from research.fmz_round7_magnifier import aggregate, date_ms
from research.fmz_round12_pine_authored import provider_bars
from research.fmz_round28_pine_callback import cache_bars

MONTHS = ("2023-10", "2023-11", "2023-12")
M1 = 60_000
HOUR = 60 * M1
DAY = 24 * HOUR
WEEK = 7 * DAY
START, CUT, STOP = map(date_ms, ("2023-10-24", "2023-11-23", "2023-12-23"))
WARMUP = date_ms("2023-10-02")
FMZ_CUSTOM = 39 * M1
FMZ_BASE = 15 * M1
BTC_DAILY_SHA = "60fbc08c0a73afa5f04d8bc9b8b960cb782435147c1a1080a2b449714db1ea20"
ETH_DAILY_SHA = "f921e814a1dabaa5d32ef2160890da5b8155cd177f623d675d557874ee9d94c3"
ETH_API_SHA = "381046283250f181b75c66bb848c8a7e84833095f96d63bcbfe0b7b60f52561e"
FMZ_RECEIPTS = {
    (
        "BTC",
        FMZ_CUSTOM,
    ): "de353cb8612b008c8800fb72673dfd3c7d60098e91b7e1f6cd8bf8883c42ce66",
    (
        "ETH",
        FMZ_CUSTOM,
    ): "844b59a1821e9e7ac8b428b5135a1b1f1de46d444799ff0c299832defe555c75",
    (
        "BTC",
        FMZ_BASE,
    ): "5727fb2f8cc682bbfea81b4cdb3f0a091439da7023ed486b64ce585331591a31",
    (
        "ETH",
        FMZ_BASE,
    ): "4463be618b4586d265a728b3b4cb1bc5a2ec258e5bf051f1cfb8aacc9b07e856",
}
ETH_DIRECT = "https://fapi.binance.com/fapi/v1/klines?symbol=ETHUSDT&interval=1m&startTime=1699959600000&endTime=1699963199999&limit=60"


def read_pinned(path, expected):
    raw = path.read_bytes()
    assert sha256(raw).hexdigest() == expected, path
    return json.loads(raw)


def rolls(data, keyer):
    buckets = defaultdict(list)
    for row in data:
        buckets[keyer(row[0])].append(row)
    out = []
    for t, group in sorted(buckets.items()):
        if group[0][0] != t:
            continue
        out.append(
            [
                t,
                group[0][1],
                max(g[2] for g in group),
                min(g[3] for g in group),
                group[-1][4],
                sum(g[5] for g in group),
            ]
        )
    return out


def binance_inputs(replacements, minute_dirs, hour_dirs, day_dirs):
    pack = {}
    receipts = []
    adjustments = {}
    for coin in ("BTC", "ETH"):
        market = coin + "USDT"
        tape = [
            list(row)
            for row in cache_bars(minute_dirs, market, "1m", MONTHS, M1, receipts)
            if WARMUP <= row[0] < STOP
        ]
        hours = [
            list(row)
            for row in cache_bars(hour_dirs, market, "1h", MONTHS, HOUR, receipts)
            if START <= row[0] < STOP
        ]
        label, digest, expected = (
            ("2023-11-10", BTC_DAILY_SHA, 100)
            if coin == "BTC"
            else ("2023-11-14", ETH_DAILY_SHA, 0)
        )
        daily = replacements / f"{market}-1m-{label}.zip"
        assert sha256(daily.read_bytes()).hexdigest() == digest
        verified = list(
            cache_bars((replacements,), market, "1m", (label,), M1, receipts)
        )
        direct = list(provider_bars(daily, M1))
        assert direct == verified and len(direct) == 1440
        url = f"https://data.binance.vision/data/futures/um/daily/klines/{market}/1m/{daily.name}"
        assert isinstance(receipts[-1], dict)
        receipts[-1]["url"] = url
        direct = {row[0]: list(row) for row in direct}
        assert (
            sum(row != direct[row[0]] for row in tape if row[0] in direct) == expected
        )
        tape = [direct.get(row[0], row) for row in tape]
        adjustments[coin] = {"daily_zip_changed_minutes": expected}
        if coin == "ETH":
            start = 1699959600000
            api = read_pinned(replacements / "3664-eth-api.json", ETH_API_SHA)
            assert [row[0] for row in api] == list(range(start, start + HOUR, M1))
            assert all(row[6] == row[0] + M1 - 1 for row in api)
            api = {row[0]: [row[0], *map(float, row[1:6])] for row in api}
            assert sum(row != api[row[0]] for row in tape if row[0] in api) == 5
            tape = [api.get(row[0], row) for row in tape]
            adjustments[coin].update(
                {
                    "api_changed_minutes": 5,
                    "api_sha256": ETH_API_SHA,
                    "api_url": ETH_DIRECT,
                }
            )
        days = [
            list(row)
            for row in cache_bars(day_dirs, market, "1d", MONTHS, DAY, receipts)
            if WARMUP <= row[0] < STOP
        ]
        assert [row[0] for row in tape] == list(range(WARMUP, STOP, M1))
        for aggregated, expected in (
            (aggregate([row for row in tape if row[0] >= START], 60), hours),
            (aggregate(tape, 1440), days),
        ):
            assert all(
                list(row[:5]) == target[:5]
                and isclose(row[5], target[5], rel_tol=1e-12)
                for row, target in zip(aggregated, expected, strict=True)
            )
        fb = {
            "1": tape,
            "30": rolls(tape, lambda t: t - t % (30 * M1)),
            "D": days,
            "W": rolls(tape, lambda t: WARMUP + (t - WARMUP) // WEEK * WEEK),
        }
        for scope, lo, hi in (("native", START, CUT), ("next", CUT, STOP)):
            panel = {
                key: [
                    row
                    for row in vals
                    if (key in ("W", "D") or row[0] >= lo) and row[0] < hi
                ]
                for key, vals in fb.items()
            }
            panel["chart"] = [row for row in hours if lo <= row[0] < hi]
            pack.setdefault(scope, {})[coin] = panel
    return {"data": pack, "proof": receipts, "binance_replacements": adjustments}


def public_fmz_url(market, period):
    params = {
        "detail": "true",
        "round": "true",
        "feeder": "local",
        "event": "feed",
        "eid": "Futures_Binance",
        "depth": 5,
        "trades": 0,
        "custom": 0,
        "period": period,
        "symbol": market + "_USDT.swap",
        "from": 1698019200,
        "to": 1703296800,
    }
    return "https://q.fmz.com/data/history?" + urlencode(params)


def crosscheck_fmz(pack, raw, market):
    receipts = []
    series = {}
    for period, count in ((FMZ_CUSTOM, 2256), (FMZ_BASE, 5865)):
        digest = FMZ_RECEIPTS[market, period]
        path = raw / f"3664-fmz-{market}-{period}-exact.json"
        data = read_pinned(path, digest)
        metadata = data["detail"]
        assert (
            metadata["symbol"],
            metadata["alias"],
            metadata["eid"],
            metadata["contractType"],
        ) == (
            market + "_USDT.swap",
            market + "USDT",
            "Futures_Binance",
            "swap",
        )
        assert metadata["basePrecision"] == 3 and metadata["quotePrecision"] == (
            1 if market == "BTC" else 2
        )
        rows = data["data"]
        assert len(rows) == count
        assert all(b[0] - a[0] == period for a, b in pairwise(rows))
        series[period] = rows
        receipts.append(
            {
                "period_ms": period,
                "row_count": count,
                "sha256": digest,
                "url": public_fmz_url(market, period),
            }
        )
    groups = defaultdict(list)
    for row in series[FMZ_BASE]:
        groups[row[0] - row[0] % FMZ_CUSTOM].append(row)

    def market_row(row):
        tick_factor = 10 if market == "BTC" else 100
        return [*(value / tick_factor for value in row[1:5]), row[5] * 0.001]

    buckets = []
    flags = Counter()
    for row in series[FMZ_CUSTOM][1:-1]:
        t, op, high, low, close, volume, *_ = row
        candles = groups[t]
        assert [op, high, low, close, volume] == [
            candles[0][1],
            max(r[2] for r in candles),
            min(r[3] for r in candles),
            candles[-1][4],
            sum(r[5] for r in candles),
        ]
        flags[len(candles)] += 1
        buckets.append([t, candles[-1][0] + FMZ_BASE, *market_row(row)])
    assert flags == {2: 901, 3: 1353}

    differences = []
    for markets in pack["data"].values():
        panel = markets[market]
        lo, hi = panel["chart"][0][0], panel["chart"][-1][0] + HOUR
        quarter = {
            row[0]: list(row[1:]) for row in aggregate(panel["1"], FMZ_BASE // M1)
        }
        corrections = defaultdict(float)
        for row in series[FMZ_BASE]:
            if not lo <= row[0] < hi:
                continue
            q = market_row(row)
            alt = quarter[row[0]]
            if q[:4] != alt[:4] or not isclose(q[4], alt[4], abs_tol=1e-8):
                corrections[row[0] - row[0] % FMZ_CUSTOM] += alt[4] - q[4]
                differences.append([row[0], q, alt])
        panel["39-fmz-native"] = [
            [label, *row] for label, _, *row in buckets if lo - FMZ_CUSTOM <= label < hi
        ]
        panel["39-fmz-causal"] = [
            [available - 1, *row]
            for _, available, *row in buckets
            if lo - FMZ_CUSTOM <= available <= hi
        ]
        panel["39-fmz-reviewed"] = [
            row for row in buckets if lo - FMZ_CUSTOM <= row[0] < hi
        ]
        panel["39-binance-sensitivity"] = [
            [available - 1, *row[:-1], row[-1] + corrections.get(label, 0.0)]
            for label, available, *row in buckets
            if lo - FMZ_CUSTOM <= available <= hi
        ]
    assert [row[0] for row in differences] == [1699628400000, 1699633800000]
    return {
        "receipts": receipts,
        "underlying_15m_counts": dict(flags),
        "four_source_differences_across_btc_and_eth": differences,
    }


def source_inputs(raw, minute_dirs, hour_dirs, day_dirs):
    pack = binance_inputs(raw, minute_dirs, hour_dirs, day_dirs)
    pack["fmz_public_archive"] = {
        market: crosscheck_fmz(pack, raw, market) for market in ("BTC", "ETH")
    }
    return pack
