import pytest

from research.fmz_round7_magnifier import aggregate, ledger_metrics


def test_aggregate_preserves_first_open_last_close_and_volume():
    assert aggregate(
        [(0, 100, 103, 99, 102, 1.5), (1, 102, 105, 101, 104, 2.5)], 2
    ) == [(0, 100, 105, 99, 104, 4.0)]
    with pytest.raises(AssertionError):
        aggregate([(0, 100, 103, 99, 102, 1.5)], 2)


def test_simultaneous_exits_reconcile_fees_and_realized_drawdown():
    trades = [
        {
            "dir": 1,
            "qty": 1,
            "entryPrice": 100,
            "exitPrice": 105,
            "commission": 1,
            "profit": 4,
            "exitTime": 10,
        },
        {
            "dir": -1,
            "qty": 2,
            "entryPrice": 100,
            "exitPrice": 103,
            "commission": 0.5,
            "profit": -6.5,
            "exitTime": 10,
        },
    ]
    result = ledger_metrics(trades, 100, 1)
    assert result["gross"] == -1
    assert result["fees"] == 1.5
    assert result["net"] == -2.5
    assert result["net_dd"] == 2.5
    assert result["net_dd_pct"] == 0.025
    assert result["net_wins"] == 1
    assert result["unsettled"] == 1
