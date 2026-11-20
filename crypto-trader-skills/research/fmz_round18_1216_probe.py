"""Probe the #1216 saved v4 body and its exact-session lower-base control."""

import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from replay_2864 import engine_options, near, pine_compat, sha256

SOURCE = "784b4554332fba13d142f8e0d58c17110190dfd8fa1b96b5b61f96160e219eee"
MINUTE = 60_000
CAPITAL = 50_000


def source_versions():
    raw = (ROOT / "source-1216.md").read_bytes()
    assert sha256(raw) == SOURCE
    (code,) = re.findall(r"(?m)^``` pinescript\n(.*?)^```", raw.decode(), re.DOTALL)
    archive, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", code)
    assert n == 1
    declaration = 'strategy(title="Triple EMA Scalper low lag strat", shorttitle="3EMA scalper", overlay=true)'
    assert archive.count(declaration) == 1
    current, n = re.subn(r"(?m)^strategy\.initial_capital = 50000[ \t]*\n", "", archive)
    assert n == 1
    active = declaration[:-1] + ", initial_capital=50000)"
    legacy = current.replace(declaration, active)
    changes = (
        ("//@version=4", "//@version=5", 1),
        ("ema(", "ta.ema(", 6),
        ("crossover(", "ta.crossover(", 4),
        ("crossunder(", "ta.crossunder(", 4),
        ('"0300-1100"', '"0300-1100:23456"', 1),
        ('"0800-1600"', '"0800-1600:23456"', 1),
        ("input(25, minval=1", "input.int(25, minval=1", 1),
        ("input(50, minval=1", "input.int(50, minval=1", 1),
        ("input(100, minval=1", "input.int(100, minval=1", 1),
        ('input(close, title="Source")', 'input.source(close, title="Source")', 1),
        (
            'input(title="Trade london session?", type=input.bool',
            'input.bool(title="Trade london session?"',
            1,
        ),
        (
            'input(title="Trade new york session?", type=input.bool',
            'input.bool(title="Trade new york session?"',
            1,
        ),
        (
            'input(1,type=input.float,title="Risk % of equity ")',
            'input.float(1,title="Risk % of equity ")',
            1,
        ),
        ('strategy.entry("long",1,', 'strategy.entry("long",strategy.long,', 2),
        ('strategy.entry("short",0,', 'strategy.entry("short",strategy.short,', 2),
    )
    combined = legacy
    for old, new, count in changes:
        assert combined.count(old) == count, (old, count)
        combined = combined.replace(old, new)
    base = combined.replace(active, active[:-1] + ", use_bar_magnifier=true)")
    return archive, legacy, combined, base


def objects(rows):
    return [
        dict(zip(("time", "open", "high", "low", "close", "volume"), r, strict=True))
        for r in rows
    ]


def load_cases():
    archive = json.loads((ROOT / "1216-inputs.json").read_bytes())
    for row in archive["samples"]:
        raw = (ROOT / row["file"]).read_bytes()
        assert sha256(raw) == row["sha256"]
        payload = json.loads(raw)
        start, end = payload["start"], payload["end"]
        chart, base = objects(payload["chart"]), objects(payload["lower"])
        assert [b["time"] for b in chart] == list(range(start, end, 15 * MINUTE))
        assert [b["time"] for b in base] == list(range(start, end, 5 * MINUTE))
        assert len(chart) * 3 == len(base)
        groups = [
            {"chartBarIndex": i, "bars": base[3 * i : 3 * i + 3]}
            for i in range(len(chart))
        ]
        for high_bar, group in zip(chart, groups, strict=True):
            a, b, c = group["bars"]
            assert high_bar["open"] == a["open"] and high_bar["close"] == c["close"]
            assert high_bar["high"] == max(a["high"], b["high"], c["high"])
            assert high_bar["low"] == min(a["low"], b["low"], c["low"])
            near(high_bar["volume"], math.fsum(x["volume"] for x in (a, b, c)))
        yield row, start, end, chart, groups


def probe():
    archive, old, modern, based = source_versions()
    cases = []
    try:
        pine_compat.compile_script(archive)
    except ValueError as error:
        original_result = str(error).splitlines()
    else:
        raise AssertionError("Expected unsupported source assignment.")
    programs = [pine_compat.compile_script(source) for source in (old, modern, based)]
    for row, start, end, chart, groups in load_cases():
        options = {**engine_options(row["market"]), "chart_timeframe": "15"}
        result = [program.run(chart, **options) for program in programs[:2]]
        result.append(
            programs[-1].run(
                chart,
                **options,
                magnifier_bars={"schemaVersion": 1, "chartBars": groups},
            )
        )
        cases.append(
            {
                **row,
                "start": start,
                "end": end,
                "old": result[0]["strategy"],
                "modern": result[1]["strategy"],
                "base": result[2]["strategy"],
                "warnings": [r["diagnostics"] for r in result],
            }
        )
    output = {"archive_error": original_result, "cases": cases}
    (ROOT / "1216-probe.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf8"
    )


if __name__ == "__main__":
    try:
        probe()
    except Exception:
        import traceback

        (ROOT / "1216-error.txt").write_text(traceback.format_exc(), encoding="utf8")
        raise
