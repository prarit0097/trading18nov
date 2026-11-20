"""Check that verified FMZ base-period candles leave #3604 market fills invariant."""

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from probe_3604 import (
    HOUR,
    INPUTS,
    load_feed,
    options_for,
    pine_compat,
    programs,
    sha256,
)

LOWER_HASHES = {
    "native-base-BTCUSDT-2026-08-01.json": "0a1b82a28d91d51ad96e27c77c2ad3e9421240276ac7871c1d2988d046e668f7",
    "native-base-BTCUSDT-2026-09-01.json": "97afd57aaae09b9b31fd3fcb7b670adf649d385b6f42d319c1fdecb9c980d312",
    "native-base-ETHUSDT-2026-08-01.json": "43bdb7addf7bed40f4f79fdb432e56b6f5dd0fe912dc6dd666db8780e0b05132",
    "native-base-ETHUSDT-2026-09-01.json": "a50b88ede23bf56a01fa33832642998328a837712f5eaa1e9bb63230bd28d46c",
}


def run():
    _, script, _, _ = programs()
    baseline = pine_compat.compile_script(script)
    marker = "initial_capital = 50000)"
    assert script.count(marker) == 1
    try:
        pine_compat.compile_script(
            script.replace(marker, "initial_capital = 50000, use_bar_magnifier = true)")
        )
    except ValueError as error:
        version_error = str(error)
        assert version_error.startswith("E_LEGACY_VERSION_FEATURE:Error:")
        assert "`use_bar_magnifier` requires Pine v5 or later" in version_error
    else:
        raise AssertionError(
            "Expected a version guard for Bar Magnifier in the v4 source."
        )
    receipts = []
    names = ("time", "open", "high", "low", "close", "volume")
    for name, checksum in INPUTS.items():
        market, start, stop, chart = load_feed(name, checksum)
        first = name.removeprefix(f"feed-{market}-60-10-")
        lower_name = f"native-base-{market}-{first}"
        lower_raw = (ROOT / lower_name).read_bytes()
        digest = sha256(lower_raw)
        assert digest == LOWER_HASHES[lower_name]
        lower = [dict(zip(names, row, strict=True)) for row in json.loads(lower_raw)]
        assert [row["time"] for row in lower] == list(range(start, stop, HOUR // 4))
        groups = [
            {"chartBarIndex": i, "bars": lower[i * 4 : (i + 1) * 4]}
            for i in range(len(chart))
        ]
        assert len(lower) == 4 * len(chart)
        for parent, child in zip(chart, groups, strict=True):
            bars = child["bars"]
            assert (
                bars[0]["open"] == parent["open"]
                and bars[-1]["close"] == parent["close"]
            )
            assert min(row["low"] for row in bars) == parent["low"]
            assert max(row["high"] for row in bars) == parent["high"]
            assert math.isclose(
                math.fsum(row["volume"] for row in bars), parent["volume"], rel_tol=1e-9
            )
        opts = options_for(market)
        reference = baseline.run(chart, **opts)
        assert not reference["diagnostics"] and not reference["strategy"]["diagnostics"]
        orders = reference["strategy"]["orders"]
        for order in orders:
            base_bar = groups[order["barIndex"]]["bars"][0]
            assert order["time"] == base_bar["time"]
            assert math.isclose(order["price"], base_bar["open"], abs_tol=1e-8)
        receipts.append(
            {
                "name": lower_name,
                "sha256": digest,
                "bars": len(lower),
                "verified_execution_prices": len(orders),
            }
        )
    output = {
        "lower_timeframe": "15",
        "explicit_magnifier_v4_guard": version_error,
        "receipts": receipts,
    }
    (ROOT / "3604-base-control.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf8"
    )


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "3604-base-error.txt").write_text(
            traceback.format_exc(), encoding="utf8"
        )
        raise
