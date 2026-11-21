"""Check archived Stochastic/SMA source, 5m callback clocks, and independent USD fills."""

from __future__ import annotations

import argparse
import re
from math import isclose
from pathlib import Path
from shutil import copy2
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, aggregate, date_ms, sha256
from research.fmz_round7_pine import EXECUTION, FEE, summarize
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH
from research.fmz_round28_pine_callback import cache_bars

IDENT = 3689
CAPITAL = 50
DAY = 86_400_000
MINUTE = 60_000
BEGIN, CUT, STOP = map(date_ms, ("2023-12-31", "2024-01-07", "2024-01-14"))
LABEL = {"native": "FMZ native window", "previous": "Next equal window"}
FX_SHA = "e95df5720b22fc782ffd7dfd4f989c9035e418bf552e4441c86892362b468d60"
FX_URL = "https://api.exchange.coinbase.com/products/USDT-USD/candles?granularity=86400&start=2023-11-06T00%3A00%3A00Z&end=2024-02-28T00%3A00%3A00Z"
WORKER = "fmz_round49_pine_stochastic_callback_probe.py"


def source_record(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (row,) = tuple(r for r in read(baseline)["disposition"] if r["id"] == IDENT)
    assert row["status"].startswith("Pending")
    with ZipFile(archive) as book:
        ((_, _, body, digest),) = documents(book, {IDENT: row})
    (raw,) = re.findall(r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", body)
    fields = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)", raw
        )
    )
    assert fields == {
        "start": "2023-12-31 00:00:00",
        "end": "2024-01-07 00:00:00",
        "period": "15m",
        "basePeriod": "5m",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    code, count = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", raw)
    assert count == 1
    code, count = re.subn(
        r"(?m)^import X4815162342/X48_LibaryStrategyStatus/2 as fuLi[ \t]*\n", "", code
    )
    assert count == 1
    masked = re.sub(r"(?m)//.*$", "", code)
    assert "fuLi" not in masked
    for name in ("current_price", "current_pricel", "current_prices"):
        assert len(re.findall(rf"\b{name}\b", masked)) == 1
    code, count = re.subn(
        r"(?m)^current_price[ls]? = request.security[^\n]*\n", "", code
    )
    assert count == 3
    requirements = (
        "calc_on_order_fills = true, initial_capital = 50,default_qty_type = strategy.fixed, default_qty_value = 1",
        "commission_value = 0, currency = currency.USD, slippage = 0",
        'Trade_Mode = input.string(defval = "Hedge"',
        'Risk_Mode = input.string(defval = "Low Risk"',
        "periodK = input.int(15",
        "smoothK = input.int(3",
        "periodD = input.int(3",
        "SMA_High = input.int(defval = 50",
        "SMA_Low = input.int(defval = 50",
        "tp_l = tpsl(input.float(0",
        "tp_s = tpsl(input.float(0",
        "sl = tpsl(input.float(0",
        "tp_pnl = input.float(defval = 1",
        "hedge_point = input.int(defval = 500",
        "hedge_gale = input.float(defval = 2.0",
        "hedge_point_size = hedge_point/100",
    )
    assert all(x in code for x in requirements)
    return row, digest, fields, code


def sources(minute, base, parent, fx_path):
    assert sha256(fx_path) == FX_SHA
    fx = sorted(
        [
            [t * 1000 + DAY, cl]
            for t, _, _, _, cl, _ in read(fx_path)
            if BEGIN <= t * 1000 + DAY <= STOP
        ]
    )
    assert [x[0] for x in fx] == list(range(BEGIN, STOP + 1, DAY)) and all(
        x[1] > 0 for x in fx
    )
    scopes, receipts = {}, []
    specs = {1: minute, 5: base, 15: parent}
    for coin in ("BTC", "ETH"):
        direct = {}
        for width, folders in specs.items():
            bars = cache_bars(
                folders,
                coin + "USDT",
                f"{width}m",
                ("2023-12", "2024-01"),
                width * MINUTE,
                receipts,
            )
            direct[width] = {
                row[0]: list(row) for row in bars if BEGIN <= row[0] < STOP
            }
        for tag, left, right in (("native", BEGIN, CUT), ("previous", CUT, STOP)):
            minute_bars = [direct[1][t] for t in range(left, right, MINUTE)]
            segments = {"1m": minute_bars}
            for step in (5, 15):
                independent = [
                    direct[step][t] for t in range(left, right, step * MINUTE)
                ]
                rolled = [list(row) for row in aggregate(minute_bars, step)]
                assert all(
                    x[:5] == y[:5] and close(x[5], y[5])
                    for x, y in zip(rolled, independent, strict=True)
                )
                segments[f"{step}m"] = rolled
            scopes.setdefault(tag, {})[coin] = segments
    return {"scopes": scopes, "fx": fx, "market": receipts}


def smooth(seq, n):
    out = []
    good = []
    for a in seq:
        if a is not None:
            good.append(a)
        out.append(sum(good[-n:]) / n if len(good) >= n else None)
    return out


def source_gates(tape):
    fast = []
    for i, (_, op, _, _, cl, _) in enumerate(tape):
        if i < 14:
            fast.append(None)
            continue
        ls = min(a[3] for a in tape[i - 14 : i + 1])
        hs = max(a[2] for a in tape[i - 14 : i + 1])
        fast.append(100 * (cl - ls) / (hs - ls) if hs > ls else None)
    k = smooth(fast, 3)
    d = smooth(k, 3)
    high = smooth([a[2] for a in tape], 50)
    low = smooth([a[3] for a in tape], 50)
    long = []
    short = []
    for i, (_, op, hi, lo, cl, vol) in enumerate(tape):
        ready = i > 0 and all(
            v is not None for v in (high[i], low[i], k[i], d[i], k[i - 1], d[i - 1])
        )
        long.append(
            ready
            and k[i] > d[i]
            and k[i - 1] <= d[i - 1]
            and d[i] <= 20
            and op < low[i]
            and cl < low[i]
        )
        short.append(
            ready
            and k[i] < d[i]
            and k[i - 1] >= d[i - 1]
            and d[i] >= 80
            and op > high[i]
            and cl > high[i]
        )
    return long, short, {"K": k, "D": d, "SMA high": high, "SMA low": low}


def source_model(tape, long, short, fx):
    cash = 50.0
    holding = []
    side = 0
    queued = None
    orders = []
    trades = []
    eqs = []
    valid = []

    def close_all(index, price, rate):
        nonlocal cash
        for tag, origin, px, qty in holding:
            gross = side * qty * (price - px) * rate
            cash += gross
            trades.append([tag, origin, index, px, price, side * qty, gross])

    for i, (at, op, _, _, cl, _) in enumerate(tape):
        rate = fx[at // DAY * DAY]
        if queued is not None:
            direction, kind, qty = queued
            total = qty
            if side and side != direction:
                close_all(i, op, rate)
                total += sum(q for *_, q in holding)
                holding = []
            side = direction
            orders.append([kind, i, op, total, side])
            holding.append([kind, i, op, qty])
            queued = None
        marked = side * sum(q * (cl - px) * rate for _, d, px, q in holding)
        if marked >= 1:
            valid.append([i, marked])
            close_all(i, cl, rate)
            holding = []
            side = 0
            marked = 0.0
        else:
            assert not (long[i] and short[i])
            direction = 1 if long[i] else -1 if short[i] else 0
            if direction:
                kind = "Long" if direction > 0 else "Short"
                if side != direction:
                    queued = direction, kind, 1.0
                elif side * (holding[-1][2] - cl) >= 5:
                    queued = direction, kind + "2", sum(q for *_, q in holding) * 2
        eqs.append(cash + marked)
    return orders, trades, eqs, len(holding), valid


def close(x, y):
    return isclose(x, y, rel_tol=1e-10, abs_tol=1e-7)


def validate_scope(label, item, pack):
    window, coin = label.split("/")
    tape = pack["scopes"][window][coin]["15m"]
    fx = dict(pack["fx"])
    longs, shorts, known = source_gates(tape)
    normal = item["normal"]
    assert not item["normal_diagnostics"] and not item.get("error")
    assert all(v["code"] == "E_STRATEGY_EXIT_PRICE" for v in normal["diagnostics"])
    assert len(normal["diagnostics"]) == item["literal_non_finite_exit_diagnostics"]
    orders, trades, marked, remaining, profit_exits = source_model(
        tape, longs, shorts, fx
    )
    for name, expected in (("LongGate", longs), ("ShortGate", shorts)):
        assert all(
            bool(a) == bool(b)
            for a, b in zip(expected, item["normal_gate"][name], strict=True)
        )
    for indicator, expect in known.items():
        assert all(
            (a is None and b is None)
            or (a is not None and b is not None and close(a, b))
            for a, b in zip(expect, item["normal_gate"][indicator], strict=True)
        )
    for granularity in ("5m", "1m"):
        check = item[granularity]
        broker = check["strategy"]
        assert not check["price_disagreements"] and not broker["diagnostics"]
        assert all(broker[k] == normal[k] for k in ("orders", "trades", "equity"))
        for (tag, i, model_price, qty, side), (t, phase, px, row) in zip(
            orders, check["event"]["orders"], strict=True
        ):
            assert (
                phase == f"{granularity} open" and t == tape[i][0] and px == tape[i][1]
            )
            assert (row["id"], row["barIndex"], row["time"], row["direction"]) == (
                tag,
                i,
                t,
                "strategy.long" if side > 0 else "strategy.short",
            )
            assert close(model_price, px) and close(qty, row["qty"])
        for (tag, i, j, p0, p1, qty, gross), (t, phase, px, row) in zip(
            trades, check["event"]["trades"], strict=True
        ):
            expected = (
                tape[j][0] if phase.endswith(" open") else tape[j][0] + 15 * MINUTE - 1
            )
            assert t == expected and close(px, p1)
            assert (tag, i, j) == (row["id"], row["entryBarIndex"], row["exitBarIndex"])
            assert all(
                close(a, row[k])
                for a, k in (
                    (qty, "qty"),
                    (p0, "entryPrice"),
                    (p1, "exitPrice"),
                    (gross, "profit"),
                )
            )
        assert all(
            close(a, b["equity"]) for a, b in zip(marked, broker["equity"], strict=True)
        )
    flows = []
    for (_, i, j, entry, exit, qty, gross), (t, _, _, _) in zip(
        trades, item["5m"]["event"]["trades"], strict=True
    ):
        notional = abs(qty) * (
            entry * fx[tape[i][0] // DAY * DAY] + exit * fx[tape[j][0] // DAY * DAY]
        )
        flows.append((t, gross, notional * FEE, notional * EXECUTION))
    return (
        flows,
        remaining,
        {
            "period": window,
            "market": coin,
            "fills": len(orders),
            "closed_lots": len(trades),
            "marked_profit_exits": len(profit_exits),
            "unsettled": remaining,
            "native_noop_diagnostics": len(normal["diagnostics"]),
            "max_order_size": max(order[3] for order in orders),
            "peak_marked_drawdown": max(
                (max(marked[: i + 1]) - val for i, val in enumerate(marked)),
                default=0.0,
            ),
        },
    )


def report(args, root, source_sha, fields, code, pack):
    work = args.work
    receipt = work / "round47-3689-guard.json"
    guard = Path(__file__).with_name(WORKER)
    assert sha256(guard) == sha256(work / WORKER)
    assert (work / "round47-3689-active.pine").read_text(encoding="utf8") == code
    assert read(work / "round47-3689-feeds.json") == pack
    runtime = work / "priced-runtime/pine_compat/pine_compat.pyd"
    isolate = read(work / "round3-isolation-python.json")
    assert sha256(runtime) == NATIVE_BINARY_HASH and all(
        isolate[k][0] == "PermissionError" for k in ("file_error", "network_error")
    )
    rows, proof = [], []
    pooled = {name: ([], 0) for name in LABEL}
    common = {
        "id": IDENT,
        "source": root["source"],
        "source_sha256": source_sha,
        "executed_source_sha256": sha256(work / "round47-3689-active.pine"),
        "group": "FMZ Pine · Causal 5m Stochastic/SMA replay",
        "currency": "USD",
        "quote_currency": "USD",
        "interval": "15m",
        "archive_interval": "5m",
        "market_data": "Official Binance USD-M 1m, 5m and 15m; prior Coinbase USDT/USD close",
        "exit": "Source immediate marked P&L close or reversal",
    }
    receipt_scopes = read(receipt)
    guarded_hashes = {
        scope["guarded_source_sha256"] for scope in receipt_scopes.values()
    }
    literal_hashes = {
        scope["literal_source_sha256"] for scope in receipt_scopes.values()
    }
    assert len(guarded_hashes) == len(literal_hashes) == 1
    common["executed_source_sha256"] = next(iter(guarded_hashes))
    for label, data in receipt_scopes.items():
        window, coin = label.split("/")
        flows, n, summary = validate_scope(label, data, pack)
        combined, opened = pooled[window]
        pooled[window] = (combined + flows, opened + n)
        rows.append(
            {
                **common,
                "period": LABEL[window],
                "market": coin + "USDT",
                **summarize(flows, n, CAPITAL),
            }
        )
        proof.append(summary)
    for label, (flows, n) in pooled.items():
        rows.append(
            {
                **common,
                "period": LABEL[label],
                "market": "BTCUSDT + ETHUSDT",
                **summarize(flows, n, 2 * CAPITAL),
            }
        )
    assert [x["closed_lots"] for x in proof] == [23, 25, 30, 31]
    status = "Tested · FMZ causal 5m Stochastic/SMA model"
    write(
        args.out,
        {
            "baseline_coverage_sha256": sha256(args.baseline),
            "archive_sha256": FMZ_SHA256,
            "document_sha256": source_sha,
            "archived_settings": fields,
            "runtime_sha256": NATIVE_BINARY_HASH,
            "native_isolation_probe": isolate,
            "worker_sha256": sha256(guard),
            "native_receipt_sha256": sha256(receipt),
            "literal_source_sha256": next(iter(literal_hashes)),
            "guarded_source_sha256": common["executed_source_sha256"],
            "provider_archives": pack["market"],
            "fx_provider": {"sha256": FX_SHA, "url": FX_URL},
            "verification": proof,
            "cost_model": {
                "original_fee_per_side": 0,
                "comparison_fee_per_side": FEE,
                "execution_buffer_per_side": EXECUTION,
            },
            "method": [
                "The source has one display-only library import whose alias is never executed and three reference series with no consumers. Their removal changes no order rule. Four dynamic exit calls are explicitly gated against passing only NA. All source-default stop loss and percent take profits are disabled. The literal 15m comparison and guarded code match all recorded orders and closed lots in every scope.",
                "The exact 5m base model and independent 1m chronological prefixes present only observed opens and completed closes with cumulative available high, low and volume. 1m rollups exactly reconcile archived official 5m and 15m parents. Each replay uses source order-fill callbacks and produces identical fills, closes and account equity.",
                "Independent 15/3/3 Stochastic and 50-period high and low SMA gates reconcile every historical bar and all four asset/windows. Source uses one base unit, 2x existing units to scale after five quote units of adverse movement, synthetic $50 equity, and $1 marked USD profit as the immediate close trigger, without margin or liquidation.",
                "The workbook comparison applies fees and execution buffer after the source zero-fee replay using prior Coinbase UTC USD conversion on each leg. Drawdown uses settled-lot equity and open exposures are shown separately. The source positive trades do not imply deployable results under real collateral, spread, funding or liquidation.",
            ],
            "references": [
                "https://www.fmz.com/doc/9293",
                "https://www.tradingview.com/pine-script-docs/concepts/strategies/#calc_on_order_fills",
                "https://github.com/binance/binance-public-data",
                "https://docs.cdp.coinbase.com/exchange/reference/exchangerestapi_getproductcandles",
            ],
            "coverage": [
                [
                    IDENT,
                    status,
                    "Source guards disable only no-price orders. Both causal base-5m and more granular 1m ledgers match all source fills and independent entry gates, martingale quantities, USD closes and marked equity.",
                ]
            ],
            "results": rows,
        },
    )
    print(
        f"{len(rows)} verified rows and {sum(x['closed_lots'] for x in proof)} source lots"
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("stage", "report"))
    for name in ("archive", "baseline", "work", "fx", "out"):
        p.add_argument(name, type=Path)
    for name in ("minute", "base", "parent"):
        p.add_argument(f"--{name}", type=Path, nargs="+", required=True)
    args = p.parse_args()
    root, digest, fields, code = source_record(args.archive, args.baseline)
    pack = sources(args.minute, args.base, args.parent, args.fx)
    if args.mode == "stage":
        (args.work / "round47-3689-active.pine").write_text(
            code, encoding="utf8", newline="\n"
        )
        write(args.work / "round47-3689-feeds.json", pack)
        copy2(Path(__file__).with_name(WORKER), args.work / WORKER)
    else:
        report(args, root, digest, fields, code, pack)


if __name__ == "__main__":
    main()
