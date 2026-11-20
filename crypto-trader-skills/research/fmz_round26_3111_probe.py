"""Probe recursive #3111 with and without historical recalculation on fills."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from probe_1216 import objects
from replay_2864 import engine_options, pine_compat, sha256

SOURCE_SHA = "9d07debc4023acd5925f1ffe221f15516983d25501279b94f89c3c90aeb12570"
OBS = '''
plot(kamaEntry, title="Observed KAMA")
plot(n1, title="Observed HMA")
plot(n2, title="Observed prior HMA")
plot(buyEntry ? 1 : 0, title="Observed buy")
plot(sellEntry ? 1 : 0, title="Observed sell")
plot(strategy.position_size, title="Observed position")
'''


def scripts():
    raw = (ROOT / "source-3111.md").read_bytes()
    assert sha256(raw) == SOURCE_SHA
    (source,) = re.findall(r"(?m)^``` pinescript\n(.*?)^```", raw.decode(), re.DOTALL)
    bare, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", source)
    assert n == 1
    v2 = bare.replace("request.security(", "security(").replace("syminfo.tickerid", "tickerid").replace("timeframe.period", "period")
    assert v2 != bare
    v5 = bare
    changes = (
        (r"//@version=2", "//@version=5", 1),
        (r"\bk = nz\(k\[1\]\)", "float k = na\n    k := nz(k[1])", 1),
        (r"\biff\(volatility != 0, change/volatility, 0\)", "volatility != 0 ? change/volatility : 0", 1),
        (r"\binput\((8|4), minval=1\)", r"input.int(\1, minval=1)", 2),
        (r"\babs\(", "math.abs(", 2),
        (r"\bsum\(", "math.sum(", 1),
        (r"\bwma\(", "ta.wma(", 6),
        (r"\bsqrt\(", "math.sqrt(", 2),
        (r"\bround\(", "math.round(", 4),
        (r"\bpow\(", "math.pow(", 1),
        (r"\bcross\(", "ta.cross(", 1),
        (r"style = cross\b", "style = plot.style_cross", 1),
        (r"style=line\b", "style=plot.style_line", 1),
        (r"\b(lime|red|gray)\b", r"color.\1", 3),
    )
    for old, new, expected in changes:
        v5, count = re.subn(old, new, v5)
        assert count == expected, (old, count, expected)
    unrounded = v5
    v5 = unrounded.replace("math.round(n/2)", "math.round(int(n/2))")
    assert v5 != unrounded
    variants = {"raw": bare, "legacy": v2, "typed": v5, "typed_unrounded": unrounded}
    variants["legacy_same_context"] = v2.replace("security(tickerid,period,kama(kamaPeriod))", "kama(kamaPeriod)")
    variants["typed_same_context"] = v5.replace("request.security(syminfo.tickerid,timeframe.period,kama(kamaPeriod))", "kama(kamaPeriod)")
    assert variants["legacy_same_context"] != v2 and variants["typed_same_context"] != v5
    variants["typed_close_only"] = v5.replace("calc_on_order_fills=true", "calc_on_order_fills=false")
    variants["typed_magnifier"] = v5.replace("calc_on_order_fills=true", "calc_on_order_fills=true, use_bar_magnifier=true")
    return variants


def cases():
    receipt = json.loads((ROOT / "3111-inputs.json").read_bytes())
    for r in receipt["feeds"]:
        raw = (ROOT / r["file"]).read_bytes()
        assert sha256(raw) == r["sha256"]
        data = json.loads(raw)
        chart, base = (objects(data[k]) for k in ("chart", "base"))
        group = [{"chartBarIndex": i, "bars": base[i * 9 : (i + 1) * 9]} for i in range(len(chart))]
        options = {**engine_options(r["market"]), "chart_timeframe": "45"}
        yield r, chart, group, options


def run():
    results = []
    for r, chart, group, opts in cases():
        observed = {"file": r["file"]}
        for label, script in scripts().items():
            options = {**opts}
            if label == "typed_magnifier":
                options["magnifier_bars"] = {"schemaVersion": 1, "chartBars": group}
            try:
                observed[label] = pine_compat.run_script(script + OBS, chart, **options)
            except ValueError as error:
                observed[label] = {"exception": str(error).splitlines()}
        bar_open_controls = []
        if "strategy" in observed["typed"]:
            round_trips = [t for t in observed["typed"]["strategy"]["trades"] if t["entryBarIndex"] == t["exitBarIndex"]]
            for lot in round_trips:
                i = lot["entryBarIndex"]
                bar = chart[i]
                at_open = {**bar, "high": bar["open"], "low": bar["open"], "close": bar["open"]}
                as_of = pine_compat.run_script(scripts()["typed_close_only"] + OBS, [*chart[:i], at_open], **opts)
                saved = []
                for report in (as_of, observed["typed_close_only"]):
                    flags = {p["title"]: p["values"][i] for p in report["plots"] if p.get("title") in ("Observed buy", "Observed sell")}
                    saved.append(flags)
                bar_open_controls.append({"lot": lot, "open_only_flags": saved[0], "full_bar_flags": saved[1]})
        observed["available_at_open_control"] = bar_open_controls
        results.append(observed)
    (ROOT / "3111-replay.json").write_text(json.dumps(results, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "3111-replay-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
