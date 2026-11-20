import pytest

from research.nonpine_round5_boros import INTERVAL, YEAR, rate, roundtrip, top


def test_signed_tick_and_executable_size():
    assert rate(-100) == pytest.approx(-(1.00005**200 - 1))
    book = {
        "long": [{"t": 100, "sz": "10000000000000000"}],
        "short": [{"t": 110, "sz": "9000000000000000"}],
    }
    assert top(book, -1, 0.01) == pytest.approx(rate(100))
    assert top(book, 1, 0.01) is None


def test_upfront_fixed_time_uses_settlement_boundary():
    at = 100 * INTERVAL
    maturity = at + 9 * INTERVAL
    opened = at + 3600
    closed = at + 2 * INTERVAL + 3600
    before, fees = roundtrip(1, 2, maturity, opened, closed, 0.04, 0.04, [0.06, 0.06])
    assert before == pytest.approx(2 * 0.02 * 2 * INTERVAL / YEAR)
    assert fees > 0
    short, short_fees = roundtrip(
        -1, 2, maturity, opened, closed, 0.04, 0.04, [0.06, 0.06]
    )
    assert short == pytest.approx(-before)
    assert short_fees == pytest.approx(fees)
