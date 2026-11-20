from research.fmz_native_round6_bollinger import Frame, actions


def test_archived_breakout_and_contraction_use_source_order():
    before = Frame(105, 110, 100, 90, 111, 89, 104, 61)
    breakout = Frame(106, 112, 101, 89, 111, 88, 104, 62)
    contraction = Frame(106, 110, 101, 90, 111, 88, 104, 60)
    assert actions(before, breakout, 0) == ([1], 1)
    assert actions(breakout, contraction, 1) == ([-1], 0)
    assert actions(breakout, contraction, 0) == ([], 0)
