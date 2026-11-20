"""Probe native archives and a mechanical lower-timeframe migration for #1404."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from probe_1216 import objects
from replay_2864 import engine_options, pine_compat, sha256

SOURCE_SHA = "4680d886ec40d847a9b7547624cdedc3b00e4045fc36d61051ad9c6275df442e"
OBS = '\nplot(myRSI)\nplot(buy ? 1 : 0)\nplot(sell ? 1 : 0)\nplot(myPosition)\nplot(london ? 1 : 0)\nplot(newyork ? 1 : 0)\nplot(strategy.position_size)\n'


def scripts():
    raw = (ROOT / "source-1404.md").read_bytes()
    assert sha256(raw) == SOURCE_SHA
    (source,) = re.findall(r"(?m)^``` pinescript\n(.*?)^```", raw.decode(), re.DOTALL)
    invalid, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", source)
    assert n == 1
    v4, n = re.subn(r"(?m)^strategy\.initial_capital = 50000[ \t]*\n", "", invalid)
    assert n == 1
    header = 'strategy("RSI Algo", overlay=true)'
    capital = 'strategy("RSI Algo", overlay=true, initial_capital=50000)'
    assert v4.count(header) == 1
    v4 = v4.replace(header, capital)
    stop_literal = 'stop = input(250, title="stop loss pips")'
    assert v4.count(stop_literal) == 1
    v4 = v4.replace(stop_literal, 'stop = float(input(250, title="stop loss pips"))')
    v5 = v4
    for old, new, count in (
        ("//@version=4", "//@version=5", 1),
        ("input(defval=14, type=input.integer,", "input.int(defval=14,", 1),
        ("input(defval=75, type=input.float,", "input.float(defval=75,", 1),
        ("input(defval=25, type=input.float,", "input.float(defval=25,", 1),
        ("type=input.bool, ", "", 3),
        ("input(2,type=input.float,", "input.float(2,", 1),
        ('"long",1,size', '"long",strategy.long,size', 1),
        ('"short",0,size', '"short",strategy.short,size', 1),
    ):
        assert v5.count(old) == count, (old, v5.count(old), count)
        v5 = v5.replace(old, new)
    for old, new, count in (
        (r'iff\(DST==0,"(\d{4}-\d{4})","(\d{4}-\d{4})"\)', r'(DST==0 ? "\1:23456" : "\2:23456")', 4),
        (r'(?<!\w)(rsi|rising|falling|cross)\(', r'ta.\1(', 9),
    ):
        v5, n = re.subn(old, new, v5)
        assert n == count, (old, n, count)
    base = v5.replace(capital, capital[:-1] + ", use_bar_magnifier=true)")
    for old, new in (("buy==1", "buy"), ("sell==1", "sell")):
        assert base.count(old) == 1
    explicit = base.replace("buy==1", "buy").replace("sell==1", "sell")
    return invalid, v4, v5, base, explicit


def cases():
    manifest = json.loads((ROOT / "1404-inputs.json").read_bytes())
    for ref in manifest["feeds"]:
        stamp = (ROOT / ref["file"]).read_bytes()
        assert sha256(stamp) == ref["sha256"]
        data = json.loads(stamp)
        chart, lower = objects(data["chart"]), objects(data["lower"])
        assert not ref["zero_print_timestamps"]
        assert len(chart) * 3 == len(lower)
        groups = [{"chartBarIndex": i, "bars": lower[3 * i : 3 * i + 3]} for i in range(len(chart))]
        opts = {**engine_options(ref["market"]), "chart_timeframe": "3"}
        yield ref, chart, groups, opts


def run():
    source = list(zip(("invalid", "original", "migrated", "base", "explicit_bool"), scripts(), strict=True))
    results = []
    for ref, chart, groups, opts in cases():
        result = {"file": ref["file"]}
        for key, script in source:
            args = {**opts}
            if key in ("base", "explicit_bool"):
                args["magnifier_bars"] = {"schemaVersion": 1, "chartBars": groups}
            try:
                result[key] = pine_compat.run_script(script + OBS, chart, **args)
            except ValueError as error:
                result[key] = {"exception": str(error).splitlines()}
        results.append(result)
    (ROOT / "1404-replay.json").write_text(json.dumps(results, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "1404-replay-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
