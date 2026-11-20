from math import isclose

import pytest

pd = pytest.importorskip("pandas")

from research.delta_strategy_replay import EXECUTION, FEE
from research.fmz_mylanguage_round4 import features, simulate


def test_dual_thrust_uses_only_prior_price_channels():
    bars = pd.DataFrame({
        "open": [10, 8, 11], "high": [16, 100, 12], "low": [4, 7, 9],
        "close": [13, 15, 10], "volume": [1, 1, 1],
    })
    signals = features(262, bars, {"N": 1, "KS": .5, "KX": .5})
    assert list(signals.long) == [False, True, False]
    assert list(signals.short) == [False, False, False]


def test_reversal_uses_next_open_and_funds_old_side_first():
    days = pd.date_range("2026-09-24", periods=4, freq="D", tz="UTC")
    chart = pd.DataFrame({
        "open": [91, 102, 123], "high": [100, 123, 125], "low": [90, 100, 104],
        "close": [98, 119, 107], "volume": [1, 1, 1],
        "long": [True, False, True], "short": [False, True, False],
        "close_long": [False, False, False], "close_short": [False, False, False],
    }, index=days[:3])
    minute = pd.DataFrame({"open": [100, 120, 110], "volume": [1, 1, 1]}, index=days[1:])
    first = int(days[0].timestamp())
    one, two, three = (int(t.timestamp()) for t in days[1:])
    rows, trades, unsettled = simulate(262, chart, minute, [(two, 125, .001), (three, 111, .001)], first, three + 60, {})
    assert len(rows) == len(trades) == 2 and unsettled == 1
    assert trades[0][:6] == [1, one, two, 100, 120, 10]
    assert isclose(rows[0][1], 200)
    assert isclose(rows[0][2], 200 - 2200 * FEE)
    assert isclose(rows[0][3], 200 - 2200 * (FEE + EXECUTION) - 1.25)
    assert isclose(rows[1][4], 111 * .001 * 1000 / 120)
