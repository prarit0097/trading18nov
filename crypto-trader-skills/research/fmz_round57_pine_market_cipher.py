"""Reproduce authored #4432 WaveTrend defaults with the venue-documented EMA."""

from __future__ import annotations

import argparse
import re
from math import fsum, isclose
from pathlib import Path
from shutil import copy2
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, aggregate, date_ms, sha256
from research.fmz_round7_pine import EXECUTION, FEE, summarize
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH
from research.fmz_round28_pine_callback import cache_bars

IDENT = 4432
HOUR = 3_600_000
QUARTER = HOUR // 4
CAPITAL = 50_000
START, POINT, END = map(date_ms, ("2023-12-01", "2024-01-01", "2024-02-01"))
WORKER = "fmz_round57_pine_market_cipher_probe.py"
MODES = ("ha", "reference")


def archive_source(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (item,) = [row for row in read(baseline)["disposition"] if row["id"] == IDENT]
    assert item["status"].startswith("Pending")
    with ZipFile(archive) as book:
        ((_, _, doc, digest),) = documents(book, {IDENT: item})
    (raw,) = re.findall(r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", doc)
    fields = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)", raw
        )
    )
    assert fields == {
        "start": "2023-12-01 00:00:00",
        "end": "2023-12-31 23:59:59",
        "period": "1h",
        "basePeriod": "15m",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    s, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", raw)
    assert n == 1 and s.count("//@version=5") == 1
    expected = (
        "strategy.initial_capital = 50000",
        "equity = strategy.initial_capital + strategy.netprofit",
        "if equity>0 and timeCond",
        'strategy.entry("long" , strategy.long )',
        'strategy.entry("short", strategy.short)',
        "i_sl  = input.float(0.0,",
        "i_tp  = input.float(0.0,",
        "i_tsl = input.float(0.0,",
        "sl  = i_sl >0? i_sl /100 : 99999",
        "tp  = i_tp >0? i_tp /100 : 99999",
        "tsl = i_tsl>0? i_tsl/100 : 99999",
        "timeCond   = true",
    )
    assert all(mark in s for mark in expected)
    assert s.count("strategy.entry(") == s.count("strategy.exit(") == 2
    harness = '\nplot(wt1,"WT1")\nplot(wt2,"WT2")\nplot(longCond?1:0,"LongCond")\nplot(shortCond?1:0,"ShortCond")\nplot(pos,"Trade flag")\nplot(equity,"Gate equity")\nplot(strategy.equity,"Broker equity")\nplot(sl_long,"SL long")\nplot(sl_short,"SL short")\nplot(tp_long,"TP long")\nplot(tp_short,"TP short")\n'

    def get_line(token):
        return next(x for x in s.splitlines() if x.startswith(token))

    decl = [
        "//@version=5",
        get_line("strategy("),
        *[
            get_line(k)
            for k in (
                "wtChannelLen ",
                "wtAverageLen ",
                "wtMASource ",
                "wtMALen ",
                "obLevel ",
                "osLevel ",
            )
        ],
    ]
    waves = s[s.index("f_wavetrend(src,") : s.index("f_tc(")]
    waves = waves[: waves.index("\n\n")].rstrip()
    rec = get_line("[wt1, wt2, wtOversold")
    tail = s[s.index("long = ta.crossover") :]
    tail = tail[: tail.index("\nalertcondition")].rstrip()
    p = "\n".join(decl + [waves, rec, tail]) + harness

    return item, digest, fields, {"archive": s + harness, "projection": p}


def source_inputs(hour_dirs, quarter_dirs):
    pack = {}
    receipts = []
    months = ("2023-12", "2024-01")
    for coin in ("BTC", "ETH"):
        pair = coin + "USDT"
        hours = [
            list(row)
            for row in cache_bars(hour_dirs, pair, "1h", months, HOUR, receipts)
            if START <= row[0] < END
        ]
        quarters = list(
            cache_bars(quarter_dirs, pair, "15m", months, QUARTER, receipts)
        )
        assert [row[0] for row in hours] == list(range(START, END, HOUR))
        assert [row[0] for row in quarters] == list(range(START, END, QUARTER))
        for actual, expected in zip(aggregate(quarters, 4), hours, strict=True):
            assert list(actual[:5]) == expected[:5]
            assert isclose(actual[5], expected[5], rel_tol=1e-12)
        pack[coin] = {
            "native": [row for row in hours if row[0] < POINT],
            "next": [row for row in hours if row[0] >= POINT],
        }
    return {"data": pack, "receipts": receipts}


def ema(values, length, sma_seed):
    current = None
    initial = []
    rate = 2 / (length + 1)
    for value in values:
        if value is None:
            yield None
            continue
        if current is not None:
            current = rate * value + (1 - rate) * current
        elif not sma_seed:
            current = value
        else:
            initial.append(value)
            if len(initial) == length:
                current = fsum(initial) / length
        yield current


def waves(bars, sma_seed):
    hlc3 = [(bar[2] + bar[3] + bar[4]) / 3 for bar in bars]
    basis = list(ema(hlc3, 9, sma_seed))
    deviation = ema(
        (
            None if base is None else abs(value - base)
            for base, value in zip(basis, hlc3, strict=True)
        ),
        9,
        sma_seed,
    )
    osc = (
        None if dev in (None, 0) else (value - base) / (0.015 * dev)
        for base, dev, value in zip(basis, deviation, hlc3, strict=True)
    )
    fast = list(ema(osc, 12, sma_seed))
    window = []
    slow = []
    for value in fast:
        if value is not None:
            window = [*window[-2:], value]
        slow.append(fsum(window) / 3 if len(window) == 3 else None)
    return fast, slow


def market_flags(fast, slow):
    direction = None
    positions = []
    for i, (value, avg) in enumerate(zip(fast, slow, strict=True)):
        previous = direction
        long = (
            i > 0
            and None not in (fast[i - 1], slow[i - 1], value, avg)
            and fast[i - 1] <= slow[i - 1]
            and value > avg
            and value < -70
        )
        short = (
            i > 0
            and None not in (fast[i - 1], slow[i - 1], value, avg)
            and fast[i - 1] >= slow[i - 1]
            and value < avg
            and value > 70
        )
        assert not (long and short)
        if long or short:
            direction = 1 if long else -1
        positions.append(
            (direction, int(long and previous != 1), int(short and previous != -1))
        )
    return positions


def close_ledger(bars, flags, capital, observations):
    cash = capital
    side = 0
    held = None
    queued = None
    orders = []
    trades = []
    marks = []
    floor = min(row[3] for row in bars)
    ceiling = max(row[2] for row in bars)
    assert floor > 0
    for i, ((stamp, op, hi, lo, close, _), (_, long, short)) in enumerate(
        zip(bars, flags, strict=True)
    ):
        if queued:
            qty = 2.0 if side else 1.0
            if side:
                entry_i, entry_px = held
                gain = side * (op - entry_px)
                cash += gain
                trades.append(
                    (
                        "long" if side > 0 else "short",
                        entry_i,
                        i,
                        entry_px,
                        op,
                        float(side),
                        gain,
                    )
                )
            orders.append(
                (
                    "long" if queued > 0 else "short",
                    i,
                    stamp,
                    "strategy.long" if queued > 0 else "strategy.short",
                    qty,
                    op,
                )
            )
            held = i, op
            side = queued
            queued = None
        assert cash > 0
        queued = 1 if long else -1 if short else None
        for name, expect in (
            ("SL long", "below"),
            ("TP short", "below"),
            ("SL short", "above"),
            ("TP long", "above"),
        ):
            limit = observations[name][i]
            assert limit is None or (
                limit < floor if expect == "below" else limit > ceiling
            )
        mark = side * (close - held[1]) if held else 0.0
        marks.append((cash, cash + mark, side * held[1] if held else 0.0, side * close))
    return orders, trades, marks, int(side != 0)


def close(a, b):
    return (
        a is None
        and b is None
        or a is not None
        and b is not None
        and isclose(a, b, rel_tol=1e-10, abs_tol=1e-8)
    )


def verify_case(bars, record, fee, friction):
    coin, window, alternative, diagnostics, native, obs, _ = record
    assert not diagnostics and not native["diagnostics"]
    capital = 1_000_000 if alternative.endswith("-1m") else 50_000
    sma_seed = not alternative.startswith("reference-")
    fast, slow = waves(bars, sma_seed)
    for key, values in (("WT1", fast), ("WT2", slow)):
        assert all(close(a, b) for a, b in zip(values, obs[key], strict=True))
    flags = market_flags(fast, slow)
    assert flags == list(
        zip(obs["Trade flag"], obs["LongCond"], obs["ShortCond"], strict=True)
    )
    orders, trades, marks, terminal = close_ledger(bars, flags, capital, obs)
    assert orders == [
        tuple(row[k] for k in ("id", "barIndex", "time", "direction", "qty", "price"))
        for row in native["orders"]
    ]
    flows = []
    for lot, actual in zip(trades, native["trades"], strict=True):
        _tag, begin, end, entry, exit, quantity, gross = lot
        assert lot[:-1] == tuple(
            actual[key]
            for key in (
                "id",
                "entryBarIndex",
                "exitBarIndex",
                "entryPrice",
                "exitPrice",
                "qty",
            )
        )
        assert close(gross, actual["profit"])
        timestamp = bars[end][0]
        assert (bars[begin][0], timestamp) == (actual["entryTime"], actual["exitTime"])
        assert entry == bars[begin][1] and exit == bars[end][1]
        turnover = abs(quantity) * (entry + exit)
        flows.append((timestamp, gross, turnover * fee, turnover * friction))
    for i, ((cash, equity, open_notional, market_value), row) in enumerate(
        zip(marks, native["equity"], strict=True)
    ):
        assert all(
            close(a, b)
            for a, b in (
                (cash - open_notional, row["cash"]),
                (equity, row["equity"]),
                (market_value, row["marketValue"]),
                (cash, obs["Gate equity"][i]),
                (equity, obs["Broker equity"][i]),
            )
        ), (i, cash, equity, row, obs["Gate equity"][i], obs["Broker equity"][i])
    return (flows, terminal), {
        "market": coin,
        "period": window,
        "mode": alternative,
        "number_of_orders": len(orders),
        "number_of_closed_reversals": len(trades),
        "number_of_terminal_positions": terminal,
        "first_entry": list(orders[0]) if orders else None,
        "minimum_realized_gate_equity": min(row[0] for row in marks),
        "final_marked_equity": marks[-1][1],
    }


def report(item, digest, fields, app, pack, records):
    findings = []
    hashes = {}
    by_key = {}
    failures = {}
    for record in records:
        coin, scope, mode, diagnostics, broker, *_ = record
        if mode == "archive":
            assert broker is None and diagnostics == [
                "E_PARSE_EXPR:Error:523:26: expected expression"
            ]
            failures[coin + " " + scope] = diagnostics
            continue
        assert hashes.setdefault(mode, record[-1]) == record[-1]
        counts, witness = verify_case(pack["data"][coin][scope], record, FEE, EXECUTION)
        findings.append(witness)
        by_key[coin, scope, mode] = counts, record
    assert len(failures) == 4
    assert len(by_key) == 36
    common = {
        "id": IDENT,
        "source": item["source"],
        "source_sha256": digest,
        "executed_source_sha256": hashes["reference-archive"],
        "group": "FMZ Pine · Market Cipher WaveTrend · documented EMA",
        "interval": "1h",
        "archive_interval": "15m",
        "currency": "USDT",
        "quote_currency": "USDT",
        "market_data": "Official Binance USD-M hourly and verified quarter-hour archive",
        "exit": "Authored WaveTrend direction reversal at the following hourly open",
    }
    rows = []
    sensitivities = []
    for scope, label in (
        ("native", "FMZ native dates · documented EMA"),
        ("next", "Next equal dates · documented EMA"),
    ):
        pooled = []
        opened = 0
        for coin in ("BTC", "ETH"):
            (cashflows, n), reference = by_key[coin, scope, "reference-archive"]
            for mode in (
                "reference-archive-display",
                "reference-inline-50k",
                "reference-inline-1m",
            ):
                result, control = by_key[coin, scope, mode]
                assert result == (cashflows, n)
                assert reference[4]["orders"] == control[4]["orders"]
                assert reference[4]["trades"] == control[4]["trades"]
                if mode != "reference-inline-1m":
                    assert reference[4] == control[4] and reference[5] == control[5]
            builtin, baseline = by_key[coin, scope, "archive-capital-only"]
            for mode in (
                "archive-perturbed-display",
                "projection-same-chart",
                "inline-50k",
                "inline-1m",
            ):
                result, control = by_key[coin, scope, mode]
                assert result == builtin
                assert baseline[4]["orders"] == control[4]["orders"]
                if mode != "inline-1m":
                    assert baseline[4] == control[4] and baseline[5] == control[5]
            first = reference[4]["orders"][0]
            control_first = baseline[4]["orders"][0]
            sensitivities.append(
                {
                    "market": coin,
                    "period": scope,
                    "documented_first_fill": [
                        first["barIndex"],
                        first["time"],
                        first["price"],
                    ],
                    "sma_seed_first_fill": [
                        control_first["barIndex"],
                        control_first["time"],
                        control_first["price"],
                    ],
                }
            )
            rows.append(
                {
                    **common,
                    "period": label,
                    "market": coin + "USDT",
                    **summarize(cashflows, n, CAPITAL),
                }
            )
            pooled.extend(cashflows)
            opened += n
        rows.append(
            {
                **common,
                "period": label,
                "market": "BTCUSDT + ETHUSDT",
                **summarize(pooled, opened, CAPITAL * 2),
            }
        )
    assert [row["trades"] for row in rows] == [5, 2, 7, 2, 6, 8]
    assert (
        sum(
            r["documented_first_fill"] != r["sma_seed_first_fill"]
            for r in sensitivities
        )
        == 3
    )
    return {
        **app,
        "document_sha256": digest,
        "archived_settings": fields,
        "provider_archives": pack["receipts"],
        "source_controls_sha256": hashes,
        "original_failure_receipts": failures,
        "verification": {
            "source_replay_cases": len(by_key),
            "source_closing_lots": 15,
            "initial_entry_seed_sensitivity": sensitivities,
            "recomputed_ledgers": findings,
        },
        "cost_model": {
            "source_fee_per_side": 0,
            "comparison_fee_per_side": FEE,
            "execution_buffer_per_side": EXECUTION,
            "capital_assumption_usdt": CAPITAL,
            "base_units_per_position": 1,
        },
        "method": [
            "The archived Pine v5 source uses a platform-style assignment of 50,000 to strategy.initial_capital, which the isolated compatibility parser rejects. The original literal is represented by the research broker configuration. The alternative 1,000,000 capital control proves exact order, size and quote P&L invariance on all four scopes. Drawdown percentage uses the labelled 50,000 USDT research denominator.",
            "The active WaveTrend requests the chart's own native timeframe. The original wrapper, independently inlined source, untouched full-state controls and display-only 4h/12h and Heikin-Ashi perturbations fall into identical execution groups. Display-derived series have no impact on orders. Native compatibility EMA starts at an SMA seed, whereas the FMZ published recurrence uses its first finite source sample. That difference moves three first fills. Research rows use the FMZ first-sample recurrence only within the same-chart WaveTrend branch.",
            "Independently reconstructed oscillator lines, crossover transitions, entry flags, every OHLC price and one-unit next-open reversal were reconciled. Defaults make all four stop/target bounds unreachable on this tape, and the active capital gate remains positive. The four terminal long/short lots stay open. Fees and execution buffer are charged after each source reversal in quote USDT. No demo qualification is inferred.",
        ],
        "references": [
            "https://www.fmz.com/doc/9293",
            "https://github.com/binance/binance-public-data",
        ],
        "coverage": [
            [
                IDENT,
                "Tested · FMZ Market Cipher documented EMA",
                "Same-chart FMZ WaveTrend specification, isolated source controls and exact Binance base tape verify 15 fixed-unit reversals at the next hourly open. Four terminal positions remain open.",
            ]
        ],
        "results": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "report"))
    for name in ("archive", "baseline", "work", "out"):
        parser.add_argument(name, type=Path)
    for name in ("hour", "quarter"):
        parser.add_argument(f"--{name}", type=Path, nargs="+", required=True)
    args = parser.parse_args()
    item, digest, fields, scripts = archive_source(args.archive, args.baseline)
    pack = source_inputs(args.hour, args.quarter)
    feeds = args.work / "r48-4432-feeds.json"
    worker = Path(__file__).with_name(WORKER)
    if args.mode == "stage":
        write(feeds, pack)
        for tag, source in scripts.items():
            (args.work / f"r48-4432-{tag}.pine").write_text(
                source, encoding="utf8", newline="\n"
            )
        copy2(worker, args.work / WORKER)
        return
    assert read(feeds) == pack
    for tag, source in scripts.items():
        assert (args.work / f"r48-4432-{tag}.pine").read_text(encoding="utf8") == source
    assert sha256(worker) == sha256(args.work / WORKER)
    assert (
        sha256(args.work / "priced-runtime/pine_compat/pine_compat.pyd")
        == NATIVE_BINARY_HASH
    )
    isolation = read(args.work / "round3-isolation-python.json")
    assert (
        isolation["network_error"][0] == isolation["file_error"][0] == "PermissionError"
    )
    receipts = {mode: args.work / f"r48-4432-{mode}.json" for mode in MODES}
    app = {
        "baseline_coverage_sha256": sha256(args.baseline),
        "archive_sha256": FMZ_SHA256,
        "native_runtime_sha256": NATIVE_BINARY_HASH,
        "worker_sha256": sha256(worker),
        "source_tape_sha256": sha256(feeds),
        "offline_isolation": isolation,
        "native_receipt_sha256": {
            mode: sha256(path) for mode, path in receipts.items()
        },
    }
    result = report(
        item,
        digest,
        fields,
        app,
        pack,
        [record for path in receipts.values() for record in read(path)],
    )
    write(args.out, result)
    print(
        "Verified six report rows, fifteen distinct reversals and four open terminal positions"
    )


if __name__ == "__main__":
    main()
