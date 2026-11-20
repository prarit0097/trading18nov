"""Replay the archived 4D pivot strategy under predeclared UTC phase zero."""

from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from itertools import groupby
from math import floor
from pathlib import Path
from shutil import copy2
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, date_ms, sha256
from research.fmz_round7_pine import EXECUTION, summarize
from research.fmz_round18_pine_qqe import executable_lines
from research.fmz_round19_pine_broker import equal
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH
from research.fmz_round28_pine_callback import cache_bars

IDENT = 3435
GROUP = "FMZ Pine · Closed 4D Classic pivots and archived long-only rules"
MARKETS = ("BTCUSDT", "ETHUSDT")
LABEL = {"native": "FMZ native window", "next": "Next equal window"}
DAY = 86_400_000
HOUR = 3_600_000
CAPITAL = 100_000
FEE = 0.0001
LOT = 0.001
PLOTS = ("R1", "S2", "Date gate", "Buy", "Sell", "Position")
ANCHORS = ("2023-12-29", "2024-02-29", "2026-11-21")
PRIMARY = "0"
PRODUCER = "fmz_round36_pine_pivots_probe.py"


def record(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (row,) = (r for r in read(baseline)["disposition"] if r["id"] == IDENT)
    assert row["status"].startswith("Pending")
    with ZipFile(archive) as source:
        ((_, original, doc, digest),) = documents(source, {IDENT: row})
    (raw,) = re.findall(r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", doc)
    fields = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)", raw
        )
    )
    assert fields == {
        "start": "2022-12-22 00:00:00",
        "end": "2023-12-28 00:00:00",
        "period": "1d",
        "basePeriod": "1h",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    assert "//@version=4" in raw
    active = "\n".join(executable_lines(raw))
    for witness in (
        "initial_capital = 100000, default_qty_type = strategy.percent_of_equity, default_qty_value = 100",
        "commission_type = strategy.commission.percent, pyramiding = 1, commission_value = 0.01, calc_on_order_fills = true",
        "Source = input(close)",
        'resolution = input("4D", type=input.resolution)',
        'ppType = "fib"',
        "defval=strategy.direction.long",
        "defval=10, minval=1, maxval=30",
        'defval="years", options=["days", "months", "years"]',
        "f_secureSecurity(_symbol, _res, _src) => security(_symbol, _res, _src[1], lookahead = barmerge.lookahead_on)",
        "PP = (HIGHprev + LOWprev + CLOSEprev) / 3",
        "R1 = PP * 2 - LOWprev",
        "S2 = PP - (HIGHprev - LOWprev)",
        "[Rf5, Rf4, Rf3, Rf2, Rf1, PPf, Sf1, Sf2, Sf3, Sf4, Sf5] = f_getFibPivots(HIGHprev, LOWprev, CLOSEprev)",
        "[R5, R4, R3, R2, R1, PP, S1, S2, S3, S4, S5]",
        "yr = year(timenow)",
        "yr := yr - backtestBars",
        "strategy.risk.allow_entry_in(tradeDirection)",
        "longCondition = crossover(Source[1],R1) and inDateRange",
        "shortCondition = crossunder(Source[1], S2) and inDateRange",
        'strategy.entry("Buy", strategy.long, when=longCondition, oca_name="oca")',
        'strategy.entry("Sell", strategy.short, when=shortCondition, oca_name="oca")',
    ):
        assert witness in active, witness
    return original, digest, fields, raw.encode()


def bucket(stamp, phase):
    return ((stamp // DAY - phase) // 4 * 4 + phase) * DAY


def feed_data(folders):
    start, boundary, prehistory = map(
        date_ms, ("2022-12-22", "2023-12-28", "2022-12-12")
    )
    end = 2 * boundary - start
    months = sorted(
        {
            datetime.fromtimestamp(t / 1000, UTC).strftime("%Y-%m")
            for t in range(prehistory, end, DAY)
        }
    )
    cases, manifest = {}, []
    for market in MARKETS:
        candles = [
            r
            for r in cache_bars(folders, market, "1d", months, DAY, manifest)
            if prehistory <= r[0] < end
        ]
        assert [r[0] for r in candles] == list(range(prehistory, end, DAY))
        for period, lo, hi in (("native", start, boundary), ("next", boundary, end)):
            chart = [list(r) for r in candles if lo <= r[0] < hi]
            contexts = {}
            for phase in range(4):
                context = []
                for t, rows in groupby(
                    (r for r in candles if r[0] < hi),
                    lambda r, phase=phase: bucket(r[0], phase),
                ):
                    members = list(rows)
                    if members[0][0] != t:
                        continue
                    context.append(
                        [
                            t,
                            members[0][1],
                            max(r[2] for r in members),
                            min(r[3] for r in members),
                            members[-1][4],
                            sum(r[5] for r in members),
                        ]
                    )
                contexts[str(phase)] = context
            cases.setdefault(period, {})[market] = {
                "chart": chart,
                "contexts": contexts,
            }
    return manifest, cases


def stage(archive, baseline, work, daily):
    _, _, _, raw = record(archive, baseline)
    _, data = feed_data(daily)
    (work / "r36-pivots-source.pine").write_bytes(raw)
    write(work / "r36-pivots-feeds.json", data)
    copy2(Path(__file__).with_name(PRODUCER), work / "r36_pivots_probe.py")


def quantity(cash, price):
    return floor(float(f"{cash:.9e}") / (price * (1 + FEE)) / LOT + 1e-9) * LOT


def replay(tape, phase):
    context = {r[0]: r for r in tape["contexts"][str(phase)]}
    chart = tape["chart"]
    cash = CAPITAL
    entry = None
    pending = 0
    last_price = last_r = last_s = None
    fills, states, marks, opens, callbacks = [], [], [], [], []
    for i, (t, o, h, l, c, _) in enumerate(chart):
        if pending > 0 and entry is None:
            q = quantity(cash, o)
            entry = (i, o, q)
            cash -= q * o * (1 + FEE)
            opens.append(entry)
        closed = pending < 0 and entry is not None
        if closed:
            j, p, q = entry
            fills.append((j, i, p, o, q))
            cash += q * o * (1 - FEE)
            entry = None
        prior = bucket(t, phase) - 4 * DAY
        assert prior + 4 * DAY <= t
        _, _, high, low, close, _ = context[prior]
        pivot = (high + low + close) / 3
        r, s = 2 * pivot - low, pivot - (high - low)
        source_price = chart[i - 1][4] if i else None
        has_previous = last_price is not None and source_price is not None
        buy = has_previous and source_price > r and last_price <= last_r
        sell = has_previous and source_price < s and last_price >= last_s
        assert not (buy and sell)
        pending = int(buy) - int(sell)
        if closed and buy:
            # A historical daily market callback is filled at the next modeled tick.
            p = h if h - o < o - l else l
            q = quantity(cash, p)
            entry = (i, p, q)
            cash -= q * p * (1 + FEE)
            opens.append(entry)
            callbacks.append(
                {"time": t, "daily_open": o, "daily_emulator_rebuy": p, "qty": q}
            )
            pending = 0
        last_price, last_r, last_s = source_price, r, s
        amount = entry[-1] if entry is not None else 0
        states.append((r, s, True, buy, sell, amount))
        marks.append((cash, amount * c, cash + amount * c))
    return states, fills, marks, opens, callbacks


def check_fields(a, b):
    return all(equal(x, y) for x, y in zip(a, b, strict=True))


def verify(tape, receipt):
    assert {d["code"] for d in receipt["diagnostics"]} == {
        "W_LEGACY_SECURITY_LOOKAHEAD"
    }
    assert not receipt["strategy"]["diagnostics"]
    states, fills, marks, opens, callbacks = replay(tape, int(receipt["phase"]))
    plots = zip(*(receipt["plots"][p] for p in PLOTS), strict=True)
    assert all(check_fields(a, b) for a, b in zip(states, plots, strict=True))
    chart = tape["chart"]
    strategy = receipt["strategy"]
    for i, (mark, state) in enumerate(zip(marks, strategy["equity"], strict=True)):
        assert state["barIndex"] == i
        assert check_fields(
            (*mark, mark[-1] - CAPITAL),
            (state[k] for k in ("cash", "marketValue", "equity", "netProfit")),
        )
    for (i, p, q), order in zip(opens, strategy["orders"], strict=True):
        assert order["id"] == "Buy" and order["direction"] == "strategy.long"
        assert (order["barIndex"], order["time"], order["price"]) == (i, chart[i][0], p)
        assert equal(q, order["qty"])
    ledger = []
    for (i, j, paid, received, qty), lot in zip(fills, strategy["trades"], strict=True):
        assert lot["id"] == "Buy"
        assert (lot["entryTime"], lot["exitTime"]) == (chart[i][0], chart[j][0])
        assert check_fields(
            (i, j, paid, received, qty),
            (
                lot[k]
                for k in (
                    "entryBarIndex",
                    "exitBarIndex",
                    "entryPrice",
                    "exitPrice",
                    "qty",
                )
            ),
        )
        gross = qty * (received - paid)
        cash_turnover = qty * (received + paid)
        fees = cash_turnover * FEE
        assert equal(lot["profit"], gross - fees)
        ledger.append((chart[j][0], gross, fees, cash_turnover * EXECUTION))
    return (
        ledger,
        int(states[-1][-1] > 0),
        {
            "closed": len(fills),
            "opens": len(opens),
            "chart_bars": len(chart),
            "long_signals": sum(r[3] for r in states),
            "close_signals": sum(r[4] for r in states),
            "terminal_qty": states[-1][-1],
            "callbacks": callbacks,
            "ending_marked_equity": marks[-1][-1],
            "verified_plot_values": len(states) * len(PLOTS),
        },
    )


def finalize(archive, baseline, work, daily, hourly, output):
    datum, digest, settings, raw = record(archive, baseline)
    manifest, cases = feed_data(daily)
    staged = work / "r36-pivots-source.pine"
    feed = work / "r36-pivots-feeds.json"
    producer = Path(__file__).with_name(PRODUCER)
    assert staged.read_bytes() == raw and read(feed) == cases
    assert producer.read_bytes() == (work / "r36_pivots_probe.py").read_bytes()
    assert (
        sha256(work / "priced-runtime/pine_compat/pine_compat.pyd")
        == NATIVE_BINARY_HASH
    )
    isolation = read(work / "round3-isolation-python.json")
    assert all(
        isolation[k][0] == "PermissionError" for k in ("file_error", "network_error")
    )
    diagnostics = work / "r36-pivots-full.json"
    assert (work / "r36-pivots-full.exit").read_text().strip() == "0"
    receipts = read(diagnostics)
    index = {(x["period"], x["market"], x["phase"], x["anchor"]): x for x in receipts}
    assert len(index) == len(receipts) == 48
    (executed_hash,) = {x["executed_source_sha256"] for x in receipts}
    metadata = {
        "id": IDENT,
        "name": datum["name"],
        "source": datum["source"],
        "group": GROUP,
        "interval": "1d",
        "archive_interval": "1d",
        "quote_currency": "USDT",
        "source_sha256": digest,
        "executed_source_sha256": executed_hash,
        "comparison_fee": FEE,
        "market_data": "Binance USD-M daily OHLCV and predeclared UTC phase-0 4D synthesis",
        "exit": "Opposite signal closes the long at the next daily open",
    }
    rows, sensitivity, callback_events = [], [], []
    for period, markets in cases.items():
        pooled, outstanding = [], 0
        for symbol, tape in markets.items():
            for phase in map(str, range(4)):
                variants = [
                    verify(tape, index[(period, symbol, phase, anchor)])
                    for anchor in ANCHORS
                ]
                ledger, terminal, counts = variants[0]
                assert all(entry == variants[0] for entry in variants)
                metrics = summarize(ledger, terminal, CAPITAL)
                sensitivity.append(
                    {
                        "period": LABEL[period],
                        "market": symbol,
                        "utc_phase": int(phase),
                        **metrics,
                        **counts,
                    }
                )
                callback_events.extend(
                    (period, symbol, phase, r) for r in counts["callbacks"]
                )
                if phase == PRIMARY:
                    assert not counts["callbacks"]
                    rows.append(
                        {
                            **metadata,
                            "period": LABEL[period],
                            "market": symbol,
                            **metrics,
                        }
                    )
                    pooled.extend(ledger)
                    outstanding += terminal
        rows.append(
            {
                **metadata,
                "period": LABEL[period],
                "market": "BTCUSDT + ETHUSDT",
                **summarize(pooled, outstanding, 2 * CAPITAL),
            }
        )
    ((period, market, phase, event),) = callback_events
    assert (period, market, phase) == ("native", "BTCUSDT", "3")
    assert event["time"] == date_ms("2023-11-16")
    hours = list(cache_bars(hourly, market, "1h", ("2023-11",), HOUR, manifest))
    day = [r for r in hours if event["time"] <= r[0] < event["time"] + DAY]
    assert [r[0] for r in day] == list(range(event["time"], event["time"] + DAY, HOUR))
    assert (
        day[0][1] == event["daily_open"]
        and max(r[2] for r in day) == event["daily_emulator_rebuy"]
    )
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(baseline),
            "archive_sha256": FMZ_SHA256,
            "pine_compat_binary_sha256": NATIVE_BINARY_HASH,
            "isolation_probe": isolation,
            "source_audit": {
                "document_sha256": digest,
                "archive_settings": settings,
                "archive_market": "BTCUSDT USD-M",
                "archive_4d_phase_available": False,
                "phase_assumption": "UTC daily ordinal since Unix epoch modulo four; primary phase selected before the outcomes",
                "primary_utc_phase": int(PRIMARY),
                "pinned_execution_clocks_utc": ANCHORS,
                "verified_run_count": len(index),
                "executed_source_sha256": executed_hash,
                "qualified_for_strategy_promotion": False,
            },
            "provider_archives": manifest,
            "artifacts": {
                p.name: sha256(p) for p in (staged, feed, producer, diagnostics)
            },
            "phase_sensitivity_not_in_workbook": sensitivity,
            "phase_3_intraday_callback_evidence": {
                **event,
                "next_hour_open": day[1][1],
                "first_hour_high": day[0][2],
                "hours_with_daily_high": [
                    r[0] for r in day if r[2] == event["daily_emulator_rebuy"]
                ],
                "scope": "Separate daily-emulator sensitivity. The archived FMZ base-period fill was not recovered.",
            },
            "method": [
                "Runs the unmodified archived Pine v4 order path, with plots added for verification. The default resolution is 4D. The helper returns Classic pivot levels despite its fib-labelled variable. It reads high, low and close from the previous completed four-day block through the authored one-block offset, so the lookahead warning does not imply future data in these signals.",
                "UTC phase zero was specified before results. The original FMZ anchor was unavailable, so all four UTC alignments are preserved as sensitivities and only phase zero has workbook rows. Completed context warmup predates each reset daily strategy window. Three separately pinned valid UTC execution clocks produce identical date gates and order ledgers because the default cutoff is January 1 of execution year minus ten.",
                "Default 100% long-only equity and 0.01% per-side commission are preserved. Opposite entries close longs. An independent model matches all plots, orders, cash, marked equity and closed trades across 48 runs. A 0.001 contract-quantity step and separate 0.03% per-side execution buffer are replay assumptions. Any terminal position remains open.",
                "All phase-zero fills occur at observed daily opens and the authored fill callback causes no additional order there. The alternate BTC phase-three archived window is marked as a daily broker-emulator sensitivity because a callback rebuys at the modeled daily high. The first-hour high equals that price, while the next official hourly open differs. That phase is not attributed to the original FMZ hourly base-period fill path.",
                "The exact saved historical dates, equal later dates and same-venue ETH comparisons are research scopes. These replay observations do not qualify the strategy for trading.",
            ],
            "references": [
                "https://www.fmz.com/lang/en/syntax-guide/fun/market/exchange.getrecords",
                "https://www.tradingview.com/pine-script-docs/v4/essential/strategies/",
                "https://www.tradingview.com/pine-script-docs/concepts/strategies/",
                "https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/",
                "https://github.com/binance/binance-public-data",
            ],
            "coverage": [
                [
                    IDENT,
                    f"Tested · {GROUP}",
                    "Replayed archived Classic 4D rules with explicit UTC anchor and compared all four possible phases. Independently verified daily open orders, quantities, fees and marked equity. Unrecovered FMZ phase remains a disclosed comparison assumption.",
                ]
            ],
            "results": rows,
        },
    )
    primary_closes = sum(
        r["closed"] for r in sensitivity if r["utc_phase"] == int(PRIMARY)
    )
    print(
        f"Verified {IDENT}: {len(rows)} workbook results, {primary_closes} closed lots, {len(receipts)} audited runs."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "finalize"))
    for name in ("archive", "baseline", "work", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for name in ("daily", "hourly"):
        parser.add_argument(f"--{name}", type=Path, nargs="+", required=True)
    args = parser.parse_args()
    common = (args.archive, args.baseline, args.work, args.daily)
    if args.mode == "stage":
        stage(*common)
    else:
        finalize(*common, args.hourly, args.output)


if __name__ == "__main__":
    main()
