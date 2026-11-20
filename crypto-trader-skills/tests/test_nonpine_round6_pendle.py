from research.nonpine_round6_pendle import accrued_interest


def test_yt_interest_uses_both_indices_and_integer_rounding():
    scale = 10**18
    assert accrued_interest(10_000, scale, scale * 5 // 4) == 2_000
    assert accrued_interest(10_000, scale, scale) == 0
