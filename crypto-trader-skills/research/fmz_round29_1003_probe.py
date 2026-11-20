"""Verify the #1003 UTC session windows and the archive's unguarded range reset."""

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from probe_1216 import objects
from replay_2864 import engine_options, pine_compat, sha256

SOURCE = "f2715f774c0f3c96ed574b3d865b5a9d8078e392827d00d5ecd8375ccaac729e"
MINUTE = 60_000
DAY = MINUTE * 1440
OBS = '''
plot(Notradetime,title="Opening exclusion clock")
plot(Tradetime,title="Trading window clock")
plot(bartimeSess,title="Session daily clock")
plot(newbarSess ? 1 : 0,title="Opening reset")
plot(highRes,title="Opening range high")
plot(lowRes,title="Opening range low")
plot(Enterlong ? 1 : 0,title="Long entry")
plot(Entershort ? 1 : 0,title="Short entry")
plot(Select_short ? 1 : 0,title="Archived short enabled")
'''
LOWER_FIXTURE = '''//@version=2
study("Opening range session observations")
session_value = time('D','0930-1100')
plot(session_value,title="Session projection")
plot(session_value != session_value[1] ? 1 : 0,title="Unguarded reset")
plot(not na(session_value) and (na(session_value[1]) or session_value != session_value[1]) ? 1 : 0,title="Guarded reset")
'''


def programs():
    md = (ROOT / "source-1003.md").read_bytes()
    assert sha256(md) == SOURCE
    (block,) = re.findall(r"(?m)^``` pinescript\n(.*?)^```", md.decode(), re.DOTALL)
    assert 'args: [["v_input_10",true]]' in block
    raw, count = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", block)
    assert count == 1
    legacy = raw
    for old, new, expected in (
        ("syminfo.tickerid", "tickerid", 2),
        ("timeframe.period", "period", 2),
        ('color=black, style=shape.triangleup, text="Enter", location=location.belowbar,', "colorup=black,", 1),
        ("plotarrow(Enterlong,", "plotarrow(Enterlong ? 1 : 0,", 1),
        ("Select_short = input(false,", "Select_short = input(true,", 1),
    ):
        assert legacy.count(old) == expected
        legacy = legacy.replace(old, new)
    broken = "newbarSess = bartimeSess != bartimeSess[1]"
    assert legacy.count(broken) == 1
    control = legacy.replace(broken, "newbarSess = not na(bartimeSess) and (na(bartimeSess[1]) or bartimeSess != bartimeSess[1])")
    return raw, legacy, control


def utc_session(stamp):
    date = datetime.fromtimestamp(stamp / 1_000, UTC)
    current = date.hour * 60 + date.minute
    if date.weekday() < 5 and 570 <= current < 660:
        return stamp // DAY * DAY + 570 * MINUTE
    return None


def run():
    manifest = json.loads((ROOT / "1003-inputs.json").read_bytes())
    raw_source, original, comparison = programs()
    results = []
    for ref in manifest["feeds"]:
        raw = (ROOT / ref["file"]).read_bytes()
        assert sha256(raw) == ref["sha256"]
        frame = json.loads(raw)
        chart, lower = (objects(frame[k]) for k in ("chart", "reference"))
        opts = {**engine_options(ref["market"]), "chart_timeframe": "60"}
        opts["request_bars"][f"{opts['chart_symbol']}:30"] = lower
        try:
            pine_compat.run_script(raw_source, chart[:24], **opts)
        except ValueError as error:
            diagnostics = str(error).splitlines()
            assert any(d.startswith("E_LEGACY_VERSION_FEATURE") for d in diagnostics)
        else:
            raise AssertionError("The verbatim mixed-version strategy unexpectedly compiled.")
        native, alternate = [pine_compat.run_script(x + OBS, chart, **opts) for x in (original, comparison)]
        fixture = pine_compat.run_script(LOWER_FIXTURE, lower, **{**opts, "chart_timeframe": "30"})
        expected = [utc_session(b["time"]) for b in lower]
        opens = [int(now is not None and (i == 0 or expected[i - 1] != now)) for i, now in enumerate(expected)]
        values = [p["values"] for p in fixture["plots"]]
        assert values == [expected, [0] * len(lower), opens]
        all_bars = len(chart)
        marks = {p["title"]: p["values"] for p in native["plots"][-9:]}
        assert marks["Opening exclusion clock"] == [None] * all_bars
        assert marks["Trading window clock"] == [b["time"] if utc_session(b["time"]) else None for b in chart]
        assert marks["Session daily clock"] == [utc_session(b["time"]) for b in chart]
        for title in ("Opening range high", "Opening range low"):
            assert marks[title] == [None] * all_bars
        assert marks["Opening reset"] == marks["Long entry"] == marks["Short entry"] == [0] * all_bars
        assert marks["Archived short enabled"] == [1] * all_bars
        ledger = native["strategy"]
        assert not ledger["diagnostics"] and ledger["orders"] == ledger["trades"] == ledger["position"] == []
        assert len(ledger["equity"]) == all_bars
        for i, row in enumerate(ledger["equity"]):
            assert row == {"barIndex": i, "cash": 1_000_000, "marketValue": 0, "equity": 1_000_000, "netProfit": 0}
        changed = {p["title"]: p["values"] for p in alternate["plots"][-9:]}
        assert any(p is not None for p in changed["Opening range high"])
        results.append({**ref, "start": frame["start"], "end": frame["end"], "verified_zero_trades": True, "session_starts": sum(opens), "altered_na_guard_orders": len(alternate["strategy"]["orders"]), "original_compile_diagnostics": diagnostics, "legacy_runtime_notices": native["diagnostics"]})
    output = {"cases": results, "normalized_sha256": sha256(original.encode()), "guard_control_sha256": sha256(comparison.encode())}
    (ROOT / "1003-verified.json").write_text(json.dumps(output, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "1003-replay-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
