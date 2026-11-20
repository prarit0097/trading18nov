import math

from research.nonpine_round11_daily import replay


def test_oco_stop_has_priority_and_gap_is_accounted_for():
    bars = [
        (0, 100, 100, 98, 100, 100),
        (60, 90, 110, 89, 100, 100),
    ]
    result = replay(bars, {0: (100, "short", 0.5)}, 0, 120, 0.001)
    [fill] = result["fills"]
    assert (fill["reason"], fill["price"]) == ("stop", 90)
    assert fill["quantity"] == 5
    [_, gross, fees, costs] = result["receipts"][0]
    assert gross == -50
    assert math.isclose(fees, 0.45)
    assert math.isclose(costs, 0.135)


def test_stop_stays_triggered_when_volume_is_insufficient():
    bars = [
        (0, 100, 105, 96, 100, 1),
        (60, 95, 96, 94, 95, 1),
        (120, 99, 103, 98, 100, 100),
    ]
    result = replay(bars, {0: (100, "short", 0.5)}, 0, 180, 0.001)
    [fill] = result["fills"]
    assert (fill["at"], fill["reason"], fill["price"]) == (120, "stop", 99)
    assert result["remaining_base"] == 5
    assert result["pending"] is None


def test_limit_requires_trade_through_and_neutral_keeps_order():
    bars = [
        (0, 100, 101, 98.75, 100, 100),
        (60, 100, 101, 98.70, 100, 100),
    ]
    result = replay(bars, {0: (100, "long", -0.5), 60: (100, "neutral", 0)}, 0, 120, 0.001)
    [fill] = result["fills"]
    assert fill["at"] == 60
    assert math.isclose(fill["price"], 98.75)
    assert fill["reason"] == "limit"
    assert result["remaining_base"] > 10
    assert result["remaining_cash"] >= 0
