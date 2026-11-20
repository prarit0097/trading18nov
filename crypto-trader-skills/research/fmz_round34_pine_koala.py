"""Reproduce the Koala source session and minute-level bracket fills."""

from __future__ import annotations

import argparse
import re
from collections import Counter
from datetime import UTC, datetime
from itertools import batched, pairwise
from math import fsum
from pathlib import Path
from shutil import copy2
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import (
    FMZ_SHA256,
    aggregate,
    date_ms,
    sha256,
    verified_archives,
)
from research.fmz_round7_pine import EXECUTION, summarize
from research.fmz_round12_pine_authored import provider_bars
from research.fmz_round18_pine_qqe import executable_lines
from research.fmz_round19_pine_broker import equal
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH
from research.fmz_round28_pine_callback import cache_bars

IDENT = 5486
CAPITAL = 1000
FEE = 0.000065
MARKETS = ("BTCUSDT", "ETHUSDT")
LABEL = {"native": "FMZ native window", "next": "Next equal window"}
GROUP = "FMZ Pine · Legacy UTC session and minute bracket verification"
MASKS = {1699628400000, 1699632000000}
HOUR = 3_600_000
MINUTE = 60_000
PINE = """//@version=5
strategy("Koala Script",initial_capital=1000, commission_type=strategy.commission.cash_per_contract, commission_value=0.000065, slippage=3, use_bar_magnifier=true, margin_long=0, margin_short=0)
smma=ta.rma(hl2,3)
smma2=ta.rma(hl2,6)
smma3=ta.rma(hl2,9)
smma4=ta.rma(close,50)
out5=0.0
emaK=2.0/201
out5:=na(out5[1])?close:emaK*close+(1-emaK)*out5[1]
london=not na(time(timeframe.period,"0300-1045:23456","Etc/UTC"))
londonEntry=not na(time(timeframe.period,"0300-0845:23456","Etc/UTC"))
longCond=close > out5 and close > smma4 and close > smma3 and close > smma2 and close > smma and londonEntry and smma > smma2 and smma2>smma3 and smma3>smma4 and smma4>out5
shortCond=close < out5 and close < smma4 and close < smma3 and close < smma2 and close < smma and londonEntry and smma < smma2 and smma2<smma3 and smma3<smma4 and smma4<out5
strategy.entry("long",strategy.long,when=longCond)
strategy.exit("closelong","long",profit=300,loss=300)
strategy.entry("short",strategy.short,when=shortCond)
strategy.exit("closeshort","short",profit=300,loss=300)
strategy.close_all(when=not london)
"""


def source(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (row,) = (q for q in read(baseline)["disposition"] if q["id"] == IDENT)
    assert row["status"].startswith("Pending")
    with ZipFile(archive) as z:
        ((_, r, markdown, digest),) = documents(z, {IDENT: row})
    (raw,) = re.findall(
        r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", markdown
    )
    config = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)", raw
        )
    )
    assert config == {
        "start": "2023-10-22 00:00:00",
        "end": "2023-11-21 00:00:00",
        "period": "1h",
        "basePeriod": "15m",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    active = "\n".join(executable_lines(raw))
    required = (
        'strategy("Koala Script",initial_capital=1000,',
        "commission_type=strategy.commission.cash_per_contract",
        "commission_value=0.000065",
        "slippage=3)",
        "strategy.initial_capital = 50000",
        "timeinrange(res, sess) => time(res, sess) != 0",
        'london=timeinrange(timeframe.period, "0300-1045")',
        'londonEntry=timeinrange(timeframe.period, "0300-0845")',
        "len = input(3,",
        "len2 = input(6,",
        "len3 = input(9,",
        "len4 = input(50,",
        "len5 = input(200,",
        "out5 = ema(src5, len5)",
        "tp=input(300,",
        "sl=input(300,",
        'strategy.entry("long",1,when=longCond )',
        'strategy.entry("short",0,when=shortCond )',
        'strategy.exit("closelong","long", profit=tp,loss=sl)',
        'strategy.exit("closeshort","short", profit=tp,loss=sl)',
        "strategy.close_all(when = not london)",
    )
    assert "//@version=4" in raw and all(q in active for q in required)
    assert [
        line.strip() for line in active.splitlines() if re.search(r"\bsize\b", line)
    ] == ["size = temp03 - temp03%1000", "if(size < 10000)", "size := 10000"]
    assert active.count("time_cond") == 1
    return r, digest, config, raw.encode()


def feeds(public, minute):
    a, b = map(date_ms, ("2023-10-22", "2023-11-21"))
    hi = 2 * b - a
    months = ("2023-10", "2023-11", "2023-12")
    manifest, data, exceptions = [], {}, {}
    for market in MARKETS:
        lanes = verified_archives(public, market, "1h", months, manifest)
        main = [r for p in lanes for r in provider_bars(p, HOUR) if a <= r[0] < hi]
        lower = [
            r
            for r in cache_bars(minute, market, "1m", months, MINUTE, manifest)
            if a <= r[0] < hi
        ]
        assert [r[0] for r in main] == list(range(a, hi, HOUR))
        assert [r[0] for r in lower] == list(range(a, hi, MINUTE))
        discrep = [
            (tuple(raw[:5]), tuple(native[:5]))
            for raw, native in zip(aggregate(lower, 60), main, strict=True)
            if raw[:5] != native[:5]
        ]
        assert {x[0][0] for x in discrep} == (MASKS if market == "BTCUSDT" else set())
        exceptions[market] = discrep
        for period, lo, end in (("native", a, b), ("next", b, hi)):
            data.setdefault(period, {})[market] = {
                "chart": [list(r) for r in main if lo <= r[0] < end],
                "base": [list(r) for r in lower if lo <= r[0] < end],
            }
    return manifest, data, exceptions


def stage(archive, baseline, work, public, minute):
    _, _, _, raw = source(archive, baseline)
    _, data, _ = feeds(public, minute)
    (work / "r34-koala-source.pine").write_bytes(raw)
    (work / "r34-koala-v5.pine").write_bytes(PINE.encode())
    write(work / "r34-koala-feeds.json", data)
    copy2(
        Path(__file__).with_name("fmz_round34_pine_koala_probe.py"),
        work / "r34_koala_probe.py",
    )


def rma(seq, n):
    out = [None] * (n - 1)
    x = fsum(seq[:n]) / n
    out.append(x)
    for v in seq[n:]:
        x = (x * (n - 1) + v) / n
        out.append(x)
    return out


def signals(chart):
    mids = [(r[2] + r[3]) / 2 for r in chart]
    closes = [r[4] for r in chart]
    ma = [rma(mids, n) for n in (3, 6, 9)] + [rma(closes, 50)]
    ema = None
    for i, c in enumerate(closes):
        t = datetime.fromtimestamp(chart[i][0] / 1000, UTC)
        weekend = t.weekday() >= 5
        mid_session = not weekend and 3 <= t.hour <= 10
        entry = not weekend and 3 <= t.hour <= 8
        ema = c if ema is None else c * (2 / 201) + (1 - 2 / 201) * ema
        m = [seq[i] for seq in ma]
        bars = (c, *m, ema)
        defined = all(x is not None for x in bars)
        upside = entry and defined and all(x > y for x, y in pairwise(bars))
        downside = entry and defined and all(x < y for x, y in pairwise(bars))
        yield mid_session, entry, *m, ema, upside, downside


def walk(k, sigs, mag):
    chart = k["chart"]
    minutes = list(batched(k["base"], 60, strict=True))
    side = 0
    holding = None
    requested = 0
    close_next = False
    fills = []
    positions = []
    gaps = []
    for i, (bar, sub, decision) in enumerate(zip(chart, minutes, sigs, strict=True)):
        t, o, _, _, _, _ = bar
        if t in MASKS and mag == 0.1:
            assert side == 0 and requested == 0
            assert not decision[0]
        if side and close_next:
            j, p = holding
            fills.append((j, i, side, p, o - side * mag * 3, "market", t))
            side = 0
        if requested and requested != side:
            if side:
                j, p = holding
                fills.append((j, i, side, p, o - side * mag * 3, "reverse", t))
            side = requested
            holding = (i, o + requested * mag * 3)
        if side:
            j, p = holding
            take, stop = p + side * mag * 300, p - side * mag * 300
            for stamp, op, hi, lo, cl, vol in sub:
                if not vol:
                    continue
                reach_take = hi >= take if side > 0 else lo <= take
                reach_stop = lo <= stop if side > 0 else hi >= stop
                gap_take = side * (op - take) >= 0
                gap_stop = side * (stop - op) >= 0
                if gap_take:
                    fill = op
                    way = "take gap"
                    gaps.append((stamp, "take", op, take))
                elif gap_stop:
                    fill = op - side * mag * 3
                    way = "stop gap"
                    gaps.append((stamp, "stop", op, stop))
                elif reach_take and reach_stop:
                    raise AssertionError((i, stamp, "both bracket levels reached"))
                elif reach_take:
                    fill = take
                    way = "take"
                elif reach_stop:
                    fill = stop - side * mag * 3
                    way = "stop"
                else:
                    continue
                fills.append((j, i, side, p, fill, way, stamp))
                side = 0
                break
        positions.append(side)
        requested = 1 if decision[-2] else -1 if decision[-1] else 0
        close_next = not decision[0]
    return fills, positions, gaps


KEYS = (
    "Session",
    "Entry hours",
    "SMMA 3",
    "SMMA 6",
    "SMMA 9",
    "SMMA 50",
    "EMA 200",
    "Long gate",
    "Short gate",
)


def audit(sample, market, base, real):
    bars = sample["chart"]
    seq = list(signals(bars))
    for case in (base, real):
        assert not case["strategy"]["diagnostics"]
        plots = case["witnesses"]
        for i, (expected, got) in enumerate(
            zip(seq, zip(*(plots[k] for k in KEYS), strict=True), strict=True)
        ):
            assert all(equal(x, y) for x, y in zip(expected, got, strict=True)), (
                i,
                expected,
                got,
            )
    tick = 0.1 if market == "BTCUSDT" else 0.01
    ledger, positions, gaps = walk(sample, seq, tick)
    assert not gaps
    assert positions == real["witnesses"]["Position"]
    fallback = [
        i for i, bar in enumerate(bars) if market == "BTCUSDT" and bar[0] in MASKS
    ]
    assert [s["code"] for s in real["diagnostics"]] == ["W_MAGNIFIER_FALLBACK"] * len(
        fallback
    )
    assert all(
        f"chart bar {i}" in d["message"]
        for i, d in zip(fallback, real["diagnostics"], strict=True)
    )
    assert not base["diagnostics"]
    for rows in (base["strategy"]["orders"], real["strategy"]["orders"]):
        assert all(r["barIndex"] not in fallback for r in rows)
        assert all(r["time"] == bars[r["barIndex"]][0] for r in rows)
        assert all(r["qty"] == 1 for r in rows)
    results = []
    labels = Counter()
    for expected, observed in zip(ledger, real["strategy"]["trades"], strict=True):
        start, end, side, entered, exited, style, ms = expected
        primary = (
            observed["entryBarIndex"],
            observed["exitBarIndex"],
            observed["qty"],
            observed["entryPrice"],
            observed["exitPrice"],
        )
        assert all(equal(a, b) for a, b in zip(expected[:5], primary, strict=True)), (
            expected,
            primary,
        )
        assert (
            observed["entryTime"] == bars[start][0]
            and observed["exitTime"] == bars[end][0]
        )
        assert observed["id"] == ("long" if side > 0 else "short")
        gross = side * (exited - entered)
        fee = 2 * FEE
        assert equal(observed["profit"], gross - fee)
        results.append((ms, gross, fee, (entered + exited) * EXECUTION))
        labels[style] += 1
    # The default hourly path is retained as an execution diagnostic only.
    different = sum(
        not equal(x["exitPrice"], y["exitPrice"])
        for x, y in zip(
            base["strategy"]["trades"], real["strategy"]["trades"], strict=True
        )
    )
    return (
        results,
        int(bool(positions[-1])),
        {
            "closed": len(results),
            "verified_minute_exit_count": len(results),
            "observed_exit_paths": dict(labels),
            "exit_minute_ms": [j[-1] for j in ledger],
            "omitted_no_exposure_hour_indices": fallback,
            "standard_hourly_path_price_differences": different,
            "terminal_position": positions[-1],
            "same_minute_both_barriers": 0,
        },
    )


def report(archive, baseline, work, public, minute, output):
    row, digest, settings, raw = source(archive, baseline)
    manifest, samples, discrepancies = feeds(public, minute)
    original = work / "r34-koala-source.pine"
    transformed = work / "r34-koala-v5.pine"
    input_path = work / "r34-koala-feeds.json"
    assert original.read_bytes() == raw and transformed.read_bytes() == PINE.encode()
    assert read(input_path) == samples
    binary = work / "priced-runtime/pine_compat/pine_compat.pyd"
    assert sha256(binary) == NATIVE_BINARY_HASH
    isolation = read(work / "round3-isolation-python.json")
    assert all(
        isolation[k][0] == "PermissionError" for k in ("file_error", "network_error")
    )
    runner = Path(__file__).with_name("fmz_round34_pine_koala_probe.py")
    assert runner.read_bytes() == (work / "r34_koala_probe.py").read_bytes()
    artifacts = [original, transformed, input_path, runner]
    executions = {}
    hashes = {}
    for label in ("firstseed", "firstseed-magnified"):
        assert (work / f"r34-koala-{label}.exit").read_text().strip() == "0"
        path = work / f"r34-koala-{label}-receipt.json"
        artifacts.append(path)
        entries = read(path)
        cases = {(case["period"], case["market"]): case for case in entries}
        assert len(entries) == len(cases) == 4
        executions[label] = cases
        (hashes[label],) = {case["executed_source_sha256"] for case in entries}
    common = {
        "id": IDENT,
        "name": row["name"],
        "source": row["source"],
        "source_sha256": digest,
        "executed_source_sha256": hashes["firstseed-magnified"],
        "group": GROUP,
        "interval": "1h",
        "archive_interval": "1h",
        "quote_currency": "USDT",
        "market_data": "Official Binance USD-M hourly plus one-minute OHLCV",
        "exit": "300-tick source bracket or out-of-session market exit",
    }
    results, stats = [], []
    for period, markets in samples.items():
        combined = []
        terminal = 0
        for market, data in markets.items():
            k = period, market
            realized, opened, stats_i = audit(
                data,
                market,
                executions["firstseed"][k],
                executions["firstseed-magnified"][k],
            )
            combined.extend(realized)
            terminal += opened
            stats.append(
                {"id": IDENT, "period": LABEL[period], "market": market, **stats_i}
            )
            results.append(
                {
                    **common,
                    "period": LABEL[period],
                    "market": market,
                    **summarize(realized, opened, CAPITAL),
                }
            )
        results.append(
            {
                **common,
                "period": LABEL[period],
                "market": "BTCUSDT + ETHUSDT",
                **summarize(combined, terminal, 2 * CAPITAL),
            }
        )
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(baseline),
            "archive_sha256": FMZ_SHA256,
            "pine_compat_binary_sha256": NATIVE_BINARY_HASH,
            "isolation_probe": isolation,
            "provider_archives": manifest,
            "source_audit": {
                "descriptor_sha256": digest,
                "settings": settings,
                "archived_pine_sha256": sha256(original),
                "executed_scope_hashes": hashes,
            },
            "artifacts": {a.name: sha256(a) for a in artifacts},
            "official_hour_minute_ohlc_discrepancies": discrepancies,
            "per_case_order_counts": stats,
            "cost_model": {
                "commission_per_contract_per_side": FEE,
                "numeric_slippage_in_ticks": 3,
                "tick_size": {"BTCUSDT": 0.1, "ETHUSDT": 0.01},
                "execution_buffer_per_side": EXECUTION,
            },
            "method": [
                "Original v4 source uses implicit weekdays and the exchange's UTC chart sessions. Verified entry order windows are on weekday hours whose opens occur from 03:00 through 08:00 UTC. The close-all rule starts on the first chart bar outside the 03:00–10:45 UTC session. The inactive date gate does not reach the entry conditions.",
                "The source contains an invalid assignment to strategy.initial_capital. It is removed from the v4 control because it feeds only a calculated size that is never passed into an active order. Broker capital remains 1,000 and default order size is one. Documented first-value EMA initialization is expressed explicitly.",
                "The v5 projection enables one-minute magnification and retains the verified original order path, v4 weekday behavior, all explicit moving-average lengths, 300-tick brackets and 3-tick authored slippage. Independent weekday and price math agree with both native gate receipts. The held lot and every bracket result agree with the official one-minute price path. No compared bar requires an inferred order between both barriers within one minute.",
                "The official BTC minute archives disagree with the venue's hourly range during two out-of-session hours. The hourly metrics use the native hourly archive. There were no positions or queued orders in these two hours, and neither path reported an order within them. Magnifier groups for those two inactive hours are omitted.",
                "Gross includes the authored order slippage and precedes the $0.000065 per-contract commission. The after-fees column deducts that commission on both legs. Net also deducts the project execution allowance. The results describe the sample with 1-minute evidence and omit funding.",
            ],
            "references": [
                "https://github.com/binance/binance-public-data",
                "https://www.tradingview.com/pine-script-docs/v5/concepts/sessions/",
                "https://www.tradingview.com/pine-script-docs/v5/concepts/strategies/",
                "https://www.tradingview.com/pine-script-reference/v5/#fun_ta.ema",
            ],
            "coverage": [
                [
                    IDENT,
                    f"Tested · {GROUP}",
                    "Legacy session and order rules retained. Every eligible minute-level entry/exit price and all cashflows reconcile independently.",
                ]
            ],
            "results": results,
        },
    )
    print(
        f"Verified {IDENT}: {len(results)} workbook rows and {sum(s['closed'] for s in stats)} closures."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "finalize"))
    for name in ("archive", "baseline", "work", "public", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--minute", type=Path, nargs="+", required=True)
    a = parser.parse_args()
    settings = (a.archive, a.baseline, a.work, a.public, a.minute)
    if a.mode == "stage":
        stage(*settings)
    else:
        report(*settings, a.output)


if __name__ == "__main__":
    main()
