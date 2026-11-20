"""Audit exact-terminal #1073 with the independent #2994 decision and cash model."""

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from replay_1073 import cases, sha256, scripts
from replay_2864 import near
from verify_2994 import FEE, ORDER_CASH, orders, size, source_logic

OBSERVE = ("Observed long", "Observed short", "Observed short-side close", "Observed long-side close")


def run():
    raw_path = ROOT / "1073-replay.json"
    piner_path = ROOT / "1073-piner.json"
    raw, alternate = (json.loads(path.read_bytes()) for path in (raw_path, piner_path))
    legacy, active = scripts()
    assert len(legacy) - len(active) == 2
    controls = alternate["fixture"]["closedTrades"]
    assert [x["qty"] for x in controls] == [size(190.3), size(277.6)] == [52.548, 36.023]
    for lot in controls:
        near(lot["commission"], FEE * lot["qty"] * (lot["entryPrice"] + lot["exitPrice"]))
    results = []
    for case, compare, (ref, data, chart, base, _) in zip(raw, alternate["sample"], cases(), strict=True):
        assert case["file"] == ref["file"] and compare["market"] == ref["market"]
        assert compare["dataSha256"] == ref["sha256"]
        observed = case["observed"]
        assert not observed["strategy"]["diagnostics"]
        assert {d["code"] for d in observed["diagnostics"]} == {"W_LEGACY_SECURITY_LOOKAHEAD"}
        native_plots = {p["title"]: p["values"] for p in observed["plots"] if (p.get("title") or "").startswith("Observed")}
        wt1, wt2, decisions = source_logic(chart)
        for expected, name in ((wt1, "Observed WT1"), (wt2, "Observed WT2")):
            for a, b in zip(expected, native_plots[name], strict=True):
                near(a, b)
        assert decisions == list(zip(*(native_plots[name] for name in OBSERVE), strict=True))
        lots, open_, events, equity = orders(chart, decisions)
        receipt = compare["result"]
        assert receipt["initialCapital"] == ORDER_CASH and receipt["barsProcessed"] == len(chart)
        for expected, native in zip(lots, receipt["closedTrades"], strict=True):
            for k, a in expected.items():
                if isinstance(a, float):
                    near(a, native[k])
                else:
                    assert a == native[k]
        for actual, expected in zip(receipt["equityCurve"], equity, strict=True):
            near(actual["equity"] if isinstance(actual, dict) else actual, expected)
        zero = ref["zero_print_quarters"]
        for order in events:
            hour = base[order["bar"] * 8]
            assert hour["volume"] > 0 and hour["time"] not in zero and order["price"] == hour["open"]
            assert chart[order["bar"]]["time"] == hour["time"] < data["end"]
        assert chart[-1]["close"] == data["terminal_clipped_quarter"][4]
        assert data["excluded_minute"][0] == data["end"]
        stock = [o for o in observed["strategy"]["orders"] if o["direction"] != "strategy.close"]
        corrected = [o for o in events if o["kind"] == "entry"]
        for a, b in zip(stock, corrected, strict=True):
            i = b["bar"]
            assert (a["id"], a["barIndex"], a["price"]) == (b["id"], i, b["price"])
            near(a["qty"], size(chart[i - 1]["close"]))
        results.append({
            **ref, "start": data["start"], "end": data["end"],
            "terminal_ohlcv": data["terminal_clipped_quarter"],
            "excluded_minute": data["excluded_minute"],
            "zero_prints_at_execution_open": 0,
            "flag_counts": {name: sum(native_plots[name]) for name in OBSERVE},
            "native_unsupported_cash_quantities": sum(a["qty"] != b["qty"] for a, b in zip(stock, corrected, strict=True)),
            "marker": equity[-1], "open": open_, "closed": lots,
            "order_events": dict(Counter(o["kind"] for o in events)),
            "piner_strategy_adapter_sha256": compare["sourceSha256"],
        })
    out = {
        "cases": results, "native_sha256": sha256(raw_path.read_bytes()),
        "piner_sha256": sha256(piner_path.read_bytes()), "piner_engine_sha256": alternate["engine"],
        "restored_body_sha256": sha256(active.encode()), "literal_archived_body_sha256": sha256(legacy.encode()),
        "cash_fixture": controls,
    }
    (ROOT / "1073-verified.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "1073-verify-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
