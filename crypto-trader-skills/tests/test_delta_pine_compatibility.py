"""Assert narrow FMZ compatibility changes before the full candle replay."""

import unittest

try:
    from research.delta_pine_compatibility import (
        fixed_default_inputs,
        plain_pine,
        rsi_calls,
        session_calls,
        shell,
    )
    from research.delta_pinets_migration import MigrationBlocked
except ModuleNotFoundError as exc:
    if exc.name not in {"numpy", "talib"}:
        raise
    raise unittest.SkipTest("Optional research dependencies are required") from exc


class PineCompatibilityTests(unittest.TestCase):
    def test_title_only_fmz_adapter(self):
        body = '//@version=4\n// strategy("t", pyramiding=9)\nstrategy.entry("L", strategy.long)'
        output, labels = shell(body)
        assert output == body.replace(
            "//@version=4\n", '//@version=4\nstrategy("FMZ archived strategy")\n'
        )
        assert labels == {"FMZ implicit strategy declaration": 1}
        with self.assertRaises(MigrationBlocked):
            shell('//@version=4\n// strategy.entry("L", strategy.long)')
        with self.assertRaises(MigrationBlocked):
            shell('//@version=4\nstudy("Study")\nstrategy.entry("L", strategy.long)')

    def test_rsi_recognizes_integer_lengths_without_guessing_series(self):
        code = 'a = input(14, "Len"), b = input(20)\nr1 = rsi(close, 14)\nr2 = rsi(close, (50))\nr3 = rsi(close, a)\nr4 = rsi(close, b)\nr5 = rsi(close, input(16))\nr6 = rsi(close, close)\nr7 = rsi(close, 2.0)'
        output, count = rsi_calls(code)
        assert output == code.replace("rsi(", "ta.rsi(", 5)
        assert count == 5
        assert rsi_calls("n = input(14)\nn := 12\nz = rsi(close, n)")[1] == 0
        assert rsi_calls("rsi(x, y) => x + y\nz = rsi(close, 14)")[1] == 0
        assert rsi_calls("n = input(14)\nf(n) => rsi(close, n)")[1] == 0

    def test_normalizes_crlf_without_stripping_source_lines(self):
        assert (
            plain_pine("/*backtest\r\nperiod: 1h\r\n*/\r\n//@version=4\r\ncode\r\n")
            == "\n//@version=4\ncode\n"
        )

    def test_session_day_migration_uses_chart_timeframe_only(self):
        code = '//@version=4\nstrategy("x")\nopen_now = time(timeframe.period, "0900-1700")\n'
        adapted, count = session_calls(code)
        assert count == 1
        assert 'time(timeframe.period, "0900-1700:23456")' in adapted
        adapted, count = session_calls(code.replace('"0900-1700"', "session_input"))
        assert count == 1
        assert "time(timeframe.period, fmz_legacy_session(session_input))" in adapted
        assert 'str.contains(spec, ":")' in adapted
        explicit = code.replace('"0900-1700"', '"0900-1700:1234567"')
        assert session_calls(explicit) == (explicit, 0)
        with self.assertRaises(MigrationBlocked):
            session_calls(code.replace("timeframe.period", '"60"'))

    def test_fixed_default_input_parity_preserves_integer_domain_and_default(self):
        original = 'n = input.int(14, "Length", minval = 2.1, maxval = 15.9, step = .1)'
        assert fixed_default_inputs(original) == (
            'n = input.int(14, "Length", minval = 3, maxval = 15)',
            1,
        )
        named = 'n = input.int(title = "n", defval = -1, minval = -2.5, maxval = -0.1)'
        assert fixed_default_inputs(named) == (
            'n = input.int(title = "n", defval = -1, minval = -2, maxval = -1)',
            1,
        )
        for blocked in (
            original.replace("14,", "2,"),
            original.replace("maxval = 15.9", "maxval = upper"),
            original.replace('14, "Length"', '14, "Length", defval = 15'),
            original.replace("step = .1", "step = -.1"),
        ):
            assert fixed_default_inputs(blocked) == (blocked, 0)
