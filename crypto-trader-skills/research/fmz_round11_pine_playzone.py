"""Replay Playzone on its native daily chart with an independent signal ledger."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from hashlib import sha512
from itertools import chain, pairwise
from math import floor, fsum, isclose
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
from research.fmz_round10_pine_chart import ema
from research.fmz_round10_pine_legacy import replace_once

IDENT = 1884
DAY = 86_400_000
LOT_STEP = 0.001
CAPITAL, CASH = 10_000, 1_000
MARGIN = (4, 2)
MARKETS = ("BTCUSDT", "ETHUSDT")
WINDOWS = (
    ("FMZ native daily", "2023-01-01", "2023-10-25"),
    ("Next equal daily", "2023-10-25", "2024-08-17"),
)
GROUP = "FMZ Pine · Native daily · Verified Playzone signals"


def typed_input(line):
    match = re.search(r"type=input\.(integer|bool|float|source|resolution)", line)
    if not match:
        return line
    kind = {"integer": "int", "resolution": "timeframe"}.get(match[1], match[1])
    line, edits = re.subn(r",\s*type=input\.\w+(?=\s*[,)])", "", line)
    assert edits == 1
    return line.replace("input(", f"input.{kind}(", 1)


def daily_variant(code):
    assert re.search(
        r'(?m)^tffix = input\(title="Fixed Timeframe",type=input.bool,defval=true\)$',
        code,
    )
    assert re.search(
        r'(?m)^tfn = input\(title="Timeframe in",type=input.resolution,defval="D"\)$',
        code,
    )
    code = replace_once(code, "//@version=4", "//@version=5")
    for name, period in (("efast", "ema1"), ("eslow", "ema2")):
        pattern = rf"(?m)^{name} = tffix \?  ema\(security\(syminfo.tickerid,tfn,ema\(srcf,{period}\), gaps = barmerge.gaps_off,lookahead = barmerge.lookahead_on\),smooter\) :ema\(xcross,{period}\)$"
        code, count = re.subn(
            pattern, f"{name} = ema(ema(srcf,{period}),smooter)", code
        )
        assert count == 1
    code = "\n".join(typed_input(line) for line in code.splitlines())
    code = replace_once(code, "G1[1]==0", "not G1[1]")
    code = replace_once(code, "R1[1]==0", "not R1[1]")
    up = (
        "roundedK = math.round(K, 9)\nroundedD = math.round(D, 9)\n"
        "momentumUp = roundedK > roundedD and roundedK[1] < roundedD[1]\n"
        "buymore = bullish ? (roundedD < OSlel and momentumUp ? 2 : roundedD > OSlel and momentumUp ? 1 : 0) : 0"
    )
    down = (
        "momentumDown = roundedK < roundedD and roundedK[1] > roundedD[1]\n"
        "sellmore = bearish ? (roundedD > OBlel and momentumDown ? 2 : roundedD < OBlel and momentumDown ? 1 : 0) : 0"
    )
    for tag, expression in (("buymore", up), ("sellmore", down)):
        code, count = re.subn(rf"(?m)^{tag} = iff[^\n]+$", expression, code)
        assert count == 1
    code = re.sub(r"(?<![\w.])(ema|sma|rsi|stoch|barssince)\(", r"ta.\1(", code)
    code, removed = re.subn(
        r"(?m)^(?:(?:line[123] = )?plot\(|plotshape\(|fill\(|barcolor\()[^\n]+\n",
        "",
        code,
    )
    assert removed == 9
    for action, polarity, name in (("Long", "true", "buy"), ("Short", "false", "sell")):
        direction = action.lower()
        entry = f'strategy.entry("{action}",{polarity},when=window() and {name} or {name}more)'
        code = replace_once(
            code,
            entry,
            f'strategy.entry("{action}",strategy.{direction},when={direction}Gate)',
        )
        closing = "Short" if action == "Long" else "Long"
        code = replace_once(
            code,
            f'strategy.close("{closing}",when=window() and {name} or {name}more,',
            f'strategy.close("{closing}",when={direction}Gate,',
        )
    anchor = 'strategy.entry("Long",strategy.long,when=longGate)'
    gates = "longGate = window() and buy or buymore != 0\nshortGate = window() and sell or sellmore != 0\n"
    code = replace_once(code, anchor, gates + anchor)
    for variable, title in (
        ("efast", "Fast"),
        ("eslow", "Slow"),
        ("K", "K"),
        ("D", "D"),
        ("longGate ? 1 : 0", "Long"),
        ("shortGate ? 1 : 0", "Short"),
    ):
        code += f'\nplot({variable}, "{title} proof")'
    return (code + "\n").encode("utf-8")


def archive_input(archive, ledger):
    assert sha256(archive) == FMZ_SHA256
    (row,) = [item for item in read(ledger)["disposition"] if item["id"] == IDENT]
    assert row["status"].startswith("Pending")
    _, originals = archival_items(archive, {IDENT: row})
    code, digest, interval = originals[IDENT]
    assert interval == "1d"
    with ZipFile(archive) as source:
        _, _, document, verified = next(documents(source, {IDENT: row}))
    assert digest == verified
    fields = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):\s*([^\r\n]+)", document
        )
    )
    assert fields == {
        "start": "2023-01-01 00:00:00",
        "end": "2023-10-25 00:00:00",
        "period": "1d",
        "basePeriod": "1h",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    original, _ = strip_fmz_wrapper(code)
    return (
        row,
        digest,
        fields,
        original.encode("utf-8"),
        daily_variant(original.replace("\r\n", "\n")),
    )


def provider_input(public):
    feeds, manifest = {}, []
    months = [f"2023-{month:02}" for month in range(1, 13)] + [
        f"2024-{month:02}" for month in range(1, 9)
    ]
    for market in MARKETS:
        archives = verified_archives(public, market, "1d", months, manifest)
        records = list(chain.from_iterable(raw_ohlcv(path, DAY) for path in archives))
        for name, first, last in WINDOWS:
            start, end = date_ms(first), date_ms(last)
            assert end - start == 297 * DAY
            candles = [list(item) for item in records if start <= item[0] < end]
            assert [item[0] for item in candles] == list(range(start, end, DAY))
            feeds.setdefault(name, {})[market] = candles
    return manifest, feeds


def stage(archive, ledger, public, runtime, work):
    _, _, _, original, variant = archive_input(archive, ledger)
    _, feeds = provider_input(public)
    work.mkdir(parents=True, exist_ok=True)
    copy_runtime(runtime, work)
    copy2(Path(__file__).with_suffix(".mjs"), work / "run.mjs")
    (work / "source-1884.pine").write_bytes(original)
    (work / "variant-1884.pine").write_bytes(variant)
    write(work / "feeds.json", feeds)


def exponential(values, length):
    output = []
    for value in values:
        output.append(ema(value, output[-1] if output else None, length))
    return output


def simple(values, length):
    seen, output = [], []
    for value in values:
        if value is not None:
            seen.append(value)
        output.append(fsum(seen[-length:]) / length if len(seen) >= length else None)
    return output


def stoch_rsi(prices):
    delta = [b - a for a, b in pairwise(prices)]
    gains = [max(0, price_change) for price_change in delta]
    losses = [max(0, -price_change) for price_change in delta]
    average_up, average_down = fsum(gains[:14]) / 14, fsum(losses[:14]) / 14
    rsi = [None] * 14 + [
        100 if average_down == 0 else 100 - 100 / (1 + average_up / average_down)
    ]
    for gain, loss in zip(gains[14:], losses[14:], strict=True):
        average_up = (13 * average_up + gain) / 14
        average_down = (13 * average_down + loss) / 14
        rsi.append(
            100 if average_down == 0 else 100 - 100 / (1 + average_up / average_down)
        )
    output, seen = [], []
    for value in rsi:
        normalized = None
        if value is not None:
            seen.append(value)
        if len(seen) >= 14:
            low, high = min(seen[-14:]), max(seen[-14:])
            if high != low:
                normalized = 100 * (value - low) / (high - low)
        output.append(normalized)
    return output


def indicator_reference(bars):
    close = [bar[4] for bar in bars]
    fast, slow = (exponential(exponential(close, length), 2) for length in (12, 26))
    base = exponential(close, 2)
    k = simple(stoch_rsi(close), 5)
    d = simple(k, 4)
    long, short = [], []
    last_buy = last_sell = None
    prior_green = prior_red = prior_bull = prior_bear = False
    for i, (f, s, x) in enumerate(zip(fast, slow, base, strict=True)):
        green, red = f > s and x > f, f < s and x < f
        buy, sell = green and not prior_green, red and not prior_red
        if buy:
            last_buy = i
        if sell:
            last_sell = i
        seeded = last_buy is not None and last_sell is not None
        bull, bear = seeded and last_buy > last_sell, seeded and last_sell > last_buy
        extra_long = extra_short = False
        if i and d[i] is not None and d[i - 1] is not None:
            rounded_k, rounded_d = round(k[i], 9), round(d[i], 9)
            previous_k, previous_d = round(k[i - 1], 9), round(d[i - 1], 9)
            extra_long = (
                bull
                and rounded_k > rounded_d
                and previous_k < previous_d
                and rounded_d != 20
            )
            extra_short = (
                bear
                and rounded_k < rounded_d
                and previous_k > previous_d
                and rounded_d != 80
            )
        long.append(int(prior_bear and buy or extra_long))
        short.append(int(prior_bull and sell or extra_short))
        prior_green, prior_red, prior_bull, prior_bear = green, red, bull, bear
    return fast, slow, k, d, long, short


def verify_case(case, bars):
    expected = indicator_reference(bars)
    for series, observed in zip(expected, case["witnesses"], strict=True):
        for x, y in zip(series, observed, strict=True):
            assert (
                x is None
                and y is None
                or x is not None
                and y is not None
                and isclose(x, y, rel_tol=1e-11, abs_tol=1e-9)
            )
    pivots = []
    direction = 0
    for index, (long, short) in enumerate(
        zip(expected[-2][:-1], expected[-1][:-1], strict=True)
    ):
        assert not (long and short)
        side = long - short
        if side and side != direction:
            pivots.append((index + 1, side))
            direction = side
    assert case["unsettled"] == int(bool(pivots)) and len(case["closed"]) == max(
        0, len(pivots) - 1
    )
    epochs, flow = [bar[0] for bar in bars], []
    for trade, ((entry, side), (exit_bar, _)) in zip(
        case["closed"], pairwise(pivots), strict=True
    ):
        assert (entry, side, exit_bar) == (
            trade["entryBar"],
            trade["dir"],
            trade["exitBar"],
        )
        assert (
            trade["entryPrice"] == bars[entry][1]
            and trade["exitPrice"] == bars[exit_bar][1]
        )
        assert isclose(
            trade["qty"],
            floor(CASH / trade["entryPrice"] / LOT_STEP) * LOT_STEP,
            rel_tol=1e-10,
        )
        flow.append(verify_trade(trade, epochs))
    return flow


def finalize(archive, ledger, public, work, output):
    row, digest, fields, original, variant = archive_input(archive, ledger)
    manifest, feeds = provider_input(public)
    assert feeds == read(work / "feeds.json")
    assert (
        original == (work / "source-1884.pine").read_bytes()
        and variant == (work / "variant-1884.pine").read_bytes()
    )
    assert (
        Path(__file__).with_suffix(".mjs").read_bytes()
        == (work / "run.mjs").read_bytes()
    )
    assert (work / "run.exit").read_text().strip() == "0"
    isolation = read(work / "isolation-probe.json")
    assert isolation == {"privateDenied": True, "networkDenied": True}
    package = work / f"piner-{PINER_VERSION}.tgz"
    assert b64encode(sha512(package.read_bytes()).digest()).decode("ascii") == PINER_PIN
    with open_tar(package, "r:gz") as distribution:
        assert (
            distribution.extractfile("package/dist/index.js").read()
            == (work / "package/dist/index.js").read_bytes()
        )
    receipt = read(work / "receipt.json")
    assert receipt["source_hash"] == sha256(work / "source-1884.pine") and receipt[
        "variant_hash"
    ] == sha256(work / "variant-1884.pine")
    assert (
        tuple(receipt["settings"][field] for field in ("marginLong", "marginShort"))
        == MARGIN
    )
    cases = {(case["period"], case["market"]): case for case in receipt["cases"]}
    assert len(cases) == len(receipt["cases"]) == 4
    summaries, closes = [], 0
    for label, markets in feeds.items():
        combined, remaining = [], 0
        common = {
            "id": IDENT,
            "name": row["name"],
            "source": row["source"],
            "source_sha256": digest,
            "executed_source_sha256": receipt["variant_hash"],
            "interval": "1d",
            "archive_interval": "1d",
            "period": label,
            "group": GROUP,
            "exit": "Archived next-open market close or reversal",
            "quote_currency": "USDT",
            "market_data": "Binance USD-M historical futures candles",
            "repairs": {
                "Saved same-symbol daily request adopts the identical chart close": 2,
                "Legacy oscillator crossings preserve documented comparison precision": 2,
            },
        }
        for market, bars in markets.items():
            case = cases[(label, market)]
            flow = verify_case(case, bars)
            summaries.append(
                {
                    **common,
                    "market": market,
                    **summarize(flow, case["unsettled"], CAPITAL),
                }
            )
            combined.extend(flow)
            remaining += case["unsettled"]
            closes += len(flow)
        summaries.append(
            {
                **common,
                "market": "BTCUSDT + ETHUSDT",
                **summarize(combined, remaining, 2 * CAPITAL),
            }
        )
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(ledger),
            "archive_sha256": FMZ_SHA256,
            "original_archive_settings": fields,
            "original_document_sha256": digest,
            "published_binance_candles": manifest,
            "piner_version": PINER_VERSION,
            "piner_tarball_sha512": PINER_PIN,
            "isolation_probe": isolation,
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
                "https://www.fmz.com/bbs-topic/9293",
                "https://www.tradingview.com/pine-script-docs/language/type-system/",
            ],
            "method": "Saved chart and requested context are both native daily for the same symbol. FMZ's strict prior-bar crossover definitions and Pine's nine-decimal comparison precision are explicit in the replay. Both Piner backends and independent EMA, RSI, oscillator, decision, fill and fee verifiers agree.",
            "coverage": [
                [
                    IDENT,
                    f"Tested · {GROUP}",
                    "Verified same-context historical decisions and the resulting market trade ledger.",
                ]
            ],
            "results": summaries,
        },
    )
    print(
        f"Verified Playzone source {IDENT}, {len(summaries)} rows and {closes} closed trades."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, handler, arguments in (
        ("stage", stage, ("archive", "ledger", "public", "runtime", "work")),
        ("finalize", finalize, ("archive", "ledger", "public", "work", "output")),
    ):
        operation = commands.add_parser(name)
        for argument in arguments:
            operation.add_argument(argument, type=Path)
        operation.set_defaults(handler=handler)
    options = vars(parser.parse_args())
    options.pop("command")
    options.pop("handler")(**options)


if __name__ == "__main__":
    main()
