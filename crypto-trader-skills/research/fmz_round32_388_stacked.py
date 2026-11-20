"""Check relative exit bases when two open fills share the same entry ID."""

import json
import sys
from pathlib import Path

ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from replay_2864 import engine_options,pine_compat

BARS=[
    (100,101,99,100),
    (100,101,99,100),
    (200,201,199,200),
    (105,115,101,113),
    (108,211,104,200),
]
scripts={
 "shared": """
if bar_index == 0 or bar_index == 1
    strategy.entry("L", strategy.long, qty=1)
if bar_index == 2
    strategy.exit("X", "L", profit=10, loss=300)
""",
 "distinct": """
if bar_index == 0
    strategy.entry("L1", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("L2", strategy.long, qty=1)
if bar_index == 2
    strategy.exit("X1", "L1", profit=10, loss=300)
    strategy.exit("X2", "L2", profit=10, loss=300)
""",
 "shared_reissue": """
if bar_index == 0 or bar_index == 1
    strategy.entry("L", strategy.long, qty=1)
strategy.exit("X", "L", profit=10, loss=300)
""",
}
def main():
    out={}
    for variant,body in scripts.items():
        src='//@version=4\nstrategy("388 stacked target fixture",pyramiding=100)\n'+body
        bars=[dict(time=1704067200000+i*3600000,open=o,high=h,low=l,close=c,volume=1)
              for i,(o,h,l,c) in enumerate(BARS)]
        opts={**engine_options("BTCUSDT"),"chart_timeframe":"60"}
        opts["request_bars"]["$chart"].update(priceScale=1, minMove=1,pointValue=.001,quantityStep="1",minContract="1")
        r=pine_compat.run_script(src,bars,**opts)
        out[variant]={"source":src,"broker":r["strategy"],"bars":bars}
    (ROOT/"388-stacked-fixture.json").write_bytes(json.dumps(out,separators=(",",":")).encode())
if __name__=="__main__":
    main()
