import pytest

from research.nonpine_round6_pmm import SECOND, Level, consume, limit_price, settle


def test_trade_through_uses_a_print_only_once_and_prioritizes_better_limits():
    first = Level(1, 100, 0.35, 10)
    better = Level(1, 101, 0.35, 10)
    levels = [first, better]
    assert not consume(levels, 10 * SECOND, 1, 99, 0.4)
    assert not consume(levels, 11 * SECOND, 1, 101, 0.4)
    assert consume(levels, 11 * SECOND, 1, 99, 0.4) == [better]
    assert first.entered is None
    assert better.entered == 11 * SECOND


def test_closing_limits_quantize_away_from_crossing_and_costs_reconcile():
    assert limit_price(100.124, 0.1, 1) == pytest.approx(100.1)
    assert limit_price(100.124, 0.1, -1) == pytest.approx(100.2)
    long = Level(1, 100, 0.5, 10)
    at, gross, fee, execution = settle(long, 102, 42, 0.0005)
    assert at == 42
    assert gross == pytest.approx(1)
    assert fee == pytest.approx(0.5 * (100 * 0.0002 + 102 * 0.0005))
    assert execution == pytest.approx(0.5 * (100 + 102) * 0.0003)
