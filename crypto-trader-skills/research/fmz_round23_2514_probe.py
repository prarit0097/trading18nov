"""Exercise the #2514 source's actual 4h-in-daily requests and USD quote."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from probe_1216 import objects
from replay_2864 import engine_options, pine_compat, sha256

SOURCE_SHA = "b8092e2408152bd6c8c87000ff6ed99e9732f2a59f8b70d9333cfc4668e142a3"
NAMES = (
    "sma10", "sma20", "sma30", "sma50", "sma100", "sma200",
    "ema10", "ema20", "ema30", "ema50", "ema100", "ema200", "hull9", "vwma20",
    "rsi", "stoch", "cci", "ao", "mom", "macd", "stochrsi", "wpr", "uo", "adx", "bbp",
)
OBS = "\n" + "\n".join(f'plot({name}_index, title="Observed {name} vote")' for name in NAMES)
OBS += '\nplot(strategy.position_size, title="Observed position")\n'


def program():
    raw = (ROOT / "source-2514.md").read_bytes()
    assert sha256(raw) == SOURCE_SHA
    (source,) = re.findall(r"(?m)^``` pinescript\n(.*?)^```", raw.decode(), re.DOTALL)
    source, removed = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", source)
    assert removed == 1
    source, request_count = re.subn(r"\brequest\.security\(", "security(", source)
    source, colors = re.subn(r"(color\s*=\s*)(red|green|blue|silver|orange)\b", r"\1color.\2", source)
    assert (request_count, colors) == (20, 10)
    return source


def cases():
    manifest = json.loads((ROOT / "2514-inputs.json").read_bytes())
    fx_raw = (ROOT / manifest["fx"]["file"]).read_bytes()
    assert sha256(fx_raw) == manifest["fx"]["sha256"]
    fx = json.loads(fx_raw)
    for ref in manifest["feeds"]:
        raw = (ROOT / ref["file"]).read_bytes()
        assert sha256(raw) == ref["sha256"]
        data = json.loads(raw)
        chart, base, hours = (objects(data[k]) for k in ("chart", "base", "hours"))
        opts = {**engine_options(ref["market"]), "chart_timeframe": "D"}
        opts["request_bars"][f"{opts['chart_symbol']}:240"] = base
        opts["request_bars"]["$currencyRates"] = fx
        yield ref, chart, base, hours, opts


def fixture(opts):
    original = '''//@version=4
study("Closed 4h sample probe")
average(src, len) => security(syminfo.tickerid, "240", sma(src, len))
plot(average(close, 2), title="last confirmed")
plot(security(syminfo.tickerid, "240", close, barmerge.gaps_off, barmerge.lookahead_on), title="first in bucket")
'''
    symbol = opts["chart_symbol"]
    first, span = 1_702_944_000_000, 14_400_000
    lower = [{"time": first + i * span, "open": 100 + i, "high": 100 + i, "low": 100 + i, "close": 100 + i, "volume": 1} for i in range(18)]
    daily = [
        {"time": group[0]["time"], "open": group[0]["open"], "high": group[-1]["high"], "low": group[0]["low"], "close": group[-1]["close"], "volume": 6}
        for group in (lower[i : i + 6] for i in range(0, len(lower), 6))
    ]
    cfg = {**opts, "request_bars": {"$chart": opts["request_bars"]["$chart"], f"{symbol}:240": lower}}
    result = pine_compat.run_script(original, daily, **cfg)
    return {"values": [p["values"] for p in result["plots"]], "diagnostics": result["diagnostics"]}


def run():
    results = []
    source = program()
    for ref, chart, _, _, opts in cases():
        result = {"file": ref["file"]}
        if not results:
            result["lower_fixture"] = fixture(opts)
        try:
            result["native"] = pine_compat.run_script(source + OBS, chart, **opts)
        except ValueError as error:
            result["native"] = {"exception": str(error).splitlines()}
        results.append(result)
        (ROOT / "2514-replay.json").write_text(json.dumps(results, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "2514-replay-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
