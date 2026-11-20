"""Validate the authored Bollinger loop, delayed 4h context and market exits."""

from __future__ import annotations

import argparse
import re
from collections import deque
from math import floor, fsum
from pathlib import Path
from shutil import copy2
from statistics import pstdev
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import (
    FMZ_SHA256,
    aggregate,
    date_ms,
    sha256,
    verified_archives,
)
from research.fmz_round7_pine import EXECUTION, FEE, summarize
from research.fmz_round12_pine_authored import provider_bars
from research.fmz_round18_pine_qqe import executable_lines
from research.fmz_round19_pine_broker import equal
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH

IDENT = 4821
CAPITAL = 1_000_000
HOUR = 3_600_000
MARKETS = ("BTCUSDT", "ETHUSDT")
GROUP = "FMZ Pine · Confirmed 4h trend and native Bollinger/ATR gates"
LABEL = {"native": "FMZ native window", "next": "Next equal window"}
PRODUCER = "fmz_round35_pine_bbe_probe.py"


def record(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (row,) = (i for i in read(baseline)["disposition"] if i["id"] == IDENT)
    assert row["status"].startswith("Pending")
    with ZipFile(archive) as z:
        ((_, original, doc, digest),) = documents(z, {IDENT: row})
    (raw,) = re.findall(r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", doc)
    facts = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)", raw
        )
    )
    assert facts == {
        "start": "2023-09-30 00:00:00",
        "end": "2023-10-30 00:00:00",
        "period": "1h",
        "basePeriod": "15m",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    active = "\n".join(executable_lines(raw))
    assert "//@version=4" in raw and "strategy(title=" not in active
    assert raw.count('// strategy(title="[EURUSD60] BB Expansion Strategy"') == 1
    witnesses = (
        'largeBbRes = input(title="Large BB Resolution", type=input.resolution, defval=""',
        'smallBbRes = input(title="Small BB Resolution ", type=input.resolution, defval=""',
        "defval=40",
        "defval=20",
        "defval=2.0",
        'defval="240"',
        "emaLen = input(14",
        "smooth = input(3",
        "index = barstate.isrealtime ? 1 : 0",
        "base=security(syminfo.tickerid, resFirstTime, ema(close[index],emaLen))",
        "sig=security(syminfo.tickerid, resFirstTime, ema(base[index],smooth))",
        'var riskManagementRule1 = "ATR"',
        "riskManagementRule = input(riskManagementRule1",
        "atrMulti = input(3.0",
        "riskRewardRatio = input(1.5",
        "atr_ = atr(14) * atrMulti",
        'validLen = input(title="BB expand valid length", defval=14',
        "for i=0 to validLen",
        "isBbEntry := bbTrade==true ? true : bbTrade[i]==true ? true : false",
        'strategy.entry("LongEntry", strategy.long',
        'strategy.entry("ShortEntry", strategy.short',
        'strategy.close("LongEntry", when=isAtrLongStop',
        'strategy.close("ShortEntry", when=isAtrShortStop',
        'strategy.close("LongEntry", when=isAtrLongLimit',
        'strategy.close("ShortEntry", when=isAtrShortLimit',
    )
    assert all(f in active for f in witnesses)
    return original, digest, facts, raw.encode()


def market_feeds(public):
    a, b = map(date_ms, ("2023-09-30", "2023-10-30"))
    hi = b * 2 - a
    cases, manifest = {}, []
    for market in MARKETS:
        zips = verified_archives(
            public, market, "1h", ("2023-09", "2023-10", "2023-11"), manifest
        )
        full = [r for path in zips for r in provider_bars(path, HOUR) if a <= r[0] < hi]
        assert [r[0] for r in full] == list(range(a, hi, HOUR))
        for label, lo, end in (("native", a, b), ("next", b, hi)):
            main = [r for r in full if lo <= r[0] < end]
            cases.setdefault(label, {})[market] = {
                "chart": [list(r) for r in main],
                "ref": [list(r) for r in aggregate(main, 4)],
            }
    return manifest, cases


def stage(archive, baseline, work, public):
    _, _, _, raw = record(archive, baseline)
    _, data = market_feeds(public)
    (work / "r35-bbe-source.pine").write_bytes(raw)
    write(work / "r35-bbe-feeds.json", data)
    copy2(Path(__file__).with_name(PRODUCER), work / "r35_bbe_probe.py")


def ema(vals, length, sma_seed):
    view = deque(maxlen=length)
    point = None
    weight = 2 / (length + 1)
    for value in vals:
        if value is not None:
            view.append(value)
            if point is not None:
                point = weight * value + (1 - weight) * point
            elif not sma_seed:
                point = value
            elif len(view) == length:
                point = fsum(view) / length
        yield point


def bands(closes, n):
    buf = deque(maxlen=n)
    for p in closes:
        buf.append(p)
        if len(buf) == n:
            mean = fsum(buf) / n
            width = 2 * pstdev(buf)
            yield mean, mean + width, mean - width
        else:
            yield None, None, None


def replay(tape, sma_seed):
    chart = tape["chart"]
    close = [b[4] for b in chart]
    big, small = list(bands(close, 40)), list(bands(close, 20))
    base = list(ema([bar[4] for bar in tape["ref"]], 14, sma_seed))
    signal = list(ema(base, 3, sma_seed))
    exp = []
    shares = []
    trades = []
    side = 0
    pending = 0
    close_next = False
    entry = None
    all_ranges = []
    for i, (t, o, h, l, c, _) in enumerate(chart):
        if side and close_next:
            ix, p = entry
            trades.append((side, ix, i, p, o))
            side = 0
        if pending and side != pending:
            if side:
                ix, p = entry
                trades.append((side, ix, i, p, o))
            side = pending
            entry = (i, o)
        offset = (i + 1) // 4 - 1
        b, s = (base[offset], signal[offset]) if offset >= 0 else (None, None)
        ema_up = b is not None and s is not None and b >= s
        ema_down = b is not None and s is not None and b < s
        avg_large, upper_big, lower_big = big[i]
        avg_small, upper_small, lower_small = small[i]
        cur = (
            avg_large is not None
            and upper_big < upper_small
            and lower_big > lower_small
        )
        prior = exp[i - 14] if i >= 14 else False
        exp.append(cur)
        allow = cur or prior
        go_buy = allow and o < avg_small and c > avg_small and ema_up
        go_sell = allow and o > avg_small and c < avg_small and ema_down
        last = close[i - 1] if i else c
        all_ranges.append(max(h - l, abs(h - last), abs(l - last)))
        if i == 13:
            atr = fsum(all_ranges) / 14
        if i > 13:
            atr = (atr * 13 + all_ranges[-1]) / 14
        if side:
            stop = shares[-1][6 if side == 1 else 7] if shares else None
            target = shares[-1][8 if side == 1 else 9] if shares else None
            if stop is None:
                stop = floor((c - side * atr * 3) * 1000 + 0.5) / 1000
                target = c + side * atr * 4.5
        else:
            stop = target = None
        if side > 0:
            long_stop, long_target = stop, target
            short_stop = short_target = None
            out_long = l <= stop or h >= target
            out_short = False
        elif side < 0:
            short_stop, short_target = stop, target
            long_stop = long_target = None
            out_short = h >= stop or l <= target
            out_long = False
        else:
            short_stop, short_target, long_stop, long_target = None, None, None, None
            out_long = out_short = False
        shares.append(
            (
                avg_large,
                avg_small,
                allow,
                b,
                s,
                go_buy,
                long_stop,
                short_stop,
                long_target,
                short_target,
                out_long,
                out_short,
                go_sell,
                side,
            )
        )
        assert not (go_buy and go_sell)
        pending = 1 if go_buy else -1 if go_sell else 0
        close_next = out_long or out_short
    return shares, trades


PLOTS = (
    "Big mean",
    "Small mean",
    "BB eligible",
    "Trend base",
    "Trend signal",
    "Buy",
    "Stop long",
    "Stop short",
    "Target long",
    "Target short",
    "Exit long",
    "Exit short",
    "Sell",
    "Position",
)


def verify(payload, case, sma_seed):
    states, fills = replay(payload, sma_seed)
    assert not case["diagnostics"] and not case["strategy"]["diagnostics"]
    for index, (expected, actual) in enumerate(
        zip(states, zip(*(case["plots"][k] for k in PLOTS), strict=True), strict=True)
    ):
        assert all(equal(a, b) for a, b in zip(expected, actual, strict=True)), (
            index,
            expected,
            actual,
        )
    candles = payload["chart"]
    assert all(
        (r["time"], r["price"]) == tuple(candles[r["barIndex"]][:2])
        for r in case["strategy"]["orders"]
    )
    ledger = []
    for model, native in zip(fills, case["strategy"]["trades"], strict=True):
        side, i, j, entry, exit = model
        fields = ("qty", "entryBarIndex", "exitBarIndex", "entryPrice", "exitPrice")
        assert model == tuple(native[k] for k in fields)
        assert (native["entryTime"], native["exitTime"]) == (
            candles[i][0],
            candles[j][0],
        )
        assert native["id"] == ("LongEntry" if side > 0 else "ShortEntry")
        turnover = entry + exit
        fee = turnover * FEE
        gross = side * (exit - entry)
        assert equal(native["profit"], gross - fee)
        ledger.append((candles[j][0], gross, fee, turnover * EXECUTION))
    return (
        ledger,
        int(bool(states[-1][-1])),
        {
            "closed": len(ledger),
            "chart_bars": len(states),
            "orders": len(case["strategy"]["orders"]),
            "eligible_expansion_bars": sum(r[2] for r in states),
            "terminal_position": states[-1][-1],
            "verified_output_values": len(states) * len(PLOTS),
        },
    )


def report(archive, baseline, work, public, output):
    datum, digest, facts, raw = record(archive, baseline)
    manifest, data = market_feeds(public)
    core = work / "r35-bbe-source.pine"
    feed = work / "r35-bbe-feeds.json"
    assert core.read_bytes() == raw and read(feed) == data
    assert (
        sha256(work / "priced-runtime/pine_compat/pine_compat.pyd")
        == NATIVE_BINARY_HASH
    )
    isolation = read(work / "round3-isolation-python.json")
    assert all(
        isolation[k][0] == "PermissionError" for k in ("file_error", "network_error")
    )
    runner = Path(__file__).with_name(PRODUCER)
    assert runner.read_bytes() == (work / "r35_bbe_probe.py").read_bytes()
    artifacts = [core, feed, runner]
    receipts, hashes = {}, {}
    for name in ("native", "firstseed"):
        path = work / f"r35-bbe-{name}.json"
        assert (work / f"r35-bbe-{name}.exit").read_text().strip() == "0"
        artifacts.append(path)
        raw_cases = read(path)
        index = {(r["period"], r["market"]): r for r in raw_cases}
        assert len(index) == len(raw_cases) == 4
        (hashes[name],) = {r["executed_source_sha256"] for r in raw_cases}
        receipts[name] = index
    assert hashes["native"] != hashes["firstseed"]
    meta = {
        "id": IDENT,
        "name": datum["name"],
        "source": datum["source"],
        "source_sha256": digest,
        "executed_source_sha256": hashes["firstseed"],
        "group": GROUP,
        "interval": "1h",
        "archive_interval": "1h",
        "quote_currency": "USDT",
        "comparison_fee": FEE,
        "market_data": "Official Binance USD-M hourly and aggregated four-hour OHLCV",
        "exit": "Default ATR stop or target flag, or opposite entry at next open",
    }
    stats, rows = [], []
    for period, assets in data.items():
        combined = []
        terminal = 0
        for symbol, sample in assets.items():
            scope = period, symbol
            ledger, opened, counts = verify(sample, receipts["firstseed"][scope], False)
            _, _, fallback = verify(sample, receipts["native"][scope], True)
            stats.append(
                {
                    "id": IDENT,
                    "period": LABEL[period],
                    "market": symbol,
                    **counts,
                    "diagnostic_sma_seed_closes": fallback["closed"],
                }
            )
            rows.append(
                {
                    **meta,
                    "period": LABEL[period],
                    "market": symbol,
                    **summarize(ledger, opened, CAPITAL),
                }
            )
            terminal += opened
            combined.extend(ledger)
        rows.append(
            {
                **meta,
                "period": LABEL[period],
                "market": "BTCUSDT + ETHUSDT",
                **summarize(combined, terminal, 2 * CAPITAL),
            }
        )
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(baseline),
            "archive_sha256": FMZ_SHA256,
            "pine_compat_binary_sha256": NATIVE_BINARY_HASH,
            "isolation_probe": isolation,
            "source_audit": {
                "document_sha256": digest,
                "archive_settings": facts,
                "commented_source_declaration_reinstated": True,
                "executed_variants_sha256": hashes,
            },
            "provider_archives": manifest,
            "artifacts": {p.name: sha256(p) for p in artifacts},
            "per_case_order_counts": stats,
            "method": [
                "The archive left its only strategy declaration commented while retaining active order calls. The harness reinstates that authored declaration with explicit Pine default capital and the project comparison fee. The original Pine v4 source otherwise supplies both nested trend requests and all Bollinger, threshold, and order rules.",
                "The literal engine probe establishes that the nested requests use the same confirmed four-hour clock. In the workbook run, EMA starts at its first valid price. Its EMA14 then EMA3 outputs are sampled from completed four-hour candles only. An independently implemented chronology matches both the literal SMA-seeded engine diagnostic and the documented first-price EMA projection. The diagnostic provides no workbook performance rows.",
                "Each chart has the source 40/20 Bollinger pair and a literal loop whose last assignment uses the current signal or its 14-bar history. The default ATR mode sets fixed stop/target reference levels at the first bar where the position exists. Confirmed chart highs or lows then generate next-open market exits. The inactive priced-bracket mode contributes no orders.",
                "Both BTCUSDT and ETHUSDT use official Binance USD-M candles. The next equal windows reset strategy state. Fixed one-unit orders, 0.059% per-side comparison fee and 0.03% per-side separate execution buffer apply. All recorded fills use the actual market open. Any terminal holding remains unsettled.",
            ],
            "references": [
                "https://www.fmz.com/strategy/430678",
                "https://www.tradingview.com/pine-script-docs/language/script-structure/#declaration-statement",
                "https://www.tradingview.com/pine-script-docs/v5/concepts/other-timeframes-and-data/",
                "https://www.tradingview.com/pine-script-reference/v5/#fun_ta.ema",
                "https://github.com/binance/binance-public-data",
            ],
            "coverage": [
                [
                    IDENT,
                    f"Tested · {GROUP}",
                    "Restored the archived declaration and matched original static request timing, source-default Bollinger and ATR gates, then verified each fill independently.",
                ]
            ],
            "results": rows,
        },
    )
    print(
        f"Verified {IDENT}: {len(rows)} workbook rows and {sum(s['closed'] for s in stats)} closed lots."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "finalize"))
    for name in ("archive", "baseline", "work", "public", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    a = parser.parse_args()
    ordered = (a.archive, a.baseline, a.work, a.public)
    if a.mode == "stage":
        stage(*ordered)
    else:
        report(*ordered, a.output)


if __name__ == "__main__":
    main()
