"""Quantify unavailable higher-timeframe facts in the archived MTF strategy."""

from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from itertools import groupby
from pathlib import Path
from shutil import copy2
from zipfile import ZipFile

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, date_ms, sha256
from research.fmz_round27_pine_rng import NATIVE_BINARY_HASH
from research.fmz_round28_pine_callback import cache_bars

IDENT = 3281
DAY = 86_400_000
PERIODS = (1, 10, 15, 30)
PRODUCER = "fmz_round43_pine_mtf_probe.py"


def record(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (row,) = (r for r in read(baseline)["disposition"] if r["id"] == IDENT)
    assert row["status"].startswith("Pending")
    with ZipFile(archive) as book:
        ((_, _, doc, checksum),) = documents(book, {IDENT: row})
    (raw,) = re.findall(r"(?ms)^\x60{3}[ \t]*pinescript[ \t]*\r?\n(.+?)^\x60{3}", doc)
    facts = dict(
        re.findall(
            r"(?m)^(start|end|period|basePeriod|exchanges):[ \t]*([^\r\n]+)", raw
        )
    )
    assert facts == {
        "start": "2024-01-19 00:00:00",
        "end": "2024-02-18 00:00:00",
        "period": "1d",
        "basePeriod": "1h",
        "exchanges": '[{"eid":"Futures_Binance","currency":"BTC_USDT"}]',
    }
    assert "//@version=2" in raw
    assert raw.count("style=linestyle") == 5
    for index, frame in enumerate(PERIODS, 1):
        literal = "D" if frame == 1 else f"{frame}D"
        assert f'TF_{index}_time = input("{literal}",' in raw
        assert (
            f"request.security(syminfo.tickerid, TF_{index}_time, open) < request.security(syminfo.tickerid, TF_{index}_time, close)"
            in raw
        )
    assert "TF_global = TF_1 and TF_2 and TF_3 and TF_4" in raw
    assert (
        "TF_global_bear = TF_1 == false and TF_2 == false and TF_3 == false and TF_4 == false"
        in raw
    )
    assert 'strategy.entry("MTF_Long", strategy.long, qty=transaction_size)' in raw
    assert 'strategy.entry("MTF_Short", strategy.short, qty=transaction_size)' in raw
    link = re.search(r"https://www\.fmz\.com/strategy/\d+", doc)[0]
    return raw.encode(), facts, checksum, link


def start_of(t, days):
    length = days * DAY
    return t // length * length


def input_data(cache):
    first, split, history = map(date_ms, ("2024-01-19", "2024-02-18", "2023-10-01"))
    last = 2 * split - first
    months = sorted(
        {
            datetime.fromtimestamp(t / 1000, UTC).strftime("%Y-%m")
            for t in range(history, last + 30 * DAY, DAY)
        }
    )
    data, manifest = {}, []
    for market in ("BTCUSDT", "ETHUSDT"):
        daily = [
            r
            for r in cache_bars(cache, market, "1d", months, DAY, manifest)
            if history <= r[0] < last + 30 * DAY
        ]
        assert [r[0] for r in daily] == list(range(history, last + 30 * DAY, DAY))
        contexts = {}
        for length in PERIODS:
            groups = []
            for start, cand in groupby(
                daily, lambda c, span=length: start_of(c[0], span)
            ):
                seq = list(cand)
                if len(seq) == length:
                    groups.append(
                        [
                            start,
                            seq[0][1],
                            max(r[2] for r in seq),
                            min(r[3] for r in seq),
                            seq[-1][4],
                            sum(r[5] for r in seq),
                        ]
                    )
            contexts[str(length)] = groups
        for period, begin, end in (("native", first, split), ("next", split, last)):
            data.setdefault(period, {})[market] = {
                "chart": [list(r) for r in daily if begin <= r[0] < end],
                "contexts": contexts,
            }
    return data, manifest


def verify(tape, receipt, previous):
    assert not receipt["strategy"]["diagnostics"]
    assert {r["code"] for r in receipt["diagnostics"]} == {
        "W_LEGACY_SECURITY_LOOKAHEAD"
    }
    contexts = {int(k): {r[0]: r for r in rows} for k, rows in tape["contexts"].items()}
    output = []
    plots = receipt["plots"]
    for i, candle in enumerate(tape["chart"]):
        known = candle[0] + DAY
        symbols, unavailable = [], []
        for index, days in enumerate(PERIODS, 1):
            start = start_of(candle[0], days)
            if previous and days > 1:
                start -= days * DAY
            ref = contexts[days][start]
            result = ref[1] < ref[4]
            assert result == plots[f"TF {index}"][i]
            symbols.append(result)
            if start + days * DAY > known:
                unavailable.append(
                    {
                        "days": days,
                        "candle_close_available_utc_ms": start + days * DAY,
                        "future_close": ref[4],
                        "candle_open": ref[1],
                    }
                )
        buy, sell = all(symbols), not any(symbols)
        assert buy == plots["Long"][i] and sell == plots["Short"][i]
        output.append(
            {
                "chart_start": candle[0],
                "known_at": known,
                "buy": buy,
                "sell": sell,
                "unconfirmed_references": unavailable,
            }
        )
    if previous:
        assert all(not i["unconfirmed_references"] for i in output)
    for order in receipt["strategy"]["orders"]:
        assert (order["time"], order["price"]) == tuple(
            tape["chart"][order["barIndex"]][:2]
        )
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "finalize"))
    for key in ("archive", "baseline", "work", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    parser.add_argument("--cache", type=Path, nargs="+", required=True)
    a = parser.parse_args()
    raw, facts, checksum, link = record(a.archive, a.baseline)
    data, manifest = input_data(a.cache)
    source, tape = a.work / "r43-mtf-source.pine", a.work / "r43-mtf-feeds.json"
    producer = Path(__file__).with_name(PRODUCER)
    staged = a.work / "r43_mtf_probe.py"
    if a.mode == "stage":
        source.write_bytes(raw)
        write(tape, data)
        copy2(producer, staged)
        return
    assert source.read_bytes() == raw and read(tape) == data
    assert producer.read_bytes() == staged.read_bytes()
    assert (
        sha256(a.work / "priced-runtime/pine_compat/pine_compat.pyd")
        == NATIVE_BINARY_HASH
    )
    isolation = read(a.work / "round3-isolation-python.json")
    assert all(
        isolation[k][0] == "PermissionError" for k in ("file_error", "network_error")
    )
    err = a.work / "r43-mtf-literal-error.txt"
    errors = [
        x for x in err.read_text().splitlines() if "E_LEGACY_VERSION_FEATURE" in x
    ]
    assert len(errors) == 8 and all(
        "`request.security` requires Pine v5" in x for x in errors
    )
    views, signatures = {}, {}
    artifacts = [source, tape, producer, err]
    for mode in ("legacy", "confirmed"):
        path = a.work / f"r43-mtf-{mode}.json"
        observations = read(path)
        views[mode] = {(r["period"], r["market"]): r for r in observations}
        assert len(views[mode]) == len(observations) == 4
        (signatures[mode],) = {r["executed_source_sha256"] for r in observations}
        artifacts.append(path)
    reports = []
    for period, markets in data.items():
        for market, chart in markets.items():
            scope = (period, market)
            original, settled = views["legacy"][scope], views["confirmed"][scope]
            first, second = verify(chart, original, False), verify(chart, settled, True)
            changed = [
                {"legacy": p, "previous_complete": q}
                for p, q in zip(first, second, strict=True)
                if (p["buy"], p["sell"]) != (q["buy"], q["sell"])
            ]
            reports.append(
                {
                    "period": period,
                    "market": market,
                    "changed_decisions": len(changed),
                    "changed_while_future_fields_unavailable": sum(
                        bool(r["legacy"]["unconfirmed_references"]) for r in changed
                    ),
                    "first_changed_witness": changed[0] if changed else None,
                    "legacy_ledger_order_count": len(original["strategy"]["orders"]),
                    "confirmed_ledger_order_count": len(settled["strategy"]["orders"]),
                }
            )
    assert [x["changed_decisions"] for x in reports] == [5, 13, 0, 6]
    assert any(x["changed_while_future_fields_unavailable"] for x in reports)
    write(
        a.output,
        {
            "baseline_coverage_sha256": sha256(a.baseline),
            "archive_sha256": FMZ_SHA256,
            "document_sha256": checksum,
            "archived_settings": facts,
            "pine_compat_binary_sha256": NATIVE_BINARY_HASH,
            "isolation_probe": isolation,
            "provider_archives": manifest,
            "artifacts": {p.name: sha256(p) for p in artifacts},
            "source_audit": {
                "literal_compile_errors": errors,
                "executed_source_hashes": signatures,
                "diagnostic_calendar": "Epoch-aligned UTC days for 10D, 15D and 30D witnesses. The archive gives no original aggregate phase.",
            },
            "decision_diagnostics": reports,
            "references": [
                link,
                "https://www.tradingview.com/pine-script-docs/v5/concepts/other-timeframes-and-data/",
                "https://github.com/binance/binance-public-data",
            ],
            "method": [
                "The pasted v2 strategy calls a modern v5 request namespace. Legacy security/ticker spellings and removing the five reporting styles recover the source order path for diagnostic purposes. Explicit daily ordinal aggregation establishes availability times for each requested 10D, 15D and 30D candle.",
                "An independent model matches every timeframe flag and long/short decision in both controls. The legacy path uses the final higher-timeframe close before that close is observable. Switching to the preceding completed higher-timeframe candle changes 24 decisions across matched BTC and ETH dates. The pinned source has no causal timing selection or saved aggregation phase.",
            ],
            "coverage": [
                [
                    IDENT,
                    "Pending · FMZ future-leaking multi-day request clock",
                    "Legacy v2 adaptation and confirmed prior-block controls show 24 changed decisions. The archived 10D/15D/30D direction uses future final closes and lacks a saved aggregation origin or author-specified causal replacement. No results row is admitted.",
                ]
            ],
            "results": [],
        },
    )
    print(
        "Verified eight isolated scopes and 24 changed order gates. #3281 remains pending."
    )


if __name__ == "__main__":
    main()
