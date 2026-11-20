"""Compare #3952's unconfirmed daily confidence with causal confirmed inputs."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from probe_1216 import objects
from replay_2864 import engine_options, pine_compat, sha256

SOURCE = "4d54a899e3638fd582f3fcec3126da7aa72ad1314d0b4915906e99c10dc20624"
OBS = '''
plot(confidence,title="Observed confidence")
plot(longCondition ? 1 : 0,title="Observed long")
plot(shortCondition ? 1 : 0,title="Observed short")
plot(closelong ? 1 : 0,title="Observed exit long")
plot(closeshort ? 1 : 0,title="Observed exit short")
'''


def scripts():
    md = (ROOT / "source-3952.md").read_bytes()
    assert sha256(md) == SOURCE
    (block,) = re.findall(r"(?m)^``` pinescript\n(.*?)^```", md.decode(), re.DOTALL)
    raw, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", block)
    assert n == 1
    fixed = raw.replace("step=0.0001)`", "step=0.0001)")
    assert fixed != raw
    legacy = fixed.replace("syminfo.tickerid", "tickerid")
    after = fixed
    for old, new, expected in (
        (r"//@version=2", "//@version=5", 1),
        (r"(?m)^((?:keh|conversionPeriods|basePeriods|laggingSpan2Periods|displacement)\s*=\s*)input\(", r"\1input.int(", 5),
        (r"(?m)^((?:dt|SL|TP)\s*=\s*)input\(", r"\1input.float(", 3),
        (r"\b(wma|cross|highest|lowest|ema)\(", r"ta.\1(", 13),
        (r"\b(round|sqrt|avg)\(", r"math.\1(", 8),
        (r"\b(lime|green|red)\b", r"color.\1", 10),
        (r"(style\s*=\s*)(circles|line)\b", r"\1plot.style_\2", 2),
        (r"\bsecurity\(", "request.security(", 3),
    ):
        after, n = re.subn(old, new, after)
        assert n == expected, (old, n, expected)
    before, n = re.subn(r"request.security\(syminfo.tickerid, 'D', (close(?:\[1\])?)\)", r"request.security(syminfo.tickerid, 'D', \1, lookahead=barmerge.lookahead_on)", after)
    assert n == 3
    return {"raw": raw, "legacy": legacy, "v5_on": before, "v5_off": after}


def run():
    cases = json.loads((ROOT / "3952-inputs.json").read_bytes())["feeds"]
    data = []
    for case in cases:
        raw = (ROOT / case["file"]).read_bytes()
        assert sha256(raw) == case["sha256"]
        payload = json.loads(raw)
        chart, higher = (objects(payload[k]) for k in ("chart", "higher"))
        opts = {**engine_options(case["market"]), "chart_timeframe": "240"}
        opts["request_bars"][f"{opts['chart_symbol']}:D"] = higher
        sample = {"market": case["market"]}
        for mode, script in scripts().items():
            try:
                sample[mode] = pine_compat.run_script(script + OBS, chart, **opts)
            except ValueError as error:
                sample[mode] = {"exceptions": str(error).splitlines()}
        data.append(sample)
    (ROOT / "3952-replay.json").write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "3952-replay-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
