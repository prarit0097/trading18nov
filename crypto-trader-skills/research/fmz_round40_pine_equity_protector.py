"""Pin the source-active equity-protector balance ambiguity on public futures data."""

from __future__ import annotations

import argparse
import re
from math import isclose
from pathlib import Path
from shutil import copy2
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, aggregate, date_ms, sha256
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH
from research.fmz_round28_pine_callback import cache_bars

IDENT = 3820
M1 = 60_000
M10 = 10 * M1
MODES = ("declared", "separate", "capital", "firstseed")
PROBE = "fmz_round40_pine_equity_protector_probe.py"


def source_record(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (row,) = (r for r in read(baseline)["disposition"] if r["id"] == IDENT)
    assert row["status"].startswith("Pending")
    with ZipFile(archive) as book:
        ((_, _, doc, checksum),) = documents(book, {IDENT: row})
    (raw,) = re.findall(r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", doc)
    settings = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)", raw
        )
    )
    assert settings == {
        "start": "2023-09-16 00:00:00",
        "end": "2023-10-16 00:00:00",
        "period": "10m",
        "basePeriod": "1m",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    assert raw.count("strategy.initial_capital = 50000") == 1
    for witness in (
        'strategy("EURUSD 1min strat RISK %% ", overlay=false, initial_capital = 1000)',
        "balance = strategy.netprofit + strategy.initial_capital",
        "floating = strategy.openprofit",
        'equity_protector = input(1 ,type=input.float, title="Equity Protection %")/100',
        "if(floating<0 and abs(floating/balance)>equity_protector)",
        'strategy.close_all(equity_stopout, comment="equity sl", alert_message = "equity_sl")',
        'strategy.entry("long",true,oca_name="a",when=longCondition and not is_open)',
        'strategy.entry("short",false,oca_name="a",when=shortCondition and not is_open)',
        "//and time_cond",
    ):
        assert witness in raw, witness
    link = re.search(r"https://www\.fmz\.com/strategy/\d+", doc)[0]
    return raw.encode(), settings, checksum, link


def market_data(cache):
    start, boundary = map(date_ms, ("2023-09-16", "2023-10-16"))
    end = 2 * boundary - start
    feeds, manifest = {}, []
    months = ("2023-09", "2023-10", "2023-11")
    for symbol in ("BTCUSDT", "ETHUSDT"):
        minute = [
            r
            for r in cache_bars(cache, symbol, "1m", months, M1, manifest)
            if start <= r[0] < end
        ]
        assert [r[0] for r in minute] == list(range(start, end, M1))
        for mode, lo, hi in (("native", start, boundary), ("next", boundary, end)):
            part = [r for r in minute if lo <= r[0] < hi]
            chart = [list(r) for r in aggregate(part, 10)]
            assert [r[0] for r in chart] == list(range(lo, hi, M10))
            feeds.setdefault(mode, {})[symbol] = {"chart": chart}
    return feeds, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "finalize"))
    for key in ("archive", "baseline", "work", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    parser.add_argument("--cache", type=Path, nargs="+", required=True)
    a = parser.parse_args()
    raw, settings, checksum, link = source_record(a.archive, a.baseline)
    feeds, manifest = market_data(a.cache)
    source = a.work / "r40-eur-source.pine"
    candles = a.work / "r40-eur-feeds.json"
    producer = Path(__file__).with_name(PROBE)
    staged = a.work / "r40_eur_probe.py"
    if a.mode == "stage":
        source.write_bytes(raw)
        write(candles, feeds)
        copy2(producer, staged)
        return
    assert source.read_bytes() == raw and read(candles) == feeds
    assert producer.read_bytes() == staged.read_bytes()
    assert (
        sha256(a.work / "priced-runtime/pine_compat/pine_compat.pyd")
        == NATIVE_BINARY_HASH
    )
    isolation = read(a.work / "round3-isolation-python.json")
    assert all(
        isolation[k][0] == "PermissionError" for k in ("file_error", "network_error")
    )
    error = a.work / "r40-eur-literal-error.txt"
    literal_error = error.read_text().splitlines()[-1]
    assert literal_error == "ValueError: E_PARSE_EXPR:Error:198:26: expected expression"
    responses, hashes, audits = {}, {}, []
    files = [error, source, candles, producer]
    for mode in MODES:
        result = a.work / f"r40-eur-{mode}.json"
        files.append(result)
        rows = read(result)
        assert len(rows) == 4
        (hashes[mode],) = {r["executed_source_sha256"] for r in rows}
        responses[mode] = {(r["period"], r["market"]): r for r in rows}
        for r in rows:
            assert not r["diagnostics"]
            plot = r["plots"]
            orderbook = r["strategy"]
            warmup = sum(v is None for v in plot["SL"])
            assert warmup == 13
            assert len(orderbook["diagnostics"]) == warmup * 2
            assert {d["code"] for d in orderbook["diagnostics"]} == {
                "E_STRATEGY_EXIT_TICKS"
            }
            assert all(x["barIndex"] >= warmup for x in orderbook["orders"])
            assert plot["Balance"][0] == (
                1000 if mode in ("declared", "firstseed") else 50_000
            )
            for trade in orderbook["trades"]:
                gross = (trade["exitPrice"] - trade["entryPrice"]) * trade["qty"]
                assert isclose(gross, trade["profit"], rel_tol=1e-11, abs_tol=1e-8)
            audits.append(
                {
                    "mode": mode,
                    "period": r["period"],
                    "market": r["market"],
                    "chart_bars": len(plot["Position"]),
                    "atr_warmup_bracket_diagnostics": len(orderbook["diagnostics"]),
                    "long_gate_bars": sum(plot["Long"]),
                    "short_gate_bars": sum(plot["Short"]),
                    "protector_gate_bars": sum(plot["Close all"]),
                    "closed_lots": len(orderbook["trades"]),
                    "first_closed_lot": orderbook["trades"][0],
                    "diagnostic_source_zero_fee_profit": sum(
                        t["profit"] for t in orderbook["trades"]
                    ),
                }
            )
    for scope in responses["declared"]:
        histories = [responses[m][scope] for m in MODES]
        for label in ("Long", "Short"):
            assert all(
                r["plots"][label] == histories[0]["plots"][label] for r in histories
            )
        keys = ("orders", "trades", "position")
        for x, y in ((0, 3), (1, 2)):
            assert all(
                histories[x]["strategy"][k] == histories[y]["strategy"][k] for k in keys
            )
    cases = [r for r in audits if (r["period"], r["market"]) == ("native", "BTCUSDT")]
    assert cases[0]["first_closed_lot"]["exitPrice"] == 26_496.5
    assert cases[1]["first_closed_lot"]["exitPrice"] == 27_191.0
    assert [sum(r["closed_lots"] for r in audits if r["mode"] == m) for m in MODES] == [
        70,
        29,
        29,
        70,
    ]
    write(
        a.output,
        {
            "baseline_coverage_sha256": sha256(a.baseline),
            "archive_sha256": FMZ_SHA256,
            "document_sha256": checksum,
            "archived_settings": settings,
            "pine_compat_binary_sha256": NATIVE_BINARY_HASH,
            "isolation_probe": isolation,
            "artifacts": {p.name: sha256(p) for p in files},
            "provider_archives": manifest,
            "literal_rejection": literal_error,
            "executed_diagnostic_source_sha256": hashes,
            "diagnostic_clock": "Verified Binance USD-M 1m candles were aggregated to the archived 10m chart. Fills use the native chart-broker diagnostic.",
            "diagnostic_evidence": audits,
            "references": [
                link,
                "https://www.fmz.com/doc/9293#strategy",
                "https://www.fmz.com/user-guide/backtesting-system/backtest-configuration-and-saving",
                "https://github.com/binance/binance-public-data",
            ],
            "coverage": [
                [
                    IDENT,
                    "Pending · FMZ active equity-protector balance provenance",
                    "The archived 50,000 assignment is invalid on Pine Compat and feeds the active 1% equity protector. On identical BTC/ETH 10m paths, 1,000-balance diagnostics close 70 lots and the 50,000-balance alternatives close 29 despite identical entry gates. The native BTC initial position exits at 26,496.50 or 27,191.00 depending on balance interpretation. Exact FMZ host capital remains unavailable.",
                ]
            ],
            "results": [],
        },
    )
    print(
        "Verified 16 isolated alternate-capital receipts and the original rejection. Strategy remains pending."
    )


if __name__ == "__main__":
    main()
