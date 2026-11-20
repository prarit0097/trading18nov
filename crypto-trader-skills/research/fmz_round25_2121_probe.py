"""Replay localized #2121 Pine migrations with matched decision and execution feeds."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from probe_1216 import objects
from replay_2864 import engine_options, pine_compat, sha256

SOURCE_SHA = "44c5bcf86c7e0df8c55182eb2015f3a95962e94305dabad05d1371ed1b58094a"
VARS = ("Up", "Dn", "MUp", "MDn", "Mclose", "TrendUp", "TrendDown", "MTrendUp", "MTrendDown", "Trend", "MTrend", "Tsl", "MTsl")
OBS = "\n" + "\n".join(f'plot({v}, title="Observed {v}")' for v in VARS)
OBS += '\nplot(golong ? 1 : 0, title="Observed long")\nplot(goshort ? 1 : 0, title="Observed short")\nplot(strategy.position_size, title="Observed position")\n'


def program():
    raw = (ROOT / "source-2121.md").read_bytes()
    assert sha256(raw) == SOURCE_SHA
    (program,) = re.findall(r"(?m)^``` pinescript\n(.*?)^```", raw.decode(), re.DOTALL)
    invalid, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", program)
    assert n == 1
    v4, security = re.subn(r"\brequest\.security\(", "security(", invalid)
    assert security == 3
    v4, styles = re.subn(r"(style\s*=\s*)line\b", r"\1plot.style_line", v4)
    assert styles == 2
    v4, colors = re.subn(r"\b(green|red|blue|orange|lime)\b", r"color.\1", v4)
    assert colors == 8
    for var in ("TrendUp", "TrendDown", "MTrendUp", "MTrendDown", "Trend", "MTrend"):
        kind = "int" if var in ("Trend", "MTrend") else "float"
        v4, substitutions = re.subn(rf"(?m)^{var}\s*=", f"{kind} {var} = na\n{var} :=", v4)
        assert substitutions == 1, var
    v5 = v4
    for old, new, count in (
        (r"//@version=4", "//@version=5", 1),
        (r"\bsecurity\(", "request.security(", 3),
        (r"\batr\(", "ta.atr(", 4),
        (r"\bcross\(", "ta.cross(", 2),
        (r"\bmax\(", "math.max(", 2),
        (r"\bmin\(", "math.min(", 2),
        (r"input\(1, minval=1,maxval = 100\)", "input.int(1, minval=1,maxval = 100)", 2),
        (r"color\.(green|red),0,0\)", r'color.\1,0,"0")', 2),
    ):
        v5, matches = re.subn(old, new, v5)
        assert matches == count, (old, matches, count)
    magnified = v5.replace('strategy("Anuj4912", overlay=true)', 'strategy("Anuj4912", overlay=true, use_bar_magnifier=true)')
    return invalid, v4, v5, magnified


def cases():
    manifest = json.loads((ROOT / "2121-inputs.json").read_bytes())
    for ref in manifest["feeds"]:
        raw = (ROOT / ref["file"]).read_bytes()
        assert sha256(raw) == ref["sha256"]
        data = json.loads(raw)
        chart, refs, base = (objects(data[k]) for k in ("chart", "references", "hour"))
        opts = {**engine_options(ref["market"]), "chart_timeframe": "D"}
        opts["request_bars"][f"{opts['chart_symbol']}:120"] = refs
        groups = [{"chartBarIndex": i, "bars": base[i * 24 : (i + 1) * 24]} for i in range(len(chart))]
        yield ref, chart, refs, groups, opts


def run():
    hashes = program()
    results = []
    for ref, chart, _, groups, opts in cases():
        output = {"file": ref["file"]}
        for label, source in zip(("invalid", "legacy", "migrated", "magnified"), hashes, strict=True):
            args = {**opts}
            if label == "magnified":
                args["magnifier_bars"] = {"schemaVersion": 1, "chartBars": groups}
            try:
                output[label] = pine_compat.run_script(source + OBS, chart, **args)
            except ValueError as error:
                output[label] = {"exceptions": str(error).splitlines()}
        results.append(output)
        (ROOT / "2121-replay.json").write_text(json.dumps(results, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "2121-replay-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
