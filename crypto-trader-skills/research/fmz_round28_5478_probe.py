"""Isolate #5478 saved EMA-confirmed PSAR orders and cash initialization."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from probe_1216 import objects
from replay_2864 import engine_options, pine_compat, sha256

SOURCE = "d433f98b53fedb2edca6f2ed1e8f6692b4f70058a2cc9d85a28591ba546449e7"
OBS = '''
plot(psar,title="Observed PSAR")
plot(psarDir,title="Observed PSAR direction")
plot(emaFast,title="Observed EMA fast")
plot(emaSlow,title="Observed EMA slow")
plot(psarBuySignal ? 1 : 0,title="Observed buy cross")
plot(psarSellSignal ? 1 : 0,title="Observed sell cross")
plot(psarConfirmationBuy ? 1 : 0,title="Observed bullish confirmation")
plot(psarConfirmationSell ? 1 : 0,title="Observed bearish confirmation")
plot(inDateRange ? 1 : 0,title="Observed date gate")
plot(useSL ? 1 : 0,title="Observed stop active")
'''


def source():
    raw = (ROOT / "source-5478.md").read_bytes()
    assert sha256(raw) == SOURCE
    (body,) = re.findall(r"(?m)^``` pinescript\n(.*?)^```", raw.decode(), re.DOTALL)
    pine, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", body)
    assert n == 1
    return pine


def cases():
    manifest = json.loads((ROOT / "5478-inputs.json").read_bytes())
    quote = (ROOT / manifest["fx"]["file"]).read_bytes()
    assert sha256(quote) == manifest["fx"]["sha256"]
    for ref in manifest["feeds"]:
        raw = (ROOT / ref["file"]).read_bytes()
        assert sha256(raw) == ref["sha256"]
        data = json.loads(raw)
        chart, base = (objects(data[k]) for k in ("chart", "base"))
        opts = {**engine_options(ref["market"]), "chart_timeframe": "45"}
        opts["request_bars"]["$currencyRates"] = json.loads(quote)
        yield ref, data, chart, base, opts


def run():
    out = []
    for ref, data, chart, _, opts in cases():
        observed = {"market": ref["market"]}
        for label, clock in (("primary", data["end"]), ("other_clock", data["end"] + 86_400_000 * 366)):
            try:
                observed[label] = pine_compat.run_script(source() + OBS, chart, **opts, execution_times=[clock] * len(chart))
            except ValueError as error:
                observed[label] = {"exceptions": str(error).splitlines()}
        out.append(observed)
    (ROOT / "5478-replay.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "5478-replay-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
