"""Test whether #2326's mixed Pine request semantics alter the archived crossover."""

import re
import sys
from bisect import bisect_right
from itertools import pairwise
from pathlib import Path

from research.fmz_round7_magnifier import (
    aggregate,
    date_ms,
    sha256,
    verified_archives,
    write,
)
from research.fmz_round18_5745 import ENGINE_SHA
from research.fmz_round26_977 import prices

SOURCE = "6f5756b59524762720aa7f5c760f4f3e56d7042059e9597081d639750e45f62c"
V2_DOC = "https://www.tradingview.com/pine-script-docs/v3/essential/context-switching-the-security-function/"
REQUEST_DOC = (
    "https://tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/"
)
FMT = "https://www.fmz.com/strategy/435488"
MINUTE = 60_000
HOUR = 60 * MINUTE
DAY = 24 * HOUR


def archived_diagnostics(path, engine):
    assert sha256(path) == SOURCE
    fence = chr(96) * 3
    (body,) = re.findall(
        r"(?ms)^" + fence + r" pinescript[^\n]*\n(.*?)^" + fence,
        path.read_text(encoding="utf-8"),
    )
    program, count = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", body)
    assert count == 1 and program.startswith("//@version=2")
    for code in (
        "tim=input('1440')",
        "sim=input('370')",
        "request.security(syminfo.tickerid, tim, open)",
        "request.security(syminfo.tickerid, sim, close)",
        "crossover(out2,out1)",
        "crossunder(out2,out1)",
    ):
        assert program.count(code) == 1
    try:
        engine.compile_script(program)
    except ValueError as exc:
        return str(exc)
    raise AssertionError("The exact mixed-version source unexpectedly compiles")


def revisions(rows, start):
    projected, confirmed, projected_end = [], [], []
    hourly = aggregate(rows, 12)
    assert hourly[-1][0] - hourly[0][0] + HOUR == len(hourly) * HOUR
    daily = aggregate(rows, 288)
    opens = {day[0]: day[1] for day in daily}
    begin, ends, close = [], [], []
    for day in daily:
        first = (day[0] - rows[0][0]) // (5 * MINUTE)
        boundaries = (0, 370, 740, 1110, 1440)
        for a, b in pairwise(boundaries):
            begin.append(day[0] + a * MINUTE)
            ends.append(day[0] + b * MINUTE)
            close.append(rows[first + b // 5 - 1][4])
    for stamp, *_ in hourly:
        day = stamp - stamp % DAY
        i = bisect_right(begin, stamp) - 1
        j = bisect_right(ends, stamp + HOUR) - 1
        closed_day = (stamp + HOUR) // DAY * DAY - DAY
        projected.append((stamp, close[i] - opens[day]))
        projected_end.append(ends[i])
        confirmed.append(
            (stamp, close[j] - opens[closed_day])
            if j >= 0 and closed_day in opens
            else (stamp, None)
        )

    def direction(now, prev):
        if now is None or prev is None:
            return 0
        return 1 if now > 0 >= prev else -1 if now < 0 <= prev else 0

    differences, future_uses, future_crosses = [], 0, 0
    for i in range(1, len(hourly)):
        stamp, current = projected[i]
        if stamp < start:
            continue
        optimistic = direction(current, projected[i - 1][1])
        causal = direction(confirmed[i][1], confirmed[i - 1][1])
        future_min = max(0, (projected_end[i] - stamp - HOUR) // MINUTE)
        future_uses += future_min > 0
        future_crosses += future_min > 0 and optimistic != 0
        if optimistic != causal:
            differences.append(
                {
                    "bar_timestamp": stamp,
                    "projected": optimistic,
                    "confirmed": causal,
                    "unavailable_370m_close_lead_minutes": future_min,
                }
            )
    return {
        "hours": sum(row[0] >= start for row in hourly),
        "projected_future_hours": future_uses,
        "projected_crosses_with_future_input": future_crosses,
        "crossover_disagreements": differences,
    }


def main(source, public, runtime, output):
    assert sha256(runtime / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    sys.path.insert(0, str(runtime))
    import pine_compat

    diagnostic = archived_diagnostics(source, pine_compat)
    market_data, diagnostics = [], {}
    start, end = map(date_ms, ("2023-11-14", "2023-12-14"))
    for market in ("BTCUSDT", "ETHUSDT"):
        files = verified_archives(
            public, market, "5m", ("2023-11", "2023-12"), market_data
        )
        raw = prices(files, start - DAY, end, 5 * MINUTE)
        r = revisions(raw, start)
        assert (
            r["hours"] == 720
            and r["projected_future_hours"]
            and r["crossover_disagreements"]
        )
        diagnostics[market] = r
    write(
        output,
        {
            "schema": "FMZ #2326 mixed Pine request timing diagnostic",
            "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
            "source_sha256": SOURCE,
            "native_engine_sha256": ENGINE_SHA,
            "source_page": FMT,
            "market_data": market_data,
            "primary_references": [V2_DOC, REQUEST_DOC],
            "original_compile_diagnostic": diagnostic,
            "method": "No fills or performance rows. A 5m source constructs UTC-day-reset 370m intervals, clipped at midnight. Both variants use identical underlying candles and 720 hourly signal bars. The legacy witness maps the current 370m completed value to lower bars based on their opening timestamps. The causal witness only merges values confirmed by the hourly decision time. The independent witnesses diagnose sensitivity, and do not claim recovered FMZ timeframe anchoring.",
            "coverage": [
                [
                    2326,
                    "Pending · mixed Pine versions with active 370m crossover",
                    "The pinned v2 file uses request.security, whose later defaults differ from v2 security. On both checked markets the same 5m data produces different active crossover flags under projected and confirmed timing. Original source timing and 370m anchor remain unverified.",
                ]
            ],
            "diagnostics": diagnostics,
            "results": [],
        },
    )


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
