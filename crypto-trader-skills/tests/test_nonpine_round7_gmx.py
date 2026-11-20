from decimal import Decimal

import pytest

from research.nonpine_round7_gmx import ReceiptTerms, matched_leg, quote


def test_raw_oracle_fee_and_share_normalization():
    entry = ReceiptTerms(
        100, 1000, quote(4_000_000_000, 10**24), Decimal(2), Decimal(3)
    )
    exit = ReceiptTerms(200, 500, quote(2_010_000_000, 10**24), Decimal(9), Decimal(4))
    time, gross, fees, gas = matched_leg(entry, exit, 400)
    assert time == 200
    assert gross == pytest.approx(16)
    assert fees == pytest.approx(8)
    assert gas == pytest.approx(4.4)
    assert gross - fees - gas == pytest.approx(3.6)


def test_no_borrowed_shares_or_reverse_time():
    entry = ReceiptTerms(100, 1000, Decimal(1000), Decimal(1), Decimal(1))
    exit = ReceiptTerms(200, 1010, Decimal(1030), Decimal(1), Decimal(1))
    with pytest.raises(ValueError, match="share"):
        matched_leg(entry, exit, 1001)
    with pytest.raises(ValueError, match="time"):
        matched_leg(exit, entry, 1000)
