"""Isolate first-visible and confirmed HTF values for the #1985 mixed-version source."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from probe_1216 import objects
from replay_2864 import engine_options, pine_compat, sha256

SOURCE = "96e08e35c70481f1f4011e3b34d390df3d4ad4fe24f08608b63da512e5890d5a"
OBS = '\nplot(Mclose,title="HTF close")\nplot(golong ? 1 : 0,title="long")\nplot(goshort ? 1 : 0,title="short")\n'


def scripts():
    markdown = (ROOT / "source-1985.md").read_bytes()
    assert sha256(markdown) == SOURCE
    (pine,) = re.findall(r"(?m)^``` pinescript\n(.*?)^```", markdown.decode(), re.DOTALL)
    raw, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", pine)
    assert n == 1
    legacy = raw.replace("request.security(syminfo.tickerid,", "security(tickerid,")
    assert legacy.count("security(tickerid,") == 3
    typed = raw
    for old, new, count in (
        (r"//@version=2", "//@version=5", 1),
        (r"\b(sma|atr|cross)\(", r"ta.\1(", 9),
        (r"\b(max|min)\(", r"math.\1(", 4),
        (r"\b(green|red|blue|orange|lime)\b", r"color.\1", 8),
        (r"(style\s*=\s*)line\b", r"\1plot.style_line", 2),
        (r"color\.(green|red),0,0\)", r'color.\1,0,"0")', 2),
        (r"(?m)^((?:fastLength|slowLength|signalLength|Factor|Pd)\s*=\s*)input\(", r"\1input.int(", 5),
    ):
        typed, n = re.subn(old, new, typed)
        assert n == count, (old, n, count)
    for var in ("TrendUp", "TrendDown", "MTrendUp", "MTrendDown", "Trend", "MTrend"):
        kind = "int" if var in ("Trend", "MTrend") else "float"
        typed, n = re.subn(rf"(?m)^{var}\s*=", f"{kind} {var} = na\n{var} :=", typed)
        assert n == 1
    on, n = re.subn(r"(?m)^((?:MUp|MDn|Mclose)\s*=request.security\(.*?)\)$", r"\1,lookahead=barmerge.lookahead_on)", typed)
    assert n == 3
    return {"raw": raw, "v2_default": legacy, "v5_lookahead_on": on, "v5_lookahead_off": typed}


def run():
    refs = json.loads((ROOT / "1985-inputs.json").read_bytes())["feeds"]
    result = []
    for ref in refs:
        raw = (ROOT / ref["file"]).read_bytes()
        assert sha256(raw) == ref["sha256"]
        data = json.loads(raw)
        chart, higher = (objects(data[k]) for k in ("chart", "higher"))
        opts = {**engine_options(ref["market"]), "chart_timeframe": "5"}
        opts["request_bars"][f"{opts['chart_symbol']}:120"] = higher
        item = {"market": ref["market"]}
        for mode, code in scripts().items():
            try:
                item[mode] = pine_compat.run_script(code + OBS, chart, **opts)
            except ValueError as error:
                item[mode] = {"exceptions": str(error).splitlines()}
        result.append(item)
    (ROOT / "1985-replay.json").write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "1985-replay-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
