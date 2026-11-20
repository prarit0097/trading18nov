"""Verify FMZ Pine recoveries with archived local or synthetic series semantics."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from decimal import Decimal
from hashlib import sha512
from itertools import chain
from math import floor, fsum, isclose, sqrt
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
    verify_trade,
)
from research.fmz_round11_pine_playzone import exponential
from research.fmz_round12_pine_authored import aligned, provider_bars

MARKETS = ("BTCUSDT", "ETHUSDT")
CAPITAL, CASH = 10_000, 1_000
LOT_STEP = 0.001
MINUTE = 60_000


def lines(code, names):
    text = []
    for name in names:
        (line,) = re.findall(rf"(?m)^{name}\s*=[^\n]+", code)
        text.append(line.rstrip())
    return text


def exact(code, old, new):
    assert code.count(old) == 1, old
    return code.replace(old, new)


def regression_variant(code):
    assert 'input("", "Resolution", input.resolution)' in code
    assert "input(1, minval=1)" in code
    assert (
        'data(x) => sma(security(syminfo.tickerid, mtf_val!="" ? mtf_val : timeframe.period, x), smoothing)'
        in code
    )
    names = (
        "source",
        "length",
        "offset",
        "dev",
        "linreg",
        "linreg_p",
        "x",
        "slope",
        "intercept",
        "deviationSum",
    )
    pieces = lines(code, names)
    for i, which in ((4, "offset"), (5, "offset+1")):
        ending = f"data(linreg(source, length, {which}))"
        pieces[i] = exact(pieces[i], ending, f"ta.linreg(source, length, {which})")
    body = re.search(
        r"(?m)^for i=0 to length-1\n    deviationSum:= deviationSum \+ pow\(source\[i\]-\(slope\*\(x-i\)\+intercept\), 2\) +\n",
        code,
    )
    assert body
    pieces.append(body[0].rstrip().replace("pow(", "math.pow("))
    pieces.extend(lines(code, ("deviation", "y2", "dm_current", "dp_current")))
    assert "buy = crossunder(close, dm_current)" in code
    assert "sell = crossover(close, dp_current)" in code
    pieces[-4] = pieces[-4].replace("sqrt(", "math.sqrt(")
    pieces.extend(
        (
            "px = math.round(close, 9)",
            "support = math.round(dm_current, 9)",
            "resistance = math.round(dp_current, 9)",
            "buy = px < support and px[1] > support[1]",
            "sell = px > resistance and px[1] < resistance[1]",
            'if buy\n    strategy.entry("Enter Long", strategy.long)\nelse if sell\n    strategy.entry("Enter Short", strategy.short)',
            'plot(linreg, "Regression")',
            'plot(dm_current, "Lower")',
            'plot(dp_current, "Upper")',
            'plot(buy?1:sell?-1:0, "Direction")',
        )
    )
    assert pieces[-5] in code
    return "\n".join(
        (
            "//@version=5",
            'strategy("Linear Regression ++ [Lucem Anb]", overlay=true)',
            *pieces,
            "",
        )
    )


def pullback_variant(code):
    names = (
        "HiLoLen",
        "fastEMAlength",
        "mediumEMAlength",
        "Lookback",
        "UseHAcandles",
        "haClose",
        "haOpen",
        "haHigh",
        "haLow",
        "fastEMA",
        "mediumEMA",
        "pacC",
        "pacL",
        "pacU",
        "TradeDirection",
        "pacExitU",
        "pacExitL",
        "Buy",
        "Sell",
        "Long",
        "Short",
    )
    pieces = lines(code, names)
    pieces = [
        re.sub(
            r"(?<![.\w])(security|heikinashi|ema|barssince)\(",
            lambda m: (
                {"security": "request.security", "heikinashi": "ticker.heikinashi"}.get(
                    m[1], "ta." + m[1]
                )
                + "("
            ),
            line,
        )
        for line in pieces
    ]
    pieces[:4] = [line.replace("input(", "input.int(") for line in pieces[:4]]
    trend = re.search(r"(?m)^TrendDirection = [^\n]+\n   [^\n]+", code)
    start = re.search(r"(?m)^TradeDirection := nz\(TradeDirection\[1\]\)", code)
    recursion = re.search(
        r"(?m)^TradeDirection := TradeDirection ==[^\n]+\n(?:   [^\n]+\n){3}", code
    )
    assert trend and start and recursion
    pieces.insert(names.index("TradeDirection"), trend[0])
    pieces.insert(names.index("TradeDirection") + 2, start[0])
    for sign, name in (("<", "belowCount"), (">", "aboveCount")):
        index = next(
            i
            for i, line in enumerate(pieces)
            if f"ta.barssince(haClose{sign}pacC)" in line
        )
        call = f"ta.barssince(haClose{sign}pacC)"
        pieces[index] = pieces[index].replace(call, name)
        pieces.insert(index, f"{name} = {call}")
    pieces.insert(-2, recursion[0].rstrip())
    body = 'if Long\n    strategy.entry("Enter Long", strategy.long)\nelse if Short\n    strategy.entry("Enter Short", strategy.short)'
    assert body in code
    pieces.append(body)
    for var in (
        "haOpen",
        "haClose",
        "haHigh",
        "haLow",
        "pacC",
        "pacL",
        "pacU",
        "TrendDirection",
        "TradeDirection",
    ):
        pieces.append(f'plot({var}, "{var}")')
    pieces.append('plot(Long ? 1 : Short ? -1 : 0, "Direction")')
    return "\n".join(
        (
            "//@version=5",
            'strategy("Scalping PullBack Tool R1.1",overlay=true)',
            *pieces,
            "",
        )
    )


def modulo_variant(code):
    code = exact(code, "//@version=4", "//@version=5")
    code = exact(
        code,
        "// strategy(title=",
        'strategy("Random Entry Point Strategy")\n// strategy(title=',
    )
    for var in ("i", "stop_loss", "take_profit"):
        pat = rf"(?m)^{var} = input\(([^\n]+), type = input.integer\)"
        code, count = re.subn(pat, rf"{var} = input.int(\1)", code)
        assert count == 1
    code = exact(
        code, 'strategy.entry("long", true)', 'strategy.entry("long", strategy.long)'
    )
    return (
        code
        + '\nplot(random,"Modulo")\nplot(profit,"Pct")\nplot(in_deal?1:0,"State")\n'
    )


def regression(chart):
    end, lower, upper, directions = [], [], [], []
    prices = [row[4] for row in chart]
    xbar = 49.5
    centered = [i - xbar for i in range(100)]
    denominator = fsum(x * x for x in centered)
    for index, price in enumerate(prices):
        if index < 99:
            end.append(None)
            lower.append(None)
            upper.append(None)
            directions.append(0)
            continue
        window = prices[index - 99 : index + 1]
        avg = fsum(window) / 100
        slope = fsum(x * y for x, y in zip(centered, window, strict=True)) / denominator
        estimate = avg + slope * 49.5
        variance = (
            fsum(
                (y - (avg + slope * x)) ** 2
                for x, y in zip(centered, window, strict=True)
            )
            / 100
        )
        dev = 2 * sqrt(variance)
        bottom, top = estimate - dev, estimate + dev
        down = (
            index > 99
            and round(price, 9) < round(bottom, 9)
            and round(prices[index - 1], 9) > round(lower[-1], 9)
        )
        up = (
            index > 99
            and round(price, 9) > round(top, 9)
            and round(prices[index - 1], 9) < round(upper[-1], 9)
        )
        end.append(estimate)
        lower.append(bottom)
        upper.append(top)
        directions.append(1 if down else -1 if up else 0)
    return [end, lower, upper, directions], directions


def pullback(chart):
    ha_o = []
    ha_c = []
    ha_h = []
    ha_l = []
    for _, o, h, low, c, v in chart:
        ha_o.append((ha_o[-1] + ha_c[-1]) / 2 if ha_o else (o + c) / 2)
        ha_c.append(fsum((o, h, low, c)) / 4)
        ha_h.append(max(h, ha_o[-1], ha_c[-1]))
        ha_l.append(min(low, ha_o[-1], ha_c[-1]))
    pac_c, pac_l, pac_u = (exponential(values, 34) for values in (ha_c, ha_l, ha_h))
    fast, medium = (exponential(ha_c, size) for size in (89, 200))
    state, directions = [], []
    bulls, bears = None, None
    trend = []
    td = 0
    for i, (o, c, channel, low, high, f, m) in enumerate(
        zip(ha_o, ha_c, pac_c, pac_l, pac_u, fast, medium, strict=True)
    ):
        tr = 1 if f > m and low > m else -1 if f < m and high < m else 0
        if c < channel:
            bears = i
        if c > channel:
            bulls = i
        up = tr == 1 and o < high < c and bears is not None and i - bears <= 3
        down = tr == -1 and o > low > c and bulls is not None and i - bulls <= 3
        prior = td
        if (td == 1 and c < channel) or (td == -1 and c > channel):
            td = 0
        elif td == 0 and up:
            td = 1
        elif td == 0 and down:
            td = -1
        trend.append(tr)
        state.append(td)
        directions.append(td if prior == 0 else 0)
    return [
        ha_o,
        ha_c,
        ha_h,
        ha_l,
        pac_c,
        pac_l,
        pac_u,
        trend,
        state,
        directions,
    ], directions


def modulo(chart):
    remainder, pct, state, actions = [], [], [], []
    in_deal = False
    initial = 0
    profit = 0
    for _, _, _, _, close, volume in chart:
        modulus = float(Decimal(str(volume)) % 6)
        action = 0
        if not in_deal:
            profit = 0
        if modulus < 3 and not in_deal:
            in_deal = True
            initial = close
            action = 1
        if in_deal:
            profit = (close / initial - 1) * 100
        if round(profit, 9) < -5 or round(profit, 9) > 15:
            action = -1
            in_deal = False
        remainder.append(modulus)
        pct.append(profit)
        state.append(int(in_deal))
        actions.append(action)
    return [remainder, pct, state], actions


def verify(ident, case, payload):
    chart = payload["chart"]
    expected, orders = {487: regression, 922: pullback, 858: modulo}[ident](chart)
    symbol = f"BINANCE:{case['market']}.P"
    ask = case["requested"]
    assert ask == (
        [{"symbol": symbol + "_HA", "timeframe": payload["frame"], "lowerTf": False}]
        if ident == 922
        else []
    ), ask
    for wi, (witness, actual) in enumerate(
        zip(expected, case["witnesses"], strict=True)
    ):
        for i, (x, y) in enumerate(zip(witness, actual, strict=True)):
            assert (x is None and y is None) or (
                x is not None
                and y is not None
                and isclose(x, y, rel_tol=1e-10, abs_tol=1e-8)
            ), (wi, i, x, y)
    closed = []
    side = 0
    started = None
    for i, signal in enumerate(orders[:-1], 1):
        if not signal:
            continue
        if ident == 858:
            if signal == 1:
                assert not side
                side, started = 1, i
            else:
                assert side
                closed.append((started, side, i))
                side, started = 0, None
        elif signal != side:
            if side:
                closed.append((started, side, i))
            side, started = signal, i
    assert len(case["closed"]) == len(closed), (len(case["closed"]), len(closed))
    assert case["unsettled"] == int(side != 0)
    events = []
    for trade, (entry, direction, exit_bar) in zip(case["closed"], closed, strict=True):
        assert (trade["entryBar"], trade["dir"], trade["exitBar"]) == (
            entry,
            direction,
            exit_bar,
        )
        assert close(trade["entryPrice"], chart[entry][1]) and close(
            trade["exitPrice"], chart[exit_bar][1]
        )
        assert chart[entry][5] > 0 and chart[exit_bar][5] > 0
        assert close(trade["qty"], floor(1000 / chart[entry][1] / 0.001) * 0.001)
        events.append(verify_trade(trade, [row[0] for row in chart]))
    return events, case["unsettled"]


def close(x, y):
    return isclose(x, y, rel_tol=1e-10, abs_tol=1e-10)


SPECS = {
    487: {
        "date": ("2022-04-23", "2022-05-22 23:59:00"),
        "chart": (45, "45m", "5m"),
        "provider": ("5m", 5, ("2022-04", "2022-05", "2022-06")),
        "group": "FMZ Pine · Native 45m · Verified regression reversals",
        "exit": "Archived next-open market reversal",
        "convert": regression_variant,
    },
    858: {
        "date": ("2022-09-11", "2023-04-14 00:00:00"),
        "chart": (1440, "1d", "1h"),
        "provider": (
            "1d",
            1440,
            tuple(
                [f"2022-{month:02}" for month in range(9, 13)]
                + [f"2023-{month:02}" for month in range(1, 12)]
            ),
        ),
        "group": "FMZ Pine · Native daily · Deterministic volume entry",
        "exit": "Source price-change gate and next-open market close",
        "convert": modulo_variant,
    },
    922: {
        "date": ("2022-05-12", "2022-05-18 23:59:00"),
        "chart": (3, "3m", "1m"),
        "provider": ("3m", 3, ("2022-05",)),
        "group": "FMZ Pine · Native 3m · Verified Heikin-Ashi pullback",
        "exit": "Archived next-open market reversal",
        "convert": pullback_variant,
    },
}


def archive_cases(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    pending = {
        row["id"]: row for row in read(baseline)["disposition"] if row["id"] in SPECS
    }
    assert pending.keys() == SPECS.keys()
    assert all(row["status"].startswith("Pending") for row in pending.values())
    _, originals = archival_items(archive, pending)
    cases = {}
    with ZipFile(archive) as source:
        for ident, row, document, observed in documents(source, pending):
            text, digest, interval = originals[ident]
            spec = SPECS[ident]
            _, frame, base = spec["chart"]
            start, stop = spec["date"]
            fields = dict(
                re.findall(
                    r"(?m)^(start|end|period|basePeriod|exchanges):\s*([^\r\n]+)",
                    document,
                )
            )
            assert digest == observed and interval == frame
            assert fields == {
                "start": f"{start} 00:00:00",
                "end": stop,
                "period": frame,
                "basePeriod": base,
                "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
            }
            original, _ = strip_fmz_wrapper(text)
            code = original.replace("\r\n", "\n")
            active = re.sub(r"(?m)//[^\n]*", "", code)
            calls = re.findall(r"\bstrategy\.(entry|close|exit|order)\(", active)
            assert calls == (["entry", "close"] if ident == 858 else ["entry", "entry"])
            if ident == 922:
                assert (
                    'UseHAcandles    = input(true, title="Use Heikin Ashi Candles in Algo Calculations")'
                    in code
                )
            variant = spec["convert"](code).encode("utf-8")
            cases[ident] = row, digest, fields, original.encode("utf-8"), variant
    return cases


def provider_cases(public, five_minute):
    manifest, feeds, windows = [], {}, {}
    for ident, spec in SPECS.items():
        interval, resolution, months = spec["provider"]
        frame = spec["chart"][0]
        first, last = map(date_ms, spec["date"])
        width = frame * MINUTE
        last = last // width * width
        periods = (
            ("FMZ native complete bars", first, last),
            ("Next equal window", last, 2 * last - first),
        )
        root = five_minute if ident == 487 else public
        for market in MARKETS:
            files = verified_archives(root, market, interval, months, manifest)
            source = list(
                chain.from_iterable(
                    provider_bars(file, resolution * MINUTE) for file in files
                )
            )
            for label, start, end in periods:
                chart = aligned(source, start, end, frame, resolution)
                assert chart[0][0] == start and chart[-1][0] + width == end
                feeds.setdefault(str(ident), {}).setdefault(label, {})[market] = {
                    "chart": chart,
                    "frame": "D" if ident == 858 else str(frame),
                }
        windows[ident] = {label: [start, end] for label, start, end in periods}
    return manifest, feeds, windows


def stage(archive, baseline, public, five_minute, runtime, work):
    cases = archive_cases(archive, baseline)
    _, feeds, _ = provider_cases(public, five_minute)
    work.mkdir(parents=True, exist_ok=True)
    for file in ("node.exe", f"piner-{PINER_VERSION}.tgz", "probe.cjs", "sandbox.ps1"):
        copy2(runtime / file, work / file)
    copytree(runtime / "package", work / "package", dirs_exist_ok=True)
    copy2(Path(__file__).with_suffix(".mjs"), work / "run.mjs")
    for ident, (_, _, _, original, variant) in cases.items():
        (work / f"source-{ident}.pine").write_bytes(original)
        (work / f"variant-{ident}.pine").write_bytes(variant)
    write(work / "feeds.json", feeds)


def verified_isolation(work):
    assert (work / "run.exit").read_text().strip() == "0"
    assert (work / "run.mjs").read_bytes() == Path(__file__).with_suffix(
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


def finalize(archive, baseline, public, five_minute, work, output):
    cases = archive_cases(archive, baseline)
    providers, feeds, windows = provider_cases(public, five_minute)
    assert read(work / "feeds.json") == feeds
    isolation = verified_isolation(work)
    receipts = read(work / "receipt.json")
    assert (
        len(receipts) == len(cases)
        and {entry["id"] for entry in receipts} == cases.keys()
    )
    rows, coverage, audits = [], [], {}
    for ident, (row, digest, metadata, original, variant) in cases.items():
        source_path, variant_path = (
            work / f"source-{ident}.pine",
            work / f"variant-{ident}.pine",
        )
        assert (
            original == source_path.read_bytes()
            and variant == variant_path.read_bytes()
        )
        receipt = next(entry for entry in receipts if entry["id"] == ident)
        assert receipt["sourceHash"] == sha256(source_path) and receipt[
            "variantHash"
        ] == sha256(variant_path)
        assert len(receipt["cases"]) == 4
        by_market = {(e["period"], e["market"]): e for e in receipt["cases"]}
        assert len(by_market) == len(receipt["cases"])
        spec = SPECS[ident]
        common = {
            "id": ident,
            "name": row["name"],
            "source": row["source"],
            "source_sha256": digest,
            "executed_source_sha256": receipt["variantHash"],
            "interval": metadata["period"],
            "archive_interval": metadata["period"],
            "quote_currency": "USDT",
            "group": spec["group"],
            "market_data": "Binance USD-M historical futures candles",
            "exit": spec["exit"],
        }
        total = 0
        for label, markets in feeds[str(ident)].items():
            combined, trailing = [], 0
            for market, payload in markets.items():
                events, open_count = verify(ident, by_market[(label, market)], payload)
                rows.append(
                    {
                        **common,
                        "period": label,
                        "market": market,
                        **summarize(events, open_count, CAPITAL),
                    }
                )
                total += len(events)
                combined.extend(events)
                trailing += open_count
            rows.append(
                {
                    **common,
                    "period": label,
                    "market": "BTCUSDT + ETHUSDT",
                    **summarize(combined, trailing, 2 * CAPITAL),
                }
            )
        assert total > 0
        coverage.append(
            [
                ident,
                f"Tested · {spec['group']}",
                "Archived settings and authored orders verified with both execution backends and independent signal and fill calculations.",
            ]
        )
        audits[ident] = {
            "archive_settings": metadata,
            "source_document_sha256": digest,
            "windows_utc_ms": windows[ident],
            "closed": total,
        }
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(baseline),
            "archive_sha256": FMZ_SHA256,
            "isolation_probe": isolation,
            "published_binance_candles": providers,
            "piner_version": PINER_VERSION,
            "piner_tarball_sha512": PINER_PIN,
            "artifacts": {
                name: sha256(work / name)
                for name in ("feeds.json", "run.mjs", "receipt.json")
            },
            "cost_model": {
                "fee_per_side": FEE,
                "execution_buffer_per_side": EXECUTION,
                "lot_step": LOT_STEP,
            },
            "references": [
                "https://www.fmz.com/doc/9293",
                "https://www.fmz.com/syntax-guide/exchanges/cex/binance",
                "https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-6/",
                "https://www.tradingview.com/pine-script-docs/language/type-system/",
                "https://github.com/binance/binance-public-data",
            ],
            "method": [
                "The 45m Linear Regression source defaults to chart resolution, low-pass length one, closed price and a 100-bar least-squares fit. Native 45m bars are aggregated from checksum-verified 5m exchange candles. Its strict FMZ crosses are checked against independently fitted residual bands.",
                "The daily Random Entry source deterministically tests the published base-asset volume modulo 6. Its closing conditions use the change from the signal close, with saved -5% and +15% bounds. The older USD capital and commission declaration was commented out in the archive. Comparable results use the same USDT model and fees as the rest of the cohort.",
                "The 3m Scalping PullBack source uses same-chart Heikin-Ashi for its signal only. Native exchange candle prices supply next-open fills. Both barssince histories are evaluated on every bar as in pre-v6 Pine. The independent validation checks synthetic bars, channel averages and recursive state.",
                "Native archive and following equal windows use complete candles and independent warm-up. BTC is the saved venue and instrument, ETH is a comparable perpetual on the same venue. Order fills were independently checked against standard candles with positive volume.",
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
    inputs = "archive", "baseline", "public", "five_minute"
    for name, handler, arguments in (
        ("stage", stage, (*inputs, "runtime", "work")),
        ("finalize", finalize, (*inputs, "work", "output")),
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
