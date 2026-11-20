"""Audit the v4 open versus prior high equality case on actual archived bars."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from replay_2864 import engine_options,pine_compat
from probe_1216 import objects

base="""//@version=4
strategy("Open and prior high control")
literal = false
if open >= high[1]
    literal := true
disjoined = false
if open > high[1] or open == high[1]
    disjoined := true
plot(literal ? 1 : 0, "literal")
plot(disjoined ? 1 : 0, "disjunction")
plot(open >= high[1] ? 1 : 0, "direct")
plot(open == high[1] ? 1 : 0, "equality")
plot(open-high[1], "difference")
"""
packet=json.loads((ROOT/"3458-feed.json").read_bytes())
result={}
for market, sample in packet["markets"].items():
    controls=[]
    for i in (98,123,129,240):
        observations=objects(sample["chart"][i-1:i+2])
        out=pine_compat.run_script(base,observations,**engine_options(market))
        controls.append({"source_index":i,"candles":observations,
                         "plots":{v["title"]:v["values"] for v in out["plots"]}})
    result[market]=controls
(ROOT/"3458-equality-fixtures.json").write_bytes(json.dumps(result,separators=(",",":")).encode())
