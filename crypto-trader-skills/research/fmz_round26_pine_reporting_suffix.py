"""Verify executable source before a failing display-only reporting suffix."""

from __future__ import annotations

import argparse
import re
from base64 import b64encode
from datetime import UTC, datetime
from hashlib import sha256 as bytes_hasher
from hashlib import sha512
from math import fsum, isclose
from pathlib import Path
from shutil import copy2
from tarfile import open as open_tar
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, sha256, verified_archives
from research.fmz_round7_pine import EXECUTION, FEE, PINER_PIN, PINER_VERSION, summarize
from research.fmz_round12_pine_authored import provider_bars
from research.fmz_round18_pine_qqe import executable_lines
from research.fmz_round19_pine_broker import equal

CAPITAL = 1_000_000
SPECS = {
    1930: ("2023-12-01", "2023-12-31 23:59:59", "1h", 1, FEE),
    2581: ("2023-01-10", "2024-01-16", "1d", 15, 0.001),
    4750: ("2023-01-01", "2024-01-07", "1d", 1, FEE),
}
MARKER = "// Copy below code to end of the desired strategy script"
NATIVE = "FMZ native window"
FORWARD = "Next equal window"
MARKETS = ("BTCUSDT", "ETHUSDT")
GROUP = "FMZ Pine · Next-open reversals · Reporting suffix isolated"
PLOTS = {
    "adx": 'plot(DIPlus,"DI Plus")\nplot(DIMinus,"DI Minus")\nplot(ADX,"ADX")\nplot(buy_condition?1:0,"Long")\nplot(sell_condition?1:0,"Short")',
    "breakout": 'plot(high[20],"Prior High")\nplot(low[20],"Prior Low")\nplot(longCondition?1:0,"Long")\nplot(shortCondition?1:0,"Short")',
}
WITNESSES = {
    "adx": ["DI Plus", "DI Minus", "ADX", "Long", "Short", "Position"],
    "breakout": ["Prior High", "Prior Low", "Long", "Short", "Position"],
}


def source_records(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    cohort = {r["id"]: r for r in read(baseline)["disposition"] if r["id"] in SPECS}
    assert all(row["status"].startswith("Pending") for row in cohort.values())
    with ZipFile(archive) as db:
        for ident, record, document, digest in documents(db, cohort):
            (raw,) = re.findall(
                r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", document
            )
            settings, prefix = raw.split("*/", 1)
            trading, reporting = prefix.split(MARKER)
            trading = trading.strip() + "\n"
            active = "\n".join(executable_lines(trading))
            ui = "\n".join(executable_lines(reporting))
            assert (
                trading.count("//@version=5") == 1
                and active.count("strategy.entry(") == 2
            )
            assert not re.search(
                r"request\.|alert\(|strategy\.(order|exit|close)", active
            )
            assert set(re.findall(r"\bstrategy\.([A-Za-z_]+)", ui)) == {
                "initial_capital",
                "netprofit",
                "closedtrades",
            }
            assert re.search(r"(?m)^strategy\.initial_capital\s*=\s*50000\s*$", ui)
            assert all(term not in ui for term in ("request.", "alert(", "import "))
            assert "table." in ui and "initial_balance = strategy.initial_capital" in ui
            kind = "breakout" if ident == 4750 else "adx"
            if kind == "adx":
                for token in (
                    "len = input(14)",
                    "ADX = ta.sma(DX, len)",
                    'long_diff = input(10, "Long Difference")',
                    'short_diff = input(10, "Short Difference")',
                    "diff_2 >=long_diff and diff_3 >=long_diff and (ADX < DIPlus and ADX > DIMinus)",
                    "diff_2 >=short_diff and diff_3 >=short_diff and (ADX > DIPlus and ADX < DIMinus)",
                ):
                    assert token in active
            else:
                assert re.search(
                    r"longCondition = +close > high\[20\]\s*$", active, re.MULTILINE
                )
                assert re.search(
                    r"shortCondition = +close < low\[20\]\s*$", active, re.MULTILINE
                )
            assert (
                "default_qty_value = 15, commission_type = strategy.commission.percent, commission_value = 0.1"
                in active
            ) == (ident == 2581)
            variant = (
                trading + PLOTS[kind] + '\nplot(strategy.position_size,"Position")\n'
            )
            yield ident, record, digest, settings, raw.encode(), variant.encode(), kind


def date_ms(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp() * 1000)


def bars_for(ident, folders, manifest):
    start, end, interval, _, _ = SPECS[ident]
    lo, hi = date_ms(start), date_ms(end) + (1000 if interval == "1h" else 0)
    step = 3_600_000 if interval == "1h" else 86_400_000
    assert (hi - lo) % step == 0
    upper = hi * 2 - lo
    months = sorted(
        {
            datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m")
            for ms in range(lo, upper, step)
        }
    )
    windows = {NATIVE: {}, FORWARD: {}}
    for market in MARKETS:
        full = []
        for month in months:
            folder = next(
                d for d in folders if (d / f"{market}-{interval}-{month}.zip").is_file()
            )
            (source,) = verified_archives(folder, market, interval, (month,), manifest)
            full.extend(provider_bars(source, step))
        for name, left, right in ((NATIVE, lo, hi), (FORWARD, hi, upper)):
            chosen = [list(bar) for bar in full if left <= bar[0] < right]
            assert [bar[0] for bar in chosen] == list(range(left, right, step))
            windows[name][market] = chosen
    return windows


def stage(archive, baseline, work, folders, persist=False):
    manifest, data, sources = {}, {}, {}
    for ident, record, digest, settings, raw, variant, kind in source_records(
        archive, baseline
    ):
        start, end, interval, qty, fee = SPECS[ident]
        config = dict(
            re.findall(
                r"(?m)^(start|end|period|basePeriod|exchanges):\s*([^\r\n]+)", settings
            )
        )
        assert config == {
            "start": start if len(start) > 10 else start + " 00:00:00",
            "end": end if len(end) > 10 else end + " 00:00:00",
            "period": interval,
            "basePeriod": "15m" if interval == "1h" else "1h",
            "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
        }
        sources[ident] = record, digest, config, raw, variant, kind
        manifest[ident] = []
        data[str(ident)] = {
            "model": {
                "initialCapital": CAPITAL,
                "qtyType": "fixed",
                "qtyValue": qty,
                "marginLong": 0,
                "marginShort": 0,
                "commissionType": "percent",
                "commissionValue": fee * 100,
            },
            "frame": "60" if interval == "1h" else "1D",
            "witnesses": WITNESSES[kind],
            "windows": bars_for(ident, folders, manifest[ident]),
        }
        if persist:
            (work / f"round26-source-{ident}.pine").write_bytes(raw)
            (work / f"pnl-table-variant-{ident}.pine").write_bytes(variant)
    if persist:
        copy2(Path(__file__).with_suffix(".mjs"), work / "pnl-table-run.mjs")
        write(work / "pnl-table-feeds.json", data)
    return manifest, data, sources


def signals_adx(chart):
    prev_close = prev_high = prev_low = 0
    atr = up = down = 0
    ratios = []
    for _, _, hi, lo, close, _ in chart:
        tr = max(hi - lo, abs(hi - prev_close), abs(lo - prev_close))
        plus, minus = hi - prev_high, prev_low - lo
        atr += tr - atr / 14
        up += (max(plus, 0) if plus > minus else 0) - up / 14
        down += (max(minus, 0) if minus > plus else 0) - down / 14
        pu, pd = 100 * up / atr, 100 * down / atr
        ratios.append(100 * abs(pu - pd) / (pu + pd))
        adx = fsum(ratios[-14:]) / 14 if len(ratios) >= 14 else None
        enough = adx is not None and abs(pu - adx) >= 10 and abs(pd - adx) >= 10
        yield pu, pd, adx, enough and pd < adx < pu, enough and pu < adx < pd
        prev_close, prev_high, prev_low = close, hi, lo


def signals_breakout(chart):
    for i, (_, _, _, _, price, _) in enumerate(chart):
        high = chart[i - 20][2] if i >= 20 else None
        low = chart[i - 20][3] if i >= 20 else None
        yield (
            high,
            low,
            high is not None and price > high,
            low is not None and price < low,
        )


def fill_ledger(chart, signal, qty):
    fills, sizes = [], []
    current, desired = 0, 0
    opened = None
    for index, (bar, decision) in enumerate(zip(chart, signal, strict=True)):
        if desired and current != desired:
            if opened is not None:
                fills.append((current, qty, opened, chart[opened][1], index, bar[1]))
            current, opened = desired, index
        sizes.append(current * qty)
        a, b = decision[-2:]
        assert not (a and b)
        desired = 1 if a else -1 if b else 0
    return fills, sizes, current


def reconcile(chart, kind, cases, qty, fee):
    signal = list((signals_adx if kind == "adx" else signals_breakout)(chart))
    trades, sizes, current = fill_ledger(chart, signal, qty)
    assert bool(current) == cases["unsettled"]
    for index, (metrics, size, recorded) in enumerate(
        zip(signal, sizes, zip(*cases["witnesses"], strict=True), strict=True)
    ):
        wanted = (*metrics, size)
        assert all(equal(a, b) for a, b in zip(wanted, recorded, strict=True)), (
            index,
            wanted,
            recorded,
        )
    realized = []
    for expected, observed in zip(trades, cases["closed"], strict=True):
        side, amount, entry_i, entry, exit_i, exit = expected
        fields = ("dir", "qty", "entryBar", "entryPrice", "exitBar", "exitPrice")
        assert all(equal(a, observed[b]) for a, b in zip(expected, fields, strict=True))
        assert observed["entryTime"] == chart[entry_i][0]
        assert observed["exitTime"] == chart[exit_i][0]
        turnover = amount * (entry + exit)
        gross = side * amount * (exit - entry)
        assert isclose(
            turnover * fee, observed["commission"], rel_tol=1e-9, abs_tol=1e-9
        )
        assert isclose(
            gross - turnover * fee, observed["profit"], rel_tol=1e-9, abs_tol=1e-9
        )
        realized.append(
            (observed["exitTime"], gross, turnover * fee, turnover * EXECUTION)
        )
    return (
        realized,
        int(bool(current)),
        {
            "closed": len(realized),
            "signal_and_position_values_checked": len(signal) * (len(signal[0]) + 1),
            "terminal_position": current * qty,
        },
    )


def report(archive, baseline, work, folders, output):
    manifest, feeds, sources = stage(archive, baseline, work, folders)
    assert read(work / "pnl-table-feeds.json") == feeds
    assert (work / "pnl-table-run.exit").read_text().strip() == "0"
    runner = work / "pnl-table-run.mjs"
    assert runner.read_bytes() == Path(__file__).with_suffix(".mjs").read_bytes()
    isolation = read(work / "isolation-probe.json")
    assert isolation == {"privateDenied": True, "networkDenied": True}
    pkg = work / f"piner-{PINER_VERSION}.tgz"
    assert b64encode(sha512(pkg.read_bytes()).digest()).decode("ascii") == PINER_PIN
    with open_tar(pkg, "r:gz") as tar:
        assert (
            tar.extractfile("package/dist/index.js").read()
            == (work / "package/dist/index.js").read_bytes()
        )

    rows, checks, coverage, audits = [], [], [], {}
    receipts = {r["id"]: r for r in read(work / "pnl-table-receipt.json")}
    assert set(receipts) == set(sources) == set(SPECS)
    for ident, (orig, digest, fields, raw, variant, kind) in sources.items():
        raw_path, altered_path = (
            work / f"round26-source-{ident}.pine",
            work / f"pnl-table-variant-{ident}.pine",
        )
        receipt = receipts[ident]
        assert raw_path.read_bytes() == raw and receipt["sourceHash"] == sha256(
            raw_path
        )
        assert altered_path.read_bytes() == variant and receipt[
            "variantHash"
        ] == sha256(altered_path)
        compiler_line = int(
            re.search(
                r"(\d+):\d+: invalid declaration target", receipt["archivedError"]
            )[1]
        )
        assert receipt["metadataLines"] == 7
        assert re.fullmatch(
            rb"strategy\.initial_capital\s*=\s*50000",
            raw.splitlines()[compiler_line + receipt["metadataLines"] - 1].strip(),
        )
        by_case = {(r["window"], r["market"]): r for r in receipt["cases"]}
        assert len(by_case) == len(receipt["cases"]) == 4
        _, _, interval, qty, fee = SPECS[ident]
        details = {
            "id": ident,
            "name": orig["name"],
            "source": orig["source"],
            "source_sha256": digest,
            "executed_source_sha256": receipt["variantHash"],
            "group": GROUP,
            "interval": interval,
            "archive_interval": interval,
            "quote_currency": "USDT",
            "market_data": "Official Binance USD-M OHLCV",
            "exit": "Opposite authored signal at next open",
            "comparison_fee": fee,
        }
        for window, markets in feeds[str(ident)]["windows"].items():
            pooled, terminal = [], 0
            for market, chart in markets.items():
                ledger, opens, note = reconcile(
                    chart, kind, by_case[(window, market)], qty, fee
                )
                pooled.extend(ledger)
                terminal += opens
                checks.append({"id": ident, "period": window, "market": market, **note})
                rows.append(
                    {
                        **details,
                        "period": window,
                        "market": market,
                        **summarize(ledger, opens, CAPITAL),
                    }
                )
            rows.append(
                {
                    **details,
                    "period": window,
                    "market": "BTCUSDT + ETHUSDT",
                    **summarize(pooled, terminal, 2 * CAPITAL),
                }
            )
        audits[ident] = {
            "archive_settings": fields,
            "source_document_sha256": digest,
            "source_pine_sha256": receipt["sourceHash"],
            "executed_source_sha256": receipt["variantHash"],
            "display_only_suffix_sha256": bytes_hasher(
                raw.split(MARKER.encode(), 1)[1]
            ).hexdigest(),
            "fixed_quantity": qty,
            "broker_initial_capital": CAPITAL,
            "display_balance_literal": 50000,
            "archived_compile_error": receipt["archivedError"],
            "fee": fee,
        }
        coverage.append(
            [
                ident,
                f"Tested · {GROUP}",
                "Kept the complete authored trading prefix; a display-only summary failed to compile. Exact signals, fills, costs and terminal positions were reconciled.",
            ]
        )
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(baseline),
            "archive_sha256": FMZ_SHA256,
            "piner_version": PINER_VERSION,
            "piner_tarball_sha512": PINER_PIN,
            "isolation_probe": isolation,
            "artifacts": {
                name: sha256(work / name)
                for name in (
                    "pnl-table-feeds.json",
                    "pnl-table-run.mjs",
                    "pnl-table-receipt.json",
                )
            },
            "provider_archives": manifest,
            "source_audits": audits,
            "per_case_order_counts": checks,
            "method": [
                "A shared reporting appendix writes strategy.initial_capital through an invalid dotted declaration after all order code. Its strategy references only support the display table and there are no order functions in the appendix. The test executes the exact trading prefix with non-trading plot probes.",
                "Pine v5 broker capital uses the documented default of one million where the strategy declaration omits initial_capital. The cosmetic 50,000 literal remains documented. All authors use fixed quantities and v5's default disabled margin check. Strategy 2581 preserves the authored 15 units and 0.1% commission per side; the other two use one unit and 0.059% comparison commission.",
                "The saved December 31 23:59:59 end for 1930 is treated as the final whole hour through midnight. ETH uses its own source-matched history and the next equal windows reset strategy state. Independent Python confirms every signal, position and realized fill. Fee-adjusted P&L uses the same fills and net applies the separate 0.03% per-side execution allowance. Terminal positions remain reported as unsettled.",
            ],
            "references": [
                "https://github.com/binance/binance-public-data",
                "https://www.tradingview.com/support/solutions/43000628599-strategy-properties/",
                "https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-6/#default-margin-percentage",
            ],
            "coverage": coverage,
            "results": rows,
        },
    )
    print(
        f"Verified {len(coverage)} strategy IDs, {len(rows)} workbook rows and {sum(c['closed'] for c in checks)} closes."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "finalize"))
    for name in ("archive", "baseline", "work", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--provider", type=Path, nargs="+", required=True)
    a = parser.parse_args()
    args = a.archive, a.baseline, a.work, a.provider
    if a.mode == "stage":
        stage(*args, persist=True)
    else:
        report(*args, a.output)


if __name__ == "__main__":
    main()
