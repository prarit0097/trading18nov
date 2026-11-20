from research.fmz_native_round7_turtle import permits


def test_turtle_gate_respects_archive_state_and_atr_conditions():
    assert permits(110, 105, 80, 0, 3) == (True, False)
    assert permits(110, 105, 80, 109, 3) == (False, False)
    assert permits(110, 105, 80, 108, 3) == (True, False)
    assert permits(89, 105, 80, 100, 3) == (False, True)
