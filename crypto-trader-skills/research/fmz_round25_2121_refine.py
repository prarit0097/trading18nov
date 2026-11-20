"""Reconcile the bracket ledger after resolving ambiguous hours with verified minutes."""

import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from replay_2121 import OBS, cases, objects, pine_compat, program, sha256
from verify_2121 import decisions, reconcile


def run():
    receipt = ROOT / "2121-verified.json"
    prior = json.loads(receipt.read_bytes())
    file = ROOT / "2121-minute-inputs.json"
    resolutions = json.loads(file.read_bytes())["cases"]
    source = program()[-1] + OBS
    reports = []
    fallback_check = None
    for coarse, (ref, chart, references, groups, opts) in zip(prior["results"], cases(), strict=True):
        market = ref["market"]
        detailed = {r["time"]: r for r in resolutions if r["market"] == market}
        assert set(detailed) == {lot["effective_base_exit"] for lot in coarse["ambiguities"]}
        augmented = [
            {**g, "bars": [minute for hour in g["bars"] for minute in (objects(detailed[hour["time"]]["minutes"]) if hour["time"] in detailed else [hour])]}
            for g in groups
        ]
        observed = pine_compat.run_script(source, chart, **opts, magnifier_bars={"schemaVersion": 1, "chartBars": augmented})
        if fallback_check is None:
            control = pine_compat.run_script(source, chart, **opts, magnifier_bars={"schemaVersion": 1, "chartBars": augmented[:-1]})
            fallback_check = [d["code"] for d in control["diagnostics"]]
            assert fallback_check == ["W_MAGNIFIER_FALLBACK"]
        signals = decisions(chart, references, observed)
        tick = Decimal("0.1" if market == "BTCUSDT" else "0.01")
        exact = reconcile(observed, chart, [g["bars"] for g in augmented], signals, tick)
        assert all(not lot["both_price_levels_hit"] for lot in exact["ledger"])
        checked = []
        for a, b in zip(coarse["hourly"]["ledger"], exact["ledger"], strict=True):
            assert (a["id"], a["entryTime"], a["exitTime"]) == (b["id"], b["entryTime"], b["exitTime"])
            if a["effective_base_exit"] in detailed:
                minute = b["effective_base_exit"]
                assert any(x[0] == minute for x in detailed[a["effective_base_exit"]]["minutes"])
                checked.append({"hour": a["effective_base_exit"], "minute": minute, "before_price": a["exitPrice"], "after_price": b["exitPrice"], "before_reason": a["reason"], "after_reason": b["reason"]})
            else:
                assert a == b
        assert len(checked) == len(detailed)
        reports.append({**ref, "signals": coarse["signals"], "hourly_model": coarse["hourly"]["order_counts"], "minute_resolutions": checked, **exact})
    output = {"reports": reports, "prior_verified_sha256": sha256(receipt.read_bytes()), "verified_minutes_sha256": sha256(file.read_bytes()), "missing_group_control": fallback_check}
    (ROOT / "2121-refined.json").write_text(json.dumps(output, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "2121-refine-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
