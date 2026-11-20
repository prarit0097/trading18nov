"""Replay exact #2994 with all timestamped request feeds."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from probe_1216 import objects
from replay_2864 import engine_options, pine_compat, sha256

SOURCE_SHA = "f9ccc275870a1bd0cb3dab7160fe0a46fa4c719c07aeb139798aeb28baf7c265"
OBS = '''
plot(wt1, title="Observed WT1")
plot(wt2, title="Observed WT2")
plot(long_entry ? 1 : 0, title="Observed long")
plot(short_entry ? 1 : 0, title="Observed short")
plot(long_exit_entry ? 1 : 0, title="Observed short-side close")
plot(short_exit_entry ? 1 : 0, title="Observed long-side close")
plot(strategy.position_size, title="Observed position")
'''


def source():
    raw = (ROOT / "source-2994.md").read_bytes()
    assert sha256(raw) == SOURCE_SHA
    (script,) = re.findall(r"(?m)^``` pinescript\n(.*?)^```", raw.decode(), re.DOTALL)
    script, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", script)
    assert n == 1
    return script


def heikin_ashi(rows):
    prior = None
    result = []
    for row in rows:
        o, h, low, c = (row[x] for x in ("open", "high", "low", "close"))
        new_open = (o + c) / 2 if prior is None else sum(prior) / 2
        new_close = (o + h + low + c) / 4
        result.append({**row, "open": new_open, "high": max(h, new_open, new_close), "low": min(low, new_open, new_close), "close": new_close})
        prior = (new_open, new_close)
    return result


def cases():
    manifest = json.loads((ROOT / "2994-inputs.json").read_bytes())
    for ref in manifest["feeds"]:
        raw = (ROOT / ref["file"]).read_bytes()
        assert sha256(raw) == ref["sha256"]
        data = json.loads(raw)
        day, hour, four, half = (objects(data[k]) for k in ("day", "hour", "four", "half"))
        opts = {**engine_options(ref["market"]), "chart_timeframe": "D"}
        symbol = opts["chart_symbol"]
        ticker = json.dumps({"chart": "heikinashi", "symbol": symbol}, separators=(",", ":"))
        opts["request_bars"].update({
            f"{symbol}:720": half,
            f"{symbol}:240": four,
            f"{ticker}:60": heikin_ashi(hour),
            f"{ticker}:240": heikin_ashi(four),
        })
        yield ref, day, hour, four, opts


def run():
    results = []
    for ref, chart, hour, four, opts in cases():
        result = {"file": ref["file"]}
        try:
            script = source()
            result["original"] = pine_compat.run_script(script, chart, **opts)
            result["observed"] = pine_compat.run_script(script + OBS, chart, **opts)
            changed = {
                key: [
                    {k: v * (1 + (idx % 4) / 10) if k in ("open", "high", "low", "close") else v for k, v in row.items()}
                    for idx, row in enumerate(rows)
                ] if key != "$chart" else rows
                for key, rows in opts["request_bars"].items()
            }
            result["perturbed_visual_feeds"] = pine_compat.run_script(script + OBS, chart, **{**opts, "request_bars": changed})
        except ValueError as error:
            result["original"] = {"exception": str(error).splitlines()}
        results.append(result)
    (ROOT / "2994-replay.json").write_text(json.dumps(results, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "2994-replay-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
