import json

import pytest

from research.delta_strategy_replay import FEE, stamp
from research.fmz_native_round6_audit import digest, evidence
from research.fmz_native_round6_replay import opening_metrics


def test_pine_display_only_requires_compile_order_absence():
    row = evidence(
        "pinescript", 'indicator("demo")\nplot(close)\n// strategy.entry("fake")\n'
    )
    assert row["declarations"] == ["indicator"]
    assert row["actions"] == {}


def test_javascript_capture_uses_code_and_keeps_dynamic_order_ambiguity():
    row = evidence(
        "javascript",
        "function main() { exchange[method](1); }\n// exchange.Buy(1, 1)\n",
    )
    assert row["entrypoint"]
    assert row["dynamic_dispatch"]
    assert row["actions"] == {}


def test_python_action_is_qualified_and_bindings_are_line_numbered():
    row = evidence(
        "python",
        "def main():\n    label = 'exchange.Buy(1)'\n    exchange.Buy(-1, 1)\n",
    )
    assert row["entrypoint"]
    assert row["actions"] == {"Buy": [3]}


def test_seeded_inventory_has_no_simulated_entry_fee(tmp_path):
    first, last = "2026-09-23", "2026-10-21"
    begin, end = stamp(first) * 1000, stamp(last) * 1000
    raw = json.dumps({"data": [[begin, 50, 60, 50, 60, 1]]}).encode()
    (tmp_path / "candles.json").write_bytes(raw)
    feed = {
        "file": "candles.json",
        "sha256": digest(raw),
        "start": first,
        "end": last,
        "symbol": "BTC_USDT",
        "base_seconds": 300,
    }
    opening = {"timestamp": begin - 300000, "price": 50, "base": 1, "cash": 50}
    receipt = {
        "last": {"Time": end - 10000},
        "orders": [
            {
                "Id": 1,
                "Time": begin,
                "DealAmount": 1,
                "AvgPrice": 60,
                "Symbol": "BTC_USDT",
                "Type": 1,
                "Price": 60,
            }
        ],
        "account": {
            "Balance": 50 + 60 * (1 - FEE),
            "Stocks": 0,
            "FrozenBalance": 0,
            "FrozenStocks": 0,
        },
    }
    [(time, gross, after_fee, net)], open_lots, checks = opening_metrics(
        receipt, tmp_path, feed, opening
    )
    assert (time, gross, open_lots) == (begin, 10, 0)
    assert after_fee == pytest.approx(10 - 60 * FEE)
    assert net < after_fee
    assert checks == {"cash_error": 0, "asset_error": 0}
