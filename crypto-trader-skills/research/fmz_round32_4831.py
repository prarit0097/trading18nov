"""Check #4831 archive resolution and margin-path sensitivity."""

import re
import sys
from collections import Counter
from pathlib import Path

from research.fmz_round7_magnifier import (
    aggregate,
    date_ms,
    sha256,
    verified_archives,
    write,
)
from research.fmz_round18_5745 import ENGINE_SHA, FIELDS
from research.fmz_round26_977 import prices

SOURCE = "aea6cbe32ca87c86604b0831b8689898aa726b120d9ff1e7b302a10df6b61340"
BEGIN, END = map(date_ms, ("2025-01-01", "2025-03-30"))
MONTHS = ("2025-01", "2025-02", "2025-03")


def code(doc):
    assert sha256(doc) == SOURCE
    fence = chr(96) * 3
    (archive,) = re.findall(
        r"(?ms)^" + fence + r" pinescript[^\n]*\n(.*?)^" + fence,
        doc.read_text(encoding="utf-8"),
    )
    body, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", archive)
    assert n == 1
    prefix, tail = body.split("//@version=6")
    declaration, other = tail.lstrip().split("\n", 1)
    assert declaration.startswith(
        'strategy("ThinkTech AI Signals"'
    ) and declaration.endswith(")")
    assert prefix.count("strategy.entry(") == 2 and other.count("strategy.entry(") == 4
    assert "use_bar_magnifier" not in declaration
    supplies = "//@version=6\n"
    both = prefix.rstrip() + "\n" + other
    return supplies + declaration + "\n" + both, supplies + declaration[
        :-1
    ] + ", use_bar_magnifier=true)\n" + both


def objects(rows):
    return [dict(zip(FIELDS, x, strict=True)) for x in rows]


def summarize(native):
    assert not native["diagnostics"] and not native["strategy"]["diagnostics"]
    book = native["strategy"]
    events = Counter(r["id"] for r in book["orders"])
    return {
        "closed_lots": len(book["trades"]),
        "order_events": sum(events.values()),
        "margin_calls": events["Margin Call"],
        "entry_exit_ids": dict(events),
    }


def run(doc, market_dir, runtime, out):
    assert sha256(runtime / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(runtime))
    import pine_compat

    normal, detailed = code(doc)
    manifest, checks = [], []
    for market in ("BTCUSDT", "ETHUSDT"):
        native = prices(
            verified_archives(market_dir, market, "1h", MONTHS, manifest),
            BEGIN,
            END,
            3_600_000,
        )
        minutes = prices(
            verified_archives(market_dir, market, "1m", MONTHS, manifest),
            BEGIN,
            END,
            60_000,
        )
        combined = aggregate(minutes, 60)
        differences = [
            {
                "bar_start_ms": x[0],
                "mismatched_fields": [
                    k
                    for k, a, b in zip(FIELDS[:5], x[:5], y[:5], strict=True)
                    if a != b
                ],
            }
            for x, y in zip(native, combined, strict=True)
            if x[:5] != y[:5]
        ]
        assert len(differences) == 2
        base = objects(minutes)
        trace = {
            "schemaVersion": 1,
            "chartBars": [
                {"chartBarIndex": i, "bars": base[60 * i : 60 * (i + 1)]}
                for i in range(len(native))
            ],
        }
        opts = {
            "chart_symbol": f"BINANCE:{market}",
            "chart_timeframe": "60",
            "request_bars": {
                "$chart": {
                    "minMove": 1,
                    "priceScale": 10 if market == "BTCUSDT" else 100,
                    "quantityStep": ".001",
                    "minContract": ".001",
                    "pointValue": 1,
                    "currency": "USDT",
                }
            },
        }
        native_control = summarize(
            pine_compat.run_script(normal, objects(native), **opts)
        )
        rebuilt_control = summarize(
            pine_compat.run_script(normal, objects(combined), **opts)
        )
        intrabar_control = summarize(
            pine_compat.run_script(
                detailed, objects(combined), **opts, magnifier_bars=trace
            )
        )
        assert rebuilt_control["margin_calls"] != intrabar_control["margin_calls"]
        checks.append(
            {
                "market": market,
                "hours": len(native),
                "minutes": len(minutes),
                "differences": differences,
                "archive_1h": native_control,
                "minute_rebuilt_1h": rebuilt_control,
                "same_rebuilt_candles_with_chronology": intrabar_control,
            }
        )
    write(
        out,
        {
            "schema": "FMZ 4831 · Source structure, archive disagreements and margin timing",
            "source_sha256": SOURCE,
            "engine_sha256": ENGINE_SHA,
            "archives": manifest,
            "checks": checks,
            "notes": {
                "source": "Restore the directive and strategy declaration ahead of the fused prefix. Both prefix entries and all four main-body entries remain active. The original body declares 100% equity allocation and omits a margin override.",
                "control": "Compare independently published hourly and minute-derived parent data, then hold the minute-derived parent fixed while giving the broker timestamped minute candles. Counts describe Pine emulator events only.",
                "blocking_evidence": "There are two OHLC disagreements per market. Even with the same rebuilt parent candles, adding chronological children changes the volume of margin-call events. A verified source-intended margin or liquidation model and a validated price hierarchy are needed for a performance row.",
            },
            "coverage": [
                [
                    4831,
                    "Pending · Verified OHLC mismatch and margin-path dependency",
                    "Restored fused directive without dropping any authored orders. Independent 1h and rebuilt 1m parents disagree twice per market, and fixed parent data with real intrabar chronology changes margin liquidation counts.",
                ]
            ],
            "results": [],
        },
    )


if __name__ == "__main__":
    run(*map(Path, sys.argv[1:]))
