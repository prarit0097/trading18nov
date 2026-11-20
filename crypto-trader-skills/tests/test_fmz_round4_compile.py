import unittest

from research.fmz_round4_compile import prepare_source
from research.fmz_round4_compile_targeted import amend


class RoundFourPineCompileTest(unittest.TestCase):
    def test_function_parameter_and_local_do_not_shadow_v5_names(self):
        code, _, _, _ = prepare_source("""//@version=4
strategy("fixture")
weight(input) =>
    return = input + 1
    return
value = weight(close)
plot(value, color=color.red)
if value > close
    strategy.entry("L", strategy.long)
""")
        self.assertIn("weight(fmz_local_input)", code)
        self.assertIn("fmz_local_return = fmz_local_input + 1", code)
        self.assertIn("color=color.red", code)

    def test_fixed_input_retains_literal_and_rejects_ambiguous_duplicate(self):
        source = """//@version=4
strategy("fixture")
length = input(05, title="Length", defval=5, minval=1, maxval=10)
if close > sma(close, length)
    strategy.entry("L", strategy.long)
"""
        code, _, _, _ = prepare_source(source)
        self.assertIn("input.int(5, title =", code)
        with self.assertRaisesRegex(ValueError, "conflicting defaults"):
            prepare_source(source.replace("defval=5", "defval=6"))

    def test_typed_v2_history_uses_previous_state_and_original_update_order(self):
        code, version, _, _ = prepare_source(
            """//@version=2
strategy("fixture")
before = nz(value[1])
value = before + close
if value > before
    strategy.entry("L", strategy.long)
""",
            state_types={"value": "float"},
        )
        self.assertEqual(version, 2)
        self.assertIn(
            "var float value = na\nbefore = nz(value[1])\nvalue := before + close", code
        )

    def test_legacy_eager_calls_remain_eager_through_a_function_argument(self):
        code, _, _, _ = prepare_source("""//@version=4
strategy("fixture")
value = iff(close > open, highest(3), lowest(3)) + close
if value > close
    strategy.entry("L", strategy.long)
""")
        self.assertIn("fmz_eager_if(close > open, ta.highest(3), ta.lowest(3))", code)

    def test_legacy_float_rsi_overload_retains_the_documented_formula(self):
        code, _, _, _ = prepare_source("""//@version=4
strategy("fixture")
upper = sum(volume * high, 2)
lower = sum(volume * low, 2)
value = rsi(upper, lower)
if value > 60
    strategy.entry("L", strategy.long)
""")
        self.assertIn("100.0 - (100.0 / (1.0 + ((upper) / (lower))))", code)

    def test_fixed_string_setting_preserves_option_values(self):
        code, _, _, _ = prepare_source("""//@version=4
strategy("fixture")
first = "first"
second = "second"
choice = input(first, options=[first, second])
if choice == first
    strategy.entry("L", strategy.long)
""")
        self.assertIn('input.string("first", options = ["first", "second"])', code)

    def test_audited_indentation_preserves_the_two_guarded_orders(self):
        source = 'if close > open\n     strategy.entry("L", strategy.long)\nelse\n strategy.entry("S", strategy.short)\n'
        code, _ = amend(source, 200)
        self.assertEqual(
            code.splitlines(),
            [
                "if close > open",
                '    strategy.entry("L", strategy.long)',
                "else",
                '    strategy.entry("S", strategy.short)',
            ],
        )
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            amend(source.replace(' strategy.entry("S"', 'strategy.entry("S"'), 200)


if __name__ == "__main__":
    unittest.main()
