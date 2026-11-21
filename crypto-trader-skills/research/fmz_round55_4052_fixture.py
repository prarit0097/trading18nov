"""Detect the impossible final fractional lot in the pinned broker."""
from pathlib import Path
import json, sys
root = Path(__file__).parent
sys.path.insert(0, str(root))
from replay_2864 import engine_options, pine_compat
from probe_1216 import objects
source = '//@version=5\nstrategy("quantity residual", initial_capital=50000)\nif bar_index==0\n    strategy.order("L0",strategy.long,qty=3.374*SIZE)\n    strategy.order("L1",strategy.long,qty=4.626*SIZE)\nif bar_index==1 and strategy.position_size>0\n    strategy.exit("leave",limit=110,qty=strategy.position_size)\nif bar_index==3 and strategy.opentrades==0\n    strategy.order("renew",strategy.long,qty=1*SIZE)\nplot(strategy.opentrades,"positions")\nplot(strategy.position_size,"hold")\n'
first = 1700000000000
tape = [(first + 3600000 * i, x, x + 1, x - 1, x, 1) for i, x in enumerate((100, 100, 110, 109, 107, 105))]
report = {}
for factor in (1, 1000):
    opt = engine_options('ETHUSDT')
    opt['chart_timeframe'] = '60'
    if factor == 1000:
        opt['request_bars']['$chart'].update(pointValue=0.001, quantityStep='1', minContract='1')
    d = pine_compat.run_script(source.replace('SIZE', str(factor)), objects(tape), **opt)
    report[str(factor)] = {'diag': d['diagnostics'], 'orders': d['strategy']['orders'], 'plots': {q['title']: q['values'] for q in d['plots']}}
(root / '4052-lot-fixture.json').write_bytes(json.dumps(report, separators=(',', ':')).encode())
