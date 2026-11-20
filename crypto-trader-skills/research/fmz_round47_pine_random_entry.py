"""Verify FMZ's saved random-direction strategy on historical USD-M and FX data."""

from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from decimal import Decimal
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
from research.fmz_round32_trailing_offset import daily_rates

IDENT = 5629
CAPITAL = 1_000_000
GROUP = "FMZ Pine · Saved stochastic strategy · Seed 1"
MARKETS = ("BTCUSDT", "ETHUSDT")
DAY = 86_400_000
HOUR = 3_600_000
MIN_CONTRACT = 0.001
BEGIN, CUT = map(date_ms, ("2022-10-04", "2023-10-10"))
STOP = 2 * CUT - BEGIN
WINDOWS = {"native": (BEGIN, CUT), "next": (CUT, STOP)}
LABEL = {"native": "FMZ native window", "next": "Next equal window"}
SOURCE_PROBE = "fmz_round47_pine_random_entry_probe.py"
COINBASE = (
    "https://api.exchange.coinbase.com/products/USDT-USD/candles?granularity=86400"
)
FX_EXTRA = {
    (
        "2024-02-28",
        "2024-06-19",
    ): "f48118cbb0597138d0b5378d13fe35d2291da82988cf9a584fe92a857d530570",
    (
        "2024-06-19",
        "2024-10-18",
    ): "c24b4e832c6b3030488d46339edb1838cba89eda71e883ec5dc9500055aede2d",
}


def source_record(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (row,) = (r for r in read(baseline)["disposition"] if r["id"] == IDENT)
    assert row["status"].startswith("Pending")
    with ZipFile(archive) as book:
        ((_, _, text, digest),) = documents(book, {IDENT: row})
    (body,) = re.findall(r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", text)
    fields = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges|args):[ \t]*([^\r\n]+)", body
        )
    )
    assert fields == {
        "start": "2022-10-04 00:00:00",
        "end": "2023-10-10 00:00:00",
        "period": "1d",
        "basePeriod": "1h",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
        "args": '[["v_input_1",2]]',
    }
    code, count = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", body)
    assert count == 1
    anchors = (
        "//@version=4",
        "pyramiding=0, default_qty_type=strategy.percent_of_equity, default_qty_value=100",
        "currency=currency.USD,commission_type=strategy.commission.percent,commission_value=0",
        'defval="Long Only",title="Direction",options=["Long Only", "Short Only", "Random"]',
        "enter_frequency = input(defval=10,minval=1,maxval=100",
        "exit_frequency = input(defval=3, minval=0,maxval=100",
        "start_year = input(defval=2020",
        "r = random(0,100)",
        "enter = enter_frequency > r[0]",
        "exit = exit_frequency > r[0]",
        "direction = random(0,100) >= 50",
        'strategy == "Random") and direction',
        'strategy == "Random" and not direction',
    )
    assert all(anchor in code for anchor in anchors)
    assert code.count("strategy.entry(") == code.count("strategy.close(") == 2
    assert code.count("strategy.opentrades == 0 and enter") == 2
    return row, digest, fields, code


def inputs(daily, hourly, exchange_fx, extra_fx):
    months = sorted(
        {
            datetime.fromtimestamp(t / 1000, UTC).strftime("%Y-%m")
            for t in range(BEGIN, STOP, DAY)
        }
    )
    market_receipts, tapes = [], {}
    for market in MARKETS:
        days = list(cache_bars(daily, market, "1d", months, DAY, market_receipts))
        by_date = {r[0]: list(r) for r in days}
        assert len(by_date) == len(days)
        # Entry and exit are market orders filled only at the daily open. Check the
        # source's saved base tape independently for every one of those open prices.
        first_hours = {
            row[0]: row[1]
            for row in cache_bars(hourly, market, "1h", months, HOUR, market_receipts)
            if row[0] % DAY == 0
        }
        for label, (lo, hi) in WINDOWS.items():
            chart = [by_date[t] for t in range(lo, hi, DAY)]
            assert all(candle[1] == first_hours[candle[0]] for candle in chart)
            tapes.setdefault(label, {})[market] = chart

    rates, rate_receipts = daily_rates(exchange_fx)
    for (start, end), digest in FX_EXTRA.items():
        file = extra_fx / f"USDTUSD-{start}-{end}.json"
        assert sha256(file) == digest
        rate_receipts.append(
            {
                "sha256": digest,
                "url": f"{COINBASE}&start={start}T00%3A00%3A00Z&end={end}T00%3A00%3A00Z",
            }
        )
        for t, low, high, opening, close, volume in read(file):
            rate = Decimal(str(close))
            assert rates.setdefault(t * 1000 + DAY, rate) == rate
            assert (
                0 < low <= min(opening, close) <= max(opening, close) <= high
                and volume > 0
            )
    return {
        "tapes": tapes,
        "rates": [[t, float(rates[t])] for t in range(BEGIN, STOP, DAY)],
        "market": market_receipts,
        "fx": rate_receipts,
    }


def verify_trial(chart, fx, native):
    trial = native["trial"]
    seed = trial * 65537
    draw, direction = sequence(seed), sequence(seed + 8191)
    cash = float(CAPITAL)
    opened = pending = None
    flow, lots, orders = [], [], []
    plots = native["plot"]
    assert all(len(x) == len(chart) for x in plots.values())

    for index, (time, opening, _, _, close, _) in enumerate(chart):
        rate = fx[time]
        if pending == 0:
            entry_day, side, entry, quantity = opened
            realized = side * quantity * (opening - entry) * rate
            cash += realized
            lots.append((entry_day, index, entry, opening, side * quantity, realized))
            orders.append((index, "strategy.close", quantity, opening))
            turnover = quantity * (entry * fx[chart[entry_day][0]] + opening * rate)
            flow.append((time, realized, turnover * FEE, turnover * EXECUTION))
            opened = None
        elif pending is not None and cash > 0:
            quantity = floor(cash / opening / rate / MIN_CONTRACT + 1e-9) * MIN_CONTRACT
            assert quantity > 0
            orders.append(
                (
                    index,
                    "strategy.long" if pending > 0 else "strategy.short",
                    quantity,
                    opening,
                )
            )
            opened = index, pending, opening, quantity

        draw_value, want_long = next(draw) * 100, next(direction) >= 0.5
        assert approx(draw_value, plots["R"][index])
        assert want_long == bool(plots["Direction"][index])
        pending = None
        marked, position = cash, 0.0
        if opened is None:
            if draw_value < 10:
                pending = 1 if want_long else -1
        else:
            if draw_value < 3:
                pending = 0
            _, side, entry, quantity = opened
            position = side * quantity
            marked += position * (close - entry) * rate
        assert approx(position, plots["Pos"][index]) and approx(
            marked, plots["Equity"][index]
        )

    for actual, model in zip(native["orders"], orders, strict=True):
        index, direction_name, qty, price = model
        assert (actual["barIndex"], actual["time"], actual["direction"]) == (
            index,
            chart[index][0],
            direction_name,
        )
        assert approx(qty, actual["qty"]) and approx(price, actual["price"])
    for actual, model in zip(native["trades"], lots, strict=True):
        i, j, basis, price, qty, gross = model
        direction_name = "Long" if qty > 0 else "Short"
        assert (actual["entryBarIndex"], actual["exitBarIndex"], actual["id"]) == (
            i,
            j,
            direction_name,
        )
        assert (actual["entryTime"], actual["exitTime"]) == (chart[i][0], chart[j][0])
        assert all(
            approx(x, actual[key])
            for x, key in (
                (basis, "entryPrice"),
                (price, "exitPrice"),
                (qty, "qty"),
                (gross, "profit"),
            )
        )
    return flow, int(opened is not None), len(orders)


def approx(a, b):
    return isclose(a, b, rel_tol=1e-10, abs_tol=2e-6)


def stage(args, code, data):
    args.work.mkdir(parents=True, exist_ok=True)
    (args.work / "round47-5629.pine").write_text(code, encoding="utf-8", newline="\n")
    write(args.work / "round47-5629-feeds.json", data)
    copy2(Path(__file__).with_name(SOURCE_PROBE), args.work / SOURCE_PROBE)


def report(args, source, source_sha, fields, code, feed):
    runtime = args.work / "priced-runtime/pine_compat/pine_compat.pyd"
    isolate = args.work / "round3-isolation-python.json"
    staged = args.work / SOURCE_PROBE
    receipt = args.work / "round47-5629-verified.json"
    assert sha256(runtime) == NATIVE_BINARY_HASH
    assert (args.work / "round47-5629.pine").read_text(encoding="utf-8") == code
    assert read(args.work / "round47-5629-feeds.json") == feed
    assert sha256(staged) == sha256(Path(__file__).with_name(SOURCE_PROBE))
    isolation = read(isolate)
    assert all(
        isolation[x][0] == "PermissionError" for x in ("file_error", "network_error")
    )
    resolution = read(receipt)
    raw = {(r["window"], r["market"], r["trial"]): r for r in resolution}
    assert len(raw) == len(resolution) == len(WINDOWS) * len(MARKETS) * TRIALS
    fx = dict(feed["rates"])
    first = raw[("native", "BTCUSDT", 1)]["sha256"]
    rows, samples = [], []
    checked_trades = checked_orders = 0
    common = {
        "id": IDENT,
        "source": source["source"],
        "source_sha256": source_sha,
        "executed_source_sha256": first,
        "group": GROUP,
        "interval": "1d",
        "archive_interval": "1h",
        "currency": "USD",
        "quote_currency": "USD",
        "market_data": "Official Binance USD-M 1d and first 1h opens; Coinbase daily USD conversion",
        "exit": "First next daily open after author's random exit signal",
        "seed": 1,
    }
    for window, markets in feed["tapes"].items():
        pooled = [([], 0) for _ in range(TRIALS)]
        for market, chart in markets.items():
            series = []
            for trial in range(1, TRIALS + 1):
                flow, count, order_count = verify_trial(
                    chart, fx, raw[(window, market, trial)]
                )
                full_flow, full_count = pooled[trial - 1]
                pooled[trial - 1] = (full_flow + flow, full_count + count)
                series.append(summarize(flow, count, CAPITAL))
                checked_trades += len(flow)
                checked_orders += order_count
            rows.append(
                {**common, "period": LABEL[window], "market": market, **series[0]}
            )
            samples.append(
                {"period": LABEL[window], "market": market, **ensemble(series)}
            )
        panel = [summarize(flow, n, 2 * CAPITAL) for flow, n in pooled]
        label = "BTCUSDT + ETHUSDT"
        rows.append({**common, "period": LABEL[window], "market": label, **panel[0]})
        samples.append({"period": LABEL[window], "market": label, **ensemble(panel)})

    status = "Tested · FMZ saved stochastic model"
    write(
        args.output,
        {
            "baseline_coverage_sha256": sha256(args.baseline),
            "archive_sha256": FMZ_SHA256,
            "document_sha256": source_sha,
            "archived_settings": fields,
            "runtime_sha256": NATIVE_BINARY_HASH,
            "native_isolation_probe": isolation,
            "worker_sha256": sha256(staged),
            "native_receipt_sha256": sha256(receipt),
            "seeded_source_hashes": {
                str(trial): raw[("native", "BTCUSDT", trial)]["sha256"]
                for trial in range(1, TRIALS + 1)
            },
            "provider_archives": feed["market"],
            "fx_receipts": feed["fx"],
            "verifications": {
                "paths": len(resolution),
                "orders": checked_orders,
                "closed_lots": checked_trades,
                "independently_replayed_bars": len(resolution)
                * len(feed["rates"])
                // 2,
                "independently_replayed_random_draws": len(resolution)
                * len(feed["rates"]),
            },
            "cost_model": {
                "author_fee_per_side": 0,
                "comparison_fee_per_side": FEE,
                "execution_buffer_per_side": EXECUTION,
            },
            "method": [
                "Saved FMZ argument v_input_1=2 selects Random. The source's 10% entry and 3% exit both use the same per-bar draw; a second independent draw picks direction. Both original call sites were seeded with the predeclared Round 27 schedule. Seed 1 populates the workbook and all 32 seeds are independently checked.",
                "The archived unseeded historical random samples are irretrievable. The measured distribution represents scenarios on the same candles. Native source fee is zero and the Pine runtime default starting equity is $1,000,000 per market. Orders use 100% current source equity, a 0.001 modeled order step, and daily next opens confirmed from independent hourly archives.",
                "Coinbase prior UTC close converts USDT to USD. Source quantities are fixed when comparison fees and execution allowances are applied afterward. Drawdown metrics use cumulative completed-lot cashflows. Terminal open positions stay open. Funding, liquidation and actual market impact are outside this replay.",
            ],
            "source_references": [
                "https://www.fmz.com/strategy/428974",
                "https://www.tradingview.com/pine-script-reference/v4/#fun_random",
                "https://github.com/binance/binance-public-data",
                "https://docs.cdp.coinbase.com/exchange/reference/exchangerestapi_getproductcandles",
            ],
            "stochastic_ensemble": samples,
            "coverage": [
                [
                    IDENT,
                    status,
                    "All 128 prespecified archived-argument Pine v4 BTC/ETH paths reconcile to independent random draws, orders, lots, prices, quantities and marked USD equity. Workbook uses seed 1 plus disclosed counterfactual costs.",
                ]
            ],
            "results": rows,
        },
    )
    print(
        f"{len(rows)} result rows; {len(resolution)} paths; {checked_orders} orders; {checked_trades} settled simulated lots."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "report"))
    for name in ("archive", "baseline", "work", "exchange_fx", "extra_fx", "output"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--daily", type=Path, required=True, nargs="+")
    parser.add_argument("--hourly", type=Path, required=True, nargs="+")
    args = parser.parse_args()
    source, digest, fields, code = source_record(args.archive, args.baseline)
    feed = inputs(args.daily, args.hourly, args.exchange_fx, args.extra_fx)
    if args.mode == "stage":
        stage(args, code, feed)
    else:
        report(args, source, digest, fields, code, feed)


if __name__ == "__main__":
    main()
