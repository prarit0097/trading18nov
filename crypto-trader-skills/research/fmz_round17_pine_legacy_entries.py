"""Replay original market orders in Pine fractal, RSI, and net-volume strategies."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from datetime import date, timedelta
from hashlib import sha512
from itertools import chain, pairwise
from math import floor, fsum, isclose
from pathlib import Path
from shutil import copy2, copytree
from tarfile import open as open_tar
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round6_pine import archival_items
from research.fmz_round7_magnifier import FMZ_SHA256, date_ms, sha256, verified_archives
from research.fmz_round7_pine import (
    EXECUTION,
    FEE,
    PINER_PIN,
    PINER_VERSION,
    strip_fmz_wrapper,
    summarize,
)
from research.fmz_round11_pine_playzone import exponential
from research.fmz_round12_pine_authored import aligned, provider_bars, rsi

MARKETS = ("BTCUSDT", "ETHUSDT")
CAPITAL = 10_000
LOT_STEP = 0.001
MINUTE = 60_000
DAY = 86_400_000
FEE_PER_SIDE = {3027: 0, 5454: 0.0001, 5591: FEE}
ORDER_CASH = {3027: 10_000, 5591: 1_000}


def legacy_variant(code, ident):
    active = re.sub(r"(?m)//[^\n]*", "", code)
    exits = re.findall(r"(?m)^strategy.exit\([^\n]+$", active)
    assert len(exits) == 2 and all(
        re.search(
            r"\b(?:loss|stop|profit|limit|trail_offset|trail_points|trail_price)\s*=",
            line,
        )
        is None
        for line in exits
    )
    if ident == 5454:
        existing = 'strategy("My Strategy", overlay = false, commission_value = 0.01, pyramiding = 1)'
        assert (
            existing in code
            and "vrsi = rsi(RSIprice, RSIlength)" in code
            and "RSIprice = close" in code
        )
        long = 'strategy.entry("Buy", strategy.long, 1, when = close > ema(close, 162) and vrsi < RSIOverSold)'
        short = 'strategy.entry("Sell", strategy.short, 1, when = close < ema(close, 162) and vrsi > RSIOverSold)'
        assert long in code and short in code
        assert "RSIOverSold = input(35," in code and "RSIlength = input( 14," in code
        return "\n".join(
            (
                "//@version=5",
                existing,
                "base=ta.ema(close,162)",
                "vrsi=ta.rsi(close,14)",
                "buy=close>base and vrsi<35",
                "sell=close<base and vrsi>35",
                long.replace("close > ema(close, 162) and vrsi < RSIOverSold", "buy"),
                short.replace("close < ema(close, 162) and vrsi > RSIOverSold", "sell"),
                'plot(base,"A")',
                'plot(vrsi,"B")',
                'plot(buy?1:0,"Buy")',
                'plot(sell?1:0,"Sell")',
                "",
            )
        )
    assert 'src = input(defval = close, title = "VA Source")' in code
    assert (
        "nv = change(src) > 0 ? volume : change(src) < 0 ? -volume : 0*volume" in code
    )
    assert "MAV1 = sma(volume, 3)" in code and "MAV2 = -sma(volume, 3)" in code
    assert (
        "enterLong = crossover(nv, MAV2)" in code
        and "enterShort = crossunder(nv, MAV1)" in code
    )
    assert all(
        re.search(rf"(?m)^{prefix}\s*=\s*input\(defval = {value},", code)
        for prefix, value in (
            ("FromYear", 2018),
            ("FromMonth", 1),
            ("FromDay", 1),
            ("ToYear", 9999),
            ("ToMonth", 1),
            ("ToDay", 1),
        )
    )
    assert (
        'strategy.entry(id="Long Entry", long=true, when=enterLong and window())'
        in code
    )
    assert (
        'strategy.entry(id="Short Entry", long=false, when=enterShort and window())'
        in code
    )
    return """//@version=5
strategy(title="@DankCoins - Customized Net Volume")
delta=ta.change(close)
nv=delta>0?volume:delta<0?-volume:0*volume
volAvg=ta.sma(volume,3)
n=math.round(nv,9)
positive=math.round(volAvg,9)
negative=-positive
inWindow=time>=timestamp(2018,1,1,0,0) and time<=timestamp(9999,1,1,23,59)
buy=n>negative and n[1]<negative[1] and inWindow
sell=n<positive and n[1]>positive[1] and inWindow
strategy.entry("Long Entry",strategy.long,when=buy)
strategy.entry("Short Entry",strategy.short,when=sell)
plot(nv,"A")
plot(volAvg,"B")
plot(buy?1:0,"Buy")
plot(sell?1:0,"Sell")
"""


def fractal_variant(code):
    assert (
        "cash_amout = 10000" in code
        and "pyramid_val = 1" in code
        and "cash_given_per_lot = cash_amout/pyramid_val" in code
    )
    assert (
        "filterBW = input(true," in code
        and "filterFractals = input(true," in code
        and "length = input(2," in code
    )
    assert (
        "ftop = filterBW ? regulartopfractal" in code
        and "fbot = filterBW ? regularbotfractal" in code
    )
    assert (
        "filteredtopf = filterFractals ? topf : ftop" in code
        and "filteredbotf = filterFractals ? botf : fbot" in code
    )
    for group in ("up", "down"):
        assert re.search(
            rf"(?ms)^fractal{group}_save = array.new_float\(0\)\nfor i = 0 to 4000\n    if array.size\(fractal{group}_save\) < 3\n        if array.size\(fractal{group}_save\) == 0\n            array.push\(fractal{group}_save, fractal{group}\[i\]\)",
            code,
        )
    assert (
        "Bottom_1 = array.get(fractaldown_save,  0)" in code
        and "Top_1 = array.get(fractalup_save, 0)" in code
    )
    in_scope = []
    names = (
        "regulartopfractal",
        "regularbotfractal",
        "fractalup",
        "fractaldown",
        "up",
        "down",
    )
    for name in names:
        (line,) = re.findall(rf"(?m)^{name}\s*=[^\n]+", code)
        in_scope.append(line.rstrip())
    saved = []
    for name in ("fractalup", "fractaldown"):
        (line,) = re.findall(rf"(?m)^{name}\s*:=[^\n]+", code)
        saved.append(line.rstrip())
    assert 'vamp = input(title="VolumeMA",  defval=2)' in code
    prelude = (
        "//@version=5",
        'strategy("TradingGroundhog - Strategy & Fractal V1 - Short term", overlay=true, commission_type=strategy.commission.percent, commission_value=0.00, default_qty_type=strategy.cash, default_qty_value=10000, pyramiding=1)',
        "vam=ta.sma(volume,2)",
        "topLimit=ta.highest(high,2)",
        "bottomLimit=ta.lowest(low,2)",
        *in_scope,
        *saved,
        "filteredtopf = regulartopfractal and high[2]>=topLimit",
        "filteredbotf = regularbotfractal and low[2]<=bottomLimit",
        "Top_1=fractalup",
        "Bottom_1=fractaldown",
    )
    assert "defval=0.01) * 0.01" in code
    assert all(
        f"{name} = input(title=" in code
        for name in ("startDate", "startMonth", "startYear")
    )
    (signal,) = re.findall(r"(?ms)^bool Signal_Test = false.+?(?=^//-)", code)
    signal = re.sub(
        r"(?m)^longLossPerc = [^\n]+", "longLossPerc = 0.0001", signal
    ).strip()
    authored = 'strategy.entry(id="Long", long=true, when = Signal_Test and afterStartDate)\nstrategy.close_all(when = Signal_Test_OUT_TEMP and afterStartDate)'
    assert (
        authored in code
        and "defval=2021" in code
        and "defval=9)" in code
        and "defval=13)" in code
    )
    return "\n".join(
        (
            *prelude,
            signal,
            "afterStartDate=time>=timestamp(2021,9,13,0,0)",
            authored.replace("long=true", "direction=strategy.long"),
            'plot(Top_1,"A")',
            'plot(Bottom_1,"B")',
            'plot(Signal_Test and afterStartDate?1:0,"Buy")',
            'plot(Signal_Test_OUT_TEMP and afterStartDate?1:0,"Sell")',
            "",
        )
    )


def fractal(bars):
    top, bottom, buy, sell = [], [], [], []
    top_now = bottom_now = None
    for i, bar in enumerate(bars):
        open_price = bar[1]
        valid_top = valid_bottom = False
        if i >= 4:
            h0, h1, h2, h3, h4 = [r[2] for r in bars[i - 4 : i + 1]]
            l0, l1, l2, l3, l4 = [r[3] for r in bars[i - 4 : i + 1]]
            valid_top = h0 < h1 < h2 > h3 > h4 and h2 >= max(h3, h4)
            valid_bottom = l0 > l1 > l2 < l3 < l4 and l2 <= min(l3, l4)
        if i >= 5:
            h0, h1, h2, h3, h4 = [r[2] for r in bars[i - 5 : i]]
            l0, l1, l2, l3, l4 = [r[3] for r in bars[i - 5 : i]]
            if bars[i - 3][5] > (bars[i - 3][5] + bars[i - 4][5]) / 2:
                if h2 > h1 > h0 and h2 > h3 > h4:
                    top_now = h2
                if l2 < l1 < l0 and l2 < l3 < l4:
                    bottom_now = l2
        top.append(top_now)
        bottom.append(bottom_now)
        buy.append(
            int(
                valid_bottom
                and bottom_now is not None
                and open_price < bottom_now
                and (bottom_now - open_price) / bottom_now >= 0.0001
            )
        )
        sell.append(int(valid_top and top_now is not None and open_price > top_now))
    return top, bottom, buy, sell


def rsi_chart(bars):
    values = [b[4] for b in bars]
    basis = exponential(values, 162)
    oscillator = rsi(values, 14)
    buy = []
    sell = []
    for price, base, level in zip(values, basis, oscillator, strict=True):
        buy.append(int(level is not None and level < 35 and price > base))
        sell.append(int(level is not None and level > 35 and price < base))
    return basis, oscillator, buy, sell


def net_volume(bars):
    flow = [0]
    for a, b in pairwise(bars):
        flow.append(b[5] if b[4] > a[4] else -b[5] if b[4] < a[4] else 0)
    average = [None] * 2 + [
        fsum(r[5] for r in bars[i - 2 : i + 1]) / 3 for i in range(2, len(bars))
    ]
    buy = [0] * 3
    sell = [0] * 3
    for i in range(3, len(bars)):
        prior, current = [round(v, 9) for v in (flow[i - 1], flow[i])]
        old, new = [round(v, 9) for v in (average[i - 1], average[i])]
        buy.append(int(prior < -old and current > -new))
        sell.append(int(prior > old and current < new))
    return flow, average, buy, sell


def verify(ident, case, payload):
    bars = payload["chart"]
    check = {3027: fractal, 5454: rsi_chart, 5591: net_volume}[ident]
    inputs = check(bars)
    assert not case["requested"]
    for wn, (expected, runtime) in enumerate(
        zip(inputs, case["witnesses"], strict=True)
    ):
        for i, (a, b) in enumerate(zip(expected, runtime, strict=True)):
            assert (
                a is None
                and b is None
                or a is not None
                and b is not None
                and isclose(a, b, rel_tol=1e-10, abs_tol=1e-8)
            ), (wn, i, a, b)
    pos = 0
    entrance = None
    closed = []
    for i, (buy, sell) in enumerate(
        zip(inputs[2][:-1], inputs[3][:-1], strict=True), 1
    ):
        for enabled, side in ((buy, 1), (sell, 0 if ident == 3027 else -1)):
            if not enabled or side == pos:
                continue
            if pos:
                closed.append((entrance, pos, i))
            pos = side
            entrance = i if side else None
    assert len(case["closed"]) == len(closed), (len(case["closed"]), len(closed))
    assert case["unsettled"] == int(bool(pos))
    rate = FEE_PER_SIDE[ident]
    result = []
    for trade, (i, side, j) in zip(case["closed"], closed, strict=True):
        assert (trade["entryBar"], trade["dir"], trade["exitBar"]) == (i, side, j)
        inp, out = bars[i][1], bars[j][1]
        assert (trade["entryPrice"], trade["exitPrice"]) == (inp, out)
        assert (trade["entryTime"], trade["exitTime"]) == (bars[i][0], bars[j][0])
        assert bars[i][5] > 0 and bars[j][5] > 0
        q = 1 if ident == 5454 else floor(ORDER_CASH[ident] / inp / LOT_STEP) * LOT_STEP
        assert isclose(trade["qty"], q, rel_tol=1e-10)
        turnover = (inp + out) * q
        fees = turnover * rate
        gross = (out - inp) * q * side
        assert isclose(trade["commission"], fees, rel_tol=1e-10, abs_tol=1e-9)
        assert isclose(trade["profit"], gross - fees, rel_tol=1e-10, abs_tol=1e-9)
        result.append((bars[j][0], gross, fees, turnover * EXECUTION))
    return result


SPECS = {
    3027: (
        "1h",
        "15m",
        60,
        "2023-11-03",
        "2023-12-03 00:00:00",
        "FMZ Pine · Native 1h · Verified fractal market orders",
    ),
    5454: (
        "1m",
        "1m",
        1,
        "2023-10-09",
        "2023-10-16 00:00:00",
        "FMZ Pine · Native 1m · Legacy EMA and RSI market reversals",
    ),
    5591: (
        "1m",
        "1m",
        1,
        "2023-11-14",
        "2023-11-15 03:00:00",
        "FMZ Pine · Native 1m · Legacy net-volume market reversals",
    ),
}


def archived_sources(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    rows = {
        row["id"]: row for row in read(baseline)["disposition"] if row["id"] in SPECS
    }
    assert rows.keys() == SPECS.keys()
    assert all(
        "pending" in row["status"].lower() and row["selected_report"] is None
        for row in rows.values()
    )
    _, originals = archival_items(archive, rows)
    cases = {}
    with ZipFile(archive) as source:
        for ident, row, document, observed in documents(source, rows):
            text, digest, interval = originals[ident]
            frame, base, _, first, last, _ = SPECS[ident]
            assert digest == observed and interval == frame
            fields = dict(
                re.findall(
                    r"(?m)^(start|end|period|basePeriod|exchanges):\s*([^\r\n]+)",
                    document,
                )
            )
            assert fields == {
                "start": f"{first} 00:00:00",
                "end": last,
                "period": frame,
                "basePeriod": base,
                "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
            }
            original, _ = strip_fmz_wrapper(text)
            normalized = original.replace("\r\n", "\n")
            active = re.sub(r"(?m)//[^\n]*", "", normalized)
            calls = re.findall(
                r"\bstrategy\.(entry|close_all|close|exit|order)\(", active
            )
            if ident == 3027:
                assert calls == ["entry", "close_all"]
                variant = fractal_variant(normalized)
            else:
                assert sorted(calls) == ["entry", "entry", "exit", "exit"]
                variant = legacy_variant(normalized, ident)
            cases[ident] = row, digest, fields, original.encode(), variant.encode()
    return cases


def periods(ident):
    _, _, _, first, last, _ = SPECS[ident]
    begin, end = map(date_ms, (first, last))
    return (
        ("FMZ native window", begin, end),
        ("Next equal window", end, 2 * end - begin),
    )


def verified_daily_archives(public, symbol, first_day, number_of_days, manifest):
    day = date.fromisoformat(first_day)
    files = []
    for offset in range(number_of_days):
        key = (day + timedelta(days=offset)).isoformat()
        path = public / f"{symbol}-1m-{key}.zip"
        digest = sha256(path)
        assert digest == path.with_suffix(".zip.CHECKSUM").read_text().split()[0]
        manifest.append(
            {
                "url": f"https://data.binance.vision/data/futures/um/daily/klines/{symbol}/1m/{path.name}",
                "sha256": digest,
            }
        )
        files.append(path)
    return files


def provider_cases(public, hourly):
    manifest, feeds = [], {}
    for ident, (interval, _, minutes, first, _, _) in SPECS.items():
        windows = periods(ident)
        width = minutes * MINUTE
        for market in MARKETS:
            files = (
                verified_archives(
                    hourly,
                    market,
                    interval,
                    ("2023-11", "2023-12", "2024-01"),
                    manifest,
                )
                if ident == 3027
                else verified_daily_archives(
                    public,
                    market,
                    first,
                    (windows[-1][2] - windows[0][1] + DAY - 1) // DAY,
                    manifest,
                )
            )
            source = list(
                chain.from_iterable(provider_bars(file, width) for file in files)
            )
            for label, begin, end in windows:
                chart = aligned(source, begin, end, minutes, minutes)
                assert chart[0][0] == begin and chart[-1][0] + width == end
                feeds.setdefault(str(ident), {}).setdefault(label, {})[market] = {
                    "chart": chart,
                    "frame": str(minutes),
                }
    return manifest, feeds


def stage(archive, baseline, public, hourly, runtime, work):
    sources = archived_sources(archive, baseline)
    _, feeds = provider_cases(public, hourly)
    work.mkdir(parents=True, exist_ok=True)
    if runtime.resolve() != work.resolve():
        for name in (
            "node.exe",
            f"piner-{PINER_VERSION}.tgz",
            "probe.cjs",
            "sandbox.ps1",
        ):
            copy2(runtime / name, work / name)
        copytree(runtime / "package", work / "package", dirs_exist_ok=True)
    copy2(Path(__file__).with_suffix(".mjs"), work / "three-entries-run.mjs")
    for ident, (_, _, _, source, variant) in sources.items():
        (work / f"source-{ident}.pine").write_bytes(source)
        (work / f"variant-{ident}.pine").write_bytes(variant)
    write(work / "three-entries-feeds.json", feeds)


def validated_runtime(work):
    assert (work / "three-entries-run.exit").read_text().strip() == "0"
    assert (work / "three-entries-run.mjs").read_bytes() == Path(__file__).with_suffix(
        ".mjs"
    ).read_bytes()
    isolation = read(work / "isolation-probe.json")
    assert isolation == {"privateDenied": True, "networkDenied": True}
    package = work / f"piner-{PINER_VERSION}.tgz"
    assert b64encode(sha512(package.read_bytes()).digest()).decode("ascii") == PINER_PIN
    with open_tar(package, "r:gz") as distribution:
        assert (
            distribution.extractfile("package/dist/index.js").read()
            == (work / "package/dist/index.js").read_bytes()
        )
    return isolation


def finalize(archive, baseline, public, hourly, work, output):
    sources = archived_sources(archive, baseline)
    manifests, feeds = provider_cases(public, hourly)
    assert read(work / "three-entries-feeds.json") == feeds
    isolation = validated_runtime(work)
    entries = read(work / "three-entries-receipt.json")
    receipts = {entry["id"]: entry for entry in entries}
    assert (
        len(entries) == len(receipts) == len(sources)
        and receipts.keys() == sources.keys()
    )
    rows, coverage, audits = [], [], {}
    for ident, (row, digest, metadata, original, variant) in sources.items():
        raw, rewritten = work / f"source-{ident}.pine", work / f"variant-{ident}.pine"
        assert raw.read_bytes() == original and rewritten.read_bytes() == variant
        receipt = receipts[ident]
        assert receipt["sourceHash"] == sha256(raw) and receipt[
            "variantHash"
        ] == sha256(rewritten)
        replay = {(case["period"], case["market"]): case for case in receipt["cases"]}
        assert len(replay) == len(receipt["cases"]) == 4
        group = SPECS[ident][-1]
        common = {
            "id": ident,
            "name": row["name"],
            "source": row["source"],
            "source_sha256": digest,
            "executed_source_sha256": receipt["variantHash"],
            "interval": metadata["period"],
            "archive_interval": metadata["period"],
            "quote_currency": "USDT",
            "group": group,
            "market_data": "Binance USD-M native historical candles",
            "exit": "Source close_all on next open"
            if ident == 3027
            else "Legacy source market entry reversal",
        }
        closes = 0
        for label, markets in feeds[str(ident)].items():
            pool, open_count = [], 0
            for market in markets:
                payload = markets[market]
                case = replay[(label, market)]
                cashflows = verify(ident, case, payload)
                unsettled = case["unsettled"]
                rows.append(
                    {
                        **common,
                        "period": label,
                        "market": market,
                        **summarize(cashflows, unsettled, CAPITAL),
                    }
                )
                closes += len(cashflows)
                pool.extend(cashflows)
                open_count += unsettled
            rows.append(
                {
                    **common,
                    "period": label,
                    "market": "BTCUSDT + ETHUSDT",
                    **summarize(pool, open_count, 2 * CAPITAL),
                }
            )
        assert closes > 0
        audits[ident] = {
            "archive_settings": metadata,
            "source_document_sha256": digest,
            "closed": closes,
        }
        coverage.append(
            [
                ident,
                f"Tested · {group}",
                "Archived source signals, order permissions, next-open fills, quantity and commissions verified by two Piner backends and independent calculations.",
            ]
        )
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(baseline),
            "archive_sha256": FMZ_SHA256,
            "isolation_probe": isolation,
            "published_binance_candles": manifests,
            "piner_version": PINER_VERSION,
            "piner_tarball_sha512": PINER_PIN,
            "artifacts": {
                name: sha256(work / name)
                for name in (
                    "three-entries-feeds.json",
                    "three-entries-run.mjs",
                    "three-entries-receipt.json",
                )
            },
            "cost_model": {
                "fee_per_side_by_strategy": FEE_PER_SIDE,
                "cash_per_entry_by_strategy": ORDER_CASH,
                "fixed_base_units_5454": 1,
                "execution_buffer_per_side": EXECUTION,
                "lot_step": LOT_STEP,
            },
            "references": [
                "https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/",
                "https://www.fmz.com/doc/9293",
                "https://github.com/binance/binance-public-data",
            ],
            "method": [
                "The archived TradingGroundhog source compares regular fractals and stored recent volume-qualified extrema. The orders read only slot zero of each per-bar array. Those entries are always the current value of the source's recursive fractal series. Its other array slots only support unused values and are omitted.",
                "Pre-v5 Pine did not generate orders from strategy.exit calls without a valid price or complete trailing pair. The Gold Silver and Net Volume legacy conversions omit those ineffective calls and retain the two original market-entry paths. Their results are Pine historical replays.",
                "The Gold Silver name comes from the archive title. The saved venue and instrument are Binance BTCUSDT, so the test executes one literal unit against BTC and the comparable ETH perpetual. Its saved 0.01% commission per side is retained.",
                "TradingGroundhog retains the saved 10,000 USDT cash size and zero-percent commission, and Net Volume uses the shared cash and fee model because its declaration did not specify them. All cases include a separate comparison execution-cost buffer.",
                "Both Piner backends and independent source calculations agree for all signals, order precedence, position events and cashflows. OHLC data comes from the Binance archive with verified SHA-256 sidecars. Brokerage, margin liquidation and intratrade drawdown are outside the closed-cashflow comparison.",
            ],
            "source_audits": audits,
            "coverage": coverage,
            "results": rows,
        },
    )
    print(
        f"Verified {len(audits)} strategies, {len(rows)} rows and {sum(a['closed'] for a in audits.values())} closed trades."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    shared = "archive", "baseline", "public", "hourly"
    for name, handler, arguments in (
        ("stage", stage, (*shared, "runtime", "work")),
        ("finalize", finalize, (*shared, "work", "output")),
    ):
        operation = commands.add_parser(name)
        for argument in arguments:
            operation.add_argument(argument, type=Path)
        operation.set_defaults(handler=handler)
    settings = vars(parser.parse_args())
    settings.pop("command")
    settings.pop("handler")(**settings)


if __name__ == "__main__":
    main()
