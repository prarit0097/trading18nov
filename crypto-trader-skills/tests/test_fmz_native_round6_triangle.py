from research.fmz_native_round6_triangle import margins


def test_three_leg_gate_accounts_for_both_source_directions_and_fees():
    btc = (0, 100, 101, 1, 1)
    price_cross = (0, 0.1, 0.101, 1, 1)
    assert margins(btc, (0, 11, 12, 1, 1), price_cross, 0.0015)[0] > 0
    assert margins(btc, (0, 8, 9, 1, 1), price_cross, 0.0015)[1] > 0
    assert max(margins(btc, (0, 10, 10.2, 1, 1), price_cross, 0.0015)) < 0
