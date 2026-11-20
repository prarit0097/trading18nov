"""Stage verified FMZ/Binance inputs and reconcile isolated Piner replay receipts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from itertools import chain, pairwise
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

FMZ_SHA256 = "a231a84e9f994446fe8a2ba89a7fda15e804b02f175c0bf608214a7f55295a9f"
PINER_INTEGRITY = "wyZp7irvRiBBoSkLINDqufqRsc6rZH7uoIwk1dZHlKIkLBz+fpeBi7mbgumRxiyBNZf2dN6YmiE6swRhWE9wNw=="
IDS = (59, 3254, 3843, 4167, 4601, 4721, 5117, 5514, 5520, 5540)
TESTED = (59, 3254, 3843, 4167, 4601)
SYMBOLS = ("BTCUSDT", "ETHUSDT")
HOUR_MONTHS = tuple(
    f"{y}-{m:02}" for y, n in ((2025, 12), (2026, 10)) for m in range(1, n + 1)
)
MINUTE_MONTHS = ("2026-08", "2026-09", "2026-10")
FRAMES = {
    "D-60": (
        86_400_000,
        3_600_000,
        (("2025-01-01", "2026-01-01"), ("2026-01-01", "2026-11-01")),
    ),
    "60-10": (
        3_600_000,
        600_000,
        (("2026-08-01", "2026-09-01"), ("2026-09-01", "2026-11-01")),
    ),
}


def read(path):
    return json.loads(path.read_bytes())


def write(path, data):
    path.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def date_ms(date):
    return int(datetime.fromisoformat(date).replace(tzinfo=UTC).timestamp() * 1000)


def iso_day(epoch):
    return datetime.fromtimestamp(epoch / 1000, UTC).date().isoformat()


def archive_sources(work, archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    pending = {
        r["id"]: r
        for r in read(baseline)["disposition"]
        if not r["status"].startswith(("Tested", "Excluded"))
    }
    cases = []
    with ZipFile(archive) as source:
        for ident in IDS:
            row = pending[ident]
            ref, name = unquote(row["source"].split("/blob/", 1)[1]).split("/", 1)
            data = source.read(f"strategies-{ref}/{name}")
            [block] = re.findall(
                r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}",
                data.decode("utf-8-sig"),
            )
            code = re.sub(r"(?m)//[^\n]*", "", block)
            assert re.search(r"\buse_bar_magnifier\s*=\s*true\b", code)
            cases.append(
                {
                    "id": ident,
                    "source": row["source"],
                    "source_sha256": hashlib.sha256(data).hexdigest(),
                    "script_sha256": hashlib.sha256(block.encode()).hexdigest(),
                    "period": re.search(r"(?m)^period:\s*(\S+)", block)[1],
                    "basePeriod": re.search(r"(?m)^basePeriod:\s*(\S+)", block)[1],
                    "pine_header": re.findall(
                        r"(?m)^\s*//\s*@version\s*=\s*(\d+)", block
                    ),
                    "prior_reason": row["reason"],
                }
            )
            (work / f"source-{ident}.pine").write_bytes(block.encode())
    write(work / "source-audit.json", cases)


def raw_ohlcv(path, step):
    with ZipFile(path) as archive:
        [name] = archive.namelist()
        with archive.open(name) as src:
            for row in csv.reader(io.TextIOWrapper(src, encoding="ascii")):
                if row[0].isdigit():
                    t = int(row[0])
                    o, h, low, c, volume = map(float, row[1:6])
                    assert int(row[6]) == t + step - 1
                    assert 0 < low <= min(o, c) <= max(o, c) <= h and volume > 0
                    yield t, o, h, low, c, volume


def aggregate(rows, span):
    assert span > 0 and len(rows) % span == 0
    bars = []
    for k in range(0, len(rows), span):
        group = rows[k : k + span]
        t, o = group[0][:2]
        bars.append(
            (
                t,
                o,
                max(x[2] for x in group),
                min(x[3] for x in group),
                group[-1][4],
                math.fsum(x[5] for x in group),
            )
        )
    return bars


def verified_archives(public, symbol, interval, months, manifest):
    files = []
    for month in months:
        name = f"{symbol}-{interval}-{month}.zip"
        path = public / name
        digest = sha256(path)
        assert (public / f"{name}.CHECKSUM").read_text().split() == [digest, name]
        url = f"https://data.binance.vision/data/futures/um/monthly/klines/{symbol}/{interval}/{name}"
        manifest.append({"name": name, "sha256": digest, "url": url})
        files.append(path)
    return files


def prepare_data(work, public):
    manifest = []
    for symbol in SYMBOLS:
        source = {}
        for step, interval, months in (
            (3_600_000, "1h", HOUR_MONTHS),
            (60_000, "1m", MINUTE_MONTHS),
        ):
            files = verified_archives(public, symbol, interval, months, manifest)
            candles = list(chain.from_iterable(raw_ohlcv(f, step) for f in files))
            assert all(b[0] == a[0] + step for a, b in pairwise(candles))
            source[step] = candles
        for key, (chart_step, ltf_step, windows) in FRAMES.items():
            step = 3_600_000 if key.startswith("D") else 60_000
            chart, target = key.split("-")
            for first, last in windows:
                start, end = date_ms(first), date_ms(last)
                rows = [c for c in source[step] if start <= c[0] < end]
                assert rows[0][0] == start and len(rows) * step == end - start
                lower = aggregate(rows, ltf_step // step)
                assert len(lower) <= 200_000
                payload = {
                    "symbol": symbol,
                    "chartTimeframe": chart,
                    "targetTimeframe": target,
                    "chartMs": chart_step,
                    "ltfMs": ltf_step,
                    "from": start,
                    "to": end,
                    "chart": aggregate(rows, chart_step // step),
                    "intrabar": lower,
                }
                # The compact encoding is part of the replay's input digest.
                path = work / f"feed-{symbol}-{key}-{first}.json"
                path.write_bytes(json.dumps(payload, separators=(",", ":")).encode())
    write(work / "data-manifest.json", manifest)


def reconcile_aggregate_trades(source, minute, start):
    """Check whether the published aggregate events reconstruct all minute OHLCV."""
    end = start + 86_400_000
    with ZipFile(minute) as archive:
        [name] = archive.namelist()
        with archive.open(name) as stream:
            records = csv.reader(io.TextIOWrapper(stream, encoding="ascii"))
            expected = {
                int(r[0]): tuple(map(Decimal, r[1:6]))
                for r in records
                if r[0].isdigit() and start <= int(r[0]) < end
            }
    assert list(expected) == list(range(start, end, 60_000))
    ten_seconds = {}
    count = gaps = 0
    last_id = last_time = None
    with ZipFile(source) as archive:
        [name] = archive.namelist()
        with archive.open(name) as stream:
            for row in csv.DictReader(io.TextIOWrapper(stream, encoding="ascii")):
                t, ident = int(row["transact_time"]), int(row["agg_trade_id"])
                price, qty = Decimal(row["price"]), Decimal(row["quantity"])
                assert price > 0 and qty > 0 and start <= t < end
                assert last_time is None or t >= last_time
                assert int(row["last_trade_id"]) >= int(row["first_trade_id"])
                if last_id is not None:
                    assert ident > last_id
                    gaps += ident - last_id - 1
                last_time, last_id = t, ident
                bucket = t // 10_000 * 10_000
                if bucket not in ten_seconds:
                    ten_seconds[bucket] = [price, price, price, price, qty]
                else:
                    candle = ten_seconds[bucket]
                    candle[1] = max(candle[1], price)
                    candle[2] = min(candle[2], price)
                    candle[3] = price
                    candle[4] += qty
                count += 1
    assert list(ten_seconds) == list(range(start, end, 10_000))
    mismatches = []
    for stamp, row in expected.items():
        slices = [ten_seconds[t] for t in range(stamp, stamp + 60_000, 10_000)]
        reconstructed = (
            slices[0][0],
            max(x[1] for x in slices),
            min(x[2] for x in slices),
            slices[-1][3],
            sum(x[4] for x in slices),
        )
        if reconstructed != row:
            mismatches.append(
                {
                    "minute": stamp,
                    "same_ohlc": reconstructed[:4] == row[:4],
                    "volume_offset": str(reconstructed[4] - row[4]),
                }
            )
    return {
        "observed_aggregate_trades": count,
        "aggregate_id_gaps": gaps,
        "ten_second_bars": len(ten_seconds),
        "one_minute_bars": len(expected),
        "mismatch_count": len(mismatches),
        "examples": mismatches[:5],
    }


def check_trade_data(work, public):
    evidence = []
    manifest = []
    for symbol in SYMBOLS:
        for day, window in (("2026-10-01", "2026-10"), ("2026-11-01", "2026-11-01")):
            minute_name = f"{symbol}-1m-{window}.zip"
            trade_name = f"{symbol}-aggTrades-{day}.zip"
            minute_kind = "monthly" if len(window) == 7 else "daily"
            candle_url = f"https://data.binance.vision/data/futures/um/{minute_kind}/klines/{symbol}/1m/{minute_name}"
            trade_url = f"https://data.binance.vision/data/futures/um/daily/aggTrades/{symbol}/{trade_name}"
            for name, url in ((minute_name, candle_url), (trade_name, trade_url)):
                dig = sha256(public / name)
                assert (public / f"{name}.CHECKSUM").read_text().split() == [dig, name]
                manifest.append({"name": name, "sha256": dig, "url": url})
            evidence.append(
                dict(
                    symbol=symbol,
                    date=day,
                    **reconcile_aggregate_trades(
                        public / trade_name,
                        public / minute_name,
                        date_ms(day),
                    ),
                )
            )
    write(work / "trade-validation.json", evidence)
    write(work / "trade-manifest.json", manifest)


def ledger_metrics(trades, capital, unsettled):
    by_time = defaultdict(lambda: [0.0, 0.0])
    gross = fees = 0.0
    gross_wins = fee_wins = 0
    for t in trades:
        g = t["dir"] * t["qty"] * (t["exitPrice"] - t["entryPrice"])
        fee = t["commission"]
        net = g - fee
        assert math.isclose(net, t["profit"], rel_tol=1e-9, abs_tol=1e-8)
        by_time[t["exitTime"]][0] += g
        by_time[t["exitTime"]][1] += net
        gross += g
        fees += fee
        gross_wins += g > 1e-9
        fee_wins += net > 1e-9
    drawdown = [0.0, 0.0]
    equity = [capital, capital]
    peak = [capital, capital]
    net_dd_pct = 0.0
    for stamp in sorted(by_time):
        for i, pnl in enumerate(by_time[stamp]):
            equity[i] += pnl
            peak[i] = max(peak[i], equity[i])
            drawdown[i] = max(drawdown[i], peak[i] - equity[i])
        net_dd_pct = max(net_dd_pct, (peak[1] - equity[1]) / peak[1])
    return {
        "trades": len(trades),
        "unsettled": unsettled,
        "gross_wins": gross_wins,
        "fee_wins": fee_wins,
        "net_wins": fee_wins,
        "gross": gross,
        "after_fees": gross - fees,
        "net": gross - fees,
        "fees": fees,
        "execution": 0.0,
        "gross_dd": drawdown[0],
        "fee_dd": drawdown[1],
        "net_dd": drawdown[1],
        "net_dd_pct": net_dd_pct,
    }


def replay_rows(archive, source):
    assert tuple(x["id"] for x in archive) == TESTED
    results = []
    summaries = []
    for item in archive:
        ident = item["id"]
        assert (
            item["verified"] and item["sourceSha256"] == source[ident]["source_sha256"]
        )
        assert item["scriptSha256"] == source[ident]["script_sha256"]
        windows = defaultdict(list)
        for case in sorted(item["runs"], key=lambda r: (r["from"], r["symbol"])):
            b = case["report"]["barMagnifier"]
            assert (
                case["bothBackendsEqual"]
                and b["active"]
                and b["coverage"] == "complete"
            )
            assert (
                b["fallbackBars"] == b["capFallbackBars"] == b["dataFallbackBars"] == 0
            )
            assert b["magnifiedBars"] > 0 and b["intrabarsUsed"] > b["magnifiedBars"]
            windows[case["from"], case["to"]].append(case)
        assert len(windows) == 2
        for (start, end), cases in sorted(windows.items()):
            assert tuple(x["symbol"] for x in cases) == SYMBOLS
            chart, ltf = cases[0]["chart"], cases[0]["target"]
            common = {
                "id": ident,
                "group": f"FMZ · Piner Bar Magnifier {chart}→{ltf}",
                "exit": "Archived Pine exits",
                "period": f"Binance USD-M · {iso_day(start)} to {iso_day(end)} UTC exclusive",
                "archive_interval": chart,
                "interval": chart,
                "currency": "USDT",
            }
            pooled = []
            capital = unsettled = 0
            for case in cases:
                r = case["report"]
                trades = r["closedTrades"]
                pooled.extend(trades)
                capital += r["initialCapital"]
                unsettled += case["entries"]
                summary = {k: v for k, v in case.items() if k != "report"}
                summary.update(
                    id=ident,
                    engine_magnifier=r["barMagnifier"],
                    broker_drawdown=r["maxDrawdown"],
                    broker_net_profit=r["netProfit"],
                    broker_commission=r["totalCommission"],
                    margin_calls=r["marginCalls"],
                    realized_trades=len(trades),
                    initial_capital=r["initialCapital"],
                )
                summaries.append(summary)
                results.append(
                    dict(
                        **common,
                        market=case["symbol"],
                        **ledger_metrics(trades, r["initialCapital"], case["entries"]),
                    )
                )
            results.append(
                dict(
                    **common,
                    market="BTCUSDT + ETHUSDT",
                    **ledger_metrics(pooled, capital, unsettled),
                )
            )
    return results, summaries


def final_report(work, output):
    source_file = work / "source-audit.json"
    source = {r["id"]: r for r in read(source_file)}
    replay_file = work / f"replay-{'-'.join(map(str, TESTED))}.json"
    raw = read(replay_file)
    results, runs = replay_rows(raw, source)
    assert len(results) == 6 * len(TESTED)
    for case in runs:
        symbol, chart, target, first = (
            case["symbol"],
            case["chart"],
            case["target"],
            iso_day(case["from"]),
        )
        feed = work / f"feed-{symbol}-{chart}-{target}-{first}.json"
        assert sha256(feed) == case["sha256"]
    reasons = {
        5520: (
            "Pending · Magnifier and execution recalculation",
            "Archived calc_on_order_fills=true deactivates Piner magnification and falls back to chart OHLC.",
        ),
        5540: (
            "Pending · USD account conversion",
            (
                "Archived USD account sizing is omitted by Piner for the USDT instrument. "
                "The public aggregate-trade archive does not exactly reproduce the official minute candles."
            ),
        ),
    }
    for ident in (4721, 5117, 5514):
        reasons[ident] = (
            "Pending · Original limit verification",
            "Archived one-tick limit verification is ignored by Piner 0.13.0 in its broker fixture.",
        )
    coverage = []
    for ident in IDS:
        if ident in TESTED:
            note = (
                "Pinned archived settings, checksum-verified Binance USD-M data, and identical Piner JS/interpreter "
                "results with zero magnifier fallback. Only FMZ host metadata stripped."
            )
            if ident in (3254, 3843):
                note += " Distinct archive sources produced identical trades across the selected windows."
            coverage.append([ident, "Tested · Piner Bar Magnifier", note])
        else:
            coverage.append([ident, *reasons[ident]])
    fixture = read(work / "fixture.json")
    isolation = read(work / "isolation-probe.json")
    settings_fixture = read(work / "settings-fixture.json")
    assert fixture["verified"] and all(isolation.values())
    assert settings_fixture["control"] == settings_fixture["requiresOneTick"]
    assert settings_fixture["baseUsd"] == settings_fixture["baseEur"]
    data = read(work / "data-manifest.json")
    trade_checks = read(work / "trade-validation.json")
    assert len(trade_checks) == 4 and all(x["mismatch_count"] > 0 for x in trade_checks)
    data += read(work / "trade-manifest.json")
    unique = {r["url"]: r for r in data}
    json_report = {
        "schema": "Round 7 Piner Bar Magnifier checkpoint",
        "piner_version": "0.13.0",
        "piner_package_sha512": PINER_INTEGRITY,
        "source_archive_sha256": FMZ_SHA256,
        "archive_records": list(source.values()),
        "source_replay_settings": {item["id"]: item["settings"] for item in raw},
        "raw_replay_sha256": sha256(replay_file),
        "fixture": fixture,
        "isolation": isolation,
        "setting_fixture": settings_fixture,
        "compile_probe_sha256": sha256(work / "compile-probe.json"),
        "compiler_warnings": {x["id"]: x["warnings"] for x in raw},
        "trade_data_check": trade_checks,
        "inputs": list(unique.values()),
        "summary": {
            "audited_ids": len(IDS),
            "verified": len(TESTED),
            "pending": len(reasons),
            "workbook_rows": len(results),
            "asset_window_runs": len(runs),
            "chart_bars_checked": sum(
                r["engine_magnifier"]["magnifiedBars"] for r in runs
            ),
            "intrabars_used": sum(r["engine_magnifier"]["intrabarsUsed"] for r in runs),
            "fallback_bars": 0,
        },
        "coverage": coverage,
        "results": results,
        "runs": runs,
        "scope_note": (
            "Gross trade P&L uses the archived broker's fill prices and therefore includes source slippage. "
            "Ledger drawdown uses closed trades; broker intrabar drawdown is preserved separately. "
            "Windows are independent starts. Funding is outside the Piner broker model."
        ),
    }
    write(output, json_report)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="command", required=True)
    stage = sub.add_parser("stage")
    stage.add_argument("work", type=Path)
    stage.add_argument("public", type=Path)
    stage.add_argument("fmz_archive", type=Path)
    stage.add_argument("baseline", type=Path)
    final = sub.add_parser("finalize")
    final.add_argument("work", type=Path)
    final.add_argument("output", type=Path)
    trade = sub.add_parser("check-trades")
    trade.add_argument("work", type=Path)
    trade.add_argument("public", type=Path)
    args = cli.parse_args()
    if args.command == "stage":
        args.work.mkdir(parents=True, exist_ok=True)
        archive_sources(args.work, args.fmz_archive, args.baseline)
        prepare_data(args.work, args.public)
    elif args.command == "finalize":
        final_report(args.work, args.output)
    else:
        check_trade_data(args.work, args.public)
