"""Verify archived integer arithmetic and retain an altered-coefficient control."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from probe_1216 import objects
from replay_2864 import engine_options, pine_compat, sha256

SOURCE = "9b2d58f0863e272c09f52db1026c0768aa26bce0ab307dbe055231434781bf1b"
NAMES = ("nfastend", "nslowend", "nfastend2", "nslowend2", "nAMA", "nAMA2", "out", "out2")
OBS = "\n" + "\n".join(f'plot({v},title="{v}")' for v in NAMES)
OBS += '\nplot(buyEntry ? 1 : 0,title="buy")\nplot(sellEntry ? 1 : 0,title="sell")\n'


def program():
    raw = (ROOT / "source-3805.md").read_bytes()
    assert sha256(raw) == SOURCE
    (source,) = re.findall(r"(?m)^``` pinescript\n(.*?)^```", raw.decode(), re.DOTALL)
    old, n = re.subn(r"(?ms)^/\*backtest\n.*?^\*/\n*", "", source)
    assert n == 1
    assert old.count('tf = input(title="Resolution",  defval = "current")') == 1
    prefix = 'request.security(syminfo.tickerid,tf == "current" ? timeframe.period : tf, '
    restored = old
    for key in ("fractalup", "fractaldown"):
        look = f"{prefix}{key})"
        assert restored.count(look) == 1
        restored = restored.replace(look, key)
    arithmetic_sensitivity, amount = re.subn(r"(?<![\w.])2/\(", "2.0/(", restored)
    assert amount == 12
    return old, restored, arithmetic_sensitivity


def run():
    archive = json.loads((ROOT / "3805-inputs.json").read_bytes())
    invalid, baseline, variant = program()
    results = []
    for ref in archive["feeds"]:
        payload = (ROOT / ref["file"]).read_bytes()
        assert sha256(payload) == ref["sha256"]
        data = json.loads(payload)
        chart = objects(data["chart"])
        opts = {**engine_options(ref["market"]), "chart_timeframe": "D"}
        try:
            pine_compat.run_script(invalid, chart, **opts)
        except ValueError as error:
            reasons = str(error).splitlines()
            assert sum(x.startswith("E_LEGACY_VERSION_FEATURE") for x in reasons) == 2
        else:
            raise AssertionError("Invalid archived v2 request spelling compiled.")
        native, changed = [pine_compat.run_script(script + OBS, chart, **opts) for script in (baseline, variant)]
        assert all(not r["diagnostics"] and not r["strategy"]["diagnostics"] for r in (native, changed))
        original = {p["title"]: p["values"] for p in native["plots"][-10:]}
        sensitivity = {p["title"]: p["values"] for p in changed["plots"][-10:]}
        n = len(chart)
        assert n == ref["chart_bars"] and len(data["hourly"]) == 24 * n
        assert [2 // (integer + 1) for integer in (2, 30, 4, 24)] == [0, 0, 0, 0]
        for name in (*NAMES[:6], "buy", "sell"):
            assert original[name] == [0] * n
        ledger = native["strategy"]
        assert ledger["orders"] == ledger["position"] == ledger["trades"] == []
        assert len(ledger["equity"]) == n
        for i, equity in enumerate(ledger["equity"]):
            assert equity == {"barIndex": i, "cash": 1_000_000, "marketValue": 0, "equity": 1_000_000, "netProfit": 0}
        assert any(sensitivity["buy"]) and any(sensitivity["sell"])
        results.append({
            **ref, "start": data["start"], "end": data["end"], "capital": 1_000_000,
            "zero_signals_and_orders": True, "equity_rows_verified": n,
            "first_fractional_coefficients": {name: sensitivity[name][0] for name in NAMES[:4]},
            "altered_coefficients_diagnostic_orders": len(changed["strategy"]["orders"]),
            "altered_buy_signals": sum(sensitivity["buy"]), "altered_sell_signals": sum(sensitivity["sell"]),
            "invalid_source_diagnostics": reasons,
        })
    out = {"cases": results, "baseline_script_sha256": sha256(baseline.encode()), "noncanonical_control_sha256": sha256(variant.encode())}
    (ROOT / "3805-verified.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "3805-replay-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
