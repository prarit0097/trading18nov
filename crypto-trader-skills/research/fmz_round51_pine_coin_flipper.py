"""Verify the archived Coin Flipper Pro stochastic strategy against source-state replay."""

from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from math import floor, isclose
from pathlib import Path
from shutil import copy2
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, date_ms, sha256
from research.fmz_round7_pine import EXECUTION, FEE, summarize
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH, TRIALS, ensemble, sequence
from research.fmz_round28_pine_callback import cache_bars

ID = 3697
CAPITAL = 1_000_000
DAY = 86_400_000
HOUR = 3_600_000
BEGIN, CUT = map(date_ms, ("2022-11-30", "2023-12-06"))
STOP = 2 * CUT - BEGIN
PERIOD = {"native": "FMZ native window", "next": "Next equal window"}
WORKER = "fmz_round51_pine_coin_flipper_probe.py"


def source_record(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (row,) = tuple(r for r in read(baseline)["disposition"] if r["id"] == ID)
    assert row["status"].startswith("Pending")
    with ZipFile(archive) as book:
        ((_, _, doc, digest),) = documents(book, {ID: row})
    (raw,) = re.findall(r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", doc)
    fields = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)", raw
        )
    )
    assert fields == {
        "start": "2022-11-30 00:00:00",
        "end": "2023-12-06 00:00:00",
        "period": "1d",
        "basePeriod": "1h",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    code, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", raw)
    assert n == 1
    for token in (
        "//@version=4",
        'strategy("Coin Flipper Pro",overlay=true,max_bars_back=100)',
        "maxBars=input(25.0",
        "risk=input(defval=5.0",
        "ratio= input(defval=1.5",
        "runTest=input(defval=true",
        "customTime=input(defval=false",
        "var barsBetweenflips=25",
        "var flip=true",
        "var coinLabel=0.0",
        "if barssince(flip==true)>barsBetweenflips and posLive==false",
        "coinLabel:=random(1,10)",
        "barsBetweenflips:=round(random(3,round(maxBars)))",
        "long:= flip[1]==true and coinLabel[1]>=5.0",
        "short:= flip[1]==true and coinLabel[1]<5.0",
        "round(random(1,255))",
        "barstate.isconfirmed==false?color.rgb(getColor(),getColor(),getColor(),0)",
        'strategy.entry("Sell", strategy.short,when=short==true)',
        'strategy.entry("Long", strategy.long,when=long==true)',
        "when=stoppedOut==true or takeProfit==true",
    ):
        assert token in code
    assert code.count("random(") == 3
    return row, digest, fields, code


def market_data(daily, hourly):
    months = sorted(
        {
            datetime.fromtimestamp(t / 1000, UTC).strftime("%Y-%m")
            for t in range(BEGIN, STOP, DAY)
        }
    )
    receipt = []
    result = {}
    for coin in ("BTC", "ETH"):
        symbol = coin + "USDT"
        days = {
            x[0]: list(x) for x in cache_bars(daily, symbol, "1d", months, DAY, receipt)
        }
        hours = {
            x[0]: x[1]
            for x in cache_bars(hourly, symbol, "1h", months, HOUR, receipt)
            if x[0] % DAY == 0
        }
        for tag, left, right in (("native", BEGIN, CUT), ("next", CUT, STOP)):
            chart = [days[t] for t in range(left, right, DAY)]
            assert len(chart) == 371 and all(hours[x[0]] == x[1] for x in chart)
            result.setdefault(tag, {})[coin] = chart
    return {"chart": result, "proof": receipt}


def states(tape, trial):
    state = True
    poslive = False
    last_flip = None
    coin = 0.0
    wait = 25
    target = basis = stop = 0.0
    kind = 0
    draw_coin = sequence(trial * 65537 + 8191)
    draw_wait = sequence(trial * 65537 + 2 * 8191)
    for i, (_, _, high, low, _, _) in enumerate(tape):
        prev_flip = state if i else False
        prev_coin = coin
        if state:
            last_flip = i
        if i - last_flip > wait and not poslive:
            state = True
            coin = 1 + 9 * next(draw_coin)
        if prev_flip and not poslive:
            state = False
            wait = floor(3 + 22 * next(draw_wait) + 0.5)
            poslive = True
        buy = prev_flip and prev_coin >= 5
        sell = prev_flip and prev_coin < 5
        if buy and kind != 1:
            basis = tape[i - 1][4]
            stop = basis * 0.95
            target = basis * 1.075
            kind = 1
        if sell and kind != -1:
            basis = tape[i - 1][4]
            stop = basis * 1.05
            target = basis * 0.925
            kind = -1
        stopped = (
            kind == 1
            and not buy
            and low <= stop
            or kind == -1
            and not sell
            and high >= stop
        )
        taken = (
            kind == 1
            and not buy
            and high >= target
            or kind == -1
            and not sell
            and low <= target
        )
        if stopped or taken:
            kind = 0
            poslive = False
        yield {
            "Flip": state,
            "Coin": coin,
            "Wait": wait,
            "Long": buy,
            "Short": sell,
            "Stopped": stopped,
            "Take": taken,
            "InTrade": poslive,
            "Target": target,
            "Basis": basis,
            "Stop": stop,
            "BoxPos": kind,
        }


def replay(tape, signals):
    cash = 1e6
    opened = None
    pending = None
    orders = []
    trades = []
    marks = []
    touch_both = 0
    for i, (_, o, _, _, c, _) in enumerate(tape):
        if pending is not None:
            if pending == 0:
                j, side, e = opened
                profit = side * (o - e)
                cash += profit
                trades.append(
                    ("Long" if side > 0 else "Sell", j, i, side, e, o, profit)
                )
                opened = None
                orders.append((i, "strategy.close", o, 1))
            else:
                assert opened is None
                opened = i, pending, o
                orders.append(
                    (i, "strategy.long" if pending > 0 else "strategy.short", o, 1)
                )
        s = signals[i]
        assert not (s["Long"] and s["Short"])
        if s["Stopped"] or s["Take"]:
            pending = 0 if opened else None
            touch_both += int(s["Stopped"] and s["Take"])
        elif s["Long"] or s["Short"]:
            pending = 1 if s["Long"] else -1
        else:
            pending = None
        balance = cash if not opened else cash + opened[1] * (c - opened[2])
        marks.append((opened[1] if opened else 0, balance))
    return orders, trades, marks, int(opened is not None), touch_both


def verify(tape, runner):
    trial, window, coin, diagnostics, native, observed, _ = runner
    assert not diagnostics and not native["diagnostics"]
    timeline = list(states(tape, trial))
    for i, row in enumerate(timeline):
        for key, val in row.items():
            assert isclose(val, observed[key][i], abs_tol=1e-9, rel_tol=1e-11), (
                trial,
                window,
                coin,
                i,
                key,
            )
    orders, trades, marks, unsettled, both = replay(tape, timeline)
    for (i, tag, px, qty), x in zip(orders, native["orders"], strict=True):
        assert (i, tag, px, qty) == (
            x["barIndex"],
            x["direction"],
            x["price"],
            x["qty"],
        )
        assert x["time"] == tape[i][0]
    flows = []
    for (name, i, j, qty, entry, exit, gross), x in zip(
        trades, native["trades"], strict=True
    ):
        assert (name, i, j, qty, entry, exit, gross) == (
            x["id"],
            x["entryBarIndex"],
            x["exitBarIndex"],
            x["qty"],
            x["entryPrice"],
            x["exitPrice"],
            x["profit"],
        )
        assert (x["entryTime"], x["exitTime"]) == (tape[i][0], tape[j][0])
        turnover = entry + exit
        flows.append((tape[j][0], gross, turnover * FEE, turnover * EXECUTION))
    assert all(
        pos == observed["Position"][i]
        and isclose(e, observed["Equity"][i], abs_tol=1e-8)
        for i, (pos, e) in enumerate(marks)
    )
    return (
        flows,
        unsettled,
        {"orders": len(orders), "both_threshold_signals_same_bar": both},
    )


def stage(args, code, data):
    (args.work / "round47-3697.pine").write_text(code, encoding="utf8", newline="\n")
    write(args.work / "round47-3697-feeds.json", data)
    copy2(Path(__file__).with_name(WORKER), args.work / WORKER)


def report(args, row, digest, fields, code, data):
    work = args.work
    receipts = work / "round47-3697-probe.json"
    worker = Path(__file__).with_name(WORKER)
    isolation = read(work / "round3-isolation-python.json")
    assert all(
        isolation[k][0] == "PermissionError" for k in ("file_error", "network_error")
    )
    assert (
        sha256(work / "priced-runtime/pine_compat/pine_compat.pyd")
        == NATIVE_BINARY_HASH
    )
    assert sha256(worker) == sha256(work / WORKER)
    assert (work / "round47-3697.pine").read_text(encoding="utf8") == code
    assert read(work / "round47-3697-feeds.json") == data
    native = read(receipts)
    index = {(record[1], record[2], record[0]): record for record in native}
    assert len(index) == len(native) == 128
    hashes = {i: index["native", "BTC", i][-1] for i in range(1, 1 + TRIALS)}
    common = {
        "id": ID,
        "source": row["source"],
        "source_sha256": digest,
        "executed_source_sha256": hashes[1],
        "group": "FMZ Pine · Saved coin flip with seed 1",
        "currency": "USDT",
        "quote_currency": "USDT",
        "interval": "1d",
        "archive_interval": "1h",
        "market_data": "Official Binance USD-M BTC and ETH daily bars and independent first 1h opens",
        "exit": "Author stop or target signal, realized on next daily open",
        "seed": 1,
    }
    rows = []
    distributions = []
    orders = lots = both = 0
    for tag, label in PERIOD.items():
        pooled = [([], 0) for _ in range(TRIALS)]
        for coin in ("BTC", "ETH"):
            chart = data["chart"][tag][coin]
            metrics = []
            for trial in range(1, 1 + TRIALS):
                run = index[tag, coin, trial]
                assert run[-1] == hashes[trial]
                flows, n, counts = verify(chart, run)
                combined, m = pooled[trial - 1]
                pooled[trial - 1] = (combined + flows, m + n)
                orders += counts["orders"]
                lots += len(flows)
                both += counts["both_threshold_signals_same_bar"]
                metrics.append(summarize(flows, n, CAPITAL))
            market = coin + "USDT"
            rows.append({**common, "period": label, "market": market, **metrics[0]})
            distributions.append(
                {"period": label, "market": market, **ensemble(metrics)}
            )
        metrics = [summarize(flows, n, 2 * CAPITAL) for flows, n in pooled]
        market = "BTCUSDT + ETHUSDT"
        rows.append({**common, "period": label, "market": market, **metrics[0]})
        distributions.append({"period": label, "market": market, **ensemble(metrics)})
    write(
        args.out,
        {
            "baseline_coverage_sha256": sha256(args.baseline),
            "archive_sha256": FMZ_SHA256,
            "document_sha256": digest,
            "archived_settings": fields,
            "provider_archives": data["proof"],
            "isolation_probe": isolation,
            "runtime_sha256": NATIVE_BINARY_HASH,
            "worker_sha256": sha256(worker),
            "worker_receipt_sha256": sha256(receipts),
            "executed_source_sha256_by_seed": hashes,
            "verified": {
                "paths": len(native),
                "bars": len(native) * 371,
                "orders": orders,
                "closed_lots": lots,
                "both_barriers_touch_count": both,
            },
            "cost_model": {
                "original_fee_per_side": 0,
                "comparison_fee_per_side": FEE,
                "execution_allowance_per_side": EXECUTION,
            },
            "method": [
                "The archived v4 strategy uses unseeded conditional pseudo-random numbers. Using the predeclared Round 27 schedule, add one seed to each of the original three call sites without changing the original decision formulas. The candle-color draw is unreachable on confirmed historical bars. Independent random-stream and strategy-state replay verify all 128 scenarios.",
                "The initial short comes from the archived starting state. Later entries use the original conditional waiting and biased 1–10 coin rules. Authored 5% stops and 7.5% targets are price threshold signals on completed daily bars. When both hit on one candle, the source still submits one market exit on the next open. Thresholds never serve as order fill prices.",
                "One native modeled base unit per entry. All daily fill prices match official independent first 1h open. Seed 1 is the workbook comparison; the other 31 seeds show sensitivity on the same historical sequence. Seeded runs do not recover the original unrecorded outcomes. Fees and buffer are applied separately on the exact source trades. Drawdown uses settled cashflows. Funding and liquidation are outside the replay.",
            ],
            "references": [
                "https://www.fmz.com/strategy/434600",
                "https://www.tradingview.com/pine-script-reference/v4/#fun_random",
                "https://github.com/binance/binance-public-data",
            ],
            "stochastic_ensemble": distributions,
            "coverage": [
                [
                    ID,
                    "Tested · FMZ seeded source coin flip",
                    "Exact archived v4 decision state and independent source-ledger replay agree on all 128 seeded BTC/ETH paths; six predeclared seed-1 rows.",
                ]
            ],
            "results": rows,
        },
    )
    print(
        f"{len(rows)} verified workbook rows; {len(native)} seeded paths; {lots} nonpooled closed lots"
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("stage", "report"))
    for name in ("archive", "baseline", "work", "out"):
        p.add_argument(name, type=Path)
    for name in ("daily", "hourly"):
        p.add_argument(f"--{name}", type=Path, nargs="+", required=True)
    args = p.parse_args()
    row, digest, fields, code = source_record(args.archive, args.baseline)
    data = market_data(args.daily, args.hourly)
    if args.mode == "stage":
        stage(args, code, data)
    else:
        report(args, row, digest, fields, code, data)


if __name__ == "__main__":
    main()
