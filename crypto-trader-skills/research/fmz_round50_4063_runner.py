"""Isolated saved and confirmed-option replay of the pinned Pine v4 source."""
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from replay_2864 import engine_options, pine_compat, sha256
from probe_1216 import objects


def main():
    archive = (ROOT/'source-4063.md').read_bytes()
    assert sha256(archive) == '6957b333b9e4b5829b0c38f19b8c052e5a9b2e0c34e0b4ed9b637491eddcff71'
    fence = chr(96)*3
    (source,) = re.findall(r'(?ms)^'+fence+r' pinescript[^\n]*\n(.*?)^'+fence, archive.decode())
    source, removed = re.subn(r'(?ms)^/\*backtest\n.*?^\*/\n*', '', source)
    assert removed == source.count('lookahead = input(true)') == 1
    selected = source.replace('lookahead = input(true)', 'lookahead = input(false)')
    observe = ('\nplot(nhighlast,"prior high")\nplot(nlowlast,"prior low")\n'
               'plot(buyCondition?1:0,"buy")\nplot(sellCondition?1:0,"sell")\n')
    report = {}
    feed = json.loads((ROOT/'4063-feed.json').read_bytes())
    for market, data in feed['markets'].items():
        report[market] = {}
        options = engine_options(market)
        options['chart_timeframe'] = '1D'
        options['request_bars'][options['chart_symbol']+':3M'] = objects(data['quarter'])
        for key, body in (('as_saved', source), ('confirmed_input', selected)):
            result = pine_compat.run_script(body+observe, objects(data['chart']), **options)
            report[market][key] = {'diagnostics': result['diagnostics'],
                                   'plots': {p['title']: p['values'] for p in result['plots']},
                                   'broker': result['strategy']}
    (ROOT/'4063-native.json').write_bytes(json.dumps(report, separators=(',', ':'), allow_nan=False).encode())


if __name__ == '__main__':
    main()
