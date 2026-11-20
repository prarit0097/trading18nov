"""Build and verify a deterministic two-window round-three Pine migration fixture."""

import argparse
import json
import math
from pathlib import Path

from research.delta_pinets_catalogue import read, write
from research.fmz_round3_compile import DEFAULT_VARIANT, prepare_source
from research.fmz_round3_compile_feeds import prepare_source as prepare_source_with_feeds

LEGACY = '''//@version=4
strategy("Migration fixture", process_orders_on_close=true)
offset = input(1)
counter = 0, counter := nz(counter[1]) + 1
hma(src, n) => sma(src, n) + 7
signal = hma(close, 2)
threshold = input(-1, minval=1)
enabled = input(1, type=input.bool)
plotshape(close > close[offset],
   color=color.red,
   text="entry")
if enabled and threshold < 0 and signal > close and close > close[offset] and counter == 5
    strategy.entry("L", strategy.long, qty=2)
if counter == 7
    strategy.close("L")
'''
CONTROL = '''//@version=5
strategy("Fixture control", process_orders_on_close=true)
average = ta.sma(close, 2) + 7
plotshape(close > close[1], color=color.red, text="entry")
if average > close and close > close[1] and bar_index == 4
    strategy.entry("L", strategy.long, qty=2)
if bar_index == 6
    strategy.close("L")
'''
MARKETS = ("BTCUSDT", "ETHUSDT")
FEE = 0.00059
EXECUTION = 0.0003


def prepare(work, feeds=False):
    if feeds:
        legacy_feed = LEGACY.replace(
            "if enabled",
            'confirmed = security(syminfo.tickerid, "60", close[1], lookahead=barmerge.lookahead_on)\n'
            "if confirmed == 103 and enabled",
        )
        migrated, _, repairs = prepare_source_with_feeds(legacy_feed)
    else:
        migrated, _, _, repairs = prepare_source(LEGACY, isolated_literals=True)
    assert repairs[DEFAULT_VARIANT] == 1
    candidates = [
        {
            "id": index,
            "code": source,
            "name": "Migration fixture",
            "source": "Project-authored fixture",
            "hash": "",
            "archived": "15m",
        }
        for index, source in enumerate((migrated, CONTROL), 1)
    ]
    windows = {}
    for period, first in (("Reference", 1790812800000), ("Later", 1793491200000)):
        periods = {}
        for asset in MARKETS:
            periods[asset] = [[
                {
                    "open": 100 + i,
                    "close": 100 + i,
                    "high": 100 + i,
                    "low": 100 + i,
                    "volume": 1,
                    "openTime": first + i * 900_000,
                    "closeTime": first + (i + 1) * 900_000,
                }
                for i in range(12)
            ]]
        periods["market"] = {
            "prefix": "BINANCE",
            "currency": "USDT",
            "symbols": {"BTCUSDT": {"tick": 0.1, "step": 0.001}, "ETHUSDT": {"tick": 0.01, "step": 0.001}},
        }
        if feeds:
            periods["market"]["references"] = {
                asset: {"60": [
                    {
                        "open": 100 + i,
                        "high": 103 + i,
                        "low": 100 + i,
                        "close": 103 + i,
                        "volume": 4,
                        "openTime": first + i * 900_000,
                        "closeTime": first + (i + 4) * 900_000,
                    }
                    for i in (0, 4, 8)
                ]}
                for asset in MARKETS
            }
        windows[period] = periods
    write(work / "fixture-candidates.json", candidates)
    write(work / "fixture-candles.json", windows)


def verify(work, destination, feeds=False):
    isolation = read(work / "isolation-probe.json")
    assert isolation == {"privateDenied": True, "networkDenied": True}
    receipts = {
        row["id"]: row["results"]
        for line in (work / "fixture-out.jsonl").read_text().splitlines()
        if (row := json.loads(line))
    }
    assert set(receipts) == {1, 2} and len(receipts[1]) == len(receipts[2]) == 6
    gross = 2 * (106 - 104)
    turnover = 2 * (104 + 106)
    checks = [
        "Named chart arguments preserve executable bindings",
        "Legacy variable rename preserves historical reads",
        "Explicit state statements preserve evaluation order",
        "User-defined function preserves body and dispatch",
        "Archived fixed-default variant retains intended negative threshold",
    ]
    if feeds:
        checks.append("A confirmed 60-minute close gates the same trade as the independent 15-minute control")
    for actual, control in zip(receipts[1], receipts[2], strict=True):
        assert actual == {**control, "id": 1}
        count = 1 if actual["market"] in MARKETS else 2
        assert actual["trades"] == count and actual["unsettled"] == 0
        for field, expected in (
            ("gross", gross),
            ("after_fees", gross - turnover * FEE),
            ("net", gross - turnover * (FEE + EXECUTION)),
        ):
            assert math.isclose(actual[field], count * expected, abs_tol=1e-10)
    write(
        destination,
        {
            "compared_rows": 6,
            "expected_closed_lots_per_asset_window": 1,
            "entry_close": 104,
            "exit_close": 106,
            "quantity": 2,
            "gross": gross,
            "after_fees": gross - turnover * FEE,
            "net": gross - turnover * (FEE + EXECUTION),
            "isolation_probe": isolation,
            "checks": checks,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path)
    parser.add_argument("--verify-to", type=Path)
    parser.add_argument("--feeds", action="store_true")
    args = parser.parse_args()
    if args.verify_to:
        verify(args.work, args.verify_to, args.feeds)
    else:
        prepare(args.work, args.feeds)
