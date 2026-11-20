from research.fmz_native_round6_keltner import action


def test_archived_keltner_exit_keeps_more_than_ten_percent_open():
    assert action(111.0, 120.0, 120, 100, 1, 1000, False) == "stop"
    assert action(111.0, 120.0, 140, 100, 1, 1000, False) == "sell"
    assert action(109.0, 120.0, 120, 100, 1, 1000, False) == "sell"


def test_archived_keltner_entry_requires_balance_and_breakout():
    assert action(101, 100, 100, 99, 0, 600, True) == "buy"
    assert action(101, 100, 100, 99, 0, 599, True) == "wait"
