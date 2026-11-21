"""Verify the archived selected-input Bollinger breakout and closed-bar exits."""

from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from math import floor, isclose, sqrt
from pathlib import Path
from shutil import copy2
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, date_ms, sha256
from research.fmz_round7_pine import EXECUTION, summarize
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH
from research.fmz_round28_pine_callback import cache_bars

IDENT = 3747
CAPITAL = 100
FEE = 0.001
STEP = 0.001
DAY = 86_400_000
HOUR = 3_600_000
START, CUT = map(date_ms, ("2022-09-26", "2023-09-26"))
STOP = 2 * CUT - START
PERIOD = {"native": "FMZ native window", "next": "Next equal window"}
WORKER = "fmz_round53_pine_bollinger_gates_probe.py"


def source_record(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (item,) = tuple(row for row in read(baseline)["disposition"] if row["id"] == IDENT)
    assert item["status"].startswith("Pending")
    with ZipFile(archive) as book:
        ((_, _, doc, digest),) = documents(book, {IDENT: item})
    (raw,) = re.findall(r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", doc)
    fields = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges|args):[ \t]*([^\r\n]+)", raw
        )
    )
    assert fields == {
        "start": "2022-09-26 00:00:00",
        "end": "2023-09-26 00:00:00",
        "period": "1d",
        "basePeriod": "1h",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
        "args": '[["v_input_37",1],["v_input_38",2]]',
    }
    assert (
        "|v_input_37|0|Crossover Upper Band: Not Used|Long Open|Long Close|Long Open and Long Close|"
        in doc
    )
    assert (
        "|v_input_38|0|Crossover Middle Band: Not Used|Long Open|Long Close|Long Open and Long Close|"
        in doc
    )
    code, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", raw)
    assert n == 1
    for snippet in (
        "pyramiding=1, default_qty_type=strategy.percent_of_equity, default_qty_value=100",
        "commission_value=.1, slippage=0, initial_capital=100",
        "MAPeriod = input(20",
        'title="Middle Band Type", defval="SMA"',
        "type=input.source, defval=close",
        'title="Middle Band Resolution", defval="00 Current"',
        'title="Middle Band Candle Type", defval="00 Current"',
        'UpperBandMultiplier = input(title="Upper Band Deviation Multiplier", defval=2',
        "UseATRDeviation = input(false",
        "window()  => true",
        'Open Conditions Requirement", defval="All"',
        'Close Conditions Requirement", defval="All"',
        "takeProfitPercent = input(100",
        "stopLossPercent = input(100",
        "crossover(close, UpperBand)",
        "crossover(close, MA)",
        "longClose == 1 and longOpen == 1",
    ):
        assert snippet in code
    return item, digest, fields, code


def inputs(daily, hourly):
    archive, result = [], {}
    months = sorted(
        {
            datetime.fromtimestamp(t / 1000, UTC).strftime("%Y-%m")
            for t in range(START, STOP, DAY)
        }
    )
    for coin in ("BTC", "ETH"):
        m = coin + "USDT"
        days = {r[0]: list(r) for r in cache_bars(daily, m, "1d", months, DAY, archive)}
        opens = {
            r[0]: r[1]
            for r in cache_bars(hourly, m, "1h", months, HOUR, archive)
            if r[0] % DAY == 0
        }
        for tag, a, b in (("native", START, CUT), ("next", CUT, STOP)):
            chart = [days[t] for t in range(a, b, DAY)]
            assert len(chart) == 365 and all(r[1] == opens[r[0]] for r in chart)
            result.setdefault(tag, {})[coin] = chart
    return {"chart": result, "proof": archive}


def runtime_scope(then, current, tape):
    tag, coin, diag, broker, plots, _ = then
    assert then[:4] == current[:4]
    assert not diag and not broker["diagnostics"]
    known = {r["title"]: r["values"] for r in plots}
    moved = {r["title"]: r["values"] for r in current[4]}
    assert all(
        known[n] == moved[n]
        for n in ("Open", "Close", "Pos", "Eq", "Middle Band", "Upper Band")
    )
    avg = [None] * 19
    hi = [None] * 19
    for i in range(19, len(tape)):
        prices = [r[4] for r in tape[i - 19 : i + 1]]
        center = sum(prices) / 20
        avg.append(center)
        hi.append(center + 2 * sqrt(sum((v - center) ** 2 for v in prices) / 20))
    matched = zip(avg, hi, known["Middle Band"], known["Upper Band"], strict=True)
    assert all(
        a is None
        and b is None
        and x is None
        and y is None
        or all(v is not None for v in (a, b, x, y))
        and near(a, x)
        and near(b, y)
        for a, b, x, y in matched
    )
    cash = float(CAPITAL)
    qty = 0.0
    pending = None
    basis = None
    last_idx = None
    guard = None
    fills = []
    trades = []
    signal_n = 0
    for i, (_, opening, h, l, close, _) in enumerate(tape):
        if pending == "open":
            qty = floor(cash / (opening * (1 + FEE)) / STEP + 1e-9) * STEP
            assert qty > 0
            basis = opening
            last_idx = i
            cash -= qty * basis * FEE
            fills.append((i, "strategy.long", qty, opening))
        if pending == "close":
            gross = (opening - basis) * qty
            fee = (basis + opening) * qty * FEE
            cash += gross - opening * qty * FEE
            fills.append((i, "strategy.close", qty, opening))
            trades.append((last_idx, i, qty, basis, opening, gross - fee))
            qty = 0.0
            basis = None
            guard = None
        uc = mc = False
        if i >= 20:
            prev = tape[i - 1][4]
            uc = prev <= hi[i - 1] and close > hi[i]
            mc = prev <= avg[i - 1] and close > avg[i]
        wants = uc and not mc
        assert bool(known["Open"][i]) == wants and bool(known["Close"][i]) == mc, (
            tag,
            coin,
            i,
            wants,
            mc,
            known["Open"][i],
            known["Close"][i],
        )
        assert isclose(qty, known["Pos"][i], abs_tol=1e-8)
        eq = cash + (close - basis) * qty if qty else cash
        assert isclose(eq, known["Eq"][i], abs_tol=1e-8), (
            tag,
            coin,
            i,
            eq,
            known["Eq"][i],
        )
        if qty:
            assert guard is not None and h < basis + guard and l > basis - guard
        if wants:
            guard = close
        pending = "open" if wants and not qty else "close" if mc and qty else None
        signal_n += int(wants)
    expected = [
        (r["barIndex"], r["direction"], r["qty"], r["price"]) for r in broker["orders"]
    ]
    for a, b in zip(expected, fills, strict=True):
        assert a[:2] == b[:2] and isclose(a[2], b[2], abs_tol=1e-8) and a[3] == b[3], (
            tag,
            coin,
            a,
            b,
        )
    for e, r in zip(trades, broker["trades"], strict=True):
        assert e[:2] == (r["entryBarIndex"], r["exitBarIndex"])
        assert all(
            isclose(u, r[k], abs_tol=1e-8)
            for u, k in zip(
                e[2:], ("qty", "entryPrice", "exitPrice", "profit"), strict=True
            )
        )
    result = []
    for i, j, qty, basis, exit, _ in trades:
        gross = (exit - basis) * qty
        value = (basis + exit) * qty
        result.append((tape[j][0], gross, value * FEE, value * EXECUTION))
    return (
        result,
        int(known["Pos"][-1] > 0),
        {
            "market": coin,
            "period": tag,
            "fills": len(fills),
            "signals": signal_n,
            "closes": len(trades),
            "percentage_bracket_touches": 0,
        },
    )


def near(x, y):
    return isclose(x, y, rel_tol=1e-12, abs_tol=1e-8)


def stage(args, source, data):
    (args.work / "round47-3747.pine").write_text(source, encoding="utf8", newline="\n")
    write(args.work / "round47-3747-feeds.json", data)
    copy2(Path(__file__).with_name(WORKER), args.work / WORKER)


def report(args, item, digest, settings, code, input_data):
    work = args.work
    program = Path(__file__).with_name(WORKER)
    r_inline = work / "round47-3747-inline.json"
    r_static = work / "round47-3747-static.json"
    assert (work / "round47-3747.pine").read_text(encoding="utf8") == code
    assert read(work / "round47-3747-feeds.json") == input_data
    runtime = work / "priced-runtime/pine_compat/pine_compat.pyd"
    isolation = read(work / "round3-isolation-python.json")
    assert all(
        isolation[x][0] == "PermissionError" for x in ("file_error", "network_error")
    )
    assert sha256(runtime) == NATIVE_BINARY_HASH and sha256(program) == sha256(
        work / WORKER
    )
    streams = (read(r_inline), read(r_static))
    assert all(len(r) == 4 and len({x[-1] for x in r}) == 1 for r in streams)
    rows = []
    verifications = []
    pool = {t: ([], 0) for t in PERIOD}
    main = {
        "id": IDENT,
        "source": item["source"],
        "source_sha256": digest,
        "executed_source_sha256": streams[0][0][-1],
        "group": "FMZ Pine · Saved Bollinger crossover gates",
        "interval": "1d",
        "archive_interval": "1h",
        "currency": "USDT",
        "quote_currency": "USDT",
        "market_data": "Official Binance BTC/ETH USD-M 1d and 1h archives",
        "exit": "Saved middle-band crossover, next daily open",
    }
    for recorded, control in zip(*streams, strict=True):
        t, c = recorded[:2]
        flows, n, detail = runtime_scope(recorded, control, input_data["chart"][t][c])
        df, older = pool[t]
        pool[t] = (df + flows, older + n)
        rows.append(
            {
                **main,
                "period": PERIOD[t],
                "market": c + "USDT",
                **summarize(flows, n, CAPITAL),
            }
        )
        verifications.append(detail)
    for t, (flows, n) in pool.items():
        rows.append(
            {
                **main,
                "period": PERIOD[t],
                "market": "BTCUSDT + ETHUSDT",
                **summarize(flows, n, 2 * CAPITAL),
            }
        )
    assert [v["closes"] for v in verifications] == [6, 4, 8, 5]
    write(
        args.out,
        {
            "baseline_coverage_sha256": sha256(args.baseline),
            "archive_sha256": FMZ_SHA256,
            "document_sha256": digest,
            "native_runtime_sha256": NATIVE_BINARY_HASH,
            "native_isolation": isolation,
            "worker_sha256": sha256(program),
            "source_context_receipts": {
                "inline": sha256(r_inline),
                "static": sha256(r_static),
            },
            "source_context_executed_sha256": {
                "inline": streams[0][0][-1],
                "static": streams[1][0][-1],
            },
            "archived_settings": settings,
            "provider_archives": input_data["proof"],
            "independent_checks": verifications,
            "fee_per_side": FEE,
            "execution_allowance_per_side": EXECUTION,
            "method": [
                "FMZ saved enum 37=1 enables Long Open for the upper-band crossover, and 38=2 enables Long Close for the middle-band crossover. The literal archive requests Current chart and Current timeframe. Unsupported dead nonstandard chart branches cannot affect this saved setting. Same-symbol and same-timeframe access was resolved to local chart data for this replay.",
                "A second native control retains explicit daily security calls for the middle band, upper deviation and input close. Both native runs match independent population standard deviation, twenty-day SMA, every archived open/close gate, one-slot lot sizing, prices, equity and costs.",
                "Original 100% profit/loss tick offsets were unreachable in observed holding ranges. Every realized close follows the authored next daily open. Source capital is 100 USDT and source commission 0.1% per side, with an additional separately measured allowance. Open terminal positions remain open. Funding and liquidation are outside this model.",
            ],
            "references": [
                "https://www.fmz.com/strategy/427997",
                "https://www.tradingview.com/pine-script-docs/v5/concepts/other-timeframes-and-data/",
                "https://github.com/binance/binance-public-data",
            ],
            "coverage": [
                [
                    IDENT,
                    "Tested · FMZ saved Bollinger gating",
                    "Active same-context source and daily security control independently match every archived gate, fill, source fee and 100%-equity quantity over 1,460 BTC/ETH bars. Literal unused alternate chart functions were bypassed only for the saved Current settings.",
                ]
            ],
            "results": rows,
        },
    )
    print(f"{len(rows)} verified rows and 23 closed lots")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "report"))
    for name in ("archive", "baseline", "work", "out"):
        parser.add_argument(name, type=Path)
    for name in ("daily", "hourly"):
        parser.add_argument(f"--{name}", type=Path, nargs="+", required=True)
    args = parser.parse_args()
    root, digest, settings, code = source_record(args.archive, args.baseline)
    data = inputs(args.daily, args.hourly)
    if args.mode == "stage":
        stage(args, code, data)
    else:
        report(args, root, digest, settings, code, data)


if __name__ == "__main__":
    main()
