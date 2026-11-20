"""Replay source-proven Pine v2/v4 behavior on the archived Binance daily windows."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from datetime import UTC, datetime, timedelta
from hashlib import sha512
from itertools import chain, pairwise
from math import cos, floor, isclose, sqrt
from pathlib import Path
from shutil import copy2
from tarfile import open as open_tar
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round6_pine import archival_items
from research.fmz_round7_magnifier import (
    FMZ_SHA256,
    date_ms,
    raw_ohlcv,
    sha256,
    verified_archives,
)
from research.fmz_round7_pine import (
    EXECUTION,
    FEE,
    PINER_PIN,
    PINER_VERSION,
    copy_runtime,
    strip_fmz_wrapper,
    summarize,
    verify_trade,
)

MARKETS = ("BTCUSDT", "ETHUSDT")
DAY = 86_400_000
CAPITAL = 10_000
CASH = 1000
LOT_STEP = 0.001
WINDOWS = {
    2609: ("2023-01-05", "2024-01-11", "2025-01-16", "Next equal daily"),
    5274: ("2024-01-29", "2024-02-28", "2024-06-27", "Next 120 daily"),
    5704: ("2023-01-15", "2024-01-21", "2025-01-26", "Next equal daily"),
}
REPAIRS = {
    2609: {
        "Pine v4 trailing exits with no activation removed": 2,
        "Default ATR and numeric namespaces retained": 1,
    },
    5274: {
        "Pine v4 exits with no price or trail parameters removed": 2,
        "Eager active breakout histories retained": 1,
    },
    5704: {
        "Explicit float declarations preserve v2 positive history reads and nz warmup": 3
    },
}


def replace_once(code, old, new):
    assert code.count(old) == 1
    return code.replace(old, new)


def gauss_variant(source):
    source = replace_once(source, "//@version=2", "//@version=5")
    source = replace_once(source, "input(20, minval=1", "input.int(20, minval=1")
    source = replace_once(source, "input(open,", "input.source(open,")
    bindings = list(re.finditer(r"(?m)^(ret(?:2|3)?)[ \t]*=([^\n]+)", source))
    assert [item[1] for item in bindings] == ["ret", "ret2", "ret3"]
    for item in bindings:
        assert re.findall(rf"\bnz\({item[1]}\[(\d+)\]\)", item[2]) == [
            "1",
            "2",
            "3",
            "4",
        ]
    source = re.sub(
        r"(?m)^(ret(?:2|3)?)[ \t]*=([^\n]+)", r"var float \1 = na\n\1 :=\2", source
    )
    source = re.sub(r"(?<![\w.])(cos|pow|sqrt)\(", r"math.\1(", source)
    return (
        source
        + '\nplot(ret,"Ret1 proof")\nplot(ret2,"Ret2 proof")\nplot(ret3,"Ret3 proof")\nplot(ret4,"Ret4 proof")\n'
    )


def atr_variant(source):
    changes = (
        ("//@version=4", "//@version=5"),
        (
            'input(title="ATR Period", type=input.integer, defval=10)',
            'input.int(title="ATR Period", defval=10)',
        ),
        ('input(hl2, title="Source")', 'input.source(hl2, title="Source")'),
        (
            'input(title="ATR Multiplier", type=input.float, step=0.1, defval=3.0)',
            'input.float(title="ATR Multiplier", step=0.1, defval=3.0)',
        ),
        (
            'input(title="Change ATR Calculation Method ?", type=input.bool, defval=true)',
            'input.bool(title="Change ATR Calculation Method ?", defval=true)',
        ),
        ("sma(tr, Periods)", "ta.sma(ta.tr, Periods)"),
        (
            "atr = changeATR ? atr(Periods) : atr2",
            "defaultATR = ta.atr(Periods)\natr = changeATR ? defaultATR : atr2",
        ),
        ("? max(up, up1)", "? math.max(up, up1)"),
        ("? min(dn, dn1)", "? math.min(dn, dn1)"),
    )
    for old, new in changes:
        source = replace_once(source, old, new)
    source, exits = re.subn(
        r'(?m)^strategy\.exit\("Trailing Stop (?:Long|Short)", "(?:Long|Short)", trail_offset=\w+\)\s*$',
        "",
        source,
    )
    assert exits == 2
    return (
        source
        + '\nplot(atr,"ATR proof")\nplot(up,"Up proof")\nplot(dn,"Dn proof")\nplot(trend,"Trend proof")\n'
    )


def turtle_variant(source):
    source = replace_once(source, "//@version=4", "//@version=5")
    source, inputs = re.subn(r"(?m)(length = |len2=)input\(", r"\1input.int(", source)
    assert inputs == 2
    source, graph = re.subn(
        r"(?m)^(?:K[1-4]=[^\n]+|(?:e=)?plot\(K[12][^\n]+)\n", "", source
    )
    assert graph == 6
    source, exits = re.subn(
        r'(?m)^strategy\.exit\("(?:Buy|Sell) Exit", from_entry = "(?:Buy|Sell)", when = [^,\n]+\([^\n]*\)\)\s*$',
        "",
        source,
    )
    assert exits == 2
    source, obsolete = re.subn(r"(?m)^(?:buyExit|sellExit)\s*=[^\n]+\n", "", source)
    assert obsolete == 2
    source = re.sub(
        r"(?<![\w.])(lowest|highest|crossover|barssince)\(", r"ta.\1(", source
    )
    for side, name, other, direction in (
        ("Buy", "buy", "sell", "long"),
        ("Sell", "sell", "buy", "short"),
    ):
        old = f'strategy.entry("{side}", strategy.{direction}, when = {name}Signal and ta.barssince({name}Signal) < ta.barssince({other}Signal[1]))'
        target = f"enter{direction.title()}"
        new = (
            f"{name}Now = ta.barssince({name}Signal)\n{other}Before = ta.barssince({other}Signal[1])\n"
            f"{target} = {name}Signal and {name}Now < {other}Before\n"
            f'strategy.entry("{side}", strategy.{direction}, when = {target})'
        )
        source = replace_once(source, old, new)
    source = replace_once(
        source,
        "buySignal=high==upper[1] or ta.crossover(high,upper[1])",
        "breakAbove = ta.crossover(high, upper[1])\nbuySignal = high == upper[1] or breakAbove",
    )
    source = replace_once(
        source,
        "sellSignal = low==lower[1] or ta.crossover(lower[1],low)",
        "breakBelow = ta.crossover(lower[1], low)\nsellSignal = low == lower[1] or breakBelow",
    )
    return (
        source
        + '\nplot(upper,"Upper proof")\nplot(lower,"Lower proof")\nplot(enterLong ? 1 : 0,"Long proof")\nplot(enterShort ? 1 : 0,"Short proof")\n'
    )


def archived_inputs(archive, ledger):
    assert sha256(archive) == FMZ_SHA256
    rows = {
        row["id"]: row for row in read(ledger)["disposition"] if row["id"] in WINDOWS
    }
    assert rows.keys() == WINDOWS.keys() and all(
        row["status"].startswith("Pending") for row in rows.values()
    )
    _, originals = archival_items(archive, rows)
    variants = {2609: atr_variant, 5274: turtle_variant, 5704: gauss_variant}
    output = {}
    with ZipFile(archive) as source:
        for ident, row, document, verified_digest in documents(source, rows):
            script, digest, interval = originals[ident]
            assert digest == verified_digest and interval == "1d"
            begin, end, _, _ = WINDOWS[ident]
            fields = dict(
                re.findall(
                    r"(?m)^(start|end|period|basePeriod|exchanges):\s*([^\r\n]+)",
                    document,
                )
            )
            assert fields == {
                "start": f"{begin} 00:00:00",
                "end": f"{end} 00:00:00",
                "period": "1d",
                "basePeriod": "1h",
                "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
            }
            original, _ = strip_fmz_wrapper(script)
            variant = variants[ident](original.replace("\r\n", "\n"))
            output[ident] = (
                row,
                fields,
                digest,
                original.encode("utf-8"),
                variant.encode("utf-8"),
            )
    return output


def provider_data(public):
    manifest, feeds = [], {}
    for ident, (first, split, last, followup) in WINDOWS.items():
        last_month = (
            datetime.fromisoformat(last).replace(tzinfo=UTC) - timedelta(days=1)
        ).strftime("%Y-%m")
        months = [
            f"{year}-{month:02}"
            for year in range(2023, 2026)
            for month in range(1, 13)
            if first[:7] <= f"{year}-{month:02}" <= last_month
        ]
        for symbol in MARKETS:
            files = verified_archives(public, symbol, "1d", months, manifest)
            records = list(chain.from_iterable(raw_ohlcv(file, DAY) for file in files))
            for label, start, end in (
                ("FMZ archived daily", first, split),
                (followup, split, last),
            ):
                first_ms, last_ms = date_ms(start), date_ms(end)
                bars = [list(row) for row in records if first_ms <= row[0] < last_ms]
                assert [bar[0] for bar in bars] == list(range(first_ms, last_ms, DAY))
                feeds.setdefault(str(ident), {}).setdefault(label, {})[symbol] = bars
    unique = {row["name"]: row for row in manifest}
    assert all(row == unique[row["name"]] for row in manifest)
    return list(unique.values()), feeds


def stage(archive, ledger, public, runtime, work):
    inputs = archived_inputs(archive, ledger)
    _, feeds = provider_data(public)
    work.mkdir(parents=True, exist_ok=True)
    copy_runtime(runtime, work)
    copy2(Path(__file__).with_suffix(".mjs"), work / "run.mjs")
    for ident, (_, _, _, original, variant) in inputs.items():
        (work / f"source-{ident}.pine").write_bytes(original)
        (work / f"variant-{ident}.pine").write_bytes(variant)
    write(work / "feeds.json", feeds)


def gauss_reference(bars):
    omega = 2 * 3.1415926535 / 20
    beta = (1 - cos(omega)) / (1.414 ** (2.0 / 3) - 1)
    alpha = -beta + sqrt(beta * beta + 2 * beta)
    damping = 1 - alpha
    coefficients = 4 * damping, -6 * damping**2, 4 * damping**3, -(damping**4)
    history = [[], [], []]
    trace, signals = [], []
    for bar in bars:
        price = bar[1]
        for series in history:
            price = alpha**4 * price + sum(
                weight * series[-lag]
                for lag, weight in enumerate(coefficients, 1)
                if len(series) >= lag
            )
            series.append(price)
        if trace:
            diff = bar[1] - trace[-1]
            assert diff != 0
            signals.append([1 if diff > 0 else -1])
        else:
            signals.append([])
        trace.append(3 * history[0][-1] - 3 * history[1][-1] + history[2][-1])
    return history + [trace], signals


def atr_reference(bars):
    true_ranges = []
    for i, (_, _, high, low, _, _) in enumerate(bars):
        base = high - low
        if i:
            previous = bars[i - 1][4]
            base = max(base, abs(high - previous), abs(low - previous))
        true_ranges.append(base)
    state = sum(true_ranges[:10]) / 10
    averages = [None] * 9 + [state]
    for value in true_ranges[10:]:
        state = (state * 9 + value) / 10
        averages.append(state)
    ups, downs, trends, signals = [], [], [], []
    for i, (bar, value) in enumerate(zip(bars, averages, strict=True)):
        baseline = trends[-1] if trends else 1
        up = down = None
        trend = baseline
        if value is not None:
            middle = (bar[2] + bar[3]) / 2
            up, down = middle - 3 * value, middle + 3 * value
            prior_up = ups[-1] if ups[-1] is not None else up
            prior_down = downs[-1] if downs[-1] is not None else down
            if bars[i - 1][4] > prior_up:
                up = max(up, prior_up)
            if bars[i - 1][4] < prior_down:
                down = min(down, prior_down)
            if baseline == -1 and bar[4] > prior_down:
                trend = 1
            if baseline == 1 and bar[4] < prior_up:
                trend = -1
        ups.append(up)
        downs.append(down)
        trends.append(trend)
        signals.append([trend] if trend != baseline else [])
    return [averages, ups, downs, trends], signals


def turtle_reference(bars):
    highs = [bar[2] for bar in bars]
    lows = [bar[3] for bar in bars]
    upper = [None] * 19 + [max(highs[i - 19 : i + 1]) for i in range(19, len(bars))]
    lower = [None] * 19 + [min(lows[i - 19 : i + 1]) for i in range(19, len(bars))]
    long_entry = [0] * len(bars)
    short_entry = [0] * len(bars)
    last_high = last_low = None
    for i in range(20, len(bars)):
        high_break = highs[i] == upper[i - 1] or (
            i > 20 and highs[i] > upper[i - 1] and highs[i - 1] <= upper[i - 2]
        )
        low_break = lows[i] == lower[i - 1] or (
            i > 20 and lows[i] < lower[i - 1] and lows[i - 1] >= lower[i - 2]
        )
        long_entry[i] = int(high_break and last_low is not None and (i - last_low) > 1)
        short_entry[i] = int(
            low_break and last_high is not None and (i - last_high) > 1
        )
        if high_break:
            last_high = i
        if low_break:
            last_low = i
    signals = [
        [direction for direction, active in ((1, buy), (-1, sell)) if active]
        for buy, sell in zip(long_entry, short_entry, strict=True)
    ]
    return [upper, lower, long_entry, short_entry], signals


def verify_case(ident, case, bars):
    reference = {2609: atr_reference, 5274: turtle_reference, 5704: gauss_reference}[
        ident
    ]
    witnesses, signals = reference(bars)
    for expected, actual in zip(witnesses, case["witnesses"], strict=True):
        for x, y in zip(expected, actual, strict=True):
            assert (
                x is None
                and y is None
                or x is not None
                and y is not None
                and isclose(x, y, rel_tol=1e-11, abs_tol=1e-10)
            )
    reversals = []
    current = 0
    for i, directions in enumerate(signals[:-1]):
        for side in directions:
            if side != current:
                reversals.append((i + 1, side))
                current = side
    assert case["unsettled"] == int(bool(reversals))
    assert len(case["closed"]) == max(0, len(reversals) - 1)
    times = [bar[0] for bar in bars]
    equity = CAPITAL
    settlements = []
    for trade, ((entry, side), (exit_bar, _)) in zip(
        case["closed"], pairwise(reversals), strict=True
    ):
        assert [trade[key] for key in ("entryBar", "dir", "exitBar")] == [
            entry,
            side,
            exit_bar,
        ]
        assert (
            trade["entryPrice"] == bars[entry][1]
            and trade["exitPrice"] == bars[exit_bar][1]
        )
        flow = verify_trade(trade, times)
        cash = equity if ident == 5274 else CASH
        assert isclose(
            trade["qty"],
            floor(cash / trade["entryPrice"] / LOT_STEP) * LOT_STEP,
            rel_tol=1e-10,
        )
        equity += flow[1] - flow[2]
        settlements.append(flow)
    return settlements


def finalize(archive, ledger, public, work, output):
    inputs = archived_inputs(archive, ledger)
    manifest, feeds = provider_data(public)
    assert feeds == read(work / "feeds.json")
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
    receipts = read(work / "receipt.json")
    reported = {row["id"]: row for row in receipts}
    assert (
        len(reported) == len(receipts) == len(inputs)
        and reported.keys() == inputs.keys()
    )
    coverage, results, findings = [], [], {}
    for ident, (row, fields, checksum, original, variant) in inputs.items():
        source = work / f"source-{ident}.pine"
        executed = work / f"variant-{ident}.pine"
        assert source.read_bytes() == original and executed.read_bytes() == variant
        receipt = reported[ident]
        assert receipt["diagnostics"] == []
        assert receipt["sourceHash"] == sha256(source) and receipt[
            "variantHash"
        ] == sha256(executed)
        cases = {(case["period"], case["market"]): case for case in receipt["cases"]}
        assert len(cases) == len(receipt["cases"]) == 4
        group = "FMZ Pine · Native daily · Verified legacy behavior"
        common = {
            "id": ident,
            "name": row["name"],
            "source": row["source"],
            "source_sha256": checksum,
            "executed_source_sha256": receipt["variantHash"],
            "interval": "1d",
            "archive_interval": "1d",
            "quote_currency": "USDT",
            "group": group,
            "exit": "Archived next-open market reversal",
            "market_data": "Binance USD-M historical daily futures candles",
            "repairs": REPAIRS[ident],
        }
        closes = 0
        for period, markets in feeds[str(ident)].items():
            pool, remaining = [], 0
            for market, bars in markets.items():
                case = cases[(period, market)]
                settled = verify_case(ident, case, bars)
                unsettled = case["unsettled"]
                results.append(
                    {
                        **common,
                        "period": period,
                        "market": market,
                        **summarize(settled, unsettled, CAPITAL),
                    }
                )
                pool.extend(settled)
                remaining += unsettled
                closes += len(settled)
            results.append(
                {
                    **common,
                    "period": period,
                    "market": "BTCUSDT + ETHUSDT",
                    **summarize(pool, remaining, 2 * CAPITAL),
                }
            )
        findings[ident] = {
            "original_document_sha256": checksum,
            "original_archive_settings": fields,
            "closed": closes,
        }
        coverage.append(
            [
                ident,
                f"Tested · {group}",
                "Independent replay verified the archived signal state and every historical fill and fee.",
            ]
        )
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(ledger),
            "archive_sha256": FMZ_SHA256,
            "isolation_probe": isolation,
            "published_binance_candles": manifest,
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
                "https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-3/#self-referenced-variables-are-removed",
                "https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/#strategy-exit-now-must-do-something",
            ],
            "method": "Each archived BTCUSDT period and native Binance daily resolution are preserved, alongside comparative ETHUSDT and a subsequent time window. The Turtle follow-up was lengthened to 120 days after the equal-length 30-day case produced no signals. Both Piner backends and independent state, trade, quantity and commission calculations agree.",
            "source_audits": findings,
            "coverage": coverage,
            "results": results,
        },
    )
    print(
        f"Verified {len(inputs)} legacy strategies and {len(results)} rows, {sum(row['closed'] for row in findings.values())} closed trades."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, handler, arguments in (
        ("stage", stage, ("archive", "ledger", "public", "runtime", "work")),
        ("finalize", finalize, ("archive", "ledger", "public", "work", "output")),
    ):
        command = commands.add_parser(name)
        for arg in arguments:
            command.add_argument(arg, type=Path)
        command.set_defaults(handler=handler)
    options = vars(parser.parse_args())
    options.pop("command")
    options.pop("handler")(**options)


if __name__ == "__main__":
    main()
