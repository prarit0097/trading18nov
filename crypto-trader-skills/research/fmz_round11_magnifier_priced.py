"""Stage and finalize the verified FMZ priced-stop bar magnifier replays."""

import argparse
import hashlib
import json
from collections import defaultdict
from itertools import chain, pairwise
from pathlib import Path

from research.fmz_round7_magnifier import (
    aggregate,
    date_ms,
    iso_day,
    ledger_metrics,
    raw_ohlcv,
    read,
    sha256,
    verified_archives,
    write,
)

months = ("2026-08", "2026-09", "2026-10")
windows = (("2026-08-01", "2026-09-01"), ("2026-09-01", "2026-11-01"))
minute = 60_000
day = 1440 * minute
BASELINE_FAILURES = {
    "baseline_stop": {"stop_gap_qty", "stop_traversed_qty"},
    "baseline_additional": {"priced_reversal_open_short_size"},
}


def archive_reference_report():
    return read(Path(__file__).with_name("fmz-round7-magnifier.json"))


def market_reference():
    return read(Path(__file__).with_name("fmz-round10-magnifier-market.json"))


def compact(payload):
    return json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()


def point(timestamp, price):
    return [timestamp, price, price, price, price, 0.0]


def groups_2m(rows):
    origin = rows[0][0]
    assert origin % day == 0 and len(rows) % 30 == 0
    bar_width = 15 * minute
    owned = defaultdict(list)
    for bar in aggregate(rows, 2):
        last_minute = bar[0] + minute
        owner = (last_minute - origin) // bar_width
        owned[owner].append(bar)
    assert len(owned) == len(rows) // 15
    groups = []
    split_bars = 0
    for i in range(len(rows) // 15):
        first, last = rows[i * 15], rows[i * 15 + 14]
        slots = owned[i]
        if slots[0][0] < first[0]:
            assert slots[0][0] + minute == first[0]
            first_real = point(first[0], first[1])
            straddler = [first[0] + 1, *slots[0][1:]]
            output = [first_real, straddler, *slots[1:]]
            split_bars += 1
        else:
            assert slots[0][0] == first[0]
            output = list(slots)
        if slots[-1][0] + minute < last[0]:
            assert slots[-1][0] + 2 * minute == last[0]
            output.append(point(last[0], last[4]))
        assert output[0][1] == first[1] and output[-1][4] == last[4]
        assert all(a[0] < b[0] for a, b in pairwise(output))
        assert all(first[0] <= bar[0] < first[0] + bar_width for bar in output)
        groups.append(output)
    assert split_bars == len(groups) // 2
    assert sum(map(len, groups)) == len(rows) // 2 + len(groups)
    return groups, split_bars


def verify_ownership_control():
    test = [
        (i * minute, 100.0 + i, 104.0 + i, 99.0 + i, 102.0 + i, 1.0) for i in range(30)
    ]
    demo, straddled = groups_2m(test)
    assert straddled == 1 and [len(group) for group in demo] == [8, 9]
    assert list(demo[0][-1]) == point(14 * minute, 116.0)
    assert list(demo[1][0]) == point(15 * minute, 115.0)
    assert list(demo[1][1]) == [15 * minute + 1, 114.0, 119.0, 113.0, 117.0, 2.0]


def stage(work, public, previous):
    work.mkdir(parents=True, exist_ok=True)
    verify_ownership_control()
    prior = market_reference()
    archive_reference = {row["name"]: row["sha256"] for row in prior["inputs"]}
    market_feeds = {row["feed"]: row["feed_sha256"] for row in prior["runs"]}
    daily_reference = {
        row["symbol"]: row["sha256"]
        for row in archive_reference_report()["runs"]
        if row["chart"] == "D" and row["from"] == date_ms("2026-01-01")
    }
    manifest = []
    archives = {row["id"]: row for row in archive_reference_report()["archive_records"]}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        inputs = verified_archives(public, symbol, "1m", months, manifest)
        assert all(sha256(path) == archive_reference[path.name] for path in inputs)
        minutes = list(chain.from_iterable(raw_ohlcv(path, minute) for path in inputs))
        assert all(a[0] + minute == b[0] for a, b in pairwise(minutes))
        daily_file = previous / f"feed-{symbol}-D-60-2026-01-01.json"
        assert sha256(daily_file) == daily_reference[symbol]
        daily = read(daily_file)["chart"]
        dby_time = {row[0]: row for row in daily}
        for candle in aggregate(minutes, 1440):
            assert list(candle[:5]) == dby_time[candle[0]][:5]
        for first, last in windows:
            start, end = date_ms(first), date_ms(last)
            subset = [row for row in minutes if start <= row[0] < end]
            assert len(subset) * minute == end - start
            for ident in (5117, 5514):
                chart = aggregate(subset, 60 if ident == 5117 else 15)
                if ident == 5117:
                    lower = aggregate(subset, 10)
                    groups = [lower[i * 6 : (i + 1) * 6] for i in range(len(chart))]
                    market_payload = {
                        "symbol": symbol,
                        "chartTimeframe": "60",
                        "targetTimeframe": "10",
                        "chartMs": 60 * minute,
                        "ltfMs": 10 * minute,
                        "from": start,
                        "to": end,
                        "chart": chart,
                        "intrabar": lower,
                    }
                    frozen = market_feeds[f"feed-{symbol}-60-10-{first}.json"]
                    assert hashlib.sha256(compact(market_payload)).hexdigest() == frozen
                    straddled = 0
                else:
                    groups, straddled = groups_2m(subset)
                feed = {
                    "symbol": symbol,
                    "id": ident,
                    "start": start,
                    "end": end,
                    "chart": chart,
                    "daily": daily,
                    "groups": groups,
                    "straddled_slots": straddled,
                    "archive_script_sha256": archives[ident]["script_sha256"],
                    "chart_timeframe": "60" if ident == 5117 else "15",
                    "lower_timeframe": "10" if ident == 5117 else "2",
                    "daily_input_sha256": sha256(daily_file),
                }
                file = work / f"priced-{ident}-{symbol}-{first}.json"
                file.write_bytes(compact(feed))
                print(file.name, sha256(file), flush=True)
    (work / "priced-market-inputs.json").write_bytes(compact(manifest))


def finalize(work, output):
    raw = work / "priced-market-results.json"
    priced_patch = sha256(
        Path(__file__).with_name("fmz-round11-magnifier-priced.patch")
    )
    assert (
        priced_patch
        == "d67d6891f3aa13b38550d836d48b5da78e81c398d4c0881921e553aee6c532e1"
    )
    result = json.loads(raw.read_bytes())
    assert len(result) == 8 and all(r["qualified"] for r in result)
    assert all(
        not r["runtime_diagnostics"] and not r["broker_diagnostics"] for r in result
    )
    assert {(r["id"], r["market"]) for r in result} == {
        (i, m) for i in (5117, 5514) for m in ("BTCUSDT", "ETHUSDT")
    }
    reference = archive_reference_report()
    entries = {
        x["id"]: x for x in reference["archive_records"] if x["id"] in (5117, 5514)
    }
    cases = defaultdict(list)
    for r in result:
        assert sha256(work / r["feed"]) == r["feed_sha256"]
        assert r["source_sha256"] == entries[r["id"]]["script_sha256"]
        assert r["aux_verified_chart_bars"] == r["chart_bars"] - 1
        cases[r["id"], r["start"], r["end"]].append(r)

    results = []
    for (ident, start, end), rows in sorted(cases.items()):
        rows.sort(key=lambda a: a["market"])
        assert [r["market"] for r in rows] == ["BTCUSDT", "ETHUSDT"]
        mode = (
            "60m → 10m"
            if ident == 5117
            else "15m → 2m with PineForge boundary ownership"
        )
        timeframe = "1h" if ident == 5117 else "15m"
        attrs = {
            "id": ident,
            "group": "FMZ · Pine Compat priced stop · " + mode,
            "exit": "Archived Pine exits",
            "period": f"Binance USD-M · {iso_day(start)} to {iso_day(end)} UTC exclusive",
            "archive_interval": timeframe,
            "interval": timeframe,
            "currency": "USDT",
        }
        pooled = []
        total_open = 0
        for batch in rows:
            close = []
            for lot in batch["ledger"]:
                assert (
                    lot["id"] == "Entry"
                    and start <= lot["entryTime"] <= lot["exitTime"] < end
                )
                fee = lot["qty"] * (lot["entryPrice"] + lot["exitPrice"]) * 0.00075
                close.append({**lot, "dir": 1, "commission": fee})
            closed = len(close)
            pending = int(float(batch["final_position"]) != 0)
            assert batch["closed"] == closed and batch["opens"] == closed + pending
            results.append(
                {
                    **attrs,
                    "market": batch["market"],
                    **ledger_metrics(close, 10_000, pending),
                }
            )
            pooled.extend(close)
            total_open += pending
        results.append(
            {
                **attrs,
                "market": "BTCUSDT + ETHUSDT",
                **ledger_metrics(pooled, 20_000, total_open),
            }
        )
    assert len(results) == 12

    fixtures = {
        "baseline_stop": json.loads(
            (work / "priced-stop-control-market.json").read_bytes()
        ),
        "baseline_additional": json.loads(
            (work / "priced-controls-market.json").read_bytes()
        ),
        "patched_stop": json.loads(
            (work / "priced-stop-control-priced.json").read_bytes()
        ),
        "patched_additional": json.loads(
            (work / "priced-controls-priced.json").read_bytes()
        ),
        "market_regression": json.loads(
            (work / "market-fixtures-patched.json").read_bytes()
        ),
    }
    assert (
        sum(
            len(batch["checks"])
            for key, batch in fixtures.items()
            if not key.startswith("baseline")
        )
        == 22
    )
    for key, batch in fixtures.items():
        if key.startswith("baseline"):
            failures = {name for name, passed in batch["checks"].items() if not passed}
            assert failures == BASELINE_FAILURES[key]
        else:
            assert all(batch["checks"].values())
    isolation = read(work / "round3-isolation-python.json")
    assert set(isolation) == {"file_error", "network_error"}
    assert all(error[0] == "PermissionError" for error in isolation.values())
    report = {
        "schema": "Round 11 Pine Compat priced-stop provenance",
        "evidence_base_commit": "396ff2d735ca98902cc6593725a6564829055aec",
        "cargo_lock_sha256": market_reference()["cargo_lock_sha256"],
        "market_runtime_sha256": sha256(
            work / "market-runtime/pine_compat/pine_compat.pyd"
        ),
        "source_engine_commit": "c0ecc3bde5eece9c4f2a63c6785aec9c5e571acc",
        "rust_toolchain": "1.95.0-x86_64-pc-windows-gnu",
        "market_patch_sha256": "6d044b62947bb038f824092d164ec847b5b81036ff85e2978b18934a5b7ee591",
        "priced_stop_patch_sha256": priced_patch,
        "runtime_binary_sha256": sha256(
            work / "priced-runtime/pine_compat/pine_compat.pyd"
        ),
        "lower_timeframe_ownership_reference": "https://github.com/pineforge-4pass/pineforge-engine/blob/665fc4ddc024951dd1c911ad5de9839a5c91e2e4/include/pineforge/source/magnifier_intrabars.hpp",
        "raw_ledger_sha256": sha256(raw),
        "market_inputs": json.loads((work / "priced-market-inputs.json").read_bytes()),
        "archives": list(entries.values()),
        "isolation_denial_probe": isolation,
        "fixtures": fixtures,
        "coverage": [
            [
                5117,
                "Tested · Pine Compat priced-stop replay",
                "Preserved archived BTC-USDT strategy using 60m chart and complete 10m Binance broker data. ETH-USDT is a cross-asset replay.",
            ],
            [
                5514,
                "Tested · Pine Compat priced-stop replay",
                "Preserved archived BTC-USDT strategy using 15m chart and official 2m span, with PineForge-derived chart-boundary ownership. ETH-USDT is a cross-asset replay.",
            ],
        ],
        "instrument_note": "Both FMZ headers name Binance BTC_USDT. ETHUSDT results compare the same unchanged source on a second Binance contract. Historical market windows are August to October 2026.",
        "runs": result,
        "results": results,
    }
    write(output, report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(required=True, dest="mode")
    staged = modes.add_parser("stage")
    for name in ("work", "public", "previous"):
        staged.add_argument(name, type=Path)
    finalized = modes.add_parser("finalize")
    for name in ("work", "output"):
        finalized.add_argument(name, type=Path)
    args = parser.parse_args()
    if args.mode == "stage":
        stage(args.work, args.public, args.previous)
    else:
        finalize(args.work, args.output)
