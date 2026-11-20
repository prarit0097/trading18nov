from decimal import Decimal

import pytest

from research.fmz_round8_fx import prior_close_rates, reconcile_minutes, result_lot


def test_currency_rate_becomes_available_at_the_next_utc_day():
    days = [
        [86400, 0.98, 1.01, 0.99, 0.999, 100],
        [0, 0.98, 1.02, 1, 1.001, 100],
    ]
    rates = prior_close_rates(days)
    assert rates["pairs"][0]["rates"] == [
        {"effectiveTime": 86400000, "rate": 1.001},
        {"effectiveTime": 172800000, "rate": 0.999},
    ]
    with pytest.raises(AssertionError):
        prior_close_rates([days[0], [259200, *days[1][1:]]])


def test_short_lot_reconciles_account_currency_and_two_fee_legs():
    entry_qty = 2
    fx = 0.5
    gross = (100 - 80) * entry_qty * fx
    fees = (100 + 80) * entry_qty * 0.00075 * fx
    native_lot = [1000, 2000, "Short", entry_qty, 100, 80, gross, fees, gross - fees]
    loan = result_lot(native_lot, fx)
    assert loan["dir"] == -1
    assert loan["entryPrice"] == 50
    assert loan["exitPrice"] == 40
    assert loan["commission"] == pytest.approx(fees)
    assert loan["profit"] == pytest.approx(gross - fees)
    with pytest.raises(AssertionError):
        result_lot([*native_lot[:-1], gross], fx)


def test_minute_volume_reconciliation_preserves_decimal_precision():
    lower = [
        [
            i * 10_000,
            Decimal(100),
            Decimal(100),
            Decimal(100),
            Decimal(100),
            Decimal("0.1"),
        ]
        for i in range(6)
    ]
    minutes = {0: [100, 100, 100, 100, Decimal("0.6"), 6]}
    assert reconcile_minutes(lower, [1] * 6, minutes) == [
        [0, 100.0, 100.0, 100.0, 100.0, 0.6]
    ]
    with pytest.raises(AssertionError):
        reconcile_minutes(
            lower, [1] * 6, {0: [100, 100, 100, 100, Decimal("0.60001"), 6]}
        )
