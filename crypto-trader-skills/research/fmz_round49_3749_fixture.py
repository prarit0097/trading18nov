"""Test unrelated outstanding exits across a direct position reversal."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from replay_2864 import engine_options,pine_compat
from probe_1216 import objects

SRC="""//@version=4
strategy("Reversal and limits",initial_capital=1000)
if bar_index == 0
    strategy.entry("Long",strategy.long,qty=1)
if bar_index == 2
    strategy.entry("Short",strategy.short,qty=1)
if strategy.position_size > 0
    strategy.exit("LP",qty_percent=100,limit=120)
if strategy.position_size < 0
    strategy.exit("SP",qty_percent=100,limit=95)
plot(strategy.position_size,title="Position")
"""
charts={
  "ordinary_reversal":[(100,101,99,100),(100,101,99,100),(100,101,99,100),
                        (100,101,99,100),(99,102,93,94),(94,96,92,95),(95,98,93,97)],
  "separate_entry_after_close_all":[(100,101,99,100)]*7,
  "separate_entry_after_close":[(100,101,99,100)]*7,
  "marketable_old_limit_at_reversal":[(100,101,99,100),(100,101,99,100),(100,101,99,100),
                        (104,105,101,102),(102,103,94,99),(99,101,97,100),(100,101,96,97)]
}
outputs={}
for case,ohlc in charts.items():
    tape=objects([[1704067200000+i*60000,*row,1] for i,row in enumerate(ohlc)])
    script=SRC if case!="marketable_old_limit_at_reversal" else SRC.replace("limit=120","limit=103")
    if case.startswith("separate_entry"):
        close='strategy.close_all()' if case.endswith("_all") else 'strategy.close("Long",qty_percent=100)'
        script=script.replace("if bar_index == 2", "if bar_index == 1\n    "+close+"\nif bar_index == 4")
    opts=engine_options("BTCUSDT")
    variants={}
    for kind,source in (("unbound",script),("named",script.replace('"LP",','"LP",from_entry="Long",').replace(
                                                  '"SP",','"SP",from_entry="Short",'))):
        r=pine_compat.run_script(source,tape,**opts)
        b=r["strategy"]
        variants[kind]={"orders":b["orders"],"trades":b["trades"],"diagnostics":b["diagnostics"]}
    outputs[case]=variants
(ROOT/"3749-lifecycle.json").write_bytes(json.dumps(outputs,separators=(",",":")).encode())
