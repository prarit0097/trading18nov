import pandas as pd
import pytest

from research.delta_strategy_replay import EQUITY, EXECUTION, FEE
from research.fmz_mylanguage_round5 import Book, features
from research.fmz_native_round5_recipes import kdj


def test_partial_exit_reconciles_and_charges_funding_at_boundary():
    book = Book([(150, 100, .002), (170, 110, -.001)], 1)
    assert book.open(100, 100, 2, 1, "first entry")
    book.close(150, 110, .75, "partial close")
    assert book.qty == 1.25
    first = book.settled[0]
    assert first[6:] == pytest.approx([7.5, .75 * 210 * FEE, .75 * 210 * EXECUTION, -.15])
    book.close(170, 90, 1.25, "final close")
    assert book.side == 0
    second = book.settled[1]
    assert second[6:] == pytest.approx([-12.5, 1.25 * 190 * FEE, 1.25 * 190 * EXECUTION, -.1125])
    total_turnover = 200 + .75 * 110 + 1.25 * 90
    assert book.verify(180)["ending_cash"] == pytest.approx(EQUITY - 5 - total_turnover * FEE - .2625)


def test_turtle_lookback_excludes_current_high():
    index = pd.date_range("2026-08-01", periods=30, freq="D", tz="UTC")
    bars = pd.DataFrame({"open": 100., "high": 110., "low": 90., "close": 100., "volume": 1.}, index=index)
    bars.loc[index[-2], ["high", "close"]] = [150, 111]
    for id_ in (492, 5779):
        actual = features(id_, bars, {"ratio": .01})
        assert actual.loc[index[-2], "above_20"]
        assert not actual.loc[index[-1], "above_20"]
        changed = bars.copy()
        changed.loc[index[-1], "high"] += 1000
        pd.testing.assert_frame_equal(actual.iloc[:-1], features(id_, changed, {"ratio": .01}).iloc[:-1])


def test_kdj_recurrence_and_formatting():
    high = pd.Series([100., 100., 100., 100.])
    low = pd.Series([0., 0., 0., 0.])
    close = pd.Series([0., 80., 20., 90.])
    k, d = kdj(high, low, close, 2, 2)
    assert list(k) == ["", "65.00", "42.50", "66.25"]
    assert list(d) == ["", "57.50", "50.00", "58.13"]
