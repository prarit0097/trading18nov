"""Verify authored recursive filters, entry gates, and unsettled positions."""

from __future__ import annotations

import argparse
import re
from collections import deque
from datetime import UTC, datetime
from math import exp, floor, fsum, tan
from pathlib import Path
from shutil import copy2
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, aggregate, date_ms, sha256
from research.fmz_round7_pine import EXECUTION, FEE, summarize
from research.fmz_round18_pine_qqe import executable_lines
from research.fmz_round19_pine_broker import equal
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH
from research.fmz_round28_pine_callback import cache_bars

DAY = 86_400_000
MINUTE = 60_000
MARKETS = ("BTCUSDT", "ETHUSDT")
LABEL = {"native": "FMZ native window", "next": "Next equal window"}
SPECS = {
    3530: (
        "2023-01-01",
        "2023-04-14",
        "1d",
        "1h",
        20000,
        0.0001,
        "USDT",
        "MA Candles Supertrend",
    ),
    4545: (
        "2023-12-23",
        "2024-01-10",
        "1m",
        "1m",
        1000000,
        FEE,
        "USDT",
        "IIR/ALMA with two squeeze filters",
    ),
    5166: (
        "2023-09-06",
        "2023-09-13",
        "5m",
        "1m",
        1000,
        FEE,
        "USD",
        "IIR/ALMA with positive fast slope",
    ),
}
PROBES = {
    "r31_iir_fast.py": "fmz_round31_pine_iir_probe.py",
    "r31_masu_probe.py": "fmz_round31_pine_masu_probe.py",
}


def sources(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    focus = {r["id"]: r for r in read(baseline)["disposition"] if r["id"] in SPECS}
    assert set(focus) == set(SPECS) and all(
        r["status"].startswith("Pending") for r in focus.values()
    )
    with ZipFile(archive) as z:
        for ident, row, doc, digest in documents(z, focus):
            (raw,) = re.findall(
                r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", doc
            )
            assert "//@version=4" in raw
            active = "\n".join(executable_lines(raw))
            s, e, tf, under, _, _, _, _ = SPECS[ident]
            fields = dict(
                re.findall(
                    r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)",
                    raw,
                )
            )
            assert fields == {
                "start": s + " 00:00:00",
                "end": e + " 00:00:00",
                "period": tf,
                "basePeriod": under,
                "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
            }
            if ident == 3530:
                need = (
                    "initial_capital = 20000",
                    "commission_value = 0.01",
                    'defval="rma"',
                    "LoopbackBars = input(20",
                    "AtrLength = input(30",
                    "AtrMult = input(1)",
                    "wicks = input(true)",
                    "dThreshold = input(0.2",
                    "rThreshold = input(0.7",
                    "defval=strategy.direction.long",
                    "_src[_offset], lookahead = barmerge.lookahead_on",
                    "f_secureSecurity(syminfo.tickerid, '12M', high, 1)",
                    "f_secureSecurity(syminfo.tickerid, '12M', low, 1)",
                    "longCondition = close > shortStop and dir == 1 and yearlyHighCondition",
                    "shortCondition = close < longStop and dir == -1 and yearlyLowCondition",
                    'strategy.close("Long", when=exitLongCondition)',
                )
            else:
                need = (
                    'positionType = "LONG"',
                    'strategy.entry("LONG", strategy.long, when=true)',
                    'strategy.close("LONG", when=true)',
                    "debug = input(false",
                    "posx = timenow + round(change(time)*60)",
                    "multiplier = _adjRes/timeframe.multiplier",
                    "round(_adjLength*multiplier)",
                    "cf = 2*tan(2*3.14159*(1/iirlength)/2)",
                    "out := nz(c*(iirsrc + iirsrc[3]) + 3*c*(iirsrc[1] + iirsrc[2]) + d0*out[1] + d1*out[2] + d2*out[3],iirsrc)",
                    "if (crossunderFast)",
                    "smaOTF = alma(iirmaOTF, almaXperiod, almaXalpha, almaXsigma)",
                )
                if ident == 4545:
                    need += (
                        "maRes = input(960",
                        "mal3 = input(34",
                        "showFIBMAs = input(false",
                        "madist2 := abs(ma1 - ma3)",
                        "if max(madist1, madist2) <= singlePercent*loosePercentClose",
                        "iirlength1 = input",
                        "defval=34",
                        "defval=144",
                        "defval=720",
                        "iirX = input(555",
                        "iirXperiod = input(30",
                        "iirX2 = input(13",
                        "iirX2period = input(5",
                        "almaXperiod = input(defval=15",
                        "defval=.7",
                        "defval=500",
                        "if (crossoverFast and iirma2Up == true and infastsqueeze == false and intightsqueeze == false)",
                    )
                else:
                    need += (
                        "default_qty_type = strategy.cash",
                        "default_qty_value = 1000",
                        "currency = currency.USD",
                        "iirX = input(13",
                        "iirXperiod = input(21",
                        "iirX2 = input(144",
                        "iirX2period = input(233",
                        "almaXperiod = input(defval=21",
                        "defval=.99",
                        "defval=8",
                        "iirma2Up = iirma2OTF[0] > iirma2OTF[1]",
                        "if (crossoverFast and iirma2Up == true)",
                    )
                assert active.count("timenow") == 1
                assert not re.search(r"\bsecurity\(", active)
            for token in need:
                assert token in active, (ident, token)
            yield ident, row, digest, fields, raw.encode()


def month(t):
    return datetime.fromtimestamp(t / 1000, UTC).strftime("%Y-%m")


def rebuild_data(ident, folders):
    start, end, tf, _, _, _, _, _ = SPECS[ident]
    a, b = map(date_ms, (start, end))
    hi = 2 * b - a
    step = DAY if tf == "1d" else MINUTE
    interval = "1d" if tf == "1d" else "1m"
    months = sorted({month(t) for t in range(a, hi, DAY)})
    manifest = []
    tape = {}
    years = {}
    for market in MARKETS:
        rows = list(cache_bars(folders, market, interval, months, step, manifest))
        for period, start, end in (("native", a, b), ("next", b, hi)):
            selected = [r for r in rows if start <= r[0] < end]
            assert [r[0] for r in selected] == list(range(start, end, step))
            full = list(aggregate(selected, 5)) if tf == "5m" else selected
            tape.setdefault(period, {})[market] = [list(r) for r in full]
        if ident == 3530:
            annual = []
            from_date, to_date = map(date_ms, ("2021-01-01", "2025-01-01"))
            yr_months = sorted({month(t) for t in range(from_date, to_date, DAY)})
            expanded = list(cache_bars(folders, market, "1d", yr_months, DAY, manifest))
            for year in range(2021, 2025):
                lo, up = map(date_ms, (f"{year}-01-01", f"{year + 1}-01-01"))
                rr = [r for r in expanded if lo <= r[0] < up]
                assert [r[0] for r in rr] == list(range(lo, up, DAY))
                annual.append(
                    [
                        lo,
                        rr[0][1],
                        max(r[2] for r in rr),
                        min(r[3] for r in rr),
                        rr[-1][4],
                        sum(r[5] for r in rr),
                    ]
                )
            years[market] = annual
    return manifest, tape, years


def artifact_names(ident):
    if ident == 3530:
        return (
            "round31-masu-source.pine",
            "round31-masu-feeds.json",
            ["round31-masu-receipt.json"],
        )
    paths = (
        ["round31-iir-5166-full-all.json"]
        if ident == 5166
        else [f"round31-iir-4545-full-{m}.json" for m in MARKETS]
    )
    return f"round31-iir-{ident}-source.pine", f"round31-iir-{ident}-feeds.json", paths


def stage(archive, baseline, work, folders):
    for ident, _, _, _, raw in sources(archive, baseline):
        _, fe, years = rebuild_data(ident, folders)
        pine, feed, _ = artifact_names(ident)
        (work / pine).write_bytes(raw)
        write(work / feed, fe)
        if ident == 3530:
            write(work / "round28-bb-years.json", years)
    for dest, name in PROBES.items():
        copy2(Path(__file__).with_name(name), work / dest)


def iir(sample, length):
    cf = 2 * tan(2 * 3.14159 * (1 / length) / 2)
    a0 = 8 + 8 * cf + 4 * cf**2 + cf**3
    a1 = -24 - 8 * cf + 4 * cf**2 + 3 * cf**3
    a2 = 24 - 8 * cf - 4 * cf**2 + 3 * cf**3
    a3 = -8 + 8 * cf - 4 * cf**2 + cf**3
    c = cf**3 / a0
    d0 = -a1 / a0
    d1 = -a2 / a0
    d2 = -a3 / a0
    out = list(sample[:3])
    for i in range(3, len(sample)):
        out.append(
            c * (sample[i] + sample[i - 3])
            + 3 * c * (sample[i - 1] + sample[i - 2])
            + d0 * out[i - 1]
            + d1 * out[i - 2]
            + d2 * out[i - 3]
        )
    return out


def alma(data, n, offset, sigma, round_center):
    k = offset * (n - 1)
    if round_center:
        k = int(k)
    s = n / sigma
    coeff = [exp(-((x - k) ** 2) / (2 * s * s)) for x in range(n)]
    total = sum(coeff)
    return [
        None
        if i + 1 < n
        else sum(a * b for a, b in zip(coeff, data[i - n + 1 : i + 1], strict=True))
        / total
        for i in range(len(data))
    ]


def replay(ident, chart, round_center=False):
    frame = 1 if ident == 4545 else 5
    data = [r[4] for r in chart]
    slow = iir(data, 16650 if ident == 4545 else 55)
    fast = iir(data, 65 if ident == 4545 else 6710)
    n, offset, sigma = (15, 0.7, 500) if ident == 4545 else (21, 0.99, 8)
    base = alma(slow, n, offset, sigma, round_center)
    d21, d22, d23 = (iir(data, k * 60 // frame) for k in (34, 144, 720))
    previous = None
    buy = []
    sell = []
    for i, (a, b) in enumerate(zip(slow, base, strict=True)):
        diff = None if b is None else a - b
        pc = data[i]
        tight = abs(d21[i] - d22[i]) < 0.008 * pc and pc >= max(d21[i], d22[i], d23[i])
        slope = (
            (i >= 10 and fast[i] / fast[i - 10] * 100 > 0)
            if ident == 4545
            else (i > 0 and fast[i] > fast[i - 1])
        )
        assert ident != 4545 or i < 960 * 34 - 1
        buy.append(
            int(
                diff is not None
                and previous is not None
                and diff > 0
                and previous <= 0
                and slope
                and (ident != 4545 or not tight)
            )
        )
        sell.append(
            int(
                diff is not None and previous is not None and diff < 0 and previous >= 0
            )
        )
        previous = diff
    return slow, fast, base, buy, sell


def rma(seq, length):
    q = deque(maxlen=length)
    x = None
    for val in seq:
        if val is not None:
            q.append(val)
            if len(q) == length:
                x = fsum(q) / length if x is None else (x * (length - 1) + val) / length
        yield x


def model(chart, prev_year):
    _, _, h_y, l_y, _, _ = prev_year
    hi, lo, close = tuple([r[x] for r in chart] for x in (2, 3, 4))
    high, low, smoothed = tuple(list(rma(x, 20)) for x in (hi, lo, close))
    tr = [
        (max(h, smoothed[i - 1]) - min(l, smoothed[i - 1]))
        if i and h is not None and smoothed[i - 1] is not None
        else None
        for i, (h, l) in enumerate(zip(high, low, strict=True))
    ]
    direction = 1
    prior_low = prior_high = None
    for i, atr in enumerate(rma(tr, 30)):
        a, b = (None, None) if atr is None else (smoothed[i] - atr, smoothed[i] + atr)
        prev_a = a if prior_low is None else prior_low
        prev_b = b if prior_high is None else prior_high
        if a is not None:
            a = max(a, prev_a) if low[i - 1] > prev_a else a
            b = min(b, prev_b) if high[i - 1] < prev_b else b
            if direction == -1 and high[i] > prev_b:
                direction = 1
            elif direction == 1 and low[i] < prev_a:
                direction = -1
        prior_low, prior_high = a, b
        yh = close[i] > 0.8 * h_y or close[i] > 1.7 * l_y
        yl = close[i] < 1.2 * l_y or close[i] < 0.3 * h_y
        buy = b is not None and close[i] > b and direction == 1 and yh
        sell = a is not None and close[i] < a and direction == -1 and yl
        yield (smoothed[i], high[i], low[i], direction, a, b, yh, yl, buy, sell)


def compare_rows(expected, seen):
    for i, (want, got) in enumerate(zip(expected, seen, strict=True)):
        assert all(equal(x, y) for x, y in zip(want, got, strict=True)), (i, want, got)


def iir_orders(ident, chart, case):
    iir_slow, iir_fast, smooth, long, exits = replay(ident, chart)
    names = ("IIR", "IIR small", "ALMA", "Signal long", "Signal exit")
    evidence = case["observations"]
    compare_rows(
        zip(iir_slow, iir_fast, smooth, long, exits, strict=True),
        zip(*(evidence[n] for n in names), strict=True),
    )
    held = None
    desired = None
    observed_positions = []
    want = []
    moves = []
    for i, (row, buy, sell) in enumerate(zip(chart, long, exits, strict=True)):
        if desired == "open":
            assert held is None
            held = i
            moves.append(("LONG", "strategy.long", i))
        elif desired == "close":
            assert held is not None
            want.append((held, i))
            moves.append(("Close entry(s) order LONG", "strategy.close", i))
            held = None
        observed_positions.append(int(held is not None))
        desired = (
            "open"
            if buy and held is None
            else "close"
            if sell and held is not None
            else None
        )
        assert not (buy and sell)
    assert observed_positions == evidence["Position"]
    if ident == 5166:
        assert sum(long) == 0 and not case["orders"] and not case["trades"]
    for (name, direction, i), observed in zip(moves, case["orders"], strict=True):
        assert (observed["id"], observed["direction"], observed["barIndex"]) == (
            name,
            direction,
            i,
        )
        assert (observed["qty"], observed["time"], observed["price"]) == (
            1,
            chart[i][0],
            chart[i][1],
        )
    ledger = []
    for (a, b), raw in zip(want, case["trades"], strict=True):
        price_a, price_b = chart[a][1], chart[b][1]
        gross = price_b - price_a
        turnover = price_a + price_b
        assert raw["id"] == "LONG" and raw["qty"] == 1
        assert (
            raw["entryBarIndex"],
            raw["exitBarIndex"],
            raw["entryTime"],
            raw["exitTime"],
        ) == (a, b, chart[a][0], chart[b][0])
        assert (raw["entryPrice"], raw["exitPrice"]) == (price_a, price_b)
        assert equal(raw["profit"], gross - turnover * FEE)
        ledger.append((raw["exitTime"], gross, turnover * FEE, turnover * EXECUTION))
    return (
        ledger,
        int(held is not None),
        {
            "closed": len(ledger),
            "bar_count": len(chart),
            "entry_gates": sum(long),
            "exit_gates": sum(exits),
            "orders": len(moves),
            "terminal_position": observed_positions[-1],
        },
    )


def supertrend_orders(chart, annual, case):
    prior = next(row for row in annual if row[0] == date_ms("2022-01-01"))
    points = list(model(chart, prior))
    names = (
        "Smooth close",
        "Smooth high",
        "Smooth low",
        "Direction",
        "Lower",
        "Upper",
        "Yearly high gate",
        "Yearly low gate",
        "Long gate",
        "Short gate",
    )
    observed = case["observations"]
    compare_rows(points, zip(*(observed[k] for k in names), strict=True))
    first_signal = next(i for i, obs in enumerate(points) if obs[-2])
    assert all(p[3] == 1 and not p[-1] for p in points[first_signal:])
    index = first_signal + 1
    t, price, _, _, _, _ = chart[index]
    cash, fee = SPECS[3530][4:6]
    amount = floor(cash / (price * (1 + fee)) / 0.001 + 1e-9) * 0.001
    (raw,) = case["orders"]
    assert raw == {
        "id": "Long",
        "barIndex": index,
        "time": t,
        "direction": "strategy.long",
        "qty": amount,
        "price": price,
    }
    equity = [
        cash if i < index else cash - price * amount * fee + amount * (bar[4] - price)
        for i, bar in enumerate(chart)
    ]
    assert not case["trades"]
    compare_rows(zip(equity, strict=True), [(p["equity"],) for p in case["equity"]])
    assert [0] * index + [amount] * (len(chart) - index) == observed["Position"]
    return (
        [],
        1,
        {
            "closed": 0,
            "bar_count": len(chart),
            "terminal_position": amount,
            "opening_cost": price * amount * fee,
            "yearly_filter_2022_high": prior[2],
            "yearly_filter_2022_low": prior[3],
            "orders": 1,
        },
    )


def report(archive, baseline, work, folders, output):
    binary = work / "priced-runtime/pine_compat/pine_compat.pyd"
    assert sha256(binary) == NATIVE_BINARY_HASH
    isolate = read(work / "round3-isolation-python.json")
    assert all(
        isolate[k][0] == "PermissionError" for k in ("file_error", "network_error")
    )
    producers = {}
    for target, name in PROBES.items():
        origin = Path(__file__).with_name(name)
        assert origin.read_bytes() == (work / target).read_bytes()
        producers[name] = sha256(origin)
    results, stats, coverage = [], [], []
    metrics, provider, hashes = {}, {}, {}
    for ident, record, digest, fields, raw in sources(archive, baseline):
        provider[ident], data, years = rebuild_data(ident, folders)
        pine, feed, receipts = artifact_names(ident)
        assert (work / pine).read_bytes() == raw
        assert read(work / feed) == data
        if ident == 3530:
            assert read(work / "round28-bb-years.json") == years
            hashes["round28-bb-years.json"] = sha256(work / "round28-bb-years.json")
        hashes.update({name: sha256(work / name) for name in (pine, feed, *receipts)})
        cases = [entry for name in receipts for entry in read(work / name)]
        by_case = {(entry["period"], entry["market"]): entry for entry in cases}
        assert len(cases) == len(by_case) == 4
        _, _, interval, _, capital, fee, quote, group = SPECS[ident]
        group = "FMZ Pine · " + group
        template = {
            "id": ident,
            "name": record["name"],
            "source": record["source"],
            "source_sha256": digest,
            "archived_pine_sha256": sha256(work / pine),
            "quote_currency": quote,
            "group": group,
            "interval": interval,
            "archive_interval": interval,
            "market_data": "Official Binance USD-M OHLCV",
            "exit": "Supertrend direction flip"
            if ident == 3530
            else "Authored IIR/ALMA crossunder",
            "comparison_fee": fee,
        }
        metrics[ident] = {
            "archive_settings": fields,
            "source_sha256": digest,
            "source_pine_sha256": sha256(work / pine),
            "reported_cash_currency": quote,
        }
        for period, markets in data.items():
            pooled = []
            open_lots = 0
            for market, chart in markets.items():
                case = by_case[(period, market)]
                assert not case["broker_diagnostics"]
                if ident == 3530:
                    assert len(case["diagnostics"]) == 2
                    assert all(
                        d["code"] == "W_LEGACY_SECURITY_LOOKAHEAD"
                        for d in case["diagnostics"]
                    )
                    ledger, opened, details = supertrend_orders(
                        chart, years[market], case
                    )
                else:
                    assert not case["diagnostics"]
                    ledger, opened, details = iir_orders(ident, chart, case)
                results.append(
                    {
                        **template,
                        "period": LABEL[period],
                        "market": market,
                        **summarize(ledger, opened, capital),
                    }
                )
                stats.append(
                    {"id": ident, "period": LABEL[period], "market": market, **details}
                )
                pooled.extend(ledger)
                open_lots += opened
            results.append(
                {
                    **template,
                    "period": LABEL[period],
                    "market": "BTCUSDT + ETHUSDT",
                    **summarize(pooled, open_lots, capital * 2),
                }
            )
        description = {
            3530: "The prior confirmed calendar-year high and low and all signals independently match. Each window has one confirmed opening order and no realized closes.",
            4545: "Source-equivalent 1m default filter path, all signals, original-market fills and costs reconcile. Four closed one-unit lots verified.",
            5166: "Every source 5m signal and position reconciles independently. Zero eligible entries and zero fills in the four windows.",
        }[ident]
        coverage.append([ident, f"Tested · {group}", description])
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(baseline),
            "archive_sha256": FMZ_SHA256,
            "pine_compat_binary_sha256": NATIVE_BINARY_HASH,
            "isolation_probe": isolate,
            "runtime_producers": producers,
            "artifacts": hashes,
            "source_audits": metrics,
            "provider_archives": provider,
            "per_case_order_counts": stats,
            "coverage": coverage,
            "results": results,
            "method": [
                "Each test uses the source-selected Binance USD-M timeframe and dates, its ETH counterpart, and equal subsequent windows. The 5m charts are constructed from verified official 1m archives. State resets at each window and orders fill at the next observed bar open.",
                "3530 uses 20-period Wilder-smoothed candles and 30-period Wilder-smoothed range. Daily gate compares against 2022 high/low, explicitly requested with high[1] and low[1]. The authored $20,000, 100% equity, long-only gate and 0.01% commission are preserved. Four verified open positions remain unsettled. Their entry fees are disclosed separately and no realized drawdown is fabricated.",
                "4545 and 5166 share the same recursive IIR formula but use different original period scalings, ALMA lengths, and entry gates. For 4545 the 32,640-bar SMA is always missing in each independently reset 25,920-bar sample. Its dependent fast squeeze cannot qualify. Removing those display-disabled and otherwise inert long SMAs preserves all order gates, while the active tight IIR squeeze remains calculated from its source.",
                "The 5166 script uses a USD cash account and no gates opened positions, so no FX or trade fees were incurred. Added project comparison fees for 4545 and 5166 do not alter any order gate. Before-fee and after-fee P&L use the same closed cashflows, and the separate execution buffer applies only in the net metric.",
            ],
            "references": [
                "https://github.com/binance/binance-public-data",
                "https://www.tradingview.com/pine-script-docs/v4/essential/strategies/",
                "https://www.tradingview.com/pine-script-reference/v4/#fun_alma",
                "https://www.tradingview.com/support/solutions/43000628599-strategy-properties/",
            ],
        },
    )
    print(
        f"Verified {len(coverage)} strategies, {len(results)} workbook rows, and {sum(q['closed'] for q in stats)} realized closes."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "finalize"))
    for arg in ("archive", "baseline", "work", "output"):
        parser.add_argument(f"--{arg}", type=Path, required=True)
    parser.add_argument("--provider", type=Path, nargs="+", required=True)
    vals = parser.parse_args()
    args = (vals.archive, vals.baseline, vals.work, vals.provider)
    if vals.mode == "stage":
        stage(*args)
    else:
        report(*args, vals.output)


if __name__ == "__main__":
    main()
