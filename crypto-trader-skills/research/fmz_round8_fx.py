"""Prepare and summarize the Round 8 FMZ USD account replay."""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile

from research.fmz_round7_magnifier import (
    date_ms,
    iso_day,
    ledger_metrics,
    read,
    sha256,
    write,
)
from research.fmz_round8_fx_runner import CAPITAL, DATE_FX, FEE, RUNTIME_SHA, SOURCE_SHA

BASE = "0bdfa0dd4ecc1331397e189eaddbda3f3f9b6f17"
FX_SHA = "d4ae67955c8546a6d94eab14b95384663a043c28d2d5669d30cc4a4e75a3ea22"
FX_URL = "https://api.exchange.coinbase.com/products/USDT-USD/candles?granularity=86400&start=2026-09-29T00%3A00%3A00Z&end=2026-11-03T00%3A00%3A00Z"
WHEEL_SHA = "d465365c6ea6e2cd7a25e61ef68d5abcf26440f01881435a214f440e83b7903d"
WHEEL_RELEASE = "c0ecc3bde5eece9c4f2a63c6785aec9c5e571acc"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
ONE_DAY = 86_400_000
GROUP = "FMZ · Pine Compat 1m→10s · Coinbase prior-day FX"


def prior_close_rates(candles):
    rows = sorted(candles, key=lambda candle: candle[0])
    assert rows and all(
        time % 86400 == 0 and 0 < close for time, _, _, _, close, _ in rows
    )
    times = [row[0] for row in rows]
    assert times == list(range(times[0], times[-1] + 86400, 86400))
    rates = [{"effectiveTime": (row[0] + 86400) * 1000, "rate": row[4]} for row in rows]
    return {
        "schemaVersion": 1,
        "pairs": [{"from": "USDT", "to": "USD", "rates": rates}],
    }


def result_lot(raw, rate):
    entry_time, exit_time, side, quantity, entry, exit_price, gross, fee, net = raw
    assert side in ("Long", "Short") and entry_time <= exit_time and quantity > 0
    direction = 1 if side == "Long" else -1
    assert math.isclose(
        gross,
        direction * (exit_price - entry) * quantity * rate,
        rel_tol=0,
        abs_tol=1e-7,
    )
    assert math.isclose(
        fee, (entry + exit_price) * quantity * FEE * rate, rel_tol=0, abs_tol=1e-7
    )
    assert math.isclose(net, gross - fee, rel_tol=0, abs_tol=1e-7)
    return {
        "entryTime": entry_time,
        "exitTime": exit_time,
        "dir": direction,
        "qty": quantity,
        "entryPrice": entry * rate,
        "exitPrice": exit_price * rate,
        "commission": fee,
        "profit": net,
    }


def csv_rows(path):
    with ZipFile(path) as zip_file:
        (name,) = zip_file.namelist()
        with zip_file.open(name) as file:
            yield from csv.reader(io.TextIOWrapper(file, encoding="ascii"))


def verified_digest(path):
    digest = sha256(path)
    assert path.with_name(path.name + ".CHECKSUM").read_text().split() == [
        digest,
        path.name,
    ]
    return digest


def reconcile_minutes(lower, counts, official):
    assert len(lower) == len(counts) == 6 * len(official)
    rolled = []
    for offset in range(0, len(lower), 6):
        group = lower[offset : offset + 6]
        time, open_ = group[0][:2]
        values = [
            open_,
            max(bar[2] for bar in group),
            min(bar[3] for bar in group),
            group[-1][4],
            sum(bar[5] for bar in group),
            sum(counts[offset : offset + 6]),
        ]
        assert values == official[time]
        rolled.append([time, *map(float, values[:5])])
    return rolled


def prepare_market(case, trade_file, minute_file):
    raw_checksum = verified_digest(trade_file)
    minute_checksum = verified_digest(minute_file)
    start = date_ms(case["date"])
    end = start + ONE_DAY
    official = {}
    for row in csv_rows(minute_file):
        if row[0].isdigit() and start <= int(row[0]) < end:
            official[int(row[0])] = [*map(Decimal, row[1:6]), int(row[8])]
    assert list(official) == list(range(start, end, 60_000))
    lower, counts = [], []
    last_id = last_time = None
    sequence_gaps = 0
    for row in csv_rows(trade_file):
        if row[0] == "id":
            continue
        ident, price, quantity, time = (
            int(row[0]),
            Decimal(row[1]),
            Decimal(row[2]),
            int(row[4]),
        )
        assert price > 0 and quantity > 0 and start <= time < end
        if last_id is not None:
            assert ident > last_id and time >= last_time
            sequence_gaps += ident - last_id - 1
        last_id, last_time = ident, time
        time -= time % 10_000
        if not lower or lower[-1][0] != time:
            lower.append([time, price, price, price, price, quantity])
            counts.append(1)
        else:
            candle = lower[-1]
            candle[2] = max(candle[2], price)
            candle[3] = min(candle[3], price)
            candle[4] = price
            candle[5] += quantity
            counts[-1] += 1
    assert (
        sum(counts) == case["raw_event_rows"]
        and sequence_gaps == case["raw_event_id_gaps"]
    )
    assert [row[0] for row in lower] == list(range(start, end, 10_000))
    rolled = reconcile_minutes(lower, counts, official)
    return {
        "symbol": case["symbol"],
        "chartTimeframe": "1",
        "targetTimeframe": "10S",
        "chartMs": 60_000,
        "ltfMs": 10_000,
        "from": start,
        "to": end,
        "chart": rolled,
        "intrabar": [[row[0], *map(float, row[1:])] for row in lower],
        "raw_trade_sha256": raw_checksum,
        "official_minute_sha256": minute_checksum,
        "market_minutes_reconciled": len(rolled),
        "market_10s_bars": len(lower),
    }


def stage(work, trades, klines, coinbase):
    assert sha256(coinbase) == FX_SHA
    work.mkdir(parents=True, exist_ok=True)
    rates = prior_close_rates(read(coinbase))
    schedule = {row["effectiveTime"]: row["rate"] for row in rates["pairs"][0]["rates"]}
    assert all(schedule[time] == rate for time, rate in DATE_FX.items())
    # The standalone runner records the digest of this exact compact payload.
    (work / "coinbase-fx-input.json").write_bytes(
        json.dumps(rates, separators=(",", ":"), allow_nan=False).encode()
    )
    audited = read(Path(__file__).with_name("fmz-round7-magnifier-followup.json"))
    digests = {row["filename"]: row["sha256"] for row in audited["raw_inputs"]}
    for case in audited["raw_minute_reconciliation"]:
        symbol, day = case["symbol"], case["date"]
        trade_file = trades / f"{symbol}-trades-{day}.zip"
        file = klines / f"{symbol}-1m-{day}.zip"
        if not file.is_file():
            file = klines / f"{symbol}-1m-{day[:7]}.zip"
        payload = prepare_market(case, trade_file, file)
        assert payload["raw_trade_sha256"] == digests[trade_file.name]
        path = work / f"feed-{symbol}-1-10S-{day}.json"
        path.write_bytes(
            json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
        )
        print(path.name, sha256(path), flush=True)


def finalize(work, output):
    replay = work / "round8-fx-replay.json"
    receipt = read(replay)
    runs = receipt["runs"]
    assert (
        receipt["runtime_binary_sha256"] == RUNTIME_SHA
        and receipt["incomplete_feed_detected"]
    )
    assert receipt["rates_inputs_sha256"] == sha256(work / "coinbase-fx-input.json")
    original = read(Path(__file__).with_name("fmz-round7-magnifier.json"))
    (archive,) = [row for row in original["archive_records"] if row["id"] == 5540]
    assert archive["script_sha256"] == SOURCE_SHA
    assert len(runs) == 4
    groups = defaultdict(list)
    for run in runs:
        assert run["source_sha256"] == SOURCE_SHA and run["start"] in DATE_FX
        assert (
            run["FX"] == DATE_FX[run["start"]] and run["end"] == run["start"] + ONE_DAY
        )
        assert (
            run["complete_feed_matches_both_api_entrypoints"]
            and run["empty_leg_guard_matches_original_ledger"]
        )
        assert (
            run["fallback_diagnostics"] == 0
            and run["chart_bars"] == 1440
            and run["lower_bars"] == 8640
        )
        assert run["ledger_checks"]
        assert (
            sha256(work / f"feed-{run['market']}-1-10S-{iso_day(run['start'])}.json")
            == run["feed_sha256"]
        )
        groups[run["start"]].append(run)
    assert len(groups) == 2
    results = []
    for start, group in sorted(groups.items()):
        assert [run["market"] for run in group] == list(SYMBOLS)
        common = {
            "id": 5540,
            "group": GROUP,
            "exit": "Archived Pine exits",
            "period": f"Binance USD-M · {iso_day(start)} UTC",
            "archive_interval": "1m",
            "interval": "1m",
            "currency": "USD",
        }
        combined, unresolved = [], 0
        for run in group:
            rows = [result_lot(row, run["FX"]) for row in run["ledger_checks"]]
            pending = int(run["last_position"]["size"] != 0)
            results.append(
                dict(
                    **common,
                    market=run["market"],
                    **ledger_metrics(rows, CAPITAL, pending),
                )
            )
            combined.extend(rows)
            unresolved += pending
        results.append(
            dict(
                **common,
                market="BTCUSDT + ETHUSDT",
                **ledger_metrics(combined, 2 * CAPITAL, unresolved),
            )
        )
    write(
        output,
        {
            "schema": "Round 8 FMZ USD account replay",
            "baseline_commit": BASE,
            "archive": archive,
            "runtime": {
                "version": "0.3.3",
                "release_commit": WHEEL_RELEASE,
                "wheel_sha256": WHEEL_SHA,
                "binary_sha256": RUNTIME_SHA,
            },
            "fx_reference": {
                "provider": "Coinbase Exchange USDT-USD",
                "body_sha256": FX_SHA,
                "url": FX_URL,
                "timing": "Previous complete UTC daily close",
                "replay_feed_sha256": receipt["rates_inputs_sha256"],
            },
            "raw_replay_sha256": sha256(replay),
            "coverage": [
                [
                    5540,
                    "Tested · Pine Compat with Coinbase FX",
                    "Preserved FMZ Pine on checksum-verified Binance perpetual data with real 10-second price buckets and Coinbase prior-day USD conversion.",
                ]
            ],
            "results": results,
            "runs": runs,
        },
    )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    modes = cli.add_subparsers(dest="mode", required=True)
    prep = modes.add_parser("stage")
    for name in ("work", "trades", "klines", "coinbase"):
        prep.add_argument(name, type=Path)
    report = modes.add_parser("finalize")
    for name in ("work", "output"):
        report.add_argument(name, type=Path)
    args = cli.parse_args()
    if args.mode == "stage":
        stage(args.work, args.trades, args.klines, args.coinbase)
    else:
        finalize(args.work, args.output)
