"""Verify the archived Fourier fixed-unit strategy and historical EUR cashflows."""

from __future__ import annotations

import argparse
import re
from math import cos, fsum, isclose
from pathlib import Path
from shutil import copy2
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, aggregate, date_ms, sha256
from research.fmz_round7_pine import EXECUTION, FEE, summarize
from research.fmz_round19_pine_broker import equal
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH
from research.fmz_round28_pine_callback import cache_bars

IDENT = 365
GROUP = "FMZ Pine · Authored Fourier strategy and EUR conversion comparison"
LABEL = {"native": "FMZ native window", "next": "Next equal window"}
CAPITAL = 10_000
M1 = 60_000
M10 = 10 * M1
DAY = 24 * 60 * M1
QTY = 10_000
PROBE = "fmz_round42_pine_ftsma_probe.py"
ALT_FX = "coinbase-USDT-EUR-20220424-20220624.json"
ALT_FX_SHA = "3486104abda46ae1fdf21ec7ff984df0bd32eea8fe6370230936a1d776db7071"
ALT_URL = "https://api.exchange.coinbase.com/products/USDT-EUR/candles?granularity=86400&start=2022-04-24T00:00:00Z&end=2022-06-24T00:00:00Z"
PLOTS = ("Pi", "Slow MA", "Medium MA", "Fast MA", "Long", "Short", "Position")
ID_SIDE = {1: "Long Entry", -1: "Short Entry"}
DIRECTION = {1: "strategy.long", -1: "strategy.short"}


def source_record(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (row,) = (r for r in read(baseline)["disposition"] if r["id"] == IDENT)
    assert row["status"].startswith("Pending")
    with ZipFile(archive) as book:
        ((_, datum, doc, checksum),) = documents(book, {IDENT: row})
    (raw,) = re.findall(r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", doc)
    settings = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)", raw
        )
    )
    assert settings == {
        "start": "2022-04-25 00:00:00",
        "end": "2022-05-24 23:59:00",
        "period": "10m",
        "basePeriod": "1m",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    for witness in (
        "//@version=4",
        "initial_capital=10000,calc_on_every_tick=true, pyramiding=10, default_qty_type=strategy.fixed, default_qty_value=10000, currency=currency.EUR",
        'plotSMA=input(true,"Use MA")',
        "smoothinput = input('EMA'",
        'linearReg=input(false, "Use linear regression?")',
        "int len1 = len/2",
        "_b := 1 / (6. * _i + 3) - _b / 9.",
        "\n    _pi := (4. * _a) + (4. * _b) - _pi",
        "pi=f_pi(20)",
        'N = input(defval=64, title="Lookback Period"',
        "slowMA=input(200,",
        "mediumMA=input(20,",
        "fastMA=input(5,",
        "sin1=input(1,",
        "sin2=input(2,",
        "sin3=input(3,",
        "longCondition = FASTMA>MEDMA and close > SLOWMA",
        "shortCondition = FASTMA<MEDMA and close < SLOWMA",
        'strategy.entry("Long Entry", strategy.long)',
        'strategy.entry("Short Entry", strategy.short)',
    ):
        assert witness in raw.replace("\r\n", "\n"), witness
    assert raw.count("input(defval = 0, title = ") == 4 and "commission_" not in raw
    link = re.search(r"https://www\.fmz\.com/strategy/\d+", doc)[0]
    return datum, raw.encode(), settings, checksum, link


def market_data(cache):
    start, boundary = map(date_ms, ("2022-04-25", "2022-05-25"))
    end = 2 * boundary - start
    history = start - DAY
    months = ("2022-04", "2022-05", "2022-06")
    manifest = []
    direct = {
        r[0]: 1 / r[4]
        for r in cache_bars((cache,), "EURUSDT", "1d", months, DAY, manifest)
        if history <= r[0] < end
    }
    assert all("/futures/um/" in f["url"] for f in manifest)
    manifest = [
        {**f, "url": f["url"].replace("/futures/um/", "/spot/")} for f in manifest
    ]
    assert sorted(direct) == list(range(history, end, DAY))
    alt = cache / ALT_FX
    assert sha256(alt) == ALT_FX_SHA
    response = read(alt)
    alternate = {
        int(r[0]) * 1000: r[4] for r in response if history <= int(r[0]) * 1000 < end
    }
    assert sorted(alternate) == sorted(direct)
    assert all(
        low <= min(opening, closing) <= max(opening, closing) <= high and qty > 0
        for _, low, high, opening, closing, qty in response
    )
    feeds = {}
    for market in ("BTCUSDT", "ETHUSDT"):
        candles = [
            r
            for r in cache_bars((cache,), market, "1m", months, M1, manifest)
            if start <= r[0] < end
        ]
        assert [r[0] for r in candles] == list(range(start, end, M1))
        for period, lo, hi in (("native", start, boundary), ("next", boundary, end)):
            feed = [
                list(r) for r in aggregate([r for r in candles if lo <= r[0] < hi], 10)
            ]
            assert [r[0] for r in feed] == list(range(lo, hi, M10))
            feeds.setdefault(period, {})[market] = {
                "chart": feed,
                "rates": [
                    {"effectiveTime": t, "rate": direct[t - DAY]}
                    for t in range(lo, hi, DAY)
                ],
            }
    return feeds, manifest, direct, alternate


def approximate_pi():
    a = 1 / (4 * 20 + 2)
    b = 1 / (6 * 20 + 3)
    for i in range(19, -1, -1):
        a = 1 / (4 * i + 2) - a / 4
        b = 1 / (6 * i + 3) - b / 9
    return 4 * (a + b)


def ema(values, length, first):
    points = []
    previous = None
    alpha = 2 / (length + 1)
    for value in values:
        if value is not None:
            if previous is not None:
                previous = alpha * value + (1 - alpha) * previous
            elif first:
                previous = value
            else:
                points.append(value)
                if len(points) == length:
                    previous = fsum(points) / length
        yield previous


def signals(chart, first):
    pi = approximate_pi()
    close = [r[4] for r in chart]
    ma = []
    for harmonic, length in ((1, 200), (2, 20), (3, 5)):
        amplitudes = [cos(2 * pi * harmonic * i / 64) * 2 / 64 for i in range(64)]
        angular = [
            None
            if i < 63
            else close[i]
            + fsum(close[i - j] * weight for j, weight in enumerate(amplitudes))
            for i in range(len(close))
        ]
        ma.append(ema(angular, length, first))
    for i, (slow, mid, fast) in enumerate(zip(*ma, strict=True)):
        buy = slow is not None and fast > mid and close[i] > slow
        sell = slow is not None and fast < mid and close[i] < slow
        yield pi, slow, mid, fast, buy, sell


def utc_day(t):
    return t // DAY * DAY


def check_fields(a, b):
    return all(equal(x, y) for x, y in zip(a, b, strict=True))


def verify(tape, receipt, first, alternate):
    assert not receipt["diagnostics"] and not receipt["strategy"]["diagnostics"]
    chart = tape["chart"]
    rate = {r["effectiveTime"]: r["rate"] for r in tape["rates"]}
    realized = 0.0
    orders, closed, open_lots = [], [], []
    flows, other = [], []
    actual = receipt["strategy"]
    points = zip(*(receipt["plots"][p] for p in PLOTS), strict=True)
    previous_signal = side = 0
    for i, (r, states, plots, observed) in enumerate(
        zip(chart, signals(chart, first), points, actual["equity"], strict=True)
    ):
        t, po, _, _, pc, _ = r
        fx = rate[utc_day(t)]
        reversed_quantity = 0
        if previous_signal and side != previous_signal:
            for entry, cost in open_lots:
                gross = side * QTY * (po - cost) * fx
                realized += gross
                closed.append((side, entry, i, cost, po, gross))
                entry_fx = rate[utc_day(chart[entry][0])]
                value = QTY * (cost * entry_fx + po * fx)
                flows.append((t, gross, value * FEE, value * EXECUTION))
                alt_entry = alternate[utc_day(chart[entry][0]) - DAY]
                alt_exit = alternate[utc_day(t) - DAY]
                alt_value = QTY * (cost * alt_entry + po * alt_exit)
                other.append(
                    (
                        t,
                        side * QTY * (po - cost) * alt_exit,
                        alt_value * FEE,
                        alt_value * EXECUTION,
                    )
                )
            reversed_quantity = len(open_lots) * QTY
            open_lots = []
            side = previous_signal
        if previous_signal and len(open_lots) < 10:
            open_lots.append((i, po))
            orders.append((side, i, po, QTY + reversed_quantity))
        quantity = side * len(open_lots) * QTY
        assert check_fields((*states, quantity), plots)
        previous_signal = int(states[-2]) - int(states[-1])
        market_value = quantity * pc * fx
        unrealized = fsum(side * QTY * (pc - cost) * fx for _, cost in open_lots)
        equity = CAPITAL + realized + unrealized
        assert observed["barIndex"] == i
        for key, val in (
            ("cash", equity - market_value),
            ("marketValue", market_value),
            ("equity", equity),
            ("netProfit", equity - CAPITAL),
        ):
            assert isclose(observed[key], val, rel_tol=3e-11, abs_tol=1e-4), (
                i,
                key,
                observed[key],
                val,
            )
    for (side, i, price, filled_quantity), native in zip(
        orders, actual["orders"], strict=True
    ):
        assert (
            native["id"],
            native["direction"],
            native["barIndex"],
            native["qty"],
            native["price"],
            native["time"],
        ) == (ID_SIDE[side], DIRECTION[side], i, filled_quantity, price, chart[i][0])
    for (side, i, j, start, end, gross), native in zip(
        closed, actual["trades"], strict=True
    ):
        assert native["id"] == ID_SIDE[side]
        assert (native["entryTime"], native["exitTime"]) == (chart[i][0], chart[j][0])
        assert check_fields(
            (side * QTY, i, j, start, end, gross),
            (
                native[k]
                for k in (
                    "qty",
                    "entryBarIndex",
                    "exitBarIndex",
                    "entryPrice",
                    "exitPrice",
                    "profit",
                )
            ),
        )
    return (
        flows,
        other,
        len(open_lots),
        {
            "opened": len(orders),
            "closed": len(closed),
            "marked_bars": len(chart),
            "ending_open_lots": len(open_lots),
            "verified_output_values": len(chart) * len(PLOTS),
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "finalize"))
    for key in ("archive", "baseline", "work", "cache", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    a = parser.parse_args()
    row, raw, settings, checksum, link = source_record(a.archive, a.baseline)
    feeds, archives, fx, other_fx = market_data(a.cache)
    source = a.work / "r42-ftsma-source.pine"
    tape = a.work / "r42-ftsma-feeds.json"
    producer = Path(__file__).with_name(PROBE)
    staged = a.work / "r42_ftsma_probe.py"
    if a.mode == "stage":
        source.write_bytes(raw)
        write(tape, feeds)
        copy2(producer, staged)
        return
    assert source.read_bytes() == raw and read(tape) == feeds
    assert producer.read_bytes() == staged.read_bytes()
    assert (
        sha256(a.work / "priced-runtime/pine_compat/pine_compat.pyd")
        == NATIVE_BINARY_HASH
    )
    isolation = read(a.work / "round3-isolation-python.json")
    assert all(
        isolation[k][0] == "PermissionError" for k in ("file_error", "network_error")
    )
    error = a.work / "r42-ftsma-literal-error.txt"
    literal = [
        line for line in error.read_text().splitlines() if "E_ASSIGN_TYPE" in line
    ]
    assert len(literal) == 3 and all(
        "`len1` of type int with input float" in line for line in literal
    )
    src_hashes, modes, artifacts = {}, {}, [source, tape, producer, error]
    for mode in ("ema", "first"):
        path = a.work / f"r42-ftsma-{mode}.json"
        records = read(path)
        artifacts.append(path)
        (src_hashes[mode],) = {r["executed_source_sha256"] for r in records}
        modes[mode] = {(r["period"], r["market"]): r for r in records}
        assert len(records) == len(modes[mode]) == 4
    meta = {
        "id": IDENT,
        "name": row["name"],
        "source": row["source"],
        "source_sha256": checksum,
        "executed_source_sha256": src_hashes["first"],
        "group": GROUP,
        "interval": "10m",
        "archive_interval": "10m",
        "quote_currency": "EUR",
        "comparison_fee": FEE,
        "market_data": "Binance futures 1m (10m aggregated); prior Binance spot EURUSDT daily close",
        "exit": "Opposite harmonic/EMA gate reverses at next measured opening, with no active priced exits.",
    }
    rows, audit = [], []
    for period, assets in feeds.items():
        total, alt_total, terminal_lots = [], [], 0
        for market, data in assets.items():
            legacy = verify(data, modes["ema"][(period, market)], False, other_fx)
            ledger, alternate, terminal, counts = verify(
                data, modes["first"][(period, market)], True, other_fx
            )
            audit.append(
                {
                    "period": LABEL[period],
                    "market": market,
                    **counts,
                    "diagnostic_sma_seed_closes": legacy[3]["closed"],
                    "alternate_coinbase_eur_fx": summarize(
                        alternate, terminal, CAPITAL
                    ),
                }
            )
            rows.append(
                {
                    **meta,
                    "period": LABEL[period],
                    "market": market,
                    **summarize(ledger, terminal, CAPITAL),
                }
            )
            total.extend(ledger)
            alt_total.extend(alternate)
            terminal_lots += terminal
        rows.append(
            {
                **meta,
                "period": LABEL[period],
                "market": "BTCUSDT + ETHUSDT",
                **summarize(total, terminal_lots, 2 * CAPITAL),
            }
        )
        audit.append(
            {
                "period": LABEL[period],
                "market": "BTCUSDT + ETHUSDT",
                "alternate_coinbase_eur_fx": summarize(
                    alt_total, terminal_lots, 2 * CAPITAL
                ),
            }
        )
    closed = sum(x.get("closed", 0) for x in audit)
    assert closed == 2684
    write(
        a.output,
        {
            "baseline_coverage_sha256": sha256(a.baseline),
            "archive_sha256": FMZ_SHA256,
            "document_sha256": checksum,
            "archive_settings": settings,
            "pine_compat_binary_sha256": NATIVE_BINARY_HASH,
            "isolation_probe": isolation,
            "source_audit": {
                "default_ema_and_disabled_exits": True,
                "authored_fixed_quantity_units": QTY,
                "authored_initial_capital_eur": CAPITAL,
                "maximum_entries_same_side": 10,
                "margin_liquidation_or_market_capacity_modeled": False,
                "qualified_for_strategy_promotion": False,
                "literal_compiler_diagnostic": literal,
                "executed_sources": src_hashes,
            },
            "provider_archives": archives,
            "independent_alternate_rate_source": {
                "url": ALT_URL,
                "sha256": ALT_FX_SHA,
                "verified_prior_close_dates": len(fx),
                "max_relative_direct_rate_difference": max(
                    abs(v / other_fx[t] - 1) for t, v in fx.items()
                ),
            },
            "artifacts": {p.name: sha256(p) for p in artifacts},
            "per_scope_verification": audit,
            "method": [
                "The raw v4 compiler rejects a fractional initializer for an integer inside the FRAMA function. The archived default always takes EMA and disables linear regression; using that constant branch removes the unused function from evaluation. Source Fourier recurrences, harmonic lookback, gates, market order calls and pyramiding are verified independently.",
                "FMZ documents the EMA initialized from its first source price. We apply that path and separately check the local native SMA-seeded control. All variant indicators, entry quantities, open-priced reversals, signed position sizes, closed lots, and marked account cash/equity reconcile to an independent model.",
                "Gross trading P&L is converted at the previous UTC-day close for the exit day. Fees and the execution-cost buffer use independently timed entry/exit conversion rates. Both original Binance spot EURUSDT and alternate Coinbase USDT-EUR daily candles supply direct conversions. This is an explicit comparison source, not a recovered FMZ proprietary rate series.",
                "The archived first window includes the final 23:59 one-minute print accumulated into the 23:50 ten-minute bar; the following equal window starts at midnight. The original chart history runs on settled ten-minute bars. Both market feeds come from exact checksummed one-minute Binance futures archives.",
                "Source settings specify EUR 10,000 initial equity, 10,000 underlying units per entry and up to ten active lots. This source comparison allows the declared position size without financing, liquidation, or order-queue constraints. The results cannot establish a practical trading capacity or qualify this sizing for deployment. Terminal holdings remain unsettled.",
            ],
            "references": [
                link,
                "https://www.fmz.com/bbs-topic/9293",
                "https://www.tradingview.com/pine-script-docs/v4/essential/strategies/",
                "https://github.com/binance/binance-public-data",
                "https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles",
            ],
            "coverage": [
                [
                    IDENT,
                    f"Tested · {GROUP}",
                    "Specialized the archived fixed EMA input to avoid its unused FRAMA compile error, then verified first-price EMA, market reversals, FIFO sizing and EUR historical conversion. Source-defined huge positions are hypothetical no-margin comparisons only.",
                ]
            ],
            "results": rows,
        },
    )
    print(
        f"Verified {IDENT}: {len(rows)} workbook results, {closed} closed lots, eight native receipts checked."
    )


if __name__ == "__main__":
    main()
