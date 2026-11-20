"""Probe #2547 on the saved FMZ feed before independently auditing fills."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from probe_1216 import objects
from replay_2864 import engine_options, pine_compat, sha256

SOURCE_SHA = "ed71544916ea7904153d57868e4d51219b08448bebf55f2a4cab4696e9687bf7"
OBS = '\nplot(smma)\nplot(smma2)\nplot(smma3)\nplot(smma4)\nplot(out5)\nplot(london ? 1 : 0)\nplot(longCond ? 1 : 0)\nplot(shortCond ? 1 : 0)\nplot(strategy.position_size)\n'


def scripts():
    raw = (ROOT / "source-2547.md").read_bytes()
    assert sha256(raw) == SOURCE_SHA
    (original,) = re.findall(r"(?m)^``` pinescript\n(.*?)^```", raw.decode(), re.DOTALL)
    bare, count = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", original)
    assert count == 1
    v4, count = re.subn(r"(?m)^strategy\.initial_capital\s+= 50000[ \t]*\n", "", bare)
    assert count == 1
    header = 'strategy("Money maker EURUSD 15min" )'
    capital = 'strategy("Money maker EURUSD 15min", initial_capital=50000)'
    assert v4.count(header) == 1
    v4 = v4.replace(header, capital)
    v5 = v4
    for old, new, count in (
        ("//@version=4", "//@version=5", 1),
        ("input(defval =", "input.int(defval =", 6),
        ("input(hl2,", "input.source(hl2,", 3),
        ("input(close,", "input.source(close,", 2),
        ("input(1,type=input.float,", "input.float(1,", 1),
        ("= sma(", "= ta.sma(", 4),
        ("= ema(", "= ta.ema(", 1),
        ('"long",1,1', '"long",strategy.long,1', 1),
        ('"short",0,1', '"short",strategy.short,1', 1),
    ):
        assert v5.count(old) == count, (old, count)
        v5 = v5.replace(old, new)
    v5, count = re.subn(r"input\((3|6|9|50|200), minval", r"input.int(\1, minval", v5)
    assert count == 5
    v5, count = re.subn(r'"(0300-1045|0300-0845|0745-1030)"', r'"\1:23456"', v5)
    assert count == 3
    base = v5.replace(capital, capital[:-1] + ", use_bar_magnifier=true)")
    return bare, v4, v5, base


def cases():
    manifest = json.loads((ROOT / "2547-inputs.json").read_bytes())
    for ref in manifest["feeds"]:
        raw = (ROOT / ref["file"]).read_bytes()
        assert sha256(raw) == ref["sha256"]
        frame = json.loads(raw)
        assert frame["market"] == ref["market"]
        ohlc, lower = frame["chart"], frame["lower"]
        chart = objects(ohlc)
        groups = [
            {"chartBarIndex": i, "bars": objects(lower[i * 4 : (i + 1) * 4])}
            for i in range(len(chart))
        ]
        opts = {**engine_options(ref["market"]), "chart_timeframe": "60"}
        yield ref, chart, groups, opts


def run():
    invalid, original, migrated, base = scripts()
    results = []
    for ref, chart, groups, opts in cases():
        found = {"file": ref["file"]}
        for key, code in (("invalid", invalid), ("original", original), ("migrated", migrated), ("base", base)):
            args = {**opts}
            if key == "base":
                args["magnifier_bars"] = {"schemaVersion": 1, "chartBars": groups}
            try:
                found[key] = pine_compat.run_script(code + OBS, chart, **args)
            except ValueError as error:
                found[key] = {"exception": str(error).splitlines()}
        positive_groups = [
            {**group, "bars": [row for row in group["bars"] if row["volume"] > 0]}
            for group in groups
        ]
        assert all(g["bars"] for g in positive_groups)
        if positive_groups != groups:
            price_chart = [
                {**parent, "open": children["bars"][0]["open"]}
                for parent, children in zip(chart, positive_groups, strict=True)
            ]
            for key, charts, children in (
                ("drop_zero_children", chart, positive_groups),
                ("first_print_execution_chart", price_chart, positive_groups),
            ):
                try:
                    found[key] = pine_compat.run_script(base + OBS, charts, **opts, magnifier_bars={"schemaVersion": 1, "chartBars": children})
                except ValueError as error:
                    found[key] = {"exception": str(error).splitlines()}
        results.append(found)
    (ROOT / "2547-replay.json").write_text(json.dumps(results, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "2547-replay-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
