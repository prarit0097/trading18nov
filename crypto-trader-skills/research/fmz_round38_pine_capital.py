"""Check whether rejected Pine capital assignment changes strategy order sizing."""

from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from math import isclose
from pathlib import Path
from shutil import copy2
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, date_ms, sha256
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH
from research.fmz_round28_pine_callback import cache_bars

TARGETS = (3190, 2828, 2823)
DAY = 86_400_000
ASSIGNMENT = "strategy.initial_capital = 50000"
WINDOWS = {
    3190: ("2022-12-05", "2023-12-11", 366),
    2828: ("2022-12-24", "2023-12-07", 45),
}
PROBE = "fmz_round38_pine_capital_probe.py"


def inputs(archive, baseline, folders):
    assert sha256(archive) == FMZ_SHA256
    scope = {
        r["id"]: r
        for r in read(baseline)["disposition"]
        if r["id"] in TARGETS and r["status"].startswith("Pending")
    }
    assert set(scope) == set(TARGETS)
    scripts, digest = {}, {}
    with ZipFile(archive) as book:
        mention_count = sum(
            ASSIGNMENT.encode() in book.read(name)
            for name in book.namelist()
            if name.endswith(".md")
        )
        assert mention_count == 77
        for ident, _, doc, checksum in documents(book, scope):
            (raw,) = re.findall(
                r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", doc
            )
            assert raw.count(ASSIGNMENT) == 1
            scripts[ident] = raw.encode()
            digest[ident] = checksum
    for ident in WINDOWS:
        script = scripts[ident].decode()
        assert "initial_capital=1000," in script
        assert "var float capital_ref = strategy.initial_capital" in script
        assert "var float cashOrder = strategy.initial_capital * 0.95" in script
        assert "commission_value=0.18" in script
        assert "inRange := true" in script
    assert "QTYMethod               = input.string ('EQUITY'," in scripts[2823].decode()
    assert (
        "strategy.initial_capital + (useNetProfit ? strategy.netprofit : 0)"
        in scripts[2823].decode()
    )
    assert "qty=eqty(eqty)" in scripts[2823].decode()
    all_cases, archives = {}, []
    for ident, (first, second, pad) in WINDOWS.items():
        start, close = map(date_ms, (first, second))
        stop = 2 * close - start
        history = start - pad * DAY
        months = sorted(
            {
                datetime.fromtimestamp(t / 1000, UTC).strftime("%Y-%m")
                for t in range(history, stop, DAY)
            }
        )
        cases = {}
        for market in ("BTCUSDT", "ETHUSDT"):
            candles = [
                list(r)
                for r in cache_bars(folders, market, "1d", months, DAY, archives)
                if history <= r[0] < stop
            ]
            assert [r[0] for r in candles] == list(range(history, stop, DAY))
            for period, a, b in (("native", start, close), ("next", close, stop)):
                cases.setdefault(period, {})[market] = {
                    "chart": [r for r in candles if a <= r[0] < b],
                    "with_prefix": [r for r in candles if a - pad * DAY <= r[0] < b],
                    "trading_start": a,
                }
        all_cases[ident] = cases
    return scripts, digest, all_cases, archives, mention_count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "finalize"))
    for group in ("archive", "baseline", "work", "output"):
        parser.add_argument(f"--{group}", type=Path, required=True)
    parser.add_argument("--daily", type=Path, nargs="+", required=True)
    args = parser.parse_args()
    scripts, source_hashes, all_cases, archives, mention_count = inputs(
        args.archive, args.baseline, args.daily
    )
    probe = Path(__file__).with_name(PROBE)
    scratch_probe = args.work / "r38_capital_probe.py"
    if args.mode == "stage":
        copy2(probe, scratch_probe)
        for ident, cases in all_cases.items():
            (args.work / f"r38-capital-{ident}-source.pine").write_bytes(scripts[ident])
            write(args.work / f"r38-capital-{ident}-feeds.json", cases)
        return
    assert probe.read_bytes() == scratch_probe.read_bytes()
    for ident, cases in all_cases.items():
        assert (args.work / f"r38-capital-{ident}-source.pine").read_bytes() == scripts[
            ident
        ]
        assert read(args.work / f"r38-capital-{ident}-feeds.json") == cases
    assert (
        sha256(args.work / "priced-runtime/pine_compat/pine_compat.pyd")
        == NATIVE_BINARY_HASH
    )
    isolation = read(args.work / "round3-isolation-python.json")
    assert all(
        isolation[k][0] == "PermissionError" for k in ("file_error", "network_error")
    )
    run_path = args.work / "r38-capital.json"
    cases = read(run_path)
    assert (
        len(cases)
        == len(
            {
                (c["id"], c["period"], c["market"], c["case"], c["context"])
                for c in cases
            }
        )
        == 64
    )
    literals, outputs = {}, []
    values = {
        "declared": (1000, 950),
        "separate": (1000, 23100),
        "property": (50000, 47500),
    }
    for case in cases:
        ident, mode, context = (case[k] for k in ("id", "case", "context"))
        if mode == "literal":
            error = case["error"]
            assert "E_PARSE_EXPR" in error and "expected expression" in error
            assert literals.setdefault(ident, error) == error
            continue
        assert not case["diagnostics"] and not case["strategy"]["diagnostics"]
        equity, cash = values[mode]
        strategy = case["strategy"]
        candle = all_cases[ident][case["period"]][case["market"]]
        assert strategy["equity"][0]["equity"] == equity
        assert case["plots"]["Cash order"][0] == cash
        assert len(strategy["equity"]) == len(candle[context])
        orders = strategy["orders"]
        assert all(order["time"] >= candle["trading_start"] for order in orders)
        for closed in strategy["trades"]:
            p, q = closed["entryPrice"], closed["exitPrice"]
            qty = closed["qty"]
            check = qty * (q - p) - abs(qty) * (p + q) * 0.0018
            assert isclose(check, closed["profit"], rel_tol=1e-10, abs_tol=1e-8)
        outputs.append(
            {
                k: case[k]
                for k in ("id", "period", "market", "case", "context", "source_sha256")
            }
            | {
                "initial_equity": equity,
                "initial_cash_order_after_ratio_update": cash,
                "first_executed_qty": orders[0]["qty"] if orders else None,
                "closed_lots": len(strategy["trades"]),
                "after_source_fees_diagnostic": sum(
                    x["profit"] for x in strategy["trades"]
                ),
            }
        )
    coverage = [
        [
            3190,
            "Pending · FMZ initial equity and order-size provenance",
            "The literal archive assigns 50,000 to strategy.initial_capital, which Pine Compat rejects and which feeds both capital_ref and cashOrder. Verified daily alternative uses separate 1,000 versus 50,000 holdings and unsaved 365-day prehistory, changing executable quantity from 0.519 to 12.630 or 25.972 ETH. Exact FMZ host configuration and initial history are absent.",
        ],
        [
            2828,
            "Pending · FMZ initial equity and order-size provenance",
            "The illegal 50,000 assignment feeds active sizing. Recovered presentation-only plot calls for diagnostics. On the same daily BTC tape the 1,000-property, 50,000-sizing-only and 50,000-property hypotheses produce first quantities of 0.046, 1.135 and 2.334. Host balance, assignment semantics and exact intraday bracket execution are still unverified.",
        ],
        [
            2823,
            "Pending · FMZ initial equity and order-size provenance",
            "The archived declaration sets 10,000 and an invalid alternate assignment sets 50,000. Both feed the default EQUITY quantity path when interpreted as the initial-capital value. Static dependency verified against archive. The actual FMZ host capital and exact higher-timeframe timing have not been recovered.",
        ],
    ]
    write(
        args.output,
        {
            "baseline_coverage_sha256": sha256(args.baseline),
            "archive_sha256": FMZ_SHA256,
            "pine_compat_binary_sha256": NATIVE_BINARY_HASH,
            "isolation_probe": isolation,
            "source_sha256": source_hashes,
            "provider_archives": archives,
            "probe_sha256": sha256(probe),
            "isolated_native_receipt_sha256": sha256(run_path),
            "literal_rejection": literals,
            "archive_same_assignment_document_count": mention_count,
            "daily_diagnostic_scope": "OHLC broker only; no results admitted. RSI-WMA saved end 05:20 lies within its final daily bar and only daily-open-date sampling is modeled here.",
            "references": [
                "https://www.fmz.com/doc/9293#strategy",
                "https://www.fmz.com/user-guide/backtesting-system/backtest-configuration-and-saving",
                "https://www.fmz.com/strategy/435134",
                "https://www.tradingview.com/script/l2nAUB2f/",
                "https://www.tradingview.com/script/FOf28r5x/",
            ],
            "diagnostic_engine_outputs": outputs,
            "coverage": coverage,
            "results": [],
        },
    )
    print(
        f"Verified {len(cases)} isolated diagnostics and {len(coverage)} unchanged pending dispositions."
    )


if __name__ == "__main__":
    main()
