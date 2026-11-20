"""Verify the authored breakout and EMA orders in a mixed-version FMZ Pine source."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from hashlib import sha512
from itertools import chain
from math import floor, isclose
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
    PINER_PIN,
    PINER_VERSION,
    strip_fmz_wrapper,
    summarize,
)
from research.fmz_round11_pine_playzone import exponential
from research.fmz_round12_pine_authored import aligned, provider_bars

IDENT = 2534
CAPITAL = 2500
FEE_RATE = 0.002
LOT_STEP = 0.001
HOUR = 3_600_000
MARKETS = ("BTCUSDT", "ETHUSDT")
GROUP = "FMZ Pine · Native 1h · Verified breakout and EMA orders"


def ema_breakout_variant(code):
    code = code.replace("\r\n", "\n").strip()
    pattern = 'strategy(title="ema10-21", shorttitle="10/21", overlay=true, pyramiding = 0, default_qty_type = strategy.percent_of_equity, default_qty_value = 100, initial_capital = 2500, commission_type = strategy.commission.percent, commission_value = 0.2)'
    assert code.count(pattern) == 1 and code.count("//@version=3") == 1
    code = code.replace(pattern + "\n", "").replace("//@version=3", "")
    code = re.sub(
        r"(?m)^(?P<name>len[12])\s*=\s*input\(", r"\g<name> = input.int(", code
    )
    code = re.sub(
        r"(?m)^(?P<name>src[12])\s*=\s*input\(", r"\g<name> = input.source(", code
    )
    assert code.count('strategy.close("Buy", strategy.long)') == 1
    code = code.replace('strategy.close("Buy", strategy.long)', 'strategy.close("Buy")')
    code = re.sub(r"(?m)^plot\(.*\n", "", code)
    code = code.replace(
        "if high > ta.highest(high[1], 5)",
        "highestRange = ta.highest(high, 5)[1]\nlowestRange = ta.lowest(low, 5)[1]\nupBreak = high > highestRange\ndownBreak = low < lowestRange\n\nif upBreak",
    )
    code = code.replace("else if low < ta.lowest(low[1], 5)", "else if downBreak")
    return (
        f"//@version=5\n{pattern}\n{code}\n"
        'plot(highestRange,"Highest")\n'
        'plot(lowestRange,"Lowest")\n'
        'plot(threshold,"EMA spread")\n'
        'plot(upBreak ? 1 : downBreak ? -1 : 0,"Breakout")\n'
        'plot(thresholdUp?1:thresholdDown?-1:0,"EMA direction")\n'
    )


def breakout_values(chart):
    highest, lowest, directions = [], [], []
    a, b = (exponential([r[4] for r in chart], period) for period in (10, 21))
    spread = [(p - q) * 100 / ((p + q) / 2) for p, q in zip(a, b, strict=True)]
    regimes = [
        1 if round(s, 9) > 0.15 else -1 if round(s, 9) < -0.006 else 0 for s in spread
    ]
    for i, bar in enumerate(chart):
        recent = chart[i - 5 : i]
        high = max(r[2] for r in recent) if i >= 5 else None
        low = min(r[3] for r in recent) if i >= 5 else None
        highest.append(high)
        lowest.append(low)
        directions.append(
            0 if high is None else 1 if bar[2] > high else -1 if bar[3] < low else 0
        )
    return highest, lowest, spread, directions, regimes


def independently_check(case, sample):
    chart = sample["chart"]
    expected = breakout_values(chart)
    assert not case["requested"]
    for wi, (wanted, actual) in enumerate(
        zip(expected, case["witnesses"], strict=True)
    ):
        for i, (x, y) in enumerate(zip(wanted, actual, strict=True)):
            assert (
                x is None
                and y is None
                or x is not None
                and y is not None
                and isclose(x, y, rel_tol=1e-11, abs_tol=1e-9)
            ), (wi, i, x, y)
    qty, book_id, pos, entry, wallet = 0, None, 0, None, CAPITAL
    closed = []
    events = []
    for now, (breakout, ema) in enumerate(
        zip(expected[-2][:-1], expected[-1][:-1], strict=True), 1
    ):
        ops = []
        if breakout:
            ops.append(("Enter Long" if breakout == 1 else "Enter Short", breakout))
        if ema == 1:
            ops.append(("Buy", 1))
        elif ema == -1:
            ops.append(("Buy", 0))
        for order, side in ops:
            if side == pos or (not side and book_id != order):
                continue
            price = chart[now][1]
            if pos:
                op = chart[entry][1]
                gross = (price - op) * qty * pos
                fee = (price + op) * qty * FEE_RATE
                wallet += gross - fee
                closed.append((entry, now, pos, book_id, qty, op, price, gross, fee))
                events.append(
                    (chart[now][0], gross, fee, (price + op) * qty * EXECUTION)
                )
            if side:
                qty = floor(wallet / price / LOT_STEP + 1e-9) * LOT_STEP
                entry, book_id, pos = now, order, side
            else:
                qty, entry, book_id, pos = 0, None, None, 0
    assert len(case["closed"]) == len(closed), (len(case["closed"]), len(closed))
    assert case["unsettled"] == int(bool(pos))
    equity = 0.0
    for i, (trade, witness) in enumerate(zip(case["closed"], closed, strict=True)):
        entry, closed, side, id, q, op, exit, gross, fee = witness
        assert (
            trade["entryBar"],
            trade["exitBar"],
            trade["dir"],
            trade["entryId"],
        ) == (entry, closed, side, id), (i, trade, witness)
        assert (trade["entryTime"], trade["exitTime"]) == (
            chart[entry][0],
            chart[closed][0],
        )
        a = (
            trade["qty"],
            trade["entryPrice"],
            trade["exitPrice"],
            trade["profit"],
            trade["commission"],
        )
        b = (q, op, exit, gross - fee, fee)
        assert all(
            isclose(x, y, rel_tol=1e-9, abs_tol=1e-9) for x, y in zip(a, b, strict=True)
        ), (i, a, b)
        equity += gross - fee
        assert isclose(trade["cumProfit"], equity, rel_tol=1e-9, abs_tol=1e-9)
    return events


START = "2023-08-18"
END = "2023-09-17"
WINDOWS = (
    ("FMZ native window", date_ms(START), date_ms(END)),
    ("Next equal window", date_ms(END), 2 * date_ms(END) - date_ms(START)),
)


def archived_source(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (row,) = [entry for entry in read(baseline)["disposition"] if entry["id"] == IDENT]
    assert "pending" in row["status"].lower() and row["selected_report"] is None
    _, originals = archival_items(archive, {IDENT: row})
    text, digest, period = originals[IDENT]
    with ZipFile(archive) as source:
        ((_, _, document, verified),) = documents(source, {IDENT: row})
    assert verified == digest and period == "1h"
    fields = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):\s*([^\r\n]+)", document
        )
    )
    assert fields == {
        "start": f"{START} 00:00:00",
        "end": f"{END} 00:00:00",
        "period": "1h",
        "basePeriod": "15m",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    original, _ = strip_fmz_wrapper(text)
    active = re.sub(r"(?m)//[^\n]*", "", original)
    assert re.findall(r"\bstrategy\.(entry|close|exit|order)\(", active) == [
        "entry",
        "entry",
        "entry",
        "close",
    ]
    return (
        row,
        digest,
        fields,
        original.encode(),
        ema_breakout_variant(original).encode(),
    )


def provider_cases(public):
    manifest, windows = [], {}
    for market in MARKETS:
        files = verified_archives(
            public, market, "1h", ("2023-08", "2023-09", "2023-10"), manifest
        )
        stream = list(chain.from_iterable(provider_bars(file, HOUR) for file in files))
        for label, begin, end in WINDOWS:
            chart = aligned(stream, begin, end, 60, 60)
            assert chart[0][0] == begin and chart[-1][0] + HOUR == end
            assert all(bar[5] > 0 for bar in chart)
            windows.setdefault(label, {})[market] = {"chart": chart, "frame": "60"}
    return manifest, {str(IDENT): windows}


def stage(archive, baseline, public, runtime, work):
    _, _, _, original, variant = archived_source(archive, baseline)
    _, feeds = provider_cases(public)
    work.mkdir(parents=True, exist_ok=True)
    if runtime.resolve() != work.resolve():
        for file in (
            "node.exe",
            f"piner-{PINER_VERSION}.tgz",
            "probe.cjs",
            "sandbox.ps1",
        ):
            copy2(runtime / file, work / file)
        copytree(runtime / "package", work / "package", dirs_exist_ok=True)
    copy2(Path(__file__).with_suffix(".mjs"), work / "ema-breakout-run.mjs")
    (work / f"source-{IDENT}.pine").write_bytes(original)
    (work / f"variant-{IDENT}.pine").write_bytes(variant)
    write(work / "ema-breakout-feeds.json", feeds)


def check_runtime(work):
    assert (work / "ema-breakout-run.exit").read_text().strip() == "0"
    assert (work / "ema-breakout-run.mjs").read_bytes() == Path(__file__).with_suffix(
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


def finalize(archive, baseline, public, work, output):
    row, digest, metadata, original, variant = archived_source(archive, baseline)
    manifest, feeds = provider_cases(public)
    assert read(work / "ema-breakout-feeds.json") == feeds
    isolation = check_runtime(work)
    (receipt,) = read(work / "ema-breakout-receipt.json")
    assert receipt["id"] == IDENT and len(receipt["cases"]) == 4
    source = work / f"source-{IDENT}.pine"
    normalized = work / f"variant-{IDENT}.pine"
    assert source.read_bytes() == original and normalized.read_bytes() == variant
    assert receipt["sourceHash"] == sha256(source) and receipt["variantHash"] == sha256(
        normalized
    )
    by_case = {(case["period"], case["market"]): case for case in receipt["cases"]}
    assert len(by_case) == 4
    common = {
        "id": IDENT,
        "name": row["name"],
        "source": row["source"],
        "source_sha256": digest,
        "executed_source_sha256": receipt["variantHash"],
        "interval": metadata["period"],
        "archive_interval": metadata["period"],
        "quote_currency": "USDT",
        "group": GROUP,
        "market_data": "Binance USD-M native historical 1h candles",
        "exit": "Authored market reversal or entry-ID-specific market close",
    }
    rows = []
    closes = 0
    for label, markets in feeds[str(IDENT)].items():
        pool, unsettled = [], 0
        for market, payload in markets.items():
            case = by_case[(label, market)]
            events = independently_check(case, payload)
            rows.append(
                {
                    **common,
                    "period": label,
                    "market": market,
                    **summarize(events, case["unsettled"], CAPITAL),
                }
            )
            closes += len(events)
            pool.extend(events)
            unsettled += case["unsettled"]
        rows.append(
            {
                **common,
                "period": label,
                "market": "BTCUSDT + ETHUSDT",
                **summarize(pool, unsettled, 2 * CAPITAL),
            }
        )
    assert closes > 0
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(baseline),
            "archive_sha256": FMZ_SHA256,
            "isolation_probe": isolation,
            "published_binance_candles": manifest,
            "piner_version": PINER_VERSION,
            "piner_tarball_sha512": PINER_PIN,
            "artifacts": {
                name: sha256(work / name)
                for name in (
                    "ema-breakout-feeds.json",
                    "ema-breakout-run.mjs",
                    "ema-breakout-receipt.json",
                )
            },
            "cost_model": {
                "initial_capital_per_market": CAPITAL,
                "fee_per_side": FEE_RATE,
                "execution_buffer_per_side": EXECUTION,
                "lot_step": LOT_STEP,
                "default_equity_fraction": 1,
                "pyramiding": 0,
            },
            "references": [
                "https://www.tradingview.com/pine-script-docs/faq/techniques/",
                "https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/",
                "https://www.tradingview.com/pine-script-docs/concepts/strategies/",
                "https://github.com/binance/binance-public-data",
            ],
            "method": [
                "The pinned source combines two breakout entry commands above the strategy declaration and an EMA-threshold Buy or close below it. The single migrated declaration is moved to the top, retaining all four active orders and their original order of evaluation.",
                "The rolling extrema use the five completed prior hours. Shifting the highest and lowest outputs by one bar follows TradingView's documented technique and excludes a partial four-value startup window. The EMA conditions and direction defaults are preserved.",
                "The legacy Boolean positional argument to strategy.close means an unconditional close of the named Buy entry when its enclosing condition runs, as documented by TradingView.",
                "Signal and individual fill receipts from both Piner backends match independent OHLC, EMA, next-open order sequencing, compounded percentage-equity size and commissions. The archived 2500 initial capital and 0.2% fee per side are retained.",
                "BTC matches the archived instrument and ETH adds same-venue comparison. Each window starts flat with its own indicator warm-up. This empirical check uses closed P&L and no liquidation model.",
            ],
            "source_audits": {
                IDENT: {
                    "archive_settings": metadata,
                    "source_document_sha256": digest,
                    "closed": closes,
                }
            },
            "coverage": [
                [
                    IDENT,
                    f"Tested · {GROUP}",
                    "Both original signal and order blocks verified with their published equity sizing, fees, and native chart prices.",
                ]
            ],
            "results": rows,
        },
    )
    print(f"Verified {len(rows)} rows and {closes} closed trades.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, handler, arguments in (
        ("stage", stage, ("archive", "baseline", "public", "runtime", "work")),
        ("finalize", finalize, ("archive", "baseline", "public", "work", "output")),
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
