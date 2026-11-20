import unittest

from research.fmz_round3_compile import prepare_source
from research.fmz_round3_compile_feeds import prepare_source as prepare_feed_source


STRATEGY = '//@version=4\nstrategy("Fixture")\n'


class Round3PineTests(unittest.TestCase):
    def test_multiline_named_arguments_are_not_bindings(self):
        code = STRATEGY + """plotshape(close > open,
   color=color.red,
   text="entry")
if close > open
    strategy.entry("L", strategy.long)
"""
        migrated, _, _, _ = prepare_source(code, isolated_literals=True)
        self.assertIn('color=color.red', migrated)
        self.assertIn('text="entry"', migrated)

    def test_explicit_prior_bar_assignments_are_preserved_in_order(self):
        code = STRATEGY + """position = 0, position := nz(position[1]) + 1
if position == 2
    strategy.entry("L", strategy.long)
"""
        migrated, _, _, _ = prepare_source(code, isolated_literals=True)
        self.assertIn('position = 0\nposition := nz(position[1]) + 1', migrated)

    def test_legacy_offset_variable_preserves_keyword(self):
        code = STRATEGY + """offset = input(1)
plot(close, offset=offset)
if close > close[offset]
    strategy.entry("L", strategy.long)
"""
        migrated, _, _, _ = prepare_source(code, isolated_literals=True)
        self.assertIn('offset=fmz_global_offset', migrated)
        self.assertIn('close[fmz_global_offset]', migrated)

    def test_custom_builtin_named_function_keeps_original_body(self):
        code = STRATEGY + '''hma(source, length) => sma(source, length) + 7
signal = hma(close, 4)
standard = ta.hma(close, 4)
if signal > standard
    strategy.entry("L", strategy.long)
'''
        migrated, _, _, _ = prepare_source(code, isolated_literals=True)
        self.assertIn('fmz_function_hma(source, length) => ta.sma(source, length) + 7', migrated)
        self.assertIn('signal = fmz_function_hma(close, 4)', migrated)
        self.assertIn('standard = ta.hma(close, 4)', migrated)

    def test_outside_bounds_defaults_are_an_explicit_named_variant(self):
        code = STRATEGY + '''threshold = input(-4.5, minval=1, maxval=5, step=0.5)
normal = input(2, minval=1, maxval=5)
enabled = input(1, type=input.bool)
if enabled and close - open > threshold + normal
    strategy.entry("L", strategy.long)
'''
        migrated, _, _, repairs = prepare_source(code, isolated_literals=True)
        self.assertIn('threshold = input.float(-4.5, maxval = 5, step = 0.5)', migrated)
        self.assertIn('normal = input.int(2, minval=1, maxval=5)', migrated)
        self.assertIn('enabled = input.bool(true)', migrated)
        self.assertEqual(repairs['Archived literal default outside declared bounds'], 1)

    def test_legacy_feed_source_preserves_integer_options_and_chart_period(self):
        code = '''//@version=3
strategy("Fixture")
length = input(4, minval=0.25, step=0.1)
feed = security(tickerid, period, close)
if close > sma(feed, length)
    strategy.entry("L", strategy.long)
'''
        migrated, _, _ = prepare_feed_source(code)
        self.assertIn('input.int(4, minval = 1)', migrated)
        self.assertIn('request.security(syminfo.tickerid, timeframe.period, close)', migrated)
