"""Verify equal-clock request semantics and audit unrepairable order syntax."""

from __future__ import annotations

import argparse
import re
from math import floor, fsum
from pathlib import Path
from shutil import copy2
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, date_ms, sha256, verified_archives
from research.fmz_round7_pine import EXECUTION, FEE, summarize
from research.fmz_round12_pine_authored import provider_bars
from research.fmz_round18_pine_qqe import executable_lines
from research.fmz_round19_pine_broker import equal
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH

IDENT = 4086
PENDING_IDS = (4497, 5772)
CAPITAL = 1000
HOUR = 3_600_000
MARKETS = ("BTCUSDT", "ETHUSDT")
LABEL = {"native": "FMZ native window", "next": "Next equal window"}
GROUP = "FMZ Pine · Equal-clock Ichimoku and Supertrend"
RUNNERS = {
    "r33_trend_probe.py": "fmz_round33_pine_trend_probe.py",
    "r33_martingale_probe.py": "fmz_round33_pine_martingale_probe.py",
}


def sources(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    scope = {IDENT, *PENDING_IDS}
    items = {r["id"]: r for r in read(baseline)["disposition"] if r["id"] in scope}
    assert set(items) == scope and all(
        r["status"].startswith("Pending") for r in items.values()
    )
    output = {}
    with ZipFile(archive) as z:
        for key, row, doc, digest in documents(z, items):
            (raw,) = re.findall(
                r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", doc
            )
            active = "\n".join(executable_lines(raw))
            (archive_url,) = re.findall(r"https://www\.fmz\.com/strategy/[0-9]+", doc)
            if key == IDENT:
                assert "//@version=5" in raw
                expected = (
                    "default_qty_value=80, initial_capital=1000, pyramiding=0",
                    "HTF_TimeFrame = input.timeframe(title='Higher Time Frame', defval='60'",
                    "ema = ta.ema(close, len)",
                    "defval=200",
                    "defval=10",
                    "defval=3.0",
                    "ema[barstate.isrealtime ? 1 : 0]",
                    "[barstate.isrealtime ? 0 : 1]",
                    "_isShow ? f_getDisplacement(_tf) : na",
                    "math.avg(ta.lowest(_len), ta.highest(_len))",
                    "input.int(9,",
                    "input.int(26,",
                    "input.int(52,",
                    "bPriceCloud = input.bool(true",
                    "bPriceCloudBody = input.bool(false",
                    "bPriceEMA = input.bool(false",
                    "bSuper = input.bool(true",
                    "bLTF = input.bool(false",
                    "bEMACloud1 = input.bool(true",
                    "bEMACloud2 = input.bool(false",
                    "bExitHTFTrail = input.bool(true",
                    "bExitLTFTrail = input.bool(true",
                    'strategy.entry("Long", strategy.long)',
                    'strategy.entry("Short", strategy.short)',
                    'strategy.close("Long")',
                    'strategy.close("Short")',
                )
                assert all(s in active for s in expected)
                fields = dict(
                    re.findall(
                        r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)",
                        raw,
                    )
                )
                assert fields == {
                    "start": "2024-01-01 00:00:00",
                    "end": "2024-01-31 23:59:59",
                    "period": "1h",
                    "basePeriod": "15m",
                    "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
                }
            else:
                assert "//@version=4" in raw and raw.count("\u00a0") > 0
                assert len(re.findall(r"(?m)^\s+if useMartin$", raw)) == 2
                assert re.search(r'strategy\.order\(\s*"[^"]+"\s*,\s*"Buy"', raw)
                assert re.search(r'strategy\.order\(\s*"[^"]+"\s*,\s*"Sell"', raw)
                fields = {}
            output[key] = (row, digest, fields, raw.encode(), archive_url)
    return output


def data(public):
    a, b = map(date_ms, ("2024-01-01", "2024-02-01"))
    hi = b * 2 - a
    windows, manifest = {}, []
    for market in MARKETS:
        bars = [
            r
            for p in verified_archives(
                public, market, "1h", ("2024-01", "2024-02", "2024-03"), manifest
            )
            for r in provider_bars(p, HOUR)
            if a <= r[0] < hi
        ]
        assert [r[0] for r in bars] == list(range(a, hi, HOUR))
        for period, lo, end in (("native", a, b), ("next", b, hi)):
            windows.setdefault(period, {})[market] = [
                list(r) for r in bars if lo <= r[0] < end
            ]
    return manifest, windows


def stage(archive, baseline, work, public):
    src = sources(archive, baseline)
    _, feed = data(public)
    (work / "r33-trend-source.pine").write_bytes(src[IDENT][3])
    for ident in PENDING_IDS:
        (work / f"r33-source-{ident}.pine").write_bytes(src[ident][3])
    write(work / "r33-trend-feeds.json", feed)
    for runner, original in RUNNERS.items():
        copy2(Path(__file__).with_name(original), work / runner)


def model(chart, sma_seed):
    high = [r[2] for r in chart]
    low = [r[3] for r in chart]
    close = [r[4] for r in chart]
    cp = None
    tr_raw = []
    lower = upper = atr = None
    direction = 1
    cloud_a = []
    cloud_b = []
    ema = None
    old = None
    for i, (h, l, c) in enumerate(zip(high, low, close, strict=True)):
        atr_input = max(h - l, abs(h - cp), abs(l - cp)) if cp is not None else h - l
        if i < 10:
            tr_raw.append(atr_input)
        if i == 9:
            atr = fsum(tr_raw) / 10
        elif i >= 10:
            atr = (atr * 9 + atr_input) / 10
        if atr is not None:
            u = (h + l) / 2 - 3 * atr
            d = (h + l) / 2 + 3 * atr
            pu = u if lower is None else lower
            pd = d if upper is None else upper
            lower = max(u, pu) if cp > pu else u
            upper = min(d, pd) if cp < pd else d
            direction = (
                1
                if direction < 0 and c > pd
                else -1
                if direction > 0 and c < pu
                else direction
            )

        def midpoint(n, end=i + 1):
            return (
                (min(low[end - n : end]) + max(high[end - n : end])) / 2
                if end >= n
                else None
            )

        a, b = midpoint(9), midpoint(26)
        cloud_a.append((a + b) / 2 if a is not None and b is not None else None)
        cloud_b.append(midpoint(52))
        av, bv = (None, None) if i < 26 else (cloud_a[i - 26], cloud_b[i - 26])
        top, bottom = (
            (None, None) if av is None or bv is None else (max(av, bv), min(av, bv))
        )
        allow = old is not None and top is not None and (old > top or old < bottom)
        go_l = allow and direction == 1 and c > top
        go_s = allow and direction == -1 and c < bottom
        out_l = direction == -1 or (lower is not None and c < lower)
        out_s = direction == 1 or (upper is not None and c > upper)
        if sma_seed and i < 199:
            ema = None
        elif sma_seed and i == 199:
            ema = fsum(close[:200]) / 200
        else:
            ema = c if ema is None else c * (2.0 / 201) + (1.0 - 2.0 / 201) * ema
        yield (
            old,
            direction,
            direction,
            lower,
            upper,
            cloud_a[-1],
            cloud_b[-1],
            go_l,
            go_s,
            out_l,
            out_s,
        )
        old = ema
        cp = c


def broker(chart, states):
    cash = 1000
    direction = 0
    qty = 0
    trade_in = None
    pending = (False, False, False, False)
    history = []
    closed = []
    for i, (bar, step) in enumerate(zip(chart, states, strict=True)):
        _, op, _, _, close, _ = bar
        a, b, x, y = pending
        if direction == 1 and x or direction == -1 and y:
            assert trade_in is not None
            start, price = trade_in
            gross = qty * direction * (op - price)
            fee = qty * (op + price) * FEE
            cash += gross - qty * op * FEE
            closed.append((direction * qty, start, i, price, op, gross - fee))
            direction = 0
            qty = 0
        wanted = 1 if a else -1 if b else 0
        if wanted and direction != wanted:
            assert direction == 0
            budget = float(f"{cash * 0.8:.9e}")
            qty = floor(budget / (op * (1 + FEE)) / 0.001 + 1e-9) * 0.001
            if qty:
                trade_in = (i, op)
                cash -= qty * op * FEE
                direction = wanted
        marked = (
            cash if not direction else cash + direction * qty * (close - trade_in[1])
        )
        history.append((direction * qty, marked))
        pending = step[-4:]
    return history, closed


KEYS = (
    "EMA previous",
    "HTF trend",
    "LTF trend",
    "HTF upper",
    "HTF lower",
    "Cloud A",
    "Cloud B",
    "Long gate",
    "Short gate",
    "Exit long",
    "Exit short",
)


def validate(chart, case, sma_seed):
    values = list(model(chart, sma_seed))
    obs = case["observations"]
    for i, (want, got) in enumerate(
        zip(values, zip(*(obs[k] for k in KEYS), strict=True), strict=True)
    ):
        assert all(equal(a, b) for a, b in zip(want, got, strict=True)), (i, want, got)
    state, closed = broker(chart, values)
    observed = case["strategy"]
    assert not observed["diagnostics"] and not case["source_diagnostics"]
    for i, ((size, equity), r, live_position) in enumerate(
        zip(state, observed["equity"], obs["Position"], strict=True)
    ):
        assert (
            r["barIndex"] == i
            and equal(size, live_position)
            and equal(equity, r["equity"])
        )
    for order in observed["orders"]:
        i = order["barIndex"]
        assert (order["time"], order["price"]) == tuple(chart[i][:2])
    rows = []
    for exp, r in zip(closed, observed["trades"], strict=True):
        fields = (
            "qty",
            "entryBarIndex",
            "exitBarIndex",
            "entryPrice",
            "exitPrice",
            "profit",
        )
        assert all(equal(x, r[k]) for x, k in zip(exp, fields, strict=True))
        q, start, end, p0, p1, _ = exp
        assert r["entryTime"] == chart[start][0] and r["exitTime"] == chart[end][0]
        assert r["id"] == ("Long" if q > 0 else "Short")
        notional = abs(q) * (p0 + p1)
        rows.append(
            (r["exitTime"], q * (p1 - p0), notional * FEE, notional * EXECUTION)
        )
    return (
        rows,
        int(bool(state[-1][0])),
        {
            "gates": [i[-4:] for i in values],
            "closed": len(rows),
            "chart_bars": len(chart),
        },
    )


def compile_audit(path, sources_by_id):
    data = read(path)
    assert len(data) == 6
    output = []
    for ident in PENDING_IDS:
        rows = [r for r in data if r["id"] == ident]
        assert [r["mode"] for r in rows] == [
            "archive bytes",
            "whitespace only",
            "joined nested guard diagnostic",
        ]
        raw, normalized, guard = (r["error"] for r in rows)
        assert "E_LEX_CHAR:" in raw and "E_CALL_ARG_VALUE:" in raw
        assert (
            "expected indented block" in normalized and "E_LEX_CHAR:" not in normalized
        )
        assert "only supports strategy.long or strategy.short" in guard
        source = sources_by_id[ident]
        output.append(
            {
                "id": ident,
                "source_url": source[4],
                "source_document_sha256": source[1],
                "source_file": source[0]["source"],
                "diagnostics": [
                    {
                        "mode": r["mode"],
                        "samples": list(
                            dict.fromkeys(
                                line
                                for line in r["error"].splitlines()
                                if "E_LEX_CHAR" not in line
                            )
                        )[:6],
                        "lexer_error_count": r["error"].count("E_LEX_CHAR"),
                    }
                    for r in rows
                ],
            }
        )
    return output


def report(archive, baseline, work, public, output):
    src = sources(archive, baseline)
    orig, digest, settings, raw, _ = src[IDENT]
    venue, feeds = data(public)
    raw_pine = work / "r33-trend-source.pine"
    assert raw_pine.read_bytes() == raw and read(work / "r33-trend-feeds.json") == feeds
    for ident in PENDING_IDS:
        assert (work / f"r33-source-{ident}.pine").read_bytes() == src[ident][3]
    binary = work / "priced-runtime/pine_compat/pine_compat.pyd"
    assert sha256(binary) == NATIVE_BINARY_HASH
    isolation = read(work / "round3-isolation-python.json")
    assert all(
        isolation[k][0] == "PermissionError" for k in ("file_error", "network_error")
    )
    runner_artifacts = {}
    for runner, source in RUNNERS.items():
        prod = Path(__file__).with_name(source)
        assert prod.read_bytes() == (work / runner).read_bytes()
        runner_artifacts[source] = sha256(prod)
    for label in ("r33_martingale_probe", "r33_trend_exact", "r33_trend_ema"):
        assert (work / f"{label}.exit").read_text().strip() == "0"
    compile_path = work / "r33-martingale-source-diagnostics.json"
    audited = compile_audit(compile_path, src)
    comparisons = {}
    art = {}
    hashes = {}
    for mode in ("exact", "ema shim"):
        p = work / f"r33-trend-{mode}-receipt.json"
        results = read(p)
        cases = {(r["period"], r["market"]): r for r in results}
        assert len(cases) == len(results) == 4
        (h,) = {r["executed_source_sha256"] for r in results}
        assert re.fullmatch("[0-9a-f]{64}", h)
        hashes[mode] = h
        comparisons[mode] = cases
        art[p.name] = sha256(p)
    assert hashes["exact"] != hashes["ema shim"]
    meta = {
        "id": IDENT,
        "name": orig["name"],
        "source": orig["source"],
        "source_sha256": digest,
        "executed_source_sha256": hashes["ema shim"],
        "group": GROUP,
        "interval": "1h",
        "archive_interval": "1h",
        "quote_currency": "USDT",
        "market_data": "Official Binance USD-M hourly OHLCV",
        "exit": "Authored Supertrend break or opposite entry",
        "comparison_fee": FEE,
    }
    metrics, stats = [], []
    for period, markets in feeds.items():
        pooled = []
        terminal = 0
        for market, chart in markets.items():
            key = period, market
            ledger, opened, verified = validate(
                chart, comparisons["ema shim"][key], False
            )
            _, _, reference = validate(chart, comparisons["exact"][key], True)
            gates = verified.pop("gates")
            before = reference["gates"]
            differences = sum(a != b for a, b in zip(gates, before, strict=True))
            assert differences > 0
            stats.append(
                {
                    "id": IDENT,
                    "period": LABEL[period],
                    "market": market,
                    **verified,
                    "reconciled_signal_values": len(KEYS) * len(chart),
                    "diagnostic_sma_seed_closes": reference["closed"],
                    "changed_gate_bars_vs_sma_seed": differences,
                }
            )
            metrics.append(
                {
                    **meta,
                    "period": LABEL[period],
                    "market": market,
                    **summarize(ledger, opened, CAPITAL),
                }
            )
            pooled.extend(ledger)
            terminal += opened
        metrics.append(
            {
                **meta,
                "period": LABEL[period],
                "market": "BTCUSDT + ETHUSDT",
                **summarize(pooled, terminal, 2 * CAPITAL),
            }
        )
    coverage = [
        [
            IDENT,
            f"Tested · {GROUP}",
            "The archived higher-timeframe input matches the saved chart interval. Same-clock request timing and the verified EMA recurrence reproduce the authored order rules.",
        ]
    ]
    coverage.extend(
        [
            [
                ident,
                "Pending · Missing Pine order block structure",
                "Pinned source and the related FMZ author forum example preserve malformed Martin guards and invalid string order directions. Whitespace and speculative scope diagnostics fail. A corrected authored revision is needed.",
            ]
            for ident in PENDING_IDS
        ]
    )
    write(
        output,
        {
            "baseline_coverage_sha256": sha256(baseline),
            "archive_sha256": FMZ_SHA256,
            "pine_compat_binary_sha256": NATIVE_BINARY_HASH,
            "isolation_probe": isolation,
            "runner_hashes": runner_artifacts,
            "provider_archives": venue,
            "source_audit": {
                "document_sha256": digest,
                "archive_settings": settings,
                "executed_hashes": hashes,
            },
            "artifacts": {
                **art,
                **{
                    q.name: sha256(q)
                    for q in (raw_pine, work / "r33-trend-feeds.json", compile_path)
                },
            },
            "source_compile_research": audited,
            "per_case_order_counts": stats,
            "coverage": coverage,
            "results": metrics,
            "references": [
                "https://www.fmz.com/bbs-topic/10237",
                "https://github.com/binance/binance-public-data",
                "https://www.tradingview.com/pine-script-docs/v5/concepts/other-timeframes-and-data/",
                "https://www.tradingview.com/pine-script-reference/v5/#fun_ta.ema",
            ],
            "method": [
                "The 4086 archive selects a 60-minute chart and the authored request input is exactly 60 minutes. Supertrend and Ichimoku therefore access only observations available at that same chart close. The archive's EMA request also applies one explicit historical lag, which the source-compatible projection retains.",
                "Two source probes use common exact feeds and source settings. In the literal reference, Pine Compat seeds EMA with a 200-bar SMA. The projection uses the documented first valid price and recursive EMA, replacing only the proved identity request and keeping its one-bar lag. The literal source is verified separately as an engine diagnostic and excluded from workbook metrics.",
                "An independent implementation reconciles both native probe runs, including Ichimoku 9/26/52 with 26-bar displacement, the active cloud and EMA gates, ATR10×3 Supertrend states, 80% equity sizing with the commission reserve, next-open order prices and realized cashflows. Compare the four scenario closed counts and the seed sensitivity in the audit.",
                "The saved Jan 31 23:59:59 end includes the final January UTC hour. ETH and the next equal windows reset state. A 0.059% fee per side and a separate 0.03% execution allowance are project comparison assumptions.",
                "4497 and 5772 each have two active order blocks with nonbreaking indentation and missing nested bodies. Replacing whitespace still fails. An explicitly diagnostic guard join reaches invalid string directions without supplying any executable statistical result. The related public FMZ forum example retains these issues and provides no corrected recipe.",
            ],
        },
    )
    print(
        f"Verified 4086 with {len(metrics)} workbook rows and {sum(s['closed'] for s in stats)} closed lots. Recorded blockers for {len(PENDING_IDS)} source IDs."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "finalize"))
    for name in ("archive", "baseline", "work", "public", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    ordered = (args.archive, args.baseline, args.work, args.public)
    if args.mode == "stage":
        stage(*ordered)
    else:
        report(*ordered, args.output)


if __name__ == "__main__":
    main()
