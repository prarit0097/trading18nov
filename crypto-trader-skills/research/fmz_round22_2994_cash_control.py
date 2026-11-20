"""Measure pinned cash-sizing, configured fee and market close ordering."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from replay_2864 import engine_options, pine_compat


def run():
    header = 'strategy("Cash default", initial_capital=10000, commission_value=0.025, default_qty_type=strategy.cash, default_qty_value=10000)'
    body = '''
if bar_index == 0
    strategy.entry("long", strategy.long)
if bar_index == 1
    strategy.close("long")
    strategy.entry("short", strategy.short)
if bar_index == 2
    strategy.close("short")
'''
    first = 1_702_944_000_000
    bars = [{"time": first + i * 86_400_000, "open": price, "high": max(price, close), "low": min(price, close), "close": close, "volume": 1} for i, (price, close) in enumerate(((100, 100), (190.3, 191.1), (277.6, 270.8), (208.1, 210.3)))]
    opts = {**engine_options("BTCUSDT"), "chart_timeframe": "D"}
    results = {}
    for version in (4, 5):
        src = f"//@version={version}\n" + header + body
        result = pine_compat.run_script(src, bars, **opts)
        results[str(version)] = {"diagnostics": result["diagnostics"], "strategy": result["strategy"]}
    (ROOT / "2994-cash-sizing.json").write_text(json.dumps(results, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback

        (ROOT / "2994-cash-sizing-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
