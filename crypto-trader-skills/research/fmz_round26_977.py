"""Run the authored #977 trend order branches with a strategy declaration."""

import math
import re
import sys
from pathlib import Path

from research.fmz_round7_magnifier import (
    aggregate,
    date_ms,
    ledger_metrics,
    sha256,
    verified_archives,
    write,
)
from research.fmz_round8_fx import csv_rows
from research.fmz_round18_5745 import ENGINE_SHA, FIELDS
from research.fmz_round21_1988 import ema

MINUTE = 60_000
QUARTER = 15 * MINUTE
START = date_ms("2022-05-03")
WARMUP = date_ms("2022-04-16")
END = date_ms("2022-05-10") - MINUTE
CUT = END // QUARTER * QUARTER
H4 = 240 * MINUTE
CAPITAL = 1_000_000
FEE = 0.00075
TAIL_URL = "https://data.binance.vision/data/futures/um/daily/klines"


def prices(files, start, end, step):
    rows = [
        (int(r[0]), *map(float, r[1:6]))
        for f in files
        for r in csv_rows(f)
        if r[0].isdigit() and start <= int(r[0]) < end
    ]
    assert [r[0] for r in rows] == list(range(start, end, step))
    return rows


def prepared(source):
    source, n = re.subn(r"(?m)^study\(", "strategy(", source)
    assert n == 1
    source, n = re.subn(r"\bstr\.tostring\(", "tostring(", source)
    assert n == 2
    source, n = re.subn(
        r"(?m)^if swing_(?:high and macpos|low and macneg) and showsig\n[ \t]*(?=//|\n)",
        lambda m: "//" + m[0],
        source,
    )
    assert n == 2
    old = ("if uptrend\n", "else if downtrend\n")
    assert all(source.count(x) == 1 for x in old)
    return source.replace(
        old[0], "if time >= timestamp(2022, 5, 3, 0, 0) and uptrend\n"
    ).replace(old[1], "else if time >= timestamp(2022, 5, 3, 0, 0) and downtrend\n")


def oracle(chart):
    close = [row["close"] for row in chart]
    fast, slow = (ema(close, n) for n in (20, 50))
    holding = target = 0
    entry = None
    fills, lots = [], []
    for i, (f, s) in enumerate(zip(fast, slow, strict=True)):
        row = chart[i]
        if holding != target:
            if holding:
                lots.append((entry, i, holding))
            fills.append(
                (
                    i,
                    "Enter Long" if target > 0 else "Enter Short",
                    abs(holding - target),
                )
            )
            entry = i
            holding = target
        if row["time"] >= START and s is not None and f != s:
            target = 1 if f > s else -1
    return fast, slow, fills, lots, holding


def replay(engine, src, market, base):
    chart = [dict(zip(FIELDS, row, strict=True)) for row in aggregate(base, 16)]
    assert [row["time"] for row in chart] == list(range(WARMUP, END, H4))
    opts = {
        "chart_symbol": f"BINANCE:{market}",
        "chart_timeframe": "240",
        "request_bars": {
            "$chart": {
                "minMove": 1,
                "priceScale": 100,
                "pointValue": 1,
                "quantityStep": "0.001",
                "minContract": "0.001",
                "currency": "USDT",
            }
        },
    }
    result = engine.run_script(src, chart, **opts)
    assert not result["diagnostics"]
    actual = result["strategy"]
    assert not actual["diagnostics"]
    fast, slow, orders, lots, holding = oracle(chart)
    for expected, name in ((fast, "Fast HTF EMA"), (slow, "Slow HTF EMA")):
        (p,) = [plot for plot in result["plots"] if plot.get("title") == name]
        for i, (seen, want) in enumerate(zip(p["values"], expected, strict=True)):
            assert (
                seen is None
                if want is None
                else math.isclose(seen, want, rel_tol=1e-12, abs_tol=1e-10)
            ), (market, name, i)
    by_time = {row[0]: row for row in base}
    for fill, (i, label, quantity) in zip(actual["orders"], orders, strict=True):
        stamp = chart[i]["time"]
        assert stamp >= START and by_time[stamp][5] > 0
        assert (
            fill["id"],
            fill["barIndex"],
            fill["time"],
            fill["price"],
            fill["qty"],
        ) == (label, i, stamp, by_time[stamp][1], quantity)
    earned = []
    for trade, (entry, exit, side) in zip(actual["trades"], lots, strict=True):
        ep, xp = chart[entry]["open"], chart[exit]["open"]
        assert (
            trade["entryBarIndex"],
            trade["exitBarIndex"],
            trade["qty"],
            trade["entryPrice"],
            trade["exitPrice"],
        ) == (entry, exit, side, ep, xp)
        gross = side * (xp - ep)
        fee = FEE * (xp + ep)
        assert math.isclose(gross, trade["profit"], abs_tol=1e-8)
        earned.append(
            {**trade, "dir": side, "qty": 1, "commission": fee, "profit": gross - fee}
        )
    assert actual["position"][-1]["size"] == holding
    return {
        "market": market,
        "trades": earned,
        "orders": actual["orders"],
        "ending_position": holding,
        "chart_bars": len(chart),
        "active_chart_bars": sum(bar["time"] >= START for bar in chart),
    }


def run(source_path, monthly, minutes, runtime, output):
    assert (
        sha256(source_path)
        == "15f7ae6dea897d8fc8e5407a44108785b0455479e02026231c051e045c58434e"
        and sha256(runtime / "pine_compat/pine_compat.pyd") == ENGINE_SHA
    )
    sys.path.insert(0, str(runtime))
    import pine_compat as engine

    (archive,) = re.findall(
        r"(?ms)^```[^\n]*\n(.*?)^```", source_path.read_text(encoding="utf-8")
    )
    original, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", archive)
    assert n == 1
    try:
        engine.compile_script(original)
    except ValueError as error:
        diagnostics = str(error).splitlines()
        captured = {line.split(":", 1)[0] for line in diagnostics}
        assert captured == {
            "E_PARSE_EXPECTED",
            "E_STRATEGY_MODE",
            "E_LEGACY_VERSION_FEATURE",
        }
    else:
        raise AssertionError("Archived indicator declaration compiled as a strategy")
    source = prepared(original)
    manifest = []
    cases = []
    for market in ("BTCUSDT", "ETHUSDT"):
        feeds = verified_archives(
            monthly, market, "15m", ("2022-04", "2022-05"), manifest
        )
        base = prices(feeds, WARMUP, CUT, QUARTER)
        terminal = minutes / f"{market}-1m-2022-05-09.zip"
        terminal_digest = sha256(terminal)
        assert (minutes / (terminal.name + ".CHECKSUM")).read_text().split() == [
            terminal_digest,
            terminal.name,
        ]
        manifest.append(
            {
                "name": terminal.name,
                "sha256": terminal_digest,
                "url": f"{TAIL_URL}/{market}/1m/{terminal.name}",
            }
        )
        short = prices([terminal], CUT, END, MINUTE)
        assert len(short) == 14
        base += aggregate(short, len(short))
        cases.append(replay(engine, source, market, base))
    common = {
        "id": 977,
        "group": "FMZ · Pine v4 · Restored trend-order mode",
        "period": "Binance USD-M · 2022-05-03 to 2022-05-09 23:59 UTC exclusive",
        "archive_interval": "4h",
        "interval": "4h",
        "currency": "USDT",
        "exit": "Reversal on source fast/slow EMA trend",
    }
    results = [
        {
            **common,
            "market": c["market"],
            **ledger_metrics(c["trades"], CAPITAL, int(bool(c["ending_position"]))),
        }
        for c in cases
    ]
    results.append(
        {
            **common,
            "market": "BTCUSDT + ETHUSDT",
            **ledger_metrics(
                [t for c in cases for t in c["trades"]],
                2 * CAPITAL,
                sum(bool(c["ending_position"]) for c in cases),
            ),
        }
    )
    write(
        output,
        {
            "schema": "FMZ 977 · Historical authored trend orders and original cutoff",
            "source_revision": "7853bb2bf262c4567ac238d3552d97f0e50cb801",
            "source_sha256": sha256(source_path),
            "engine_sha256": ENGINE_SHA,
            "candle_archives": manifest,
            "archived_compile_diagnostics": diagnostics,
            "notes": {
                "compatibility": "The archived Pine v4 file declares an indicator but includes two explicit broker-entry branches. A strategy declaration enables those existing orders. The v4 tostring spelling and the two inert, comment-only visual guards are repaired. Swing and MACD display logic contributes no price gate to the authored order branches.",
                "timing": "The active 240-minute EMA series uses the same four-hour chart and known closed bars. April 16 through May 2 provides price-only warmup, and both order branches become eligible at the saved May 3 start. The terminal quarter-hour includes its 14 confirmed minutes through the 23:59 UTC cutoff. No fill after the saved end is included.",
                "verification": "An independent 20/50 EMA implementation and open-price broker reproduced each trace, reversal and realized lot. Active fills use positive-volume official first 15m children. Starting capital and one fixed base unit follow the native defaults. Fees use a 0.075% per-side unchanged-fill overlay.",
            },
            "coverage": [
                [
                    977,
                    "Tested · Restored original Pine trend-order branches",
                    "Resolved the indicator/order declaration conflict without inventing signal gates. Independently verified both EMA curves, fixed-source order direction, the original minute cutoff, four closed lots and two unsettled positions.",
                ]
            ],
            "results": results,
            "scopes": cases,
        },
    )


if __name__ == "__main__":
    run(*map(Path, sys.argv[1:]))
