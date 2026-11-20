"""Check extended offline feed alignment through the production broker worker."""

import argparse
import json
import math
from datetime import UTC, datetime
from pathlib import Path

from research.delta_pine_liquid_replay import MARKET, MARKETS, POOLED, checksum
from research.delta_pinets_catalogue import read, write
from research.fmz_marketdata_replay import heikin_bars
from research.fmz_round3_liquid_feeds import reconcile
from research.fmz_round3_timeframe_feeds import worker_for

CODE = """//@version=5
strategy("Trusted offline feed timing fixture")
mClose = request.security(syminfo.tickerid, "M", close)
mConfirmed = request.security(syminfo.tickerid, "M", close[1], lookahead=barmerge.lookahead_on)
twoMinutes = request.security(syminfo.tickerid, "2", close)
haPrevious = request.security(ticker.heikinashi(syminfo.tickerid), "M", close[1], lookahead=barmerge.lookahead_on)
aligned = mClose == 207 and mConfirmed == 207 and haPrevious == 203.25
if bar_index == 0 and aligned and twoMinutes == 506
    strategy.entry("Long", strategy.long)
if bar_index == 1 and aligned and twoMinutes == 514
    strategy.close("Long")
"""


def milliseconds(year, month, day):
    return int(datetime(year, month, day, tzinfo=UTC).timestamp()) * 1000


def candle(first, stop, opened, closed=None, high=None, low=None):
    return {
        "openTime": first,
        "closeTime": stop,
        "open": opened,
        "close": opened if closed is None else closed,
        "high": opened if high is None else high,
        "low": opened if low is None else low,
        "volume": 1,
    }


def prepare(work, cross=False):
    work.mkdir(parents=True, exist_ok=True)
    start = milliseconds(2025, 2, 1)
    month = [
        candle(milliseconds(2024, 12, 1), milliseconds(2025, 1, 1), 103),
        candle(milliseconds(2025, 1, 1), start, 197, 207, 219, 190),
        candle(start, milliseconds(2025, 3, 1), 777),
    ]
    two = [
        candle(start + i * 120_000, start + (i + 1) * 120_000, 500 + i)
        for i in range(23)
    ]
    chart = [
        candle(start + i * 900_000, start + (i + 1) * 900_000, opened)
        for i, opened in enumerate((1000, 1000, 1050))
    ]
    code = CODE
    window = {m: [chart] for m in MARKETS}
    window["market"] = {
        **MARKET,
        "references": {m: {"M": month, "2": two} for m in MARKETS},
        "heikinAshi": {m: {"M": heikin_bars(month)} for m in MARKETS},
    }
    if cross:
        from research.fmz_round3_symbol_feeds import cross_worker

        eth = [{**bar, "close": 1011, "high": 1011} for bar in chart[:2]] + [chart[-1]]
        window["ETHUSDT"] = [eth]
        window["market"]["referenceSymbols"] = ["BTCUSDT", "BTCUSDT_SPOT"]
        window["market"]["references"]["BTCUSDT"]["15"] = chart
        window["market"]["references"]["BTCUSDT_SPOT"] = {
            "15": [
                {**bar, "open": 305, "high": 305, "low": 305, "close": 305}
                for bar in chart
            ],
        }
        code = code.replace(
            "aligned = ",
            'btcReference = request.security("BTCUSDT", timeframe.period, close)\n'
            'spotReference = request.security("BTCUSDT_SPOT", timeframe.period, close)\n'
            'aligned = btcReference == 1000 and spotReference == 305 and (syminfo.ticker == "BTCUSDT" or close == 1011) and ',
        ).replace(
            'strategy.entry("Long", strategy.long)',
            'strategy.entry("Long", strategy.long, qty=1)',
        )
    write(work / "candles.json", {"Fixture A": window, "Fixture B": window})
    write(
        work / "candidates.json",
        [
            {
                "id": 0,
                "name": "Trusted extended feed fixture",
                "code": code,
                "hash": checksum(code.encode()),
                "archived": "",
                "source": "trusted test fixture",
                "cross_fixture": cross,
            }
        ],
    )
    (cross_worker if cross else worker_for)(work)


def verify(work, output):
    isolation = read(work / "isolation-probe.json")
    assert isolation == {"privateDenied": True, "networkDenied": True}
    (item,) = read(work / "candidates.json")
    (receipt,) = map(
        json.loads, (work / "out.jsonl").read_text(encoding="utf-8-sig").splitlines()
    )
    assert "reason" not in receipt, receipt
    rows = receipt["results"]
    reconcile(rows, ("Fixture A", "Fixture B"), item, 15)
    for row in rows:
        lots = 2 if row["market"] == POOLED else 1
        assert row["trades"] == lots and row["unsettled"] == 0, row
        assert math.isclose(row["gross"], 50 * lots, abs_tol=1e-8), row
        assert math.isclose(row["net"], (50 - 2050 * 0.00089) * lots, abs_tol=1e-8), row
    checks = [
        "closed month selection",
        "monthly history offset",
        "Heikin-Ashi monthly history",
        "last fully closed 2-minute candle",
    ]
    if item.get("cross_fixture", False):
        checks += [
            "fixed BTC perpetual on ETH perpetual chart",
            "independent BTC spot series on both perpetual charts",
        ]
    write(
        output,
        {
            "worker_sha256": checksum((work / "worker.mjs").read_bytes()),
            "isolation_probe": isolation,
            "fixture_sha256": item["hash"],
            "candles_sha256": checksum((work / "candles.json").read_bytes()),
            "expected": {
                "btc_and_eth": {"trades": 1, "gross": 50, "net": 48.1755},
                "checks": checks,
            },
            "results": rows,
        },
    )
    print("All six offline feed alignment fixture rows reconciled.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    steps = parser.add_subparsers(dest="stage", required=True)
    for action in ("prepare", "verify"):
        cli = steps.add_parser(action)
        cli.add_argument("work", type=Path)
        if action == "verify":
            cli.add_argument("output", type=Path)
        else:
            cli.add_argument("--cross", action="store_true")
    args = vars(parser.parse_args())
    stage = args.pop("stage")
    (prepare if stage == "prepare" else verify)(**args)
