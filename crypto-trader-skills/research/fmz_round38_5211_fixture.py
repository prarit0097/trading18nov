"""Targeted controls for automatic reservation of a named trail and TP1."""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from replay_2864 import engine_options, pine_compat
from probe_1216 import objects

PREFIX = """//@version=4
strategy("5211 reservation control",initial_capital=10000,pyramiding=0)
if bar_index == 0
    strategy.entry("long",strategy.long,qty=5)
"""
DATA = ((100,101,99,100), (100,101,99,100), (100,108,99,102),
        (120,125,119,120), (120,122,118,120), (120,121,119,120))
TARGET = '    strategy.exit("TP1","long",qty_percent=20,limit=strategy.position_avg_price*1.05)\n'
TRAIL = '    strategy.exit("Trail stop","long",trail_points=20,trail_offset=5)\n'
BARS = objects([[1704067200000 + n * 86400000, *bar, 1] for n,bar in enumerate(DATA)])
CONFIGS = {
    "tp1_only": PREFIX + "if strategy.position_size > 0\n" + TARGET,
    "tp1_then_trail": PREFIX + "if strategy.position_size > 0\n" + TARGET + TRAIL,
    "trail_then_tp1": PREFIX + "if strategy.position_size > 0\n" + TRAIL + TARGET,
    "deferred_trail_then_update": PREFIX + "if bar_index == 0 or strategy.position_size > 0\n" + TARGET + TRAIL,
    "same_timing_quantity_explicit": PREFIX + "if bar_index == 0 or strategy.position_size > 0\n" + TARGET +
         TRAIL.replace("trail_points", "qty_percent=80,trail_points"),
}
def main():
    options = {**engine_options("BTCUSDT"), "chart_timeframe":"D"}
    options["request_bars"]["$chart"].update(priceScale=1,minMove=1,quantityStep="1",minContract="1")
    cases = []
    for name,script in CONFIGS.items():
        result = pine_compat.run_script(script, BARS, **options)
        strategy = result["strategy"]
        cases.append({"case":name, "source":script, "orders":strategy["orders"],
                      "trades":strategy["trades"], "diagnostics":strategy["diagnostics"]})
    (ROOT/"5211-reservation.json").write_bytes(json.dumps({"bars":BARS,"cases":cases},separators=(",",":")).encode())

if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        (ROOT/"5211-reservation-error.txt").write_text(traceback.format_exc(),encoding="utf-8")
        raise
