from research.nonpine_round5_pmm import SECOND, eligible, position_fill


def test_trade_through_requires_later_exchange_print_and_size():
    order = (100.0, 5 * SECOND)
    assert not eligible(order, 5 * SECOND, 99.0, 1.0, 1, 1.0)
    assert not eligible(order, 6 * SECOND, 100.0, 1.0, 1, 1.0)
    assert not eligible(order, 6 * SECOND, 99.0, 0.9, 1, 1.0)
    assert eligible(order, 6 * SECOND, 99.0, 1.0, 1, 1.0)
    assert eligible(order, 6 * SECOND, 101.0, 1.0, -1, 1.0)


def test_pair_fifo_both_directions():
    queue, closed = [], []
    position_fill(queue, closed, 1, 1, 100, 0.5)
    position_fill(queue, closed, 1, 2, 110, 0.5)
    position_fill(queue, closed, -1, 3, 105, 0.5)
    position_fill(queue, closed, -1, 4, 115, 0.5)
    position_fill(queue, closed, -1, 5, 130, 0.5)
    position_fill(queue, closed, 1, 6, 125, 0.5)
    assert [x[1] for x in closed] == [2.5, 2.5, 2.5]
    assert not queue
