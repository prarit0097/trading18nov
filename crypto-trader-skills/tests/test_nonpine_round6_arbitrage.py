import pytest

from research.nonpine_round6_arbitrage import SECOND, legs, replay


def quote(at, bid, ask, size=1):
    return at * SECOND - 10, bid, ask, size, size


def test_paired_quote_rejects_missing_depth_and_stale_timestamp():
    a = quote(4, 99, 100)
    b = quote(4, 103, 104, 0.25)
    assert legs(a, b, 4, 0.5) is None
    assert legs(a, quote(3, 103, 104), 4, 0.5) is None
    assert legs(a, quote(4, 103, 104), 4, 0.5) == (100, 103)


def test_arbitrage_records_adverse_execution_after_positive_signal():
    a = {4: quote(4, 99, 100), 5: quote(5, 100, 101)}
    b = {4: quote(4, 103, 104), 5: quote(5, 100, 101)}
    closed, _, signals, misses, ledger = replay(a, b, 4, 5, 0.1)
    assert (signals, misses, len(closed)) == (1, 0, 1)
    assert closed[0][1] == pytest.approx(-0.1)
    assert ledger[0][0:2] == [4, 5]
