"""Verify archived #4098 type ambiguity without assigning market performance."""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path
from shutil import copy2
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, date_ms, sha256
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH

IDENT = 4098
DAY = 86_400_000
START = date_ms("2023-01-11")
NATIVE_END = date_ms("2024-01-17")
FORWARD_END = NATIVE_END + (NATIVE_END - START)
WORKER = "fmz_round56_pine_intellitrader_probe.py"
FMZ_HASHES = {
    "BTC": "c24b53db3230dd69d7aa64f774b36cf11125cf66a9f9464a97d7331af3de02c7",
    "ETH": "9b8e568461a3a30afa19c516d71de5a1863251256b34821a017c147f8bc7cd5b",
}


def source_record(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (row,) = [r for r in read(baseline)["disposition"] if r["id"] == IDENT]
    assert row["status"].startswith("Pending")
    with ZipFile(archive) as book:
        ((_, _, doc, digest),) = documents(book, {IDENT: row})
    (raw,) = re.findall(r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", doc)
    fields = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)", raw
        )
    )
    assert fields == {
        "start": "2023-01-11 00:00:00",
        "end": "2024-01-17 00:00:00",
        "period": "1d",
        "basePeriod": "1h",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    code, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", raw)
    assert n == 1 and code.count("//@version=3") == 1
    active = re.sub(r"(?m)^\s*//.*$", "", code)
    switches = re.findall(
        r"(?m)^(?:rsi7|rsi14|stoch|stochrsi|cci)_Use_\w+\s*=\s*input\(false,", active
    )
    assert len(switches) == 30
    resets = re.findall(r"(?m)^    bool_(?:1m|5m|15m|1h|4h|1d) = false$", active)
    assert len(resets) == 6
    assert active.count("request.security(") == 38
    assert "buy==1 and (barstate.isconfirmed or barstate.ishistory)" in active
    assert "sell==1  and (barstate.isconfirmed or barstate.ishistory)" in active
    assert 'strategy.entry("Long", 1, when=longCondition)' in active
    assert 'strategy.close("Long", when=longClose )' in active
    harness = '\nplot(buy?1:0,"Buy")\nplot(longCondition?1:0,"LongCond")\nplot(longClose?1:0,"LongClose")\nplot(tradeState,"State")\n'
    return digest, fields, code + harness


def feed_receipts(raw):
    records = {}
    for coin, digest in FMZ_HASHES.items():
        path = raw / f"4098-fmz-{coin}-1d.json"
        assert sha256(path) == digest
        source = read(path)
        spec = source["detail"]
        assert (spec["alias"], spec["symbol"], spec["eid"], spec["contractType"]) == (
            coin + "USDT",
            coin + "_USDT.swap",
            "Futures_Binance",
            "swap",
        )
        market = source["data"]
        assert [row[0] for row in market] == list(range(START, FORWARD_END + DAY, DAY))
        assert all(
            lo <= min(op, close) <= max(op, close) <= hi and vol > 0
            for _, op, hi, lo, close, vol, *_ in market
        )
        records[coin] = {
            "sha256": digest,
            "native_bars": (NATIVE_END - START) // DAY,
            "forward_bars": (FORWARD_END - NATIVE_END) // DAY,
            "url": (
                "https://q.fmz.com/data/history?detail=true&round=true&feeder=local&event=feed&"
                "eid=Futures_Binance&depth=5&trades=0&custom=0&period=86400000"
                f"&symbol={coin}_USDT.swap&from={START // 1000}&to={FORWARD_END // 1000}"
            ),
        }
    return records


def diagnostics(receipt):
    expected = {
        "archive": 194,
        "legacy-security-name-only": 48,
        "lex-v3-exact-comparison": 1,
        "lex-v5-exact-comparison": 0,
        "lex-v3-explicit-boolean": 0,
        "lex-v5-explicit-boolean": 0,
        "lex-v3-explicit-boolean-with-reassigned-reset": 0,
    }
    assert {key: len(row["diagnostics"]) for key, row in receipt.items()} == expected
    assert "requires Pine v5 or later" in receipt["archive"]["diagnostics"][0]
    assert (
        "expects comparable operands"
        in receipt["lex-v3-exact-comparison"]["diagnostics"][0]
    )
    assert (
        sum(
            "expects comparable operands" in row
            for row in receipt["legacy-security-name-only"]["diagnostics"]
        )
        == 2
    )
    summary = {}
    for key, row in receipt.items():
        if row["diagnostics"]:
            kinds = Counter(r.split(":", 1)[0] for r in row["diagnostics"])
            summary[key] = {
                "counts": dict(kinds),
                "operator_examples": [
                    r for r in row["diagnostics"] if "expects comparable operands" in r
                ],
                "first": row["diagnostics"][0],
            }
        else:
            assert not row["broker_diagnostics"]
            reassign = key.endswith("-with-reassigned-reset")
            assert len(row["orders"]) == int(not reassign)
            assert all(
                values == [int(not reassign)] * 45 for values in row["plots"].values()
            )
            summary[key] = {
                "fixture_orders": len(row["orders"]),
                "distinct_observations": {
                    name: sorted(set(values)) for name, values in row["plots"].items()
                },
            }
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "report"))
    for name in ("archive", "baseline", "work", "raw", "out"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    doc_sha, fields, src = source_record(args.archive, args.baseline)
    archive_charts = feed_receipts(args.raw)
    script = Path(__file__).with_name(WORKER)
    study = args.work / "r48-4098.pine"
    if args.mode == "stage":
        study.write_text(src, encoding="utf8", newline="\n")
        copy2(script, args.work / WORKER)
        return
    assert study.read_text(encoding="utf8") == src
    assert sha256(script) == sha256(args.work / WORKER)
    assert (
        sha256(args.work / "priced-runtime/pine_compat/pine_compat.pyd")
        == NATIVE_BINARY_HASH
    )
    isolation = read(args.work / "round3-isolation-python.json")
    assert (
        isolation["network_error"][0] == isolation["file_error"][0] == "PermissionError"
    )
    receipt = args.work / "r48-4098-typed.json"
    write(
        args.out,
        {
            "baseline_coverage_sha256": sha256(args.baseline),
            "archive_sha256": FMZ_SHA256,
            "document_sha256": doc_sha,
            "archived_settings": fields,
            "archived_source_instrumented_sha256": sha256(study),
            "fmz_market_data": archive_charts,
            "runtime_sha256": NATIVE_BINARY_HASH,
            "worker_sha256": sha256(script),
            "native_receipt_sha256": sha256(receipt),
            "offline_isolation": isolation,
            "diagnostic_fixtures": diagnostics(read(receipt)),
            "method": [
                "Exact archived v3 Pine fails to parse its required v5 request namespace. Renaming only this namespace leaves later-vocabulary and order-state typing errors. Public FMZ historical daily BTC and ETH chart data were obtained independently for both listed periods, so this is a program-semantics blocker.",
                "The six conditions each declare a locally shadowed reset with the archived = token when all five switches are disabled. Both the archived language specification and the isolated declaration control explain why the outer gates can remain true. The v3 equality control refuses a Boolean operand compared to integer 1. V5 accepts the same expression and enters a position. Explicit truth testing enters in both versions, whereas introducing a reassignment in the default local reset prevents it.",
                "The publisher has no publicly verified version-pinned mixed operand contract or archived on-platform order receipt for this strategy. Neither changing the numeric equality nor servicing the default input blocks under a reinterpreted namespace establishes the actual archived order behavior. The 45-bar fixtures exist only to distinguish these interpretations.",
            ],
            "references": [
                "https://www.fmz.com/strategy/439199",
                "https://www.fmz.com/doc/9293",
                "https://www.tradingview.com/pine-script-docs/v3/language/expressions-declarations-and-statements/",
                "https://www.tradingview.com/pine-script-docs/v3/appendix/pine-version-3-migration-guide/",
            ],
            "coverage": [
                [
                    IDENT,
                    "Pending · FMZ mixed-version entry semantics",
                    "Market data is available, but the exact v3 strategy mixes v5 request vocabulary and a bool-to-int entry gate. The isolated v3 gate rejects it and v5 enters. Archived host semantics or a native order ledger are required.",
                ]
            ],
            "results": [],
        },
    )
    print(
        "Verified two exact compile attempts and five scoped controls. No market-performance row."
    )


if __name__ == "__main__":
    main()
