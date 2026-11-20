from math import isclose

from research.nonpine_round9_dip import ask_ladder, dip_note, sample_receipt


def test_floor_sizing_and_exit_quantity_reconcile():
    levels = ask_ladder(100.0, 1.0, 1.04, 0.01, 3)
    assert [px for px, _ in levels] == [101.33, 102.66, 104.0]
    assert isclose(sum(qty for _, qty in levels), 1.0)
    at, gross, fees, execution = sample_receipt(120, 100.0, 104.0, 0.3)
    assert at == 120
    assert isclose(gross, 1.2)
    assert fees > 0 and execution > 0


def test_first_slow_threshold_is_final_and_boundaries_are_strict():
    weights = [
        {
            "slow_threshold": 30,
            "fast_thresholds": [
                {"fast_threshold": 20, "weights": {"price": 1, "volume": 1}}
            ],
        },
        {
            "slow_threshold": 45,
            "fast_thresholds": [
                {"fast_threshold": 40, "weights": {"price": 3, "volume": 2}}
            ],
        },
    ]
    assert dip_note(29, 19, 19, weights) == (1, 1)
    assert dip_note(29, 20, 19, weights) is None
    assert dip_note(30, 21, 23, weights) == (3, 2)
