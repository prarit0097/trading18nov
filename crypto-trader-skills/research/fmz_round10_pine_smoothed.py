"""Replay native 10-minute FMZ Heikin-Ashi with verified 1-minute stop fills."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from hashlib import sha512
from itertools import chain
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
    aggregate,
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
)

IDENT = 3391
MARKETS = ("BTCUSDT", "ETHUSDT")
MINUTE = 60_000
LOT_STEP = 0.001
CASH = 1_000
CAPITAL = 10_000
STOP_FRACTION = 0.01
WINDOWS = (
    ("FMZ native 10m", "2023-12-19", "2023-12-26"),
    ("Next equal 10m", "2023-12-26", "2024-01-02"),
)
GROUP = "FMZ Pine · Native 10m · Verified Heikin-Ashi and 1m stops"
SECURITY_HELPER = "f_security(_symbol, _res, _src, _repaint) => request.security(_symbol, _res, _src[_repaint ? 0 : barstate.isrealtime ? 1 : 0])[_repaint ? 0 : barstate.isrealtime ? 0 : 1]"


def closed_chart_variant(code):
    assert SECURITY_HELPER in code
    for pattern in (
        r"^i_repaint\s+=\s+input \(false,",
        r"^i_useSmooth\s+=\s+input \( true,",
        r'^i_smoothingMethod = input.string\("SMA",',
        r"^i_smoothingPeriod\s+=\s+input \( 10,",
        r"^timeperiod = timeframe\.period$",
        r"^haTicker = ticker\.heikinashi\(syminfo\.tickerid\)$",
        r"^i_longLossPerc = input\.float\([^\n]+defval=1\) \* 0\.01$",
        r"^i_shortLossPerc = input\.float\([^\n]+defval=1\) \* 0\.01$",
    ):
        assert re.search(pattern, code, re.MULTILINE)
    body, definitions = re.subn(
        r"(?m)^f_(secureSecurity|security|secSecurity2)\([^\n]+\n", "", code
    )
    assert definitions == 3

    def route(call):
        scope, field = call.groups()
        if scope == "haTicker":
            return f"request.security(haTicker, timeperiod, {field})[1]"
        return field + "[1]"

    body, calls = re.subn(
        r"f_security\((syminfo.tickerid|haTicker), timeperiod, (open|high|low|close), i_repaint\)",
        route,
        body,
    )
    assert calls == 8 and "f_security(" not in body
    return (body.rstrip() + '\nplot(smaSmoothed, "Audited smoothed reverse")\n').encode(
        "utf-8"
    )


def inspect_source(archive, ledger):
    assert sha256(archive) == FMZ_SHA256
    (row,) = [item for item in read(ledger)["disposition"] if item["id"] == IDENT]
    assert row["status"].startswith("Pending")
    _, originals = archival_items(archive, {IDENT: row})
    code, digest, interval = originals[IDENT]
    assert interval == "10m"
    with ZipFile(archive) as source:
        _, _, document, observed_digest = next(documents(source, {IDENT: row}))
    assert digest == observed_digest
    fields = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):\s*([^\r\n]+)", document
        )
    )
    assert fields == {
        "start": "2023-12-19 00:00:00",
        "end": "2023-12-26 00:00:00",
        "period": "10m",
        "basePeriod": "1m",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    original, _ = strip_fmz_wrapper(code)
    return (
        row,
        digest,
        fields,
        original.encode("utf-8"),
        closed_chart_variant(original.replace("\r\n", "\n")),
    )


def provider_data(public):
    manifest, feeds = [], {}
    for market in MARKETS:
        files = verified_archives(
            public, market, "1m", ("2023-12", "2024-01"), manifest
        )
        source = list(chain.from_iterable(raw_ohlcv(path, MINUTE) for path in files))
        for label, first, last in WINDOWS:
            start, end = date_ms(first), date_ms(last)
            lower = [bar for bar in source if start <= bar[0] < end]
            assert [bar[0] for bar in lower] == list(range(start, end, MINUTE))
            assert len(lower) == 10_080
            chart = aggregate(lower, 10)
            feeds.setdefault(label, {})[market] = {
                "chart": [list(bar) for bar in chart],
                "lower": [list(bar) for bar in lower],
                "start": start,
                "end": end,
            }
    return manifest, feeds


def stage(archive, ledger, public, runtime, work):
    _, _, _, original, variant = inspect_source(archive, ledger)
    _, data = provider_data(public)
    work.mkdir(parents=True, exist_ok=True)
    copy_runtime(runtime, work)
    copy2(Path(__file__).with_suffix(".mjs"), work / "run.mjs")
    (work / "source-3391.pine").write_bytes(original)
    (work / "variant-3391.pine").write_bytes(variant)
    write(work / "feeds.json", data)


def smoothed_reverse(chart):
    heikin = []
    for _, open_price, high, low, close, _ in chart:
        earlier = heikin[-1] if heikin else (open_price, close)
        heikin.append(
            ((earlier[0] + earlier[1]) / 2, (open_price + high + low + close) / 4)
        )
    reverse = [None, None]
    for index in range(2, len(chart)):
        _, open_price, high, low, _, _ = chart[index - 1]
        open_ha, close_ha = heikin[index - 2]
        price = 2 * (open_ha + close_ha) - (high + low + open_price)
        if price < low:
            price = (low + price) / 2
        if price > high:
            price = (high + price) / 2
        reverse.append(price)
    return [None] * 11 + [
        fsum(reverse[i - 9 : i + 1]) / 10 for i in range(11, len(chart))
    ]


def signals(chart, levels):
    output = {}
    for i in range(12, len(chart) - 1):
        previous = chart[i - 2][4] - levels[i - 1]
        current = chart[i - 1][4] - levels[i]
        if previous <= 0 < current:
            output[i + 1] = (1, levels[i])
        if previous >= 0 > current:
            output[i + 1] = (-1, levels[i])
    return output


def eligible_stop(chart, minutes, index, side, price):
    already_reached = (chart[index - 1][4] - price) * side >= 0
    for epoch, open_price, high, low, _, _ in minutes[index * 10 : (index + 1) * 10]:
        if already_reached or (open_price - price) * side >= 0:
            return epoch, open_price
        extreme = high if side == 1 else low
        if (extreme - price) * side >= 0:
            return epoch, price
    return None


def verify_case(case, payload):
    chart, minutes = payload["chart"], payload["lower"]
    levels = smoothed_reverse(chart)
    for actual, expected in zip(case["target"], levels, strict=True):
        assert (
            actual is None
            if expected is None
            else isclose(actual, expected, rel_tol=1e-12)
        )
    orders = signals(chart, levels)
    coverage = case["coverage"]
    assert coverage["active"] and coverage["coverage"] == "complete"
    assert coverage["capFallbackBars"] == coverage["dataFallbackBars"] == 0
    assert case["requested"] == [
        {
            "symbol": f"BINANCE:{case['market']}.P_HA",
            "timeframe": "10",
            "lowerTf": False,
        }
    ]
    settlements = []
    for trade in case["closed"]:
        side, entry, exit_bar = (trade[key] for key in ("dir", "entryBar", "exitBar"))
        entry_price, exit_price = trade["entryPrice"], trade["exitPrice"]
        expected_side, price = orders[entry]
        assert side == expected_side and trade["entryId"] == (
            "LONG" if side == 1 else "SHORT"
        )
        first_fill = eligible_stop(chart, minutes, entry, side, price)
        assert first_fill and first_fill[0] == trade["entryTime"]
        assert isclose(first_fill[1], entry_price, rel_tol=1e-12)
        protective = entry_price * (1 - STOP_FRACTION * side)
        exits = []
        for next_bar in range(entry + 1, exit_bar + 1):
            protective_fill = eligible_stop(chart, minutes, next_bar, -side, protective)
            if protective_fill:
                exits.append(protective_fill)
            if next_bar in orders and orders[next_bar][0] == -side:
                reversing = eligible_stop(
                    chart, minutes, next_bar, -side, orders[next_bar][1]
                )
                if reversing:
                    exits.append(reversing)
        earliest = min(epoch for epoch, _ in exits)
        assert earliest == trade["exitTime"]
        assert any(
            epoch == earliest and isclose(price, exit_price, rel_tol=1e-12)
            for epoch, price in exits
        )
        qty = floor(CASH / entry_price / LOT_STEP) * LOT_STEP
        assert isclose(trade["qty"], qty, rel_tol=1e-10)
        gross = (exit_price - entry_price) * side * qty
        turnover = qty * (entry_price + exit_price)
        commission = turnover * FEE
        assert isclose(trade["commission"], commission, rel_tol=1e-10, abs_tol=1e-9)
        assert isclose(trade["profit"], gross - commission, rel_tol=1e-10, abs_tol=1e-9)
        settlements.append((earliest, gross, commission, turnover * EXECUTION))
    return settlements


def finalize(archive, ledger, public, work, output):
    row, digest, fields, original, variant = inspect_source(archive, ledger)
    manifest, feeds = provider_data(public)
    assert feeds == read(work / "feeds.json")
    assert original == (work / "source-3391.pine").read_bytes()
    assert variant == (work / "variant-3391.pine").read_bytes()
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
    receipts = read(work / "receipt.json")
    assert receipts["source_sha256"] == sha256(work / "source-3391.pine")
    assert receipts["variant_sha256"] == sha256(work / "variant-3391.pine")
    cases = {(case["period"], case["market"]): case for case in receipts["cases"]}
    assert len(cases) == len(receipts["cases"]) == 4
    results, count, audits = [], 0, []
    for period, markets in feeds.items():
        pool, unresolved = [], 0
        common = {
            "id": IDENT,
            "name": row["name"],
            "source": row["source"],
            "source_sha256": digest,
            "executed_source_sha256": receipts["variant_sha256"],
            "period": period,
            "quote_currency": "USDT",
            "interval": "10m",
            "archive_interval": "10m",
            "group": GROUP,
            "exit": "Archived protective or reversal stop in verified 1m data",
            "market_data": "Binance USD-M historical 1m futures candles aggregated to 10m",
            "repairs": {
                "Saved historical nonrepainting helper retains its same-timeframe one-bar delay": 8
            },
        }
        for market, data in markets.items():
            case = cases[(period, market)]
            flow = verify_case(case, data)
            unsettled = case["unsettled"]
            assert unsettled in (0, 1)
            results.append(
                {**common, "market": market, **summarize(flow, unsettled, CAPITAL)}
            )
            audits.append(
                {
                    "period": period,
                    "market": market,
                    "closed": len(flow),
                    "coverage": case["coverage"],
                }
            )
            pool.extend(flow)
            unresolved += unsettled
            count += len(flow)
        results.append(
            {
                **common,
                "market": "BTCUSDT + ETHUSDT",
                **summarize(pool, unresolved, 2 * CAPITAL),
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
                for name in ("run.mjs", "feeds.json", "receipt.json")
            },
            "cost_model": {"fee_per_side": FEE, "execution_buffer_per_side": EXECUTION},
            "case_audits": audits,
            "method": "The historical same-timeframe helper uses the previous regular or Heikin-Ashi candle at saved nonrepainting defaults. Piner uses its 1m magnifier to match the archived FMZ execution resolution, with complete data and zero fallbacks. Independent calculations checked every smoothed reverse level, closed trade entry, earliest eligible stop exit, quantity and fee.",
            "coverage": [
                [
                    IDENT,
                    f"Tested · {GROUP}",
                    "Verified closed-bar strategy and one-minute execution with independently checked stop fills.",
                ]
            ],
            "results": results,
        },
    )
    print(
        f"Verified native smoothed Heikin-Ashi {IDENT}, {len(results)} rows and {count} closed trades."
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
