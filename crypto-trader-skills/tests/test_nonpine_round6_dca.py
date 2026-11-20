import pytest

from research.nonpine_round6_dca import replay


def test_stop_precedes_target_and_gap_is_paid():
    bars = [
        (0, 100, 100, 99, 100),
        (60, 98, 99, 94, 95),
        (120, 80, 102, 79, 98),
    ]
    closed, held, receipts = replay(bars, 0.001)
    assert len(closed) == 1 and held == 0
    assert receipts[0]["exit_reason"] == "stop"
    assert receipts[0]["entry"] == pytest.approx(95)
    assert receipts[0]["exit"] == pytest.approx(80)
