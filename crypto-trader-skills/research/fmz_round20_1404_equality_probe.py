"""Isolate how the pinned supports runtime evaluates mixed bool/int equality."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from replay_2864 import pine_compat


CORE = '''
indicator("Strict versus implicit comparison")
parameter = BOOLEAN_INPUT
value = bar_index > 0
plot(value ? 1 : 0)
plot(value == 1 ? 1 : 0)
plot(value == true ? 1 : 0)
plot(parameter == 1 ? 1 : 0)
plot(value == 0 ? 1 : 0)
plot(true == 1 ? 1 : 0)
plot(false == 0 ? 1 : 0)
plot(1 == 1 ? 1 : 0)
'''


def run():
    first = 1_702_944_000_000
    bars = [{"time": first + i * 180_000, "open": 100, "high": 100, "low": 100, "close": 100, "volume": 1} for i in range(3)]
    rows = {}
    for v, expr in ((4, "input(true, type=input.bool)"), (5, "input.bool(true)")):
        script = f"//@version={v}\n" + CORE.replace("BOOLEAN_INPUT", expr)
        if v == 4:
            script = script.replace("indicator(", "study(")
        output = pine_compat.run_script(script, bars)
        assert not output["diagnostics"]
        rows[f"v{v}"] = [p["values"] for p in output["plots"]]
    (ROOT / "1404-equality.json").write_text(json.dumps(rows, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "1404-equality-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
