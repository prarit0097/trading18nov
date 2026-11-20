import pytest

from research.nonpine_round6_index import DAY, replay


def test_rebalance_uses_next_prices_and_preserves_open_final_basket():
    def day(signal, sale, buy):
        return dict(zip(("signal", "sell", "buy"), (signal, sale, buy), strict=True))

    sessions = {
        DAY: day(None, (100, 10), (100, 10)),
        2 * DAY: day((110, 11), (110, 11), (111, 11.1)),
        3 * DAY: day((140, 10), (139, 10), (137, 10.1)),
    }
    closed, holds, receipts = replay(sessions)
    assert len(closed) == 2 and holds == 2
    assert [x["at"] for x in receipts] == [DAY, 3 * DAY]
    assert receipts[-1]["sells"] == (139, 10)
    assert receipts[-1]["buys"] == (137, 10.1)
    assert sum(x[1] for x in closed) == pytest.approx(1947.4689, abs=0.02)
