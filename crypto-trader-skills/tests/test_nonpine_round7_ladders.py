import pytest

from research.nonpine_round7_ladders import Order, crossed, exit_values, mirror


def test_mirror_uses_spread_minus_increment_and_keeps_rebuy_budget():
    entry = Order(1, -1, 110, 1, 10, None)
    reverse = mirror(entry, 5, 0.01, 0.001, 11)
    assert reverse.side == 1 and reverse.price == 105
    assert reverse.qty == pytest.approx(1.047)
    assert reverse.posted == 11 and reverse.first is entry


def test_one_historical_print_is_allocated_in_price_order():
    orders = [Order(1, 1, 100, 0.5, 10, None), Order(2, 1, 101, 0.4, 10, None)]
    assert crossed(orders, 10, 1, 99, 0.5) == []
    assert crossed(orders, 11, 1, 101, 0.5) == []
    assert [x.slot for x in crossed(orders, 11, 1, 99, 0.7)] == [2]


def test_inventory_return_uses_completed_base_amount():
    initial = Order(1, -1, 120, 0.5, 10, None)
    rebuy = mirror(initial, 6, 0.01, 0.001, 11)
    at, gross, fees, costs = exit_values(initial, rebuy, 12)
    assert at == 12 and gross == pytest.approx(3)
    assert fees == pytest.approx((initial.qty * 120 + rebuy.qty * 114) * 0.001)
    assert costs == pytest.approx(fees * 0.3)
