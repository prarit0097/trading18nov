import json
import sys
from pathlib import Path

ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from replay_2864 import engine_options,pine_compat

def run():
    alternate=json.loads((ROOT/"388-sibling-causality.json").read_bytes())
    reports=[]
    for sample in alternate["cases"]:
        opts={**engine_options("BTCUSDT"),"chart_timeframe":"60"}
        opts["request_bars"]["$chart"].update(priceScale=10,minMove=1,pointValue=.001,minContract="1",quantityStep="1")
        result=pine_compat.run_script(alternate["script"],sample["bars"],**opts)
        reports.append(result["strategy"]["trades"])
    assert reports[0]==reports[1]
    (ROOT/"388-sibling-native.json").write_bytes(json.dumps(reports,separators=(",",":")).encode())

if __name__=="__main__":
    run()
