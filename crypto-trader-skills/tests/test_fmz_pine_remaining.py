"""Test narrow FMZ Pine replay adaptations."""

import unittest

try:
    from research.delta_pinets_migration import MigrationBlocked
    from research.fmz_pine_remaining import (
        chart_broker_declaration,
        order_block_indent,
        specialize_inputs,
        switch_commas,
    )
except ModuleNotFoundError as exc:
    if exc.name not in {"numpy", "talib"}:
        raise
    raise unittest.SkipTest("Optional research dependencies are required") from exc


class PineRemainingTests(unittest.TestCase):
    def test_chart_declaration_preserves_active_orders(self):
        body = 'signal = ta.crossover(close, open)\nif signal\n    strategy.entry("Long", strategy.long)\n'
        original = (
            '//@version=5\nindicator("Archived", overlay = true, timeframe = "", timeframe_gaps = false)\n'
            + body
        )
        fixed, count = chart_broker_declaration(original)
        self.assertEqual(
            fixed, '//@version=5\nstrategy("Archived", overlay = true)\n' + body
        )
        self.assertEqual(count, 1)
        with self.assertRaises(MigrationBlocked):
            chart_broker_declaration(
                original.replace('timeframe = ""', 'timeframe = "5"')
            )
        with self.assertRaises(MigrationBlocked):
            chart_broker_declaration(
                original.replace("strategy.entry", "//strategy.entry")
            )

    def test_specialize_verified_legacy_generic_input_arguments(self):
        code = 'kind = input("EMA", options = ["EMA", "SMA"])\na = input(title = "P", defval = 2.0, type = input.float, step = 0.1)\n'
        fixed, count = specialize_inputs(code)
        self.assertEqual(
            fixed.replace("  step", " step"),
            'kind = input.string("EMA", options = ["EMA", "SMA"])\na = input.float(title = "P", defval = 2.0, step = 0.1)\n',
        )
        self.assertEqual(count, 2)
        self.assertEqual(
            specialize_inputs('a = input("EMA", "Label", "tooltip")')[1], 0
        )

    def test_switch_branch_separator_preserves_call_arguments(self):
        code = 'x = switch syminfo.ticker\n    "BTCUSD" => math.max(a, b),\n    "ETHUSD" => a,\n    => b\ny = 5\n'
        fixed, count = switch_commas(code)
        self.assertEqual(fixed, code.replace("b),", "b)").replace("=> a,", "=> a"))
        self.assertEqual(count, 2)

    def test_single_guard_order_block_gets_exact_block_indentation(self):
        wrong = 'if enterLong\n   strategy.entry("L", strategy.long)\nelse\n    strategy.close("L")\n'
        self.assertEqual(
            order_block_indent(wrong),
            (wrong.replace("\n   strategy.entry", "\n    strategy.entry"), 1),
        )
        mixed_scope = 'if enterLong\n   strategy.entry("L", strategy.long)\n    riskyExit = true\n'
        self.assertEqual(order_block_indent(mixed_scope), (mixed_scope, 0))
