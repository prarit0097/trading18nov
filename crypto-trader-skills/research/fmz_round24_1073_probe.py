"""Replay the #1073 wrapper with its exact archived strategy header restored."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from probe_1216 import objects
from replay_2864 import engine_options, pine_compat, sha256
from replay_2994 import OBS, heikin_ashi

SOURCE_SHA = "50de3085564b9c1ab144405b1d6f4af89ee4efff64845a3227dd50c63154fa71"
VERIFIED_BODY = "667c34a5e4412baa521862ecf2aad24914f9c04b8eefb2df5c603ed5c69712f7"
HEADER = "strategy(title='VMC', shorttitle='VMC', overlay=true, precision=3, commission_value=0.025, default_qty_type=strategy.cash, default_qty_value=10000, initial_capital=10000)"


def scripts():
    raw = (ROOT / "source-1073.md").read_bytes()
    assert sha256(raw) == SOURCE_SHA
    (script,) = re.findall(r"(?m)^``` pinescript\n(.*?)^```", raw.decode(), re.DOTALL)
    legacy, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", script)
    assert n == 1
    assert not re.search(r"(?m)^\s*strategy\s*\(", legacy)
    assert legacy.count("//" + HEADER) == 1
    normalized = legacy.replace("//" + HEADER, HEADER)
    assert sha256(normalized.encode()) == VERIFIED_BODY
    return legacy, normalized


def cases():
    manifest = json.loads((ROOT / "1073-inputs.json").read_bytes())
    for ref in manifest["feeds"]:
        raw = (ROOT / ref["file"]).read_bytes()
        assert sha256(raw) == ref["sha256"]
        data = json.loads(raw)
        chart, base, hour, four, half = (objects(data[k]) for k in ("chart", "base", "hour", "four", "half"))
        opts = {**engine_options(ref["market"]), "chart_timeframe": "120"}
        symbol = opts["chart_symbol"]
        ticker = json.dumps({"chart": "heikinashi", "symbol": symbol}, separators=(",", ":"))
        opts["request_bars"].update({
            f"{symbol}:720": half,
            f"{symbol}:240": four,
            f"{ticker}:60": heikin_ashi(hour),
            f"{ticker}:240": heikin_ashi(four),
        })
        yield ref, data, chart, base, opts


def run():
    results = []
    _, script = scripts()
    for ref, _, chart, _, opts in cases():
        result = {"file": ref["file"]}
        try:
            result["observed"] = pine_compat.run_script(script + OBS, chart, **opts)
        except ValueError as error:
            result["observed"] = {"exception": str(error).splitlines()}
        results.append(result)
        (ROOT / "1073-replay.json").write_text(json.dumps(results, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "1073-replay-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
