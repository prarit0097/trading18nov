"""Replay FMZ #1070 and isolate original zero/absolute bracket behavior."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from probe_1216 import objects
from replay_2864 import engine_options, pine_compat, sha256
from replay_2994 import heikin_ashi

SOURCE_SHA = "3221a4acbc7f85c74470c2a08b96ed8360558517482ba3fd94b843b365573894"
ABSOLUTE_LIMITS = (
    "nLongs >= 1 ? strategy.position_avg_price * (1 + tp_long) : na",
    "nShorts >= 1 ? strategy.position_avg_price*(1-(tp_short)) : na",
)
NORMALIZED_LIMITS = (
    "nLongs >= 1 ? ceil(strategy.position_avg_price * (1 + tp_long) / syminfo.mintick - 1e-9) * syminfo.mintick : na",
    "nShorts >= 1 ? floor(strategy.position_avg_price*(1-(tp_short)) / syminfo.mintick + 1e-9) * syminfo.mintick : na",
)
FIELDS = {
    "signalL": "L_basic_condt and ACT_BT and testPeriod ? 1 : 0",
    "signalS": "S_basic_condt and ACT_BT and testPeriod ? 1 : 0",
    "trackL": "longCondition ? 1 : 0",
    "trackS": "shortCondition ? 1 : 0",
    "priceL": "last_open_longCondition",
    "priceS": "last_open_shortCondition",
    "sizeL": "nLongs",
    "sizeS": "nShorts",
    "profitL": "abs((last_open_longCondition * (1 + tp_long)) - last_open_longCondition) / syminfo.mintick",
    "profitS": "abs((last_open_shortCondition * (1 - tp_short)) - last_open_shortCondition) / syminfo.mintick",
    "limitL": ABSOLUTE_LIMITS[0],
    "limitS": ABSOLUTE_LIMITS[1],
    "lossL": "abs((last_open_longCondition * (1 - sl / 100)) - last_open_longCondition) / syminfo.mintick",
    "lossS": "abs((last_open_shortCondition * (1 + sl / 100)) - last_open_shortCondition) / syminfo.mintick",
    "targetRatioL": "tp_long",
    "targetRatioS": "tp_short",
    "atrStop": "ATR_L_STOP or ATR_S_STOP ? 1 : 0",
    "period": "testPeriod ? 1 : 0",
    "quantity": "strategy.position_size",
    "average": "strategy.position_avg_price",
}
OBSERVATIONS = "".join(f'\nplot({expression}, title="1070::{name}")'
                       for name, expression in FIELDS.items())
FIXTURES = {
    "zero": ("profit=0, loss=0", ((100, 101, 99), (104, 110, 95), (110, 120, 101))),
    "absolute_over_relative": ("profit=2, limit=105, loss=20",
                               ((100, 101, 99), (100, 103, 99), (103, 106, 101))),
    "absolute_missing_uses_relative": ("profit=2, limit=na, loss=20",
                                      ((100, 101, 99), (100, 103, 99), (103, 106, 101))),
    "zero_joined_after_entry": ("profit=0, loss=0",
                               ((100, 101, 99), (104, 110, 95), (110, 120, 101))),
}

def extract_source():
    raw = (ROOT / "source-1070.md").read_bytes()
    assert sha256(raw) == SOURCE_SHA
    fence = chr(96) * 3
    source, = re.findall(r"(?ms)^" + fence + r"[^\n]*\n(.*?)^" + fence, raw.decode("utf-8"))
    return source

def observations(data, opts, source):
    bars = objects(data["chart"])
    original = pine_compat.run_script(source, bars, **opts)
    witnessed = pine_compat.run_script(source + OBSERVATIONS, bars, **opts)
    bounded, count = re.subn(r"input\(3333,( +title=\"stop year\")", r"input(2222,\1", source)
    assert count == 1
    bounded_result = pine_compat.run_script(bounded + OBSERVATIONS, bars, **opts)
    assert original["strategy"] == witnessed["strategy"] == bounded_result["strategy"]
    def collect(result):
        return {p["title"].removeprefix("1070::"): p["values"] for p in result["plots"] if p.get("title", "").startswith("1070::")}
    series = collect(witnessed)
    assert series == collect(bounded_result)
    assert set(series) == set(FIELDS) and all(len(column) == len(bars) for column in series.values())
    assert all(value == 1 for value in series["period"])
    rounded_src, rounded_plots = source, OBSERVATIONS
    for raw, normalized in zip(ABSOLUTE_LIMITS, NORMALIZED_LIMITS, strict=True):
        assert rounded_src.count(raw) == rounded_plots.count(raw) == 1
        rounded_src = rounded_src.replace(raw, normalized)
        rounded_plots = rounded_plots.replace(raw, normalized)
    rounded = pine_compat.run_script(rounded_src + rounded_plots, bars, **opts)
    rounded_series = collect(rounded)
    assert all(series[k] == rounded_series[k] for k in set(FIELDS) - {"limitL", "limitS", "quantity", "average"})
    return {"broker": original["strategy"], "observations": series,
            "diagnostics": original["diagnostics"], "year_bound_proof": True,
            "normalized": {"broker": rounded["strategy"], "observations": rounded_series,
                           "diagnostics": rounded["diagnostics"], "source_sha256": sha256(rounded_src.encode())}}

def fixtures():
    results = {}
    for version in (4, 5):
        out = {}
        for name, (parameters, ohl) in FIXTURES.items():
            exit_index = 1 if name == "zero_joined_after_entry" else 0
            script = f"""//@version={version}
strategy("1070 bracket fixture", calc_on_order_fills=false, initial_capital=1000, commission_type=strategy.commission.percent, commission_value=0.03)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
if bar_index == {exit_index}
    strategy.exit("X", "L", {parameters})
"""
            bars = [{"time": 1704067200000 + i * 1800000, "open": o, "high": h, "low": low,
                     "close": o, "volume": 1} for i, (o, h, low) in enumerate(ohl)]
            opts = {**engine_options("BTCUSDT"), "chart_timeframe": "30"}
            opts["request_bars"]["$chart"].update(minMove=1, priceScale=1)
            native = pine_compat.run_script(script, bars, **opts)
            out[name] = {"source": script, "bars": bars, "broker": native["strategy"]}
        results[str(version)] = out
    return results

def main():
    source = extract_source()
    manifest = json.loads((ROOT / "1070-inputs.json").read_bytes())
    results = []
    for ref in manifest["feeds"]:
        raw = (ROOT / ref["file"]).read_bytes()
        assert sha256(raw) == ref["sha256"]
        data = json.loads(raw)
        opts = {**engine_options(ref["market"]), "chart_timeframe": "30"}
        symbol = opts["chart_symbol"]
        ticker = json.dumps({"chart": "heikinashi", "symbol": symbol}, separators=(",", ":"))
        chart = objects(data["chart"])
        opts["request_bars"].update({f"{symbol}:30": chart, f"{ticker}:30": heikin_ashi(chart)})
        results.append({"ref": ref, **observations(data, opts, source)})
    fixture_results = fixtures()
    out = {"source_sha256": SOURCE_SHA, "cases": results, "fixtures": fixture_results}
    (ROOT / "1070-native.json").write_bytes(json.dumps(out, separators=(",", ":"), allow_nan=False).encode())
    fixture_inputs = {
        version: {name: {k: fixture[k] for k in ("source", "bars")} for name, fixture in cases.items()}
        for version, cases in fixture_results.items()
    }
    (ROOT / "1070-fixture-inputs.json").write_bytes(json.dumps(fixture_inputs, separators=(",", ":")).encode())

if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        (ROOT / "1070-native-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
