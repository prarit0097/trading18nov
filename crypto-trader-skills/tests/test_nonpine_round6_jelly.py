import pytest

from research.nonpine_round6_jelly import roundtrip


def test_jelly_taker_spread_and_fees_are_charged_on_each_leg():
    before = [(0.1, 0.11)] * 4
    after = [(0.11, 0.12), (0.09, 0.10), (0.09, 0.10), (0.11, 0.12)]
    gross, fees, spread = roundtrip(before, after, 50_000)
    assert gross == pytest.approx(200)
    assert fees == pytest.approx(12)
    assert spread == pytest.approx(200)
    assert gross - fees - spread == pytest.approx(-12)
